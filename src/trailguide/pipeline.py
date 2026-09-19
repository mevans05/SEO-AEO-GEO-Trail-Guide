"""End-to-end run: load sources, model, analyze, prioritize, schedule.

The whole point of the system is that this sequence is deterministic and
repeatable. The same exports produce the same ranked portfolio every time, and
every number carries provenance back to the file it came from - which is what
makes the output reviewable in the time an analyst would otherwise spend
building it.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from .analysis import model_dark_traffic, select_analyzers
from .analysis.base import AnalysisContext
from .analysis.dark_traffic import DarkTrafficResult
from .config import Config
from .connectors import load_sources
from .core.ctr import CTRModel
from .core.economics import RevenueModel
from .core.opportunity import Opportunity
from .core.schemas import Dataset
from .prioritize import Portfolio, build_portfolio, score_opportunities
from .prioritize.overlap import PAGE_DEMAND_VISIBILITY, build_demand_map, deduplicate_overlap
from .__init__ import __version__


@dataclass
class RunResult:
    """Everything one analysis run produced."""

    config: Config
    dataset: Dataset
    manifest: list[dict[str, Any]]
    revenue: RevenueModel
    ctr: CTRModel
    dark: DarkTrafficResult
    opportunities: list[Opportunity]
    portfolio: Portfolio
    overlap: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    analyzer_log: list[dict[str, Any]] = field(default_factory=list)
    generated_at: _dt.datetime = field(default_factory=_dt.datetime.now)
    version: str = __version__

    @property
    def baseline_revenue(self) -> float:
        """Current attributed revenue: configured value, else the modeled baseline."""
        configured = self.config.baseline_revenue
        return configured if configured > 0 else self.dark.total_attributed_revenue

    def summary(self) -> dict[str, Any]:
        """Compact run summary for JSON export and the CLI."""
        return {
            "generated_at": self.generated_at.isoformat(timespec="seconds"),
            "version": self.version,
            "client": self.config.client_name,
            "domain": self.config.domain,
            "currency": self.config.currency,
            "horizon_months": self.config.horizon_months,
            "opportunities_found": len(self.opportunities),
            "scheduled": len(self.portfolio.scheduled),
            "deferred": len(self.portfolio.deferred),
            "baseline_revenue": round(self.baseline_revenue, 2),
            "target_revenue": round(self.config.revenue_target, 2),
            "projected_revenue": round(self.portfolio.projected_revenue, 2),
            "target_attainment": (
                round(self.portfolio.target_attainment, 4)
                if self.portfolio.target_attainment else None
            ),
            "input_coverage": self.dataset.coverage(),
            "sources_loaded": sorted(self.dataset.sources()),
            "warnings": self.warnings,
        }

    def to_dict(self) -> dict[str, Any]:
        """Full machine-readable result, suitable for a dashboard or a diff."""
        return {
            "summary": self.summary(),
            "economics": self.revenue.describe(),
            "dark_traffic": self.dark.to_dict(),
            "overlap": self.overlap,
            "portfolio": self.portfolio.to_dict(),
            "opportunities": [item.to_dict() for item in self.opportunities],
            "sources": self.manifest,
            "analyzers": self.analyzer_log,
        }


def _plausibility_warnings(
    opportunities: list[Opportunity], dark: DarkTrafficResult, config: Config
) -> list[str]:
    """Flag aggregate projections that outrun the site's demonstrated baseline."""
    warnings: list[str] = []
    max_share = float(config.get("planning.max_incremental_share_of_baseline", 0.60))

    search_sessions = sum(
        item.projection.incremental_sessions
        for item in opportunities
        if item.demand_pool == "search"
    )
    baseline_sessions = dark.seo.known_sessions
    if baseline_sessions > 0 and search_sessions > baseline_sessions * max_share:
        warnings.append(
            f"projected incremental organic sessions ({search_sessions:,.0f}) are "
            f"{search_sessions / baseline_sessions:.0%} of the current organic baseline "
            f"({baseline_sessions:,.0f}), above the {max_share:.0%} plausibility threshold. "
            f"Check the annualization_factor on keyword sources, the CTR curve, and whether "
            f"the Search Console export window matches what the config assumes."
        )

    generative_sessions = sum(
        item.projection.incremental_sessions
        for item in opportunities
        if item.demand_pool == "generative"
    )
    geo_pool = dark.geo.known_sessions + dark.geo.dark_sessions
    if geo_pool > 0 and generative_sessions > geo_pool:
        warnings.append(
            f"projected generative sessions ({generative_sessions:,.0f}) exceed the entire "
            f"modeled LLM-influenced pool ({geo_pool:,.0f}). The GEO opportunities are claiming "
            f"more influence than the Track 2 model says exists; revisit citation_visit_rate "
            f"and retrieval_visit_rate."
        )
    return warnings


def run(config: Config) -> RunResult:
    """Execute a full analysis run for one client configuration."""
    warnings = list(config.validate())

    # 1. Load every configured source into the canonical dataset.
    def note_source_error(spec, exc: Exception) -> None:
        warnings.append(f"source '{spec.label}' failed to load: {exc}")

    dataset, manifest = load_sources(config, on_error=note_source_error)

    # 2. Build the economic and CTR models this client is measured with.
    revenue = RevenueModel.from_config(config.section("economics"))
    ctr = CTRModel.from_config(config.section("ctr"))

    # Prefer the client's own funnel over configured assumptions wherever the
    # CRM export supports it. This runs before any valuation, so every
    # projection downstream is built on observed rates.
    if dataset.funnel and config.get("economics.calibrate_from_crm", True):
        revenue.calibrate_from_funnel(dataset.funnel)

    # 3. Model Track 2 before anything is valued, since every projection is
    #    grossed up by the dark multiplier for its surface.
    dark = model_dark_traffic(dataset, ctr, revenue, config.section("dark_traffic"))
    for track in (dark.seo, dark.geo):
        if not track.estimates:
            warnings.append(
                f"no Track 2 estimators could run for the {track.track.upper()} surface; "
                f"dark traffic is modeled as zero and total impact is understated."
            )

    # 4. Run the analyzers.
    context = AnalysisContext.build(dataset, config, revenue, ctr, dark)
    analyzers = select_analyzers(config.enabled_analyzers, config.disabled_analyzers)
    opportunities: list[Opportunity] = []
    analyzer_log: list[dict[str, Any]] = []

    for analyzer in analyzers:
        runnable, reason = analyzer.runnable(context)
        if not runnable:
            analyzer_log.append({
                "analyzer": analyzer.name, "status": "skipped",
                "reason": reason, "opportunities": 0,
            })
            continue
        try:
            found = analyzer.analyze(context)
        except Exception as exc:  # noqa: BLE001 - one analyzer must not end the run
            analyzer_log.append({
                "analyzer": analyzer.name, "status": "error",
                "reason": str(exc), "opportunities": 0,
            })
            warnings.append(f"analyzer '{analyzer.name}' failed: {exc}")
            continue
        opportunities.extend(found)
        analyzer_log.append({
            "analyzer": analyzer.name, "status": "ok",
            "reason": "", "opportunities": len(found),
        })

    warnings.extend(context.warnings)

    # 5. Remove double counting before anything is ranked: several analyzers can
    #    legitimately find the same keyword, but the clicks behind it are finite.
    #    Keywords are resolved to the pages they rank on first, so a page-level
    #    claim and a keyword-level claim on the same page contest each other.
    demand_map = build_demand_map(
        dataset,
        page_visibility=float(
            (config.get("analysis.settings.overlap") or {}).get(
                "page_demand_visibility", PAGE_DEMAND_VISIBILITY
            )
        ),
    )
    overlap = deduplicate_overlap(opportunities, demand_map)
    if overlap["opportunities_adjusted"]:
        warnings.append(
            f"overlap adjustment: {overlap['opportunities_adjusted']} opportunities claimed "
            f"demand also claimed elsewhere; "
            f"{overlap['value_removed']:,.0f} {config.currency} of annual run rate was removed "
            f"to avoid counting the same demand twice."
        )

    # 6. Rank once, centrally, so every surface competes on the same terms.
    ranked = score_opportunities(opportunities, config.get("scoring.weights"))

    # 7. Sanity-check the aggregate against the baseline the site actually has.
    #    A portfolio that claims to double organic traffic in a year is almost
    #    always a data or assumption problem, and it is surfaced rather than
    #    silently capped - the analyst needs to see it, not have it hidden.
    warnings.extend(_plausibility_warnings(ranked, dark, config))

    # 8. Schedule under capacity, against the revenue target.
    baseline = config.baseline_revenue or dark.total_attributed_revenue
    portfolio = build_portfolio(
        ranked,
        capacity_per_quarter=config.capacity_per_quarter,
        quarters=config.quarters,
        target_revenue=config.revenue_target,
        baseline_revenue=baseline,
        currency=config.currency,
        reserved_for_enabling=float(config.get("capacity.reserved_for_enabling", 0.10)),
    )

    return RunResult(
        overlap=overlap,
        config=config,
        dataset=dataset,
        manifest=manifest,
        revenue=revenue,
        ctr=ctr,
        dark=dark,
        opportunities=ranked,
        portfolio=portfolio,
        warnings=warnings,
        analyzer_log=analyzer_log,
    )
