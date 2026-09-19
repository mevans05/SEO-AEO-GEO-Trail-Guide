"""Technical analyzers: Core Web Vitals, crawl health, indexation and internal links.

Technical work is usually argued for on principle and then loses the capacity
fight to content. These analyzers give it a revenue number computed the same way
content's is, so the two compete on identical terms.

Core Web Vitals are valued through conversion rather than rankings. The
conversion effect is measurable and reasonably well evidenced; the ranking
effect is small and contested. Valuing the defensible mechanism keeps the
projection credible - and the dark-traffic gross-up is deliberately *not*
applied to it, because a faster page does not create new search demand.
"""

from __future__ import annotations

from collections import defaultdict

from ..core.coerce import clamp
from ..core.opportunity import Opportunity
from ..core.schemas import Confidence, Severity, Surface
from ..core.stats import percentile
from .base import AnalysisContext, Analyzer, register_analyzer

#: Google's "good" thresholds for the Core Web Vitals.
CWV_TARGETS = {"lcp_ms": 2500.0, "inp_ms": 200.0, "cls": 0.10}


@register_analyzer
class CoreWebVitalsAnalyzer(Analyzer):
    """Pages with vitals deficits on traffic that already exists."""

    name = "core_web_vitals"
    surface = Surface.TECHNICAL
    description = "Core Web Vitals deficits on high-traffic pages, valued through conversion."
    required_inputs = ("pages",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        min_sessions = self.setting(context, "min_annual_sessions", 1000)
        # Conversion uplift per second of LCP improvement, from published studies.
        lcp_elasticity = self.setting(context, "conversion_uplift_per_lcp_second", 0.07)
        inp_elasticity = self.setting(context, "conversion_uplift_per_inp_100ms", 0.015)
        cls_elasticity = self.setting(context, "conversion_uplift_per_cls_point", 0.10)
        max_uplift = self.setting(context, "max_conversion_uplift", 0.25)
        group_by_template = self.setting(context, "group_by_template", True)

        lag, ramp = context.timing(self.name)
        candidates = []
        for url, page in context.pages.items():
            sessions = page.sessions or page.clicks
            if sessions < min_sessions:
                continue
            uplift, deficits = _vitals_uplift(
                page, lcp_elasticity, inp_elasticity, cls_elasticity, max_uplift
            )
            if uplift <= 0:
                continue
            candidates.append((url, page, sessions, uplift, deficits))

        if not candidates:
            return []

        groups: dict[str, list] = defaultdict(list)
        for entry in candidates:
            key = (entry[1].template or "other") if group_by_template else entry[0]
            groups[key].append(entry)

        opportunities: list[Opportunity] = []
        for group_key, entries in groups.items():
            equivalent_sessions = sum(sessions * uplift for _, _, sessions, uplift, _ in entries)
            total_sessions = sum(sessions for _, _, sessions, _, _ in entries)
            if equivalent_sessions <= 0:
                continue

            revenue_pages = [
                page.revenue_per_session for _, page, _, _, _ in entries
                if page.revenue_per_session
            ]
            observed_rps = (sum(revenue_pages) / len(revenue_pages)) if revenue_pages else None

            projection = context.project(
                equivalent_sessions,
                self.surface,
                template=group_key if group_by_template else entries[0][1].template,
                observed_revenue_per_session=observed_rps,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.40,
                include_dark=False,     # faster pages convert better, they do not create demand
            )
            all_deficits = sorted({name for _, _, _, _, deficits in entries for name in deficits})
            opportunity = Opportunity(
                title=(
                    f"Fix Core Web Vitals on {len(entries)} '{group_key}' page"
                    f"{'s' if len(entries) != 1 else ''} ({', '.join(all_deficits)})"
                ),
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=min(len(entries), 8.0)),
                confidence=Confidence.DERIVED,
                confidence_modifier=0.65,
                entities=[url for url, _, _, _, _ in entries],
                owner_role=context.owner(self.name),
                tags=["technical"],
                recommended_actions=_cwv_actions(all_deficits),
                risks=[
                    "Valued on conversion elasticity from published benchmarks, not a "
                    "first-party test. Validate with an A/B or pre/post measurement.",
                ],
                measurement=[
                    "CrUX field data: 75th-percentile LCP/INP/CLS for the affected templates",
                    "Conversion rate for the same templates, pre versus post",
                ],
            )
            for url, page, sessions, uplift, deficits in sorted(
                entries, key=lambda item: item[2], reverse=True
            )[:8]:
                detail = ", ".join(
                    f"{name} {_format_vital(name, getattr(page, name))}" for name in deficits
                )
                opportunity.add_evidence(
                    "pagespeed", url,
                    f"{detail} on {sessions:,} sessions -> modeled {uplift:.1%} conversion uplift",
                    Confidence.DERIVED,
                )
            opportunity.add_evidence(
                "pagespeed", "affected traffic", f"{total_sessions:,} annual sessions",
                Confidence.OBSERVED,
            )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class CrawlHealthAnalyzer(Analyzer):
    """Crawl errors and on-page defects on URLs that carry traffic.

    Issues are grouped by type rather than URL: a client fixes "47 broken pages"
    as one workstream, not as 47 tickets, and grouping keeps the roadmap
    readable.
    """

    name = "crawl_health"
    surface = Surface.TECHNICAL
    description = "Crawl errors and on-page defects, weighted by the traffic they affect."
    required_inputs = ("crawl_issues",)
    optional_inputs = ("pages",)

    #: Share of an affected page's traffic modeled as recoverable by issue type.
    RECOVERY_RATES: dict[str, float] = {
        "server_error": 0.90,
        "broken_page": 0.75,
        "redirect": 0.05,
        "missing_title": 0.08,
        "missing_h1": 0.02,
        "missing_meta_description": 0.03,
        "thin_content": 0.15,
        "slow_response": 0.05,
    }

    #: Issue types handled by other analyzers, skipped here to avoid double counting.
    _DELEGATED = {"orphan_page", "deep_page", "non_indexable"}

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        min_sessions_gain = self.setting(context, "min_sessions_gain", 50.0)
        severity_floor = str(self.setting(context, "severity_floor", "low")).lower()
        floor_rank = _SEVERITY_RANK.get(severity_floor, 0)

        lag, ramp = context.timing(self.name)
        by_type: dict[str, list] = defaultdict(list)
        for issue in context.dataset.crawl_issues:
            if issue.issue_type in self._DELEGATED:
                continue
            if _SEVERITY_RANK.get(issue.severity.value, 0) < floor_rank:
                continue
            by_type[issue.issue_type].append(issue)

        opportunities: list[Opportunity] = []
        for issue_type, issues in by_type.items():
            recovery = self.RECOVERY_RATES.get(issue_type, 0.05)
            recoverable_sessions = 0.0
            affected_with_traffic = 0
            for issue in issues:
                page = context.pages.get(issue.url)
                if page is None:
                    continue
                sessions = page.sessions or page.clicks
                if sessions <= 0:
                    # No traffic today; value the demand the page is visible for.
                    sessions = (page.impressions or 0) * 0.02
                if sessions > 0:
                    affected_with_traffic += 1
                    recoverable_sessions += sessions * recovery

            if recoverable_sessions < min_sessions_gain:
                continue

            worst = max(issues, key=lambda item: _SEVERITY_RANK.get(item.severity.value, 0))
            projection = context.project(
                recoverable_sessions,
                self.surface,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.40,
            )
            opportunity = Opportunity(
                title=f"Resolve {len(issues)} '{issue_type.replace('_', ' ')}' issues",
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=min(float(len(issues)), 40.0)),
                confidence=Confidence.DERIVED,
                confidence_modifier=0.7 if affected_with_traffic >= 3 else 0.5,
                entities=[issue.url for issue in issues],
                owner_role=context.owner(self.name),
                tags=["technical"] + (["quick-win"] if worst.severity == Severity.CRITICAL else []),
                # Recovered organic clicks compete with the ranking analyzers.
                demand_pool_override="search",
                recommended_actions=_crawl_actions(issue_type),
                measurement=[
                    f"Re-crawl confirming zero '{issue_type}' findings",
                    "Search Console: coverage and impressions for the affected URLs",
                ],
            )
            for issue in issues[:8]:
                opportunity.add_evidence(
                    "screaming_frog", issue.url,
                    issue.detail or issue.issue_type,
                    Confidence.OBSERVED,
                    note=f"severity: {issue.severity.value}",
                )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class IndexationAnalyzer(Analyzer):
    """Pages excluded from the index that have demonstrated search demand."""

    name = "indexation"
    surface = Surface.SEO
    description = "Non-indexable URLs that hold impressions, clicks or clear commercial value."
    required_inputs = ("pages",)
    optional_inputs = ("crawl_issues",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        min_impressions = self.setting(context, "min_impressions", 100)
        capture_rate = self.setting(context, "capture_rate", 0.30)
        min_sessions_gain = self.setting(context, "min_sessions_gain", 50.0)

        lag, ramp = context.timing(self.name)
        blocked = []
        for url, page in context.pages.items():
            if page.indexable is not False:
                continue
            demand = page.impressions or 0
            if demand < min_impressions and (page.clicks or 0) == 0:
                continue
            blocked.append((url, page, demand))

        if not blocked:
            return []

        total_sessions = 0.0
        for _, page, demand in blocked:
            position = page.avg_position or 15.0
            total_sessions += demand * context.ctr.base_ctr(position) * capture_rate * 12.0

        if total_sessions < min_sessions_gain:
            return []

        lag, ramp = context.timing(self.name)
        projection = context.project(
            total_sessions,
            self.surface,
            lag_months=lag,
            ramp_months=ramp,
            base_uncertainty=0.45,
        )
        opportunity = Opportunity(
            title=f"Restore indexability for {len(blocked)} URLs with existing search demand",
            opportunity_type=self.name,
            surface=self.surface,
            projection=projection,
            effort=context.effort(self.name, units=min(float(len(blocked)), 30.0)),
            confidence=Confidence.DERIVED,
            confidence_modifier=0.6,
            entities=[url for url, _, _ in blocked],
            owner_role=context.owner(self.name),
            tags=["technical"],
            recommended_actions=[
                "Review each URL's exclusion reason: noindex, canonical elsewhere, robots.txt "
                "block or parameter handling.",
                "Remove the directive where exclusion is unintentional; where it is intentional, "
                "confirm the canonical target actually serves the demand.",
                "Submit the corrected URLs for inspection and monitor coverage weekly.",
                "Verify AI crawlers are not separately blocked in robots.txt - retrieval by "
                "GPTBot, PerplexityBot and Google-Extended is governed independently.",
            ],
            risks=[
                "Some exclusions are deliberate; each URL needs confirmation before the "
                "directive is removed.",
            ],
            measurement=["Search Console coverage: indexed count and impressions for the set"],
        )
        for url, page, demand in sorted(blocked, key=lambda item: item[2], reverse=True)[:10]:
            opportunity.add_evidence(
                "screaming_frog", url,
                f"non-indexable with {demand:,} impressions "
                f"(avg position {page.avg_position or 0:.1f})",
                Confidence.OBSERVED,
            )
        return [opportunity]


@register_analyzer
class InternalLinkingAnalyzer(Analyzer):
    """Pages with search demand that the internal link graph under-supports."""

    name = "internal_linking"
    surface = Surface.SEO
    description = "Orphaned and under-linked pages that hold impressions."
    required_inputs = ("pages",)
    optional_inputs = ("crawl_issues",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        min_impressions = self.setting(context, "min_impressions", 200)
        inlink_percentile = self.setting(context, "inlink_percentile", 0.25)
        expected_gain = self.setting(context, "expected_positions_gained", 1.5)
        min_sessions_gain = self.setting(context, "min_sessions_gain", 50.0)

        lag, ramp = context.timing(self.name)
        inlink_counts = [
            page.internal_inlinks for page in context.pages.values()
            if page.internal_inlinks is not None
        ]
        if not inlink_counts:
            return []
        threshold = max(1.0, percentile(inlink_counts, inlink_percentile))

        under_linked = []
        for url, page in context.pages.items():
            if page.internal_inlinks is None or page.internal_inlinks > threshold:
                continue
            if (page.impressions or 0) < min_impressions:
                continue
            if page.indexable is False:
                continue        # indexation analyzer owns these
            under_linked.append((url, page))

        if not under_linked:
            return []

        total_gain = 0.0
        for url, page in under_linked:
            position = page.avg_position or 12.0
            total_gain += context.ctr.click_delta(
                impressions=page.impressions or 0,
                current_position=position,
                target_position=max(1.0, position - expected_gain),
            ) * 12.0

        if total_gain < min_sessions_gain:
            return []

        projection = context.project(
            total_gain,
            self.surface,
            lag_months=lag,
            ramp_months=ramp,
            base_uncertainty=0.50,
        )
        opportunity = Opportunity(
            title=f"Strengthen internal links to {len(under_linked)} under-supported pages",
            opportunity_type=self.name,
            surface=self.surface,
            projection=projection,
            effort=context.effort(self.name, units=min(float(len(under_linked)), 30.0)),
            confidence=Confidence.DERIVED,
            confidence_modifier=0.55,
            entities=[url for url, _ in under_linked],
            owner_role=context.owner(self.name),
            recommended_actions=[
                f"Add 3-5 contextual internal links to each page from relevant, well-linked "
                f"pages (current threshold: {threshold:.0f} unique inlinks).",
                "Use descriptive anchor text matching the target page's primary query.",
                "Add the orphaned URLs to the relevant hub or category page and the XML sitemap.",
                "Re-crawl to confirm every target is reachable within three clicks of the homepage.",
            ],
            risks=[
                "Internal-link gains are modeled from a position assumption rather than "
                "observed; treat the projection as directional.",
            ],
            measurement=["Re-crawl inlink counts; Search Console position for the affected URLs"],
        )
        for url, page in sorted(
            under_linked, key=lambda item: item[1].impressions or 0, reverse=True
        )[:10]:
            opportunity.add_evidence(
                "screaming_frog", url,
                f"{page.internal_inlinks} unique inlinks, {page.impressions:,} impressions, "
                f"avg position {page.avg_position or 0:.1f}",
                Confidence.OBSERVED,
            )
        return [opportunity]


# -- helpers ---------------------------------------------------------------

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _vitals_uplift(
    page, lcp_elasticity: float, inp_elasticity: float,
    cls_elasticity: float, max_uplift: float,
) -> tuple[float, list[str]]:
    """Modeled conversion uplift from bringing a page's vitals to "good"."""
    uplift = 0.0
    deficits: list[str] = []

    if page.lcp_ms and page.lcp_ms > CWV_TARGETS["lcp_ms"]:
        seconds = (page.lcp_ms - CWV_TARGETS["lcp_ms"]) / 1000.0
        uplift += seconds * lcp_elasticity
        deficits.append("lcp_ms")
    if page.inp_ms and page.inp_ms > CWV_TARGETS["inp_ms"]:
        uplift += ((page.inp_ms - CWV_TARGETS["inp_ms"]) / 100.0) * inp_elasticity
        deficits.append("inp_ms")
    if page.cls and page.cls > CWV_TARGETS["cls"]:
        uplift += ((page.cls - CWV_TARGETS["cls"]) / 0.1) * cls_elasticity
        deficits.append("cls")

    return clamp(uplift, 0.0, max_uplift), deficits


def _format_vital(name: str, value) -> str:
    if value is None:
        return "n/a"
    if name == "cls":
        return f"{value:.3f}"
    return f"{value:,.0f}ms"


def _cwv_actions(deficits: list[str]) -> list[str]:
    """Concrete remediation steps for the specific vitals that are failing."""
    actions: list[str] = []
    if "lcp_ms" in deficits:
        actions.extend([
            "Preload the LCP image and serve it in a modern format at the rendered size.",
            "Cut render-blocking CSS/JS above the fold; inline critical CSS.",
            "Move the hero image out of any client-side-rendered component.",
        ])
    if "inp_ms" in deficits:
        actions.extend([
            "Break up long JavaScript tasks and defer non-essential third-party scripts.",
            "Audit tag manager payload; remove or lazy-load anything not needed at first input.",
        ])
    if "cls" in deficits:
        actions.extend([
            "Set explicit width/height or aspect-ratio on images, embeds and ad slots.",
            "Reserve space for late-loading banners, consent dialogs and web fonts.",
        ])
    actions.append("Re-measure in CrUX field data 28 days after deployment, not just in the lab.")
    return actions


def _crawl_actions(issue_type: str) -> list[str]:
    """Remediation steps per crawl issue type."""
    playbook = {
        "server_error": [
            "Reproduce the 5xx responses and check server logs for the failing routes.",
            "Fix or redirect the failing URLs, then request re-crawl.",
            "Add uptime and status-code monitoring so regressions surface before the next crawl.",
        ],
        "broken_page": [
            "Redirect each broken URL to its closest live equivalent, not the homepage.",
            "Fix internal links still pointing at the broken URLs.",
            "Reclaim any external links pointing at them.",
        ],
        "redirect": [
            "Update internal links to point at final destinations, removing redirect hops.",
            "Collapse redirect chains to a single hop.",
        ],
        "missing_title": [
            "Write unique, query-led titles for every affected URL.",
            "Confirm they render server-side and are not overwritten by the CMS template.",
        ],
        "thin_content": [
            "Decide per URL: expand into a genuine answer, consolidate into a stronger page, "
            "or remove it.",
            "Thin pages are also weak retrieval candidates - depth improves both ranking and "
            "citation eligibility.",
        ],
        "slow_response": [
            "Profile server response time for the affected templates and add caching at the edge.",
        ],
    }
    return playbook.get(
        issue_type,
        [f"Review and remediate the '{issue_type.replace('_', ' ')}' findings from the crawl."],
    )
