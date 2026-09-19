"""The opportunity record: what every analyzer emits and the engine ranks.

An opportunity bundles four things an analyst would otherwise assemble by hand:

* **Evidence** - the observed datapoints that prove the opportunity is real.
* **Projection** - the modeled revenue, split into known (Track 1) and dark
  (Track 2) components, phased over the planning horizon.
* **Effort** - the work required, in person-days by discipline.
* **Confidence** - how much of the projection is observed versus modeled.

Ranking divides in-horizon value by effort, so the output is a value-per-
person-day ordering rather than a subjective priority label.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .coerce import clamp
from .schemas import Confidence, Evidence, Surface, _as_dict


def _realization_curve(lag_months: float, ramp_months: float, horizon_months: int) -> list[float]:
    """Monthly share of run-rate value realized, given a lag and a linear ramp.

    Month ``m`` yields nothing until the lag elapses, then climbs linearly to
    full run-rate over ``ramp_months``. This is what separates a technical fix
    that pays back next month from a content program that pays back in Q4.
    """
    ramp = max(0.25, float(ramp_months))
    curve: list[float] = []
    for month in range(1, int(horizon_months) + 1):
        elapsed = month - float(lag_months)
        if elapsed <= 0:
            curve.append(0.0)
        else:
            curve.append(clamp(elapsed / ramp, 0.0, 1.0))
    return curve


@dataclass
class ValueProjection:
    """Modeled value of an opportunity, split by measurement track.

    ``known_*`` is Track 1 (directly attributable); ``dark_*`` is Track 2
    (modeled zero-click, LLM-influenced and unassigned demand). They are kept
    separate all the way into the report so a client can accept the observed
    number and interrogate the modeled one.
    """

    incremental_sessions: float = 0.0
    known_revenue: float = 0.0
    dark_revenue: float = 0.0
    gross_margin: float = 1.0
    lag_months: float = 1.0
    ramp_months: float = 3.0
    horizon_months: int = 12
    #: Relative uncertainty applied symmetrically to produce the range, 0-1.
    uncertainty: float = 0.35
    currency: str = "USD"

    @property
    def annual_run_rate(self) -> float:
        """Steady-state annual revenue once the opportunity is fully realized."""
        return self.known_revenue + self.dark_revenue

    @property
    def realization_curve(self) -> list[float]:
        """Per-month realization fractions across the planning horizon."""
        return _realization_curve(self.lag_months, self.ramp_months, self.horizon_months)

    @property
    def monthly_revenue(self) -> list[float]:
        """Revenue landing in each month of the horizon."""
        monthly_run_rate = self.annual_run_rate / 12.0
        return [monthly_run_rate * fraction for fraction in self.realization_curve]

    @property
    def horizon_revenue(self) -> float:
        """Revenue actually realized inside the planning horizon.

        This - not the annual run rate - is what gets measured against the
        revenue target, because a program that ramps in month 11 contributes
        almost nothing to a 12-month goal.
        """
        return sum(self.monthly_revenue)

    @property
    def horizon_gross_profit(self) -> float:
        return self.horizon_revenue * self.gross_margin

    @property
    def dark_share(self) -> float:
        """Share of the projection that is modeled rather than observed."""
        total = self.annual_run_rate
        return (self.dark_revenue / total) if total else 0.0

    @property
    def range_low(self) -> float:
        return self.horizon_revenue * (1.0 - clamp(self.uncertainty, 0.0, 0.95))

    @property
    def range_high(self) -> float:
        return self.horizon_revenue * (1.0 + clamp(self.uncertainty, 0.0, 0.95))

    def to_dict(self) -> dict[str, Any]:
        return {
            "incremental_sessions": round(self.incremental_sessions, 1),
            "known_revenue": round(self.known_revenue, 2),
            "dark_revenue": round(self.dark_revenue, 2),
            "annual_run_rate": round(self.annual_run_rate, 2),
            "horizon_revenue": round(self.horizon_revenue, 2),
            "horizon_gross_profit": round(self.horizon_gross_profit, 2),
            "range_low": round(self.range_low, 2),
            "range_high": round(self.range_high, 2),
            "dark_share": round(self.dark_share, 4),
            "lag_months": self.lag_months,
            "ramp_months": self.ramp_months,
            "horizon_months": self.horizon_months,
            "monthly_revenue": [round(value, 2) for value in self.monthly_revenue],
            "currency": self.currency,
        }


@dataclass
class EffortEstimate:
    """Work required, in person-days by discipline.

    Disciplines matter because capacity is not fungible: a quarter with 40 spare
    engineering days and no content days cannot ship a content program.
    """

    days_by_discipline: dict[str, float] = field(default_factory=dict)
    cost_per_day: dict[str, float] = field(default_factory=dict)
    default_cost_per_day: float = 900.0
    notes: str | None = None

    @property
    def total_days(self) -> float:
        return sum(self.days_by_discipline.values())

    @property
    def total_cost(self) -> float:
        """Fully loaded cost of delivering the opportunity."""
        return sum(
            days * self.cost_per_day.get(discipline, self.default_cost_per_day)
            for discipline, days in self.days_by_discipline.items()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "days_by_discipline": {k: round(v, 2) for k, v in self.days_by_discipline.items()},
            "total_days": round(self.total_days, 2),
            "total_cost": round(self.total_cost, 2),
            "notes": self.notes,
        }


@dataclass
class Opportunity:
    """A single prioritized recommendation with its full supporting case."""

    title: str
    opportunity_type: str
    surface: Surface
    projection: ValueProjection
    effort: EffortEstimate
    confidence: Confidence = Confidence.DERIVED
    #: Extra confidence discount in ``[0, 1]`` for thin samples or weak signals.
    confidence_modifier: float = 1.0
    evidence: list[Evidence] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    owner_role: str = "SEO Lead"
    dependencies: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    measurement: list[str] = field(default_factory=list)
    strategic_multiplier: float = 1.0
    tags: list[str] = field(default_factory=list)
    #: Overrides the surface-derived demand pool. Opportunities sharing a pool
    #: compete for the same finite demand and are deduplicated against each
    #: other; ``"none"`` opts out entirely (conversion- or efficiency-driven
    #: work, which creates value without claiming additional clicks).
    demand_pool_override: str | None = None
    #: Populated by the scoring engine.
    score: float = 0.0
    rank: int | None = None
    score_components: dict[str, float] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Stable identifier derived from type and entities.

        Deterministic across runs so a roadmap item can be tracked month over
        month even as its score moves.
        """
        seed = f"{self.opportunity_type}|{'|'.join(sorted(self.entities))[:512]}|{self.title}"
        return f"{self.opportunity_type[:12].upper().replace(' ', '_')}-{hashlib.sha1(seed.encode()).hexdigest()[:8]}"

    @property
    def demand_pool(self) -> str | None:
        """The finite pool of demand this opportunity claims, if any.

        Search and answer-engine work compete for the same organic clicks;
        generative work competes for assistant answers. Conversion, performance
        and distribution work claims no additional demand, so it is excluded
        from deduplication and keeps its full value.
        """
        if self.demand_pool_override is not None:
            return None if self.demand_pool_override == "none" else self.demand_pool_override
        if self.surface in (Surface.SEO, Surface.AEO):
            return "search"
        if self.surface is Surface.GEO:
            return "generative"
        return None

    @property
    def effective_confidence(self) -> float:
        """Blended confidence in ``[0, 1]`` used to risk-adjust value."""
        return clamp(self.confidence.weight * self.confidence_modifier, 0.0, 1.0)

    @property
    def expected_value(self) -> float:
        """Confidence-adjusted, strategy-weighted revenue inside the horizon."""
        return self.projection.horizon_revenue * self.effective_confidence * self.strategic_multiplier

    @property
    def expected_gross_profit(self) -> float:
        return self.expected_value * self.projection.gross_margin

    @property
    def roi(self) -> float | None:
        """Return on delivery cost. ``None`` when the opportunity is free."""
        cost = self.effort.total_cost
        if cost <= 0:
            return None
        return (self.expected_gross_profit - cost) / cost

    @property
    def value_per_day(self) -> float:
        """Expected in-horizon value per person-day - the core ranking signal."""
        days = self.effort.total_days
        if days <= 0:
            return self.expected_value
        return self.expected_value / days

    def add_evidence(
        self,
        source: str,
        metric: str,
        value: Any,
        confidence: Confidence = Confidence.OBSERVED,
        note: str | None = None,
    ) -> "Opportunity":
        """Attach a supporting datapoint and return self for chaining."""
        self.evidence.append(Evidence(source, metric, value, confidence, note))
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rank": self.rank,
            "title": self.title,
            "opportunity_type": self.opportunity_type,
            "surface": self.surface.value,
            "score": round(self.score, 4),
            "score_components": {k: round(v, 4) for k, v in self.score_components.items()},
            "confidence": self.confidence.value,
            "effective_confidence": round(self.effective_confidence, 3),
            "expected_value": round(self.expected_value, 2),
            "expected_gross_profit": round(self.expected_gross_profit, 2),
            "roi": round(self.roi, 3) if self.roi is not None else None,
            "value_per_day": round(self.value_per_day, 2),
            "strategic_multiplier": self.strategic_multiplier,
            "projection": self.projection.to_dict(),
            "effort": self.effort.to_dict(),
            "entities": self.entities[:50],
            "entity_count": len(self.entities),
            "recommended_actions": self.recommended_actions,
            "owner_role": self.owner_role,
            "dependencies": self.dependencies,
            "risks": self.risks,
            "measurement": self.measurement,
            "tags": self.tags,
            "evidence": [_as_dict(item) for item in self.evidence],
        }
