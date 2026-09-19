"""Overlap deduplication across analyzers.

Several analyzers can legitimately find the same keyword. A query might be
sitting in striking distance, be split across two cannibalizing URLs, *and* have
an unclaimed featured snippet. Each analysis is correct in isolation, but the
clicks behind them are the same clicks - and summing the three projections sells
the same traffic three times.

A human analyst resolves this by eye. This does it explicitly: opportunities
competing for the same demand pool share the value of any entity they both
claim, and the adjustment is recorded on each opportunity so the discount is
visible rather than silent.

The split is equal per claimant. A value-weighted split would be more precise,
but it would need a per-entity value breakdown the analyzers do not produce, and
an equal split is conservative and easy to explain - which matters more in a
number a client will challenge.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from ..core.opportunity import Opportunity
from ..core.schemas import Confidence


def deduplicate_overlap(opportunities: Iterable[Opportunity]) -> dict[str, Any]:
    """Scale down opportunities that claim demand already claimed elsewhere.

    Mutates each opportunity's projection in place and returns a summary of what
    was removed, for reporting.
    """
    items = list(opportunities)
    claimants: dict[tuple[str, str], int] = defaultdict(int)

    for item in items:
        pool = item.demand_pool
        if pool is None:
            continue
        for entity in set(item.entities):
            claimants[(pool, _normalize(entity))] += 1

    total_before = 0.0
    total_after = 0.0
    adjusted = 0

    for item in items:
        total_before += item.projection.annual_run_rate
        pool = item.demand_pool
        if pool is None or not item.entities:
            total_after += item.projection.annual_run_rate
            continue

        entities = {_normalize(entity) for entity in item.entities}
        shares = [1.0 / claimants[(pool, entity)] for entity in entities
                  if claimants.get((pool, entity))]
        factor = (sum(shares) / len(shares)) if shares else 1.0

        if factor < 1.0:
            contested = sum(1 for entity in entities if claimants[(pool, entity)] > 1)
            projection = item.projection
            projection.incremental_sessions *= factor
            projection.known_revenue *= factor
            projection.dark_revenue *= factor
            item.score_components["overlap_factor"] = round(factor, 4)
            item.add_evidence(
                "trailguide",
                "overlap adjustment",
                f"value scaled to {factor:.0%}",
                Confidence.DERIVED,
                note=(
                    f"{contested} of {len(entities)} targeted item(s) are also claimed by other "
                    f"opportunities in the {pool} demand pool; shared value is split equally so "
                    f"the same demand is not counted twice."
                ),
            )
            adjusted += 1
        else:
            item.score_components["overlap_factor"] = 1.0

        total_after += item.projection.annual_run_rate

    contested_entities = sum(1 for count in claimants.values() if count > 1)
    return {
        "opportunities_adjusted": adjusted,
        "contested_entities": contested_entities,
        "total_entities": len(claimants),
        "run_rate_before": round(total_before, 2),
        "run_rate_after": round(total_after, 2),
        "value_removed": round(total_before - total_after, 2),
    }


def _normalize(entity: str) -> str:
    """Normalize an entity label so the same URL or keyword matches itself."""
    return str(entity).strip().lower().rstrip("/")
