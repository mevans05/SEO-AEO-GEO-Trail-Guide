"""Capacity-constrained portfolio selection against a revenue target.

A ranked list is not a plan. This module answers the question a client actually
asks: given the team we have, what do we do, in what order, and does it add up
to the number we committed to?

Selection is greedy by score under per-discipline, per-quarter capacity. Work
scheduled later realizes less inside the horizon, and the schedule reflects that
by shifting each opportunity's value curve - which is why a high-value item that
cannot start until Q4 may contribute less than a smaller one starting in Q1.

When the portfolio falls short of the target, the shortfall is reported with the
specific constraint that caused it rather than being quietly absorbed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core.coerce import clamp
from ..core.opportunity import Opportunity, ValueProjection

#: Months per planning quarter.
MONTHS_PER_QUARTER = 3


@dataclass
class ScheduledItem:
    """An opportunity placed into the roadmap, with its realized value."""

    opportunity: Opportunity
    start_quarter: int
    end_quarter: int
    realized_revenue: float
    realized_gross_profit: float

    @property
    def realized_low(self) -> float:
        """Lower bound of the realized revenue, from the projection's uncertainty."""
        return self.realized_revenue * (1.0 - clamp(self.opportunity.projection.uncertainty, 0.0, 0.95))

    @property
    def realized_high(self) -> float:
        """Upper bound of the realized revenue, from the projection's uncertainty."""
        return self.realized_revenue * (1.0 + clamp(self.opportunity.projection.uncertainty, 0.0, 0.95))

    @property
    def delivery_cost(self) -> float:
        return self.opportunity.effort.total_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.opportunity.id,
            "title": self.opportunity.title,
            "rank": self.opportunity.rank,
            "surface": self.opportunity.surface.value,
            "opportunity_type": self.opportunity.opportunity_type,
            "owner_role": self.opportunity.owner_role,
            "start_quarter": self.start_quarter,
            "end_quarter": self.end_quarter,
            "effort_days": round(self.opportunity.effort.total_days, 2),
            "delivery_cost": round(self.delivery_cost, 2),
            "realized_revenue": round(self.realized_revenue, 2),
            "realized_revenue_low": round(self.realized_low, 2),
            "realized_revenue_high": round(self.realized_high, 2),
            "realized_gross_profit": round(self.realized_gross_profit, 2),
            "annual_run_rate": round(self.opportunity.projection.annual_run_rate, 2),
            "tags": self.opportunity.tags,
        }


@dataclass
class Portfolio:
    """The selected plan, the work that did not fit, and the revenue bridge."""

    scheduled: list[ScheduledItem] = field(default_factory=list)
    deferred: list[Opportunity] = field(default_factory=list)
    quarters: int = 4
    capacity_total: dict[str, float] = field(default_factory=dict)
    capacity_used: dict[int, dict[str, float]] = field(default_factory=dict)
    target_revenue: float = 0.0
    baseline_revenue: float = 0.0
    currency: str = "USD"
    unconstrained: bool = False

    # -- totals ----------------------------------------------------------

    @property
    def projected_revenue(self) -> float:
        """Incremental revenue realized inside the horizon by the selected work."""
        return sum(item.realized_revenue for item in self.scheduled)

    @property
    def projected_revenue_low(self) -> float:
        """Lower bound of projected revenue across the selected work."""
        return sum(item.realized_low for item in self.scheduled)

    @property
    def projected_revenue_high(self) -> float:
        """Upper bound of projected revenue across the selected work."""
        return sum(item.realized_high for item in self.scheduled)

    @property
    def projected_gross_profit(self) -> float:
        return sum(item.realized_gross_profit for item in self.scheduled)

    @property
    def projected_run_rate(self) -> float:
        """Annual run rate the portfolio reaches once everything is fully ramped."""
        return sum(item.opportunity.projection.annual_run_rate for item in self.scheduled)

    @property
    def total_cost(self) -> float:
        return sum(item.delivery_cost for item in self.scheduled)

    @property
    def total_days(self) -> float:
        return sum(item.opportunity.effort.total_days for item in self.scheduled)

    @property
    def roi(self) -> float | None:
        """Return on the portfolio's delivery cost, on gross profit."""
        if self.total_cost <= 0:
            return None
        return (self.projected_gross_profit - self.total_cost) / self.total_cost

    @property
    def gap_to_target(self) -> float:
        """Shortfall against the target; negative means the target is exceeded."""
        return self.target_revenue - self.projected_revenue

    @property
    def target_attainment(self) -> float | None:
        """Projected revenue as a share of the target."""
        if self.target_revenue <= 0:
            return None
        return self.projected_revenue / self.target_revenue

    @property
    def deferred_value(self) -> float:
        """Unfunded expected value - the cost of the current capacity ceiling."""
        return sum(item.expected_value for item in self.deferred)

    # -- analysis --------------------------------------------------------

    def revenue_bridge(self) -> list[dict[str, Any]]:
        """Baseline to target, step by step, for the executive summary."""
        steps = [
            {"label": "Current attributed revenue (Track 1 + Track 2)",
             "value": round(self.baseline_revenue, 2), "kind": "baseline"},
        ]
        by_surface: dict[str, float] = defaultdict(float)
        for item in self.scheduled:
            by_surface[item.opportunity.surface.value] += item.realized_revenue
        for surface, value in sorted(by_surface.items(), key=lambda kv: kv[1], reverse=True):
            steps.append({
                "label": f"Incremental from {surface}",
                "value": round(value, 2),
                "kind": "increment",
            })
        projected_total = self.baseline_revenue + self.projected_revenue
        steps.append({
            "label": "Projected revenue at horizon",
            "value": round(projected_total, 2),
            "kind": "subtotal",
        })
        if self.target_revenue > 0:
            steps.append({
                "label": "Incremental revenue target",
                "value": round(self.target_revenue, 2),
                "kind": "target",
            })
            steps.append({
                "label": "Gap to target" if self.gap_to_target > 0 else "Surplus over target",
                "value": round(abs(self.gap_to_target), 2),
                "kind": "gap" if self.gap_to_target > 0 else "surplus",
            })
        return steps

    def capacity_utilization(self) -> dict[int, dict[str, dict[str, float]]]:
        """Used, total and remaining days by quarter and discipline."""
        report: dict[int, dict[str, dict[str, float]]] = {}
        for quarter in range(1, self.quarters + 1):
            used = self.capacity_used.get(quarter, {})
            report[quarter] = {
                discipline: {
                    "used": round(used.get(discipline, 0.0), 2),
                    "total": round(total, 2),
                    "remaining": round(total - used.get(discipline, 0.0), 2),
                    "utilization": round(used.get(discipline, 0.0) / total, 3) if total else 0.0,
                }
                for discipline, total in sorted(self.capacity_total.items())
            }
        return report

    def gap_analysis(self) -> dict[str, Any]:
        """Explain any shortfall and what would close it.

        Walks the deferred list in rank order to find how much additional
        capacity - and in which disciplines - would cover the gap. That turns
        "we are short" into a specific, costed ask.
        """
        if self.target_revenue <= 0:
            return {"status": "no_target"}
        if self.gap_to_target <= 0:
            return {
                "status": "on_target",
                "surplus": round(-self.gap_to_target, 2),
                "attainment": round(self.target_attainment or 0.0, 4),
            }

        remaining_gap = self.gap_to_target
        needed_days: dict[str, float] = defaultdict(float)
        needed_items: list[dict[str, Any]] = []
        additional_cost = 0.0

        for opportunity in self.deferred:
            if remaining_gap <= 0:
                break
            # Deferred work would start in Q1 if capacity existed.
            realized = _realized_revenue(opportunity, start_quarter=1, quarters=self.quarters)
            if realized <= 0:
                continue
            remaining_gap -= realized
            additional_cost += opportunity.effort.total_cost
            for discipline, days in opportunity.effort.days_by_discipline.items():
                needed_days[discipline] += days
            needed_items.append({
                "id": opportunity.id,
                "title": opportunity.title,
                "realized_revenue": round(realized, 2),
                "effort_days": round(opportunity.effort.total_days, 2),
            })

        closable = remaining_gap <= 0
        return {
            "status": "short" if not closable else "closable_with_capacity",
            "gap": round(self.gap_to_target, 2),
            "attainment": round(self.target_attainment or 0.0, 4),
            "residual_gap_after_deferred": round(max(0.0, remaining_gap), 2),
            "additional_days_required": {k: round(v, 1) for k, v in sorted(needed_days.items())},
            "additional_delivery_cost": round(additional_cost, 2),
            "unlockable_opportunities": needed_items,
            "note": (
                "The deferred backlog can close the gap if capacity is added in the "
                "disciplines listed."
                if closable else
                "Even with the entire identified backlog funded, the target is not reachable "
                "inside the horizon from the opportunities in this dataset. Revisit the target, "
                "extend the horizon, or widen the input data."
            ),
        }

    def by_quarter(self) -> dict[int, list[ScheduledItem]]:
        """Scheduled items grouped by starting quarter."""
        grouped: dict[int, list[ScheduledItem]] = {
            quarter: [] for quarter in range(1, self.quarters + 1)
        }
        for item in self.scheduled:
            grouped.setdefault(item.start_quarter, []).append(item)
        for items in grouped.values():
            items.sort(key=lambda item: item.opportunity.rank or 999)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "quarters": self.quarters,
            "unconstrained": self.unconstrained,
            "totals": {
                "scheduled_count": len(self.scheduled),
                "deferred_count": len(self.deferred),
                "projected_revenue": round(self.projected_revenue, 2),
                "projected_revenue_low": round(self.projected_revenue_low, 2),
                "projected_revenue_high": round(self.projected_revenue_high, 2),
                "projected_gross_profit": round(self.projected_gross_profit, 2),
                "projected_annual_run_rate": round(self.projected_run_rate, 2),
                "delivery_cost": round(self.total_cost, 2),
                "effort_days": round(self.total_days, 2),
                "roi": round(self.roi, 3) if self.roi is not None else None,
                "baseline_revenue": round(self.baseline_revenue, 2),
                "target_revenue": round(self.target_revenue, 2),
                "gap_to_target": round(self.gap_to_target, 2),
                "target_attainment": (
                    round(self.target_attainment, 4) if self.target_attainment else None
                ),
                "deferred_value": round(self.deferred_value, 2),
            },
            "revenue_bridge": self.revenue_bridge(),
            "gap_analysis": self.gap_analysis(),
            "capacity": self.capacity_utilization(),
            "schedule": {
                str(quarter): [item.to_dict() for item in items]
                for quarter, items in self.by_quarter().items()
            },
            "deferred": [
                {
                    "id": item.id,
                    "title": item.title,
                    "rank": item.rank,
                    "expected_value": round(item.expected_value, 2),
                    "effort_days": round(item.effort.total_days, 2),
                }
                for item in self.deferred[:50]
            ],
        }


def _realized_revenue(opportunity: Opportunity, start_quarter: int, quarters: int) -> float:
    """Confidence-adjusted revenue realized inside the horizon, given a start quarter.

    Re-phases the opportunity's own value curve by the months it spends waiting
    for capacity, which is what makes scheduling a real constraint rather than a
    presentational detail. The result is risk-adjusted by the opportunity's
    effective confidence and strategic multiplier, so the portfolio total is
    directly comparable to a revenue target rather than being a best case.
    """
    projection = opportunity.projection
    adjustment = opportunity.effective_confidence * opportunity.strategic_multiplier
    delay_months = (start_quarter - 1) * MONTHS_PER_QUARTER
    if delay_months <= 0:
        return projection.horizon_revenue * adjustment
    delayed = ValueProjection(
        incremental_sessions=projection.incremental_sessions,
        known_revenue=projection.known_revenue,
        dark_revenue=projection.dark_revenue,
        gross_margin=projection.gross_margin,
        lag_months=projection.lag_months + delay_months,
        ramp_months=projection.ramp_months,
        horizon_months=projection.horizon_months,
        uncertainty=projection.uncertainty,
        currency=projection.currency,
    )
    return delayed.horizon_revenue * adjustment


def build_portfolio(
    opportunities: Iterable[Opportunity],
    capacity_per_quarter: dict[str, float],
    quarters: int = 4,
    target_revenue: float = 0.0,
    baseline_revenue: float = 0.0,
    currency: str = "USD",
    reserved_for_enabling: float = 0.10,
) -> Portfolio:
    """Select and schedule opportunities under capacity constraints.

    Enabling work (measurement instrumentation) is funded first from a reserved
    share of capacity, because deferring it means every subsequent quarter is
    planned on weaker evidence. Everything else is then placed greedily by score
    into the earliest quarter with room.
    """
    ranked = sorted(
        opportunities, key=lambda item: (item.rank if item.rank is not None else 10**6)
    )
    unconstrained = not capacity_per_quarter

    portfolio = Portfolio(
        quarters=max(1, quarters),
        capacity_total=dict(capacity_per_quarter),
        target_revenue=target_revenue,
        baseline_revenue=baseline_revenue,
        currency=currency,
        unconstrained=unconstrained,
    )

    if unconstrained:
        # No capacity model: everything is deliverable, starting immediately.
        for opportunity in ranked:
            portfolio.scheduled.append(
                ScheduledItem(
                    opportunity=opportunity,
                    start_quarter=1,
                    end_quarter=1,
                    realized_revenue=_realized_revenue(opportunity, 1, portfolio.quarters),
                    realized_gross_profit=(
                        _realized_revenue(opportunity, 1, portfolio.quarters)
                        * opportunity.projection.gross_margin
                    ),
                )
            )
        portfolio.capacity_used = {quarter: {} for quarter in range(1, portfolio.quarters + 1)}
        return portfolio

    remaining: dict[int, dict[str, float]] = {
        quarter: dict(capacity_per_quarter) for quarter in range(1, portfolio.quarters + 1)
    }
    used: dict[int, dict[str, float]] = {
        quarter: defaultdict(float) for quarter in range(1, portfolio.quarters + 1)
    }

    enabling = [item for item in ranked if "enabling" in item.tags]
    regular = [item for item in ranked if "enabling" not in item.tags]

    # Enabling work competes only against a reserved slice of capacity, ordered
    # by the revenue its absence leaves unmeasured.
    reserve_fraction = clamp(reserved_for_enabling, 0.0, 0.5)
    reserve: dict[int, dict[str, float]] = {
        quarter: {
            discipline: days * reserve_fraction
            for discipline, days in capacity_per_quarter.items()
        }
        for quarter in range(1, portfolio.quarters + 1)
    }
    enabling.sort(
        key=lambda item: item.score_components.get("revenue_at_stake", 0.0), reverse=True
    )

    for opportunity in enabling:
        placed = _place(opportunity, reserve, remaining, used, portfolio.quarters, use_reserve=True)
        if placed is None:
            portfolio.deferred.append(opportunity)
            continue
        start_quarter, end_quarter = placed
        portfolio.scheduled.append(
            ScheduledItem(opportunity, start_quarter, end_quarter, 0.0, 0.0)
        )

    for opportunity in regular:
        placed = _place(opportunity, reserve, remaining, used, portfolio.quarters, use_reserve=False)
        if placed is None:
            portfolio.deferred.append(opportunity)
            continue
        start_quarter, end_quarter = placed
        realized = _realized_revenue(opportunity, start_quarter, portfolio.quarters)
        portfolio.scheduled.append(
            ScheduledItem(
                opportunity=opportunity,
                start_quarter=start_quarter,
                end_quarter=end_quarter,
                realized_revenue=realized,
                realized_gross_profit=realized * opportunity.projection.gross_margin,
            )
        )

    portfolio.capacity_used = {quarter: dict(days) for quarter, days in used.items()}
    portfolio.scheduled.sort(
        key=lambda item: (item.start_quarter, item.opportunity.rank or 10**6)
    )
    portfolio.deferred.sort(key=lambda item: item.rank or 10**6)
    return portfolio


def _place(
    opportunity: Opportunity,
    reserve: dict[int, dict[str, float]],
    remaining: dict[int, dict[str, float]],
    used: dict[int, dict[str, float]],
    quarters: int,
    use_reserve: bool,
) -> tuple[int, int] | None:
    """Allocate an opportunity's days, spreading across quarters when needed.

    Returns ``(start_quarter, end_quarter)``, or ``None`` when the work cannot
    fit inside the horizon at all.
    """
    required = dict(opportunity.effort.days_by_discipline)
    if not required:
        return (1, 1)

    # A discipline the capacity model does not mention cannot be scheduled.
    unknown = [name for name in required if name not in remaining[1]]
    if unknown:
        return None

    outstanding = dict(required)
    start_quarter: int | None = None
    end_quarter = 1

    for quarter in range(1, quarters + 1):
        if not outstanding:
            break
        progressed = False
        for discipline in list(outstanding):
            needed = outstanding[discipline]
            if needed <= 0:
                del outstanding[discipline]
                continue
            pool = reserve[quarter] if use_reserve else remaining[quarter]
            # Non-enabling work may not consume the enabling reserve.
            available = (
                pool.get(discipline, 0.0) if use_reserve
                else max(0.0, remaining[quarter].get(discipline, 0.0)
                         - reserve[quarter].get(discipline, 0.0))
            )
            if available <= 0:
                continue
            allocated = min(available, needed)
            if use_reserve:
                reserve[quarter][discipline] -= allocated
            remaining[quarter][discipline] = max(
                0.0, remaining[quarter].get(discipline, 0.0) - allocated
            )
            used[quarter][discipline] += allocated
            outstanding[discipline] = needed - allocated
            if outstanding[discipline] <= 1e-9:
                del outstanding[discipline]
            progressed = True
            if start_quarter is None:
                start_quarter = quarter
            end_quarter = quarter
        del progressed    # a quarter with no free capacity simply contributes nothing

    if outstanding or start_quarter is None:
        # Roll back partial allocations so a rejected item frees its capacity.
        _rollback(required, outstanding, reserve, remaining, used, quarters, use_reserve)
        return None
    return (start_quarter, end_quarter)


def _rollback(
    required: dict[str, float],
    outstanding: dict[str, float],
    reserve: dict[int, dict[str, float]],
    remaining: dict[int, dict[str, float]],
    used: dict[int, dict[str, float]],
    quarters: int,
    use_reserve: bool,
) -> None:
    """Return capacity consumed by an item that ultimately could not be placed."""
    for discipline, total in required.items():
        to_return = total - outstanding.get(discipline, 0.0)
        for quarter in range(1, quarters + 1):
            if to_return <= 0:
                break
            consumed = min(to_return, used[quarter].get(discipline, 0.0))
            if consumed <= 0:
                continue
            used[quarter][discipline] -= consumed
            remaining[quarter][discipline] = remaining[quarter].get(discipline, 0.0) + consumed
            if use_reserve:
                reserve[quarter][discipline] = reserve[quarter].get(discipline, 0.0) + consumed
            to_return -= consumed
