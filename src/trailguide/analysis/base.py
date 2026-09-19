"""Analyzer framework: context, effort profiles and the registry.

An analyzer answers one question about the data and returns opportunities. It
never reads files, never talks to a vendor API and never decides priority - it
only finds and sizes. Ranking happens once, centrally, in
:mod:`trailguide.prioritize`, so every opportunity competes on the same terms
no matter which analyzer produced it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..config import Config
from ..core.coerce import clamp
from ..core.ctr import CTRModel
from ..core.economics import RevenueModel
from ..core.opportunity import EffortEstimate, Opportunity, ValueProjection
from ..core.schemas import (
    Confidence, Dataset, Intent, KeywordMetric, PageMetric, Surface,
)
from .dark_traffic import DarkTrafficResult

#: Per-opportunity-type delivery assumptions.
#:
#: ``per_unit`` scales with the number of entities in the opportunity;
#: ``base`` is the fixed setup cost paid once. ``lag_months`` is the delay
#: before any value appears and ``ramp_months`` how long it takes to reach full
#: run rate - the two numbers that decide whether an opportunity can contribute
#: to this year's target at all.
DEFAULT_EFFORT_PROFILES: dict[str, dict[str, Any]] = {
    "striking_distance": {
        "per_unit": {"seo": 0.35, "content": 0.60},
        "base": {"seo": 1.0},
        "lag_months": 1.5, "ramp_months": 3.0, "owner": "SEO Lead",
    },
    "content_gap": {
        "per_unit": {"content": 2.50, "seo": 0.50, "design": 0.30},
        "base": {"strategy": 2.0},
        "lag_months": 3.0, "ramp_months": 6.0, "owner": "Content Lead",
    },
    "cannibalization": {
        "per_unit": {"seo": 0.75, "content": 0.50, "engineering": 0.15},
        "base": {"seo": 1.0},
        "lag_months": 1.0, "ramp_months": 2.0, "owner": "SEO Lead",
    },
    "content_decay": {
        "per_unit": {"content": 1.20, "seo": 0.30},
        "base": {"seo": 1.0},
        "lag_months": 1.0, "ramp_months": 3.0, "owner": "Content Lead",
    },
    "core_web_vitals": {
        "per_unit": {"engineering": 1.50, "design": 0.25},
        "base": {"engineering": 3.0},
        "lag_months": 0.5, "ramp_months": 2.0, "owner": "Engineering Lead",
    },
    "crawl_health": {
        "per_unit": {"seo": 0.20, "engineering": 0.30},
        "base": {"seo": 1.0},
        "lag_months": 0.5, "ramp_months": 1.5, "owner": "SEO Lead",
    },
    "indexation": {
        "per_unit": {"seo": 0.25, "engineering": 0.20},
        "base": {"seo": 1.0},
        "lag_months": 1.0, "ramp_months": 2.0, "owner": "SEO Lead",
    },
    "internal_linking": {
        "per_unit": {"seo": 0.15, "engineering": 0.10},
        "base": {"seo": 2.0},
        "lag_months": 1.0, "ramp_months": 2.0, "owner": "SEO Lead",
    },
    "answer_capture": {
        "per_unit": {"content": 0.80, "seo": 0.40},
        "base": {"seo": 1.0},
        "lag_months": 1.5, "ramp_months": 3.0, "owner": "AEO Lead",
    },
    "citation_gap": {
        "per_unit": {"content": 2.00, "seo": 0.75, "strategy": 0.50},
        "base": {"strategy": 3.0},
        "lag_months": 2.0, "ramp_months": 5.0, "owner": "AEO Lead",
    },
    "retrieval_readiness": {
        "per_unit": {"engineering": 0.50, "seo": 0.40},
        "base": {"engineering": 2.0},
        "lag_months": 1.0, "ramp_months": 3.0, "owner": "Engineering Lead",
    },
    "conversion_rate": {
        "per_unit": {"design": 1.00, "engineering": 1.00, "analytics": 0.50},
        "base": {"analytics": 2.0},
        "lag_months": 1.0, "ramp_months": 2.0, "owner": "CRO Lead",
    },
    "distribution": {
        "per_unit": {"content": 0.80, "outreach": 0.50},
        "base": {"strategy": 1.0},
        "lag_months": 0.5, "ramp_months": 2.0, "owner": "Distribution Lead",
    },
    "measurement": {
        "per_unit": {"analytics": 2.00, "engineering": 1.00},
        "base": {"analytics": 3.0},
        "lag_months": 0.0, "ramp_months": 1.0, "owner": "Analytics Lead",
    },
}

#: Fallback when an opportunity type has no profile.
_FALLBACK_PROFILE: dict[str, Any] = {
    "per_unit": {"seo": 0.5},
    "base": {"seo": 1.0},
    "lag_months": 1.0, "ramp_months": 3.0, "owner": "SEO Lead",
}


@dataclass
class AnalysisContext:
    """Everything an analyzer needs, prepared once per run.

    Building the merged page and keyword indexes here means the cost is paid
    once rather than by every analyzer, and every analyzer sees exactly the same
    consolidated view of the data.
    """

    dataset: Dataset
    config: Config
    revenue: RevenueModel
    ctr: CTRModel
    dark: DarkTrafficResult
    pages: dict[str, PageMetric] = field(default_factory=dict)
    keywords: dict[str, KeywordMetric] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        dataset: Dataset,
        config: Config,
        revenue: RevenueModel,
        ctr: CTRModel,
        dark: DarkTrafficResult,
    ) -> "AnalysisContext":
        return cls(
            dataset=dataset,
            config=config,
            revenue=revenue,
            ctr=ctr,
            dark=dark,
            pages=dataset.page_index(),
            keywords=dataset.keyword_index(),
        )

    @property
    def horizon_months(self) -> int:
        return self.config.horizon_months

    def settings(self, analyzer_name: str) -> dict[str, Any]:
        return self.config.analyzer_settings(analyzer_name)

    def cluster_multiplier(self, *labels: str | None) -> float:
        """Strategic weight for the first label matching a configured cluster.

        Lets strategy tilt a data-derived ranking without overriding it: the
        multiplier is applied to expected value and always shown in the output.
        """
        multipliers = self.config.strategic_multipliers
        if not multipliers:
            return 1.0
        for label in labels:
            if not label:
                continue
            text = str(label).strip().lower()
            if text in multipliers:
                return multipliers[text]
            for key, value in multipliers.items():
                if key in text:
                    return value
        return 1.0

    # -- shared valuation --------------------------------------------------

    def project(
        self,
        incremental_sessions: float,
        surface: Surface,
        *,
        intent: Intent | str | None = None,
        template: str | None = None,
        observed_revenue_per_session: float | None = None,
        lag_months: float = 1.0,
        ramp_months: float = 3.0,
        base_uncertainty: float = 0.30,
        include_dark: bool = True,
    ) -> ValueProjection:
        """Turn incremental sessions into a two-track, phased revenue projection.

        Known value comes from the revenue model. Dark value is the known value
        grossed up by the surface's Track 2 multiplier, so an SEO win is credited
        with the zero-click demand it also generates and a GEO win with the
        assistant-mediated demand that never shows a referrer.

        Uncertainty blends the analyzer's own confidence in the session estimate
        with the dispersion between dark-traffic estimators, weighted by how much
        of the projection is modeled.
        """
        value = self.revenue.value_of_sessions(
            sessions=incremental_sessions,
            intent=intent,
            template=template,
            observed_revenue_per_session=observed_revenue_per_session,
        )
        known_revenue = value.revenue
        multiplier = self.dark.multiplier_for(surface.value) if include_dark else 0.0
        dark_revenue = known_revenue * multiplier

        total = known_revenue + dark_revenue
        dark_share = (dark_revenue / total) if total > 0 else 0.0
        dark_uncertainty = self.dark.uncertainty_for(surface.value)
        blended_uncertainty = clamp(
            base_uncertainty * (1.0 - dark_share) + dark_uncertainty * dark_share,
            0.10, 0.95,
        )

        # B2B revenue lands after the sales cycle, on top of the SEO lag.
        total_lag = lag_months + self.revenue.revenue_lag_months
        return ValueProjection(
            incremental_sessions=incremental_sessions,
            known_revenue=known_revenue,
            dark_revenue=dark_revenue,
            gross_margin=self.revenue.gross_margin,
            lag_months=total_lag,
            ramp_months=ramp_months,
            horizon_months=self.horizon_months,
            uncertainty=blended_uncertainty,
            currency=self.revenue.currency,
        )

    def effort(
        self,
        opportunity_type: str,
        units: float = 1.0,
        scale: float = 1.0,
        notes: str | None = None,
    ) -> EffortEstimate:
        """Build an effort estimate from the configured profile for a type."""
        profile = self.effort_profile(opportunity_type)
        days: dict[str, float] = {}
        for discipline, per_unit in (profile.get("per_unit") or {}).items():
            days[discipline] = days.get(discipline, 0.0) + float(per_unit) * units * scale
        for discipline, base_days in (profile.get("base") or {}).items():
            days[discipline] = days.get(discipline, 0.0) + float(base_days)
        return EffortEstimate(
            days_by_discipline={k: round(v, 2) for k, v in days.items() if v > 0},
            cost_per_day=self.config.cost_per_day,
            notes=notes,
        )

    def effort_profile(self, opportunity_type: str) -> dict[str, Any]:
        """Effort profile for a type, with config overriding built-in defaults."""
        profile = dict(DEFAULT_EFFORT_PROFILES.get(opportunity_type, _FALLBACK_PROFILE))
        override = self.config.effort_profile(opportunity_type)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(profile.get(key), dict):
                merged = dict(profile[key])
                merged.update(value)
                profile[key] = merged
            else:
                profile[key] = value
        return profile

    def timing(self, opportunity_type: str) -> tuple[float, float]:
        """``(lag_months, ramp_months)`` for an opportunity type."""
        profile = self.effort_profile(opportunity_type)
        return float(profile.get("lag_months", 1.0)), float(profile.get("ramp_months", 3.0))

    def owner(self, opportunity_type: str) -> str:
        return str(self.effort_profile(opportunity_type).get("owner", "SEO Lead"))


class Analyzer(ABC):
    """Finds and sizes one class of opportunity."""

    #: Registry key, also used in config to enable/disable and tune.
    name: str = ""
    #: Surface the resulting opportunities act on.
    surface: Surface = Surface.SEO
    #: One-line description surfaced by ``trailguide analyzers``.
    description: str = ""
    #: Dataset collections that must be non-empty for this analyzer to run.
    required_inputs: tuple[str, ...] = ()
    #: Collections that materially improve the analysis when present.
    optional_inputs: tuple[str, ...] = ()

    def runnable(self, context: AnalysisContext) -> tuple[bool, str]:
        """Whether required inputs are present, and why not when they are missing."""
        missing = [
            name for name in self.required_inputs
            if not getattr(context.dataset, name, None)
        ]
        if missing:
            return False, f"missing required input data: {', '.join(missing)}"
        return True, ""

    @abstractmethod
    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        """Return the opportunities this analyzer finds in the data."""

    # -- helpers ---------------------------------------------------------

    def settings(self, context: AnalysisContext) -> dict[str, Any]:
        """Config settings for this analyzer, merged over shared defaults."""
        return context.settings(self.name)

    def setting(self, context: AnalysisContext, key: str, default: Any) -> Any:
        """One setting with a type-preserving default."""
        value = self.settings(context).get(key, default)
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, float):
            return float(value)
        if isinstance(default, int) and not isinstance(value, bool):
            return int(value)
        return value


#: Registry of analyzer classes by name.
_ANALYZERS: dict[str, type[Analyzer]] = {}


def register_analyzer(cls: type[Analyzer]) -> type[Analyzer]:
    """Class decorator registering an analyzer under its ``name``."""
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a 'name'")
    existing = _ANALYZERS.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(f"analyzer '{cls.name}' already registered by {existing.__name__}")
    _ANALYZERS[cls.name] = cls
    return cls


def registered_analyzers() -> list[type[Analyzer]]:
    """All registered analyzer classes, sorted by name."""
    return sorted(_ANALYZERS.values(), key=lambda cls: cls.name)


def select_analyzers(
    enabled: Iterable[str] | None, disabled: Iterable[str] | None = None
) -> list[Analyzer]:
    """Instantiate the analyzers a config selects.

    ``enabled`` of ``None`` means "everything registered", which keeps a new
    analyzer live for existing clients without a config edit.
    """
    disabled_set = {str(name).lower() for name in (disabled or [])}
    if enabled is None:
        chosen = [cls for cls in registered_analyzers() if cls.name not in disabled_set]
    else:
        wanted = [str(name).lower() for name in enabled]
        unknown = [name for name in wanted if name not in _ANALYZERS]
        if unknown:
            raise ValueError(
                f"unknown analyzer(s) in config: {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(_ANALYZERS))}"
            )
        chosen = [_ANALYZERS[name] for name in wanted if name not in disabled_set]
    return [cls() for cls in chosen]


def evidence_confidence(*sources: str) -> Confidence:
    """Pick the confidence tier implied by the sources backing a finding."""
    first_party = {"gsc", "ga4", "search_console", "analytics", "hubspot", "crm"}
    if any(str(source).lower() in first_party for source in sources):
        return Confidence.OBSERVED
    return Confidence.DERIVED
