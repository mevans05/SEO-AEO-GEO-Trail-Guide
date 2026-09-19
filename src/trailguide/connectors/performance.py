"""PageSpeed Insights and Lighthouse connectors.

Core Web Vitals earn their place in a revenue model through conversion, not
rankings: slow pages lose sessions between the click and the content. The
technical analyzer converts a vitals deficit into lost conversions using
configured elasticities, so performance work competes for capacity on the same
revenue basis as content work.

Accepts three shapes: a raw Lighthouse JSON report, a PageSpeed Insights API
response (which wraps a Lighthouse report and adds field data), and a flat CSV
of URLs and metrics.
"""

from __future__ import annotations

from typing import Any

from ..core import coerce
from ..core.schemas import Dataset, PageMetric
from .base import Connector, IntakeColumn, IntakeSheet, register

_AUDIT_FIELDS = {
    "largest-contentful-paint": "lcp_ms",
    "interaction-to-next-paint": "inp_ms",
    "experimental-interaction-to-next-paint": "inp_ms",
    "cumulative-layout-shift": "cls",
    "server-response-time": "ttfb_ms",
}

_CRUX_FIELDS = {
    "LARGEST_CONTENTFUL_PAINT_MS": "lcp_ms",
    "INTERACTION_TO_NEXT_PAINT": "inp_ms",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "ttfb_ms",
}


@register
class PageSpeedConnector(Connector):
    """Normalizes PageSpeed Insights / Lighthouse output into page performance."""

    name = "pagespeed"
    aliases = ("psi", "pagespeed_insights", "lighthouse", "crux", "web_vitals")
    description = "PageSpeed Insights or Lighthouse report (JSON) or a Core Web Vitals CSV."
    produces = ("pages",)

    intake = (
        IntakeSheet(
            key="core_web_vitals",
            title="Core Web Vitals",
            source_type="pagespeed",
            priority="recommended",
            export_from=(
                "PageSpeed Insights API, CrUX, or a Lighthouse batch run across your "
                "top landing pages. Lighthouse JSON reports are read directly."
            ),
            unlocks=(
                "Core Web Vitals opportunities, valued through conversion rate rather "
                "than as an abstract score."
            ),
            notes=(
                "Field data (CrUX) beats lab data where you have it. Elasticities are "
                "published benchmarks - validate before treating them as a commitment."
            ),
            columns=(
                IntakeColumn("URL", "Page measured.", "https://example.com/shoes", True),
                IntakeColumn("Device", "mobile or desktop.", "mobile", True),
                IntakeColumn("LCP", "Largest Contentful Paint, seconds or ms.", "3.4", True),
                IntakeColumn("INP", "Interaction to Next Paint, ms.", "290"),
                IntakeColumn("CLS", "Cumulative Layout Shift.", "0.14"),
                IntakeColumn("TTFB", "Time to first byte.", "0.8"),
                IntakeColumn("Performance", "Lighthouse performance score.", "62"),
                IntakeColumn("SEO", "Lighthouse SEO score.", "92"),
                IntakeColumn("Accessibility", "Lighthouse accessibility score.", "88"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        default_device = self.spec.options.get("device", "mobile")

        for file_path, document in self.documents():
            for report in document if isinstance(document, list) else [document]:
                page = self._page_from_report(report, str(file_path), default_device)
                if page is not None:
                    dataset.pages.append(page)

        # Flat CSV/TSV inputs (a vitals dashboard export, for instance).
        for file_path, row in self._csv_rows():
            url = coerce.to_str(coerce.first_present(row, ("url", "page", "address", "origin")))
            if not url:
                continue
            dataset.pages.append(
                PageMetric(
                    source=self.source_name,
                    source_file=str(file_path),
                    url=url,
                    lcp_ms=_to_ms(coerce.first_present(row, ("lcp", "lcp_ms", "largest contentful paint"))),
                    inp_ms=_to_ms(coerce.first_present(row, ("inp", "inp_ms", "interaction to next paint"))),
                    cls=coerce.to_float(
                        coerce.first_present(row, ("cls", "cumulative layout shift"))
                    ),
                    ttfb_ms=_to_ms(coerce.first_present(row, ("ttfb", "ttfb_ms", "server response time"))),
                    performance_score=_to_score(
                        coerce.first_present(row, ("performance", "performance score", "performance_score"))
                    ),
                    seo_score=_to_score(coerce.first_present(row, ("seo", "seo score"))),
                    accessibility_score=_to_score(
                        coerce.first_present(row, ("accessibility", "accessibility score"))
                    ),
                    device=coerce.to_str(
                        coerce.first_present(row, ("device", "strategy", "form factor")), default_device
                    ),
                )
            )
        return dataset

    def _csv_rows(self):
        """Yield rows only from delimited files, leaving JSON to the report parser."""
        from .base import iter_source_files, read_rows

        options = self.spec.options
        for file_path in iter_source_files(self.spec, self.config):
            if file_path.suffix.lower() in {".json", ".jsonl", ".ndjson"}:
                continue
            for row in read_rows(
                file_path,
                skip_lines=int(options.get("skip_lines", 0)),
                delimiter=options.get("delimiter"),
            ):
                yield file_path, self._apply_column_map(row)

    def _page_from_report(
        self, report: Any, file_path: str, default_device: str
    ) -> PageMetric | None:
        """Extract a page record from a Lighthouse or PSI JSON document."""
        if not isinstance(report, dict):
            return None
        lighthouse = report.get("lighthouseResult", report)
        if not isinstance(lighthouse, dict):
            return None

        url = (
            coerce.to_str(report.get("id"))
            or coerce.to_str(lighthouse.get("finalUrl"))
            or coerce.to_str(lighthouse.get("requestedUrl"))
            or coerce.to_str(lighthouse.get("finalDisplayedUrl"))
        )
        if not url:
            return None

        page = PageMetric(
            source=self.source_name,
            source_file=file_path,
            url=url,
            device=_form_factor(lighthouse, default_device),
        )

        categories = lighthouse.get("categories") or {}
        page.performance_score = _to_score((categories.get("performance") or {}).get("score"))
        page.seo_score = _to_score((categories.get("seo") or {}).get("score"))
        page.accessibility_score = _to_score((categories.get("accessibility") or {}).get("score"))

        # Lab data from the Lighthouse audits.
        audits = lighthouse.get("audits") or {}
        for audit_id, field in _AUDIT_FIELDS.items():
            audit = audits.get(audit_id)
            if isinstance(audit, dict) and audit.get("numericValue") is not None:
                setattr(page, field, coerce.to_float(audit["numericValue"]))

        # Field data (CrUX) is real-user data and overrides lab estimates.
        field_metrics = (report.get("loadingExperience") or {}).get("metrics") or {}
        for crux_id, field in _CRUX_FIELDS.items():
            metric = field_metrics.get(crux_id)
            if isinstance(metric, dict) and metric.get("percentile") is not None:
                value = coerce.to_float(metric["percentile"])
                if value is not None:
                    setattr(page, field, value / 100.0 if field == "cls" else value)
        return page


def _form_factor(lighthouse: dict, default: str) -> str:
    """Read the emulated form factor from a Lighthouse config block."""
    settings = lighthouse.get("configSettings") or {}
    return coerce.to_str(settings.get("formFactor") or settings.get("emulatedFormFactor"), default) or default


def _to_ms(raw: Any) -> float | None:
    """Normalize a timing to milliseconds, accepting values expressed in seconds."""
    value = coerce.to_float(raw)
    if value is None:
        return None
    return value * 1000.0 if 0 < value < 60 else value


def _to_score(raw: Any) -> float | None:
    """Normalize a category score to a 0-100 scale (Lighthouse JSON uses 0-1)."""
    value = coerce.to_float(raw)
    if value is None:
        return None
    return value * 100.0 if value <= 1.0 else value
