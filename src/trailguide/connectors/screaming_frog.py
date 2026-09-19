"""Screaming Frog connector.

The crawl is the site's ground truth: what exists, what is indexable, what is
orphaned and what is thin. It emits page records (so technical facts merge onto
the same URLs analytics reports on) and explicit crawl issues.

Issue thresholds are configurable per source, because "thin" means something
different for a glossary entry than for a pillar page.
"""

from __future__ import annotations

from typing import Any

from ..core import coerce
from ..core.classify import url_template
from ..core.schemas import CrawlIssue, Dataset, PageMetric, Severity
from .base import Connector, register

DEFAULT_THRESHOLDS: dict[str, float] = {
    "thin_content_words": 300,
    "max_crawl_depth": 4,
    "slow_response_ms": 1200,
    "min_inlinks": 1,
}


@register
class ScreamingFrogConnector(Connector):
    """Normalizes a Screaming Frog ``internal_all`` / ``internal_html`` export."""

    name = "screaming_frog"
    aliases = ("crawl", "sitebulb", "screamingfrog", "deepcrawl")
    description = "Screaming Frog crawl export (status, indexability, titles, inlinks, word count)."
    produces = ("pages", "crawl_issues")

    def load(self) -> Dataset:
        dataset = Dataset()
        thresholds = dict(DEFAULT_THRESHOLDS)
        thresholds.update(
            {str(k): float(v) for k, v in (self.spec.options.get("thresholds") or {}).items()}
        )
        template_rules = self.spec.options.get("template_rules") or {}
        html_only = bool(self.spec.options.get("html_only", True))

        for file_path, row in self.rows():
            url = coerce.to_str(coerce.first_present(row, ("address", "url", "page")))
            if not url:
                continue
            content_type = (coerce.to_str(row.get("Content Type"), "") or "").lower()
            if html_only and content_type and "html" not in content_type:
                continue

            status_code = coerce.to_int(coerce.first_present(row, ("status code", "status_code")))
            indexability = (coerce.to_str(coerce.first_present(row, ("indexability",)), "") or "").lower()
            indexable = None if not indexability else indexability.startswith("index")
            word_count = coerce.to_int(coerce.first_present(row, ("word count", "word_count")))
            inlinks = coerce.to_int(coerce.first_present(row, ("unique inlinks", "inlinks")))
            depth = coerce.to_int(coerce.first_present(row, ("crawl depth", "depth")))
            response_ms = _response_ms(coerce.first_present(row, ("response time", "response_time")))
            title = coerce.to_str(coerce.first_present(row, ("title 1", "title", "page title")))

            dataset.pages.append(
                PageMetric(
                    source=self.source_name,
                    source_file=str(file_path),
                    url=url,
                    title=title,
                    word_count=word_count,
                    status_code=status_code,
                    indexable=indexable,
                    canonical_url=coerce.to_str(
                        coerce.first_present(row, ("canonical link element 1", "canonical"))
                    ),
                    internal_inlinks=inlinks,
                    ttfb_ms=response_ms,
                    template=url_template(url, template_rules),
                    updated_at=coerce.to_date(
                        coerce.first_present(row, ("last modified", "last_modified"))
                    ),
                )
            )
            dataset.crawl_issues.extend(
                self._detect_issues(
                    file_path=str(file_path),
                    url=url,
                    row=row,
                    status_code=status_code,
                    indexability=indexability,
                    indexable=indexable,
                    word_count=word_count,
                    inlinks=inlinks,
                    depth=depth,
                    response_ms=response_ms,
                    title=title,
                    thresholds=thresholds,
                )
            )
        return dataset

    def _detect_issues(
        self,
        *,
        file_path: str,
        url: str,
        row: dict[str, Any],
        status_code: int | None,
        indexability: str,
        indexable: bool | None,
        word_count: int | None,
        inlinks: int | None,
        depth: int | None,
        response_ms: float | None,
        title: str | None,
        thresholds: dict[str, float],
    ) -> list[CrawlIssue]:
        """Derive normalized issues from one crawled URL."""
        issues: list[CrawlIssue] = []

        def add(issue_type: str, severity: Severity, detail: str) -> None:
            issues.append(
                CrawlIssue(
                    source=self.source_name,
                    source_file=file_path,
                    url=url,
                    issue_type=issue_type,
                    severity=severity,
                    detail=detail,
                    status_code=status_code,
                    indexable=indexable,
                )
            )

        if status_code is not None:
            if status_code >= 500:
                add("server_error", Severity.CRITICAL, f"HTTP {status_code}")
            elif status_code == 404 or status_code == 410:
                add("broken_page", Severity.HIGH, f"HTTP {status_code}")
            elif 300 <= status_code < 400:
                add("redirect", Severity.MEDIUM, f"HTTP {status_code} redirect in the crawl path")

        indexability_status = (
            coerce.to_str(coerce.first_present(row, ("indexability status",)), "") or ""
        ).lower()
        if indexable is False and indexability_status:
            severity = Severity.HIGH if "noindex" in indexability_status else Severity.MEDIUM
            add("non_indexable", severity, f"Indexability status: {indexability_status}")

        if word_count is not None and 0 < word_count < thresholds["thin_content_words"]:
            add(
                "thin_content",
                Severity.MEDIUM,
                f"{word_count} words, below the {int(thresholds['thin_content_words'])}-word threshold",
            )

        if inlinks is not None and inlinks < thresholds["min_inlinks"]:
            add("orphan_page", Severity.HIGH, "No unique internal inlinks found in the crawl")

        if depth is not None and depth > thresholds["max_crawl_depth"]:
            add(
                "deep_page",
                Severity.MEDIUM,
                f"Crawl depth {depth} exceeds the {int(thresholds['max_crawl_depth'])}-click threshold",
            )

        if response_ms is not None and response_ms > thresholds["slow_response_ms"]:
            add("slow_response", Severity.MEDIUM, f"Server response {response_ms:.0f} ms")

        if not title:
            add("missing_title", Severity.HIGH, "Title tag is missing or empty")

        if not coerce.to_str(
            coerce.first_present(row, ("meta description 1", "meta description"))
        ):
            add("missing_meta_description", Severity.LOW, "Meta description is missing")

        if not coerce.to_str(coerce.first_present(row, ("h1-1", "h1", "h1 1"))):
            add("missing_h1", Severity.LOW, "H1 is missing")

        return issues


def _response_ms(raw: Any) -> float | None:
    """Screaming Frog reports response time in seconds; normalize to milliseconds."""
    seconds = coerce.to_float(raw)
    if seconds is None:
        return None
    return seconds * 1000.0 if seconds < 60 else seconds
