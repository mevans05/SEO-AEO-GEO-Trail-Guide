"""Composite scoring across every analyzer's output.

Ranking happens once, centrally, so a technical fix and a content program are
compared on identical terms. The score blends four normalized components:

``value``
    Confidence-adjusted revenue realized inside the horizon. Size matters.

``efficiency``
    That value per person-day. This is what stops a large, slow program from
    crowding out several fast ones that together deliver more.

``speed``
    How quickly value starts landing. A 12-month target cannot be hit with
    work that ramps in month 11.

``confidence``
    How much of the projection is observed rather than modeled, so a
    well-evidenced opportunity outranks a speculative one of equal size.

Weights are configurable per client, which is how a team expresses "we need
revenue this quarter" versus "we are building for next year" without
hand-editing a ranked list.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from ..core.coerce import clamp
from ..core.opportunity import Opportunity

#: Default component weights; overridden under ``scoring.weights`` in config.
DEFAULT_WEIGHTS: dict[str, float] = {
    "value": 0.35,
    "efficiency": 0.35,
    "speed": 0.15,
    "confidence": 0.15,
}


def _normalize(values: Sequence[float]) -> list[float]:
    """Scale values to ``[0, 1]`` by their maximum, treating all-zero as all-zero."""
    peak = max(values) if values else 0.0
    if peak <= 0:
        return [0.0 for _ in values]
    return [clamp(value / peak, 0.0, 1.0) for value in values]


def _time_to_value(opportunity: Opportunity) -> float:
    """Months until the opportunity reaches half its run rate."""
    projection = opportunity.projection
    return projection.lag_months + (projection.ramp_months / 2.0)


def score_opportunities(
    opportunities: Iterable[Opportunity],
    weights: dict[str, float] | None = None,
) -> list[Opportunity]:
    """Score and rank opportunities in place, returning them best-first.

    Enabling work (zero projected revenue) scores zero by construction and is
    ranked at the end; the portfolio builder funds it from reserved capacity
    rather than from this ranking.
    """
    items = list(opportunities)
    if not items:
        return []

    resolved = dict(DEFAULT_WEIGHTS)
    resolved.update({key: float(value) for key, value in (weights or {}).items()})
    weight_total = sum(resolved.values()) or 1.0

    values = [item.expected_value for item in items]
    efficiencies = [item.value_per_day for item in items]
    times = [_time_to_value(item) for item in items]
    slowest = max(times) if times else 1.0

    value_norm = _normalize(values)
    efficiency_norm = _normalize(efficiencies)
    speed_norm = [
        clamp(1.0 - (time / slowest), 0.0, 1.0) if slowest > 0 else 1.0 for time in times
    ]

    for index, item in enumerate(items):
        components = {
            "value": value_norm[index],
            "efficiency": efficiency_norm[index],
            "speed": speed_norm[index],
            "confidence": item.effective_confidence,
        }
        item.score = 100.0 * sum(
            components[name] * resolved.get(name, 0.0) for name in components
        ) / weight_total
        # Preserve anything an analyzer pre-set (e.g. enabling revenue_at_stake).
        item.score_components.update({
            **{f"{name}_norm": value for name, value in components.items()},
            "expected_value": item.expected_value,
            "value_per_day": item.value_per_day,
            "effort_days": item.effort.total_days,
            "delivery_cost": item.effort.total_cost,
            "months_to_half_value": times[index],
            "roi": item.roi if item.roi is not None else 0.0,
        })

    items.sort(key=lambda item: (item.score, item.expected_value), reverse=True)
    for rank, item in enumerate(items, start=1):
        item.rank = rank
    return items
