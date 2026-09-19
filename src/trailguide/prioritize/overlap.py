"""Overlap deduplication across analyzers.

Several analyzers can legitimately find the same demand. A query might be
sitting in striking distance, be split across two cannibalizing URLs, *and* have
an unclaimed featured snippet. Each analysis is correct in isolation, but the
clicks behind them are the same clicks - and summing the three projections sells
the same traffic three times.

A human analyst resolves this by eye. This does it explicitly: opportunities
competing for the same demand pool share the value of any demand they both
claim, and the adjustment is recorded on each opportunity so the discount is
visible rather than silent.

Demand is resolved to a common unit before contention is counted. Analyzers
claim demand at two different levels - some name keywords, others name URLs -
so a page-level opportunity is expanded into the keywords that page actually
ranks for, drawn from the keyword records themselves. Without that expansion a
decaying page and a striking-distance keyword on that same page look like
unrelated opportunities and both bill for the same clicks.

The expansion is impression-weighted, so contesting one minor query on a page
that ranks for fifty barely touches the page-level projection, while contesting
its head term takes a real bite. Within a single unit of demand the split stays
equal per claimant: a value-weighted split would need a per-entity value
breakdown the analyzers do not produce, and an equal split is conservative and
easy to explain - which matters more in a number a client will challenge.

A keyword export never shows everything a page ranks for: Search Console hides
anonymized long-tail queries and a rank tracker only covers terms someone chose
to track. So a page-level claim is only *partly* exposed to keyword-level
contention, and the rest of its demand is unobserved long tail that no
keyword-level opportunity is claiming. ``PAGE_DEMAND_VISIBILITY`` is the share
assumed to be visible.

That share is deliberately a stated assumption rather than a derived one.
Deriving it would mean comparing keyword impressions against page impressions,
and those two are not on a comparable basis - keyword records mix a one-month
Search Console window with monthly rank-tracker volume, while page records
accumulate across every period in the export. On the sample data that
comparison lands between 1.6x and 31x, which is a units mismatch rather than a
measurement. Naming the assumption is honest; deriving it from mismatched units
would not be.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core.opportunity import Opportunity
from ..core.schemas import Confidence, Dataset

#: Share of a page's demand assumed to be represented by the keywords visible in
#: the export. The remainder is unobserved long tail, which keyword-level
#: opportunities are not claiming and so cannot contest. Override per client with
#: ``analysis.settings.overlap.page_demand_visibility``.
PAGE_DEMAND_VISIBILITY = 0.5


@dataclass
class DemandMap:
    """Which keywords belong to which page, and how much demand each carries.

    Built from the keyword records, so it reflects what the site is actually
    observed to rank for rather than an assumed site structure.
    """

    #: normalized keyword -> normalized landing page URL
    keyword_pages: dict[str, str] = field(default_factory=dict)
    #: normalized page URL -> {normalized keyword: demand weight}
    page_keywords: dict[str, dict[str, float]] = field(default_factory=dict)
    #: Share of a page's demand the visible keywords are assumed to represent.
    page_visibility: float = PAGE_DEMAND_VISIBILITY

    def __bool__(self) -> bool:
        return bool(self.keyword_pages)


def build_demand_map(
    dataset: Dataset, page_visibility: float = PAGE_DEMAND_VISIBILITY
) -> DemandMap:
    """Map keywords to their landing pages, weighted by impressions.

    A keyword seen on several pages is attributed to the one where it earns the
    most impressions: that is the page a ranking change would actually move.
    """
    best: dict[str, tuple[float, str]] = {}
    for record in dataset.keywords:
        keyword = _normalize(record.keyword)
        url = _normalize(record.page_url or "")
        if not keyword or not url:
            continue
        weight = float(record.impressions or 0) or float(record.clicks or 0) or 1.0
        current = best.get(keyword)
        if current is None or weight > current[0]:
            best[keyword] = (weight, url)

    keyword_pages = {keyword: url for keyword, (_, url) in best.items()}
    page_keywords: dict[str, dict[str, float]] = defaultdict(dict)
    for keyword, (weight, url) in best.items():
        page_keywords[url][keyword] = weight
    return DemandMap(
        keyword_pages=keyword_pages,
        page_keywords=dict(page_keywords),
        page_visibility=min(1.0, max(0.0, float(page_visibility))),
    )


def deduplicate_overlap(
    opportunities: Iterable[Opportunity],
    demand_map: DemandMap | None = None,
) -> dict[str, Any]:
    """Scale down opportunities that claim demand already claimed elsewhere.

    Mutates each opportunity's projection in place and returns a summary of what
    was removed, for reporting. Without a ``demand_map`` every entity is treated
    as its own unit of demand, which is the behaviour when no keyword-to-page
    relationship is known.
    """
    items = list(opportunities)
    demand_map = demand_map or DemandMap()

    # Expand every opportunity's entities into weighted units of demand once,
    # then count how many opportunities claim each unit.
    expanded: list[dict[tuple[str, str], float]] = []
    claimants: dict[tuple[str, tuple[str, str]], int] = defaultdict(int)

    for item in items:
        pool = item.demand_pool
        if pool is None or not item.entities:
            expanded.append({})
            continue
        atoms = _claimed_demand(item.entities, demand_map)
        expanded.append(atoms)
        for atom in atoms:
            claimants[(pool, atom)] += 1

    total_before = 0.0
    total_after = 0.0
    adjusted = 0
    cross_level = 0

    for item, atoms in zip(items, expanded):
        total_before += item.projection.annual_run_rate
        pool = item.demand_pool
        if pool is None or not atoms:
            total_after += item.projection.annual_run_rate
            continue

        total_weight = sum(atoms.values())
        if total_weight <= 0:
            item.score_components["overlap_factor"] = 1.0
            total_after += item.projection.annual_run_rate
            continue

        factor = sum(
            weight / claimants[(pool, atom)] for atom, weight in atoms.items()
        ) / total_weight

        if factor < 0.9999:
            contested = [atom for atom in atoms if claimants[(pool, atom)] > 1]
            projection = item.projection
            projection.incremental_sessions *= factor
            projection.known_revenue *= factor
            projection.dark_revenue *= factor
            item.score_components["overlap_factor"] = round(factor, 4)

            # A page-level claim contested at keyword level is the cross-level
            # case that used to go unnoticed; worth naming in the evidence.
            resolved = any(
                atom[0] == "keyword" and _normalize(entity) != atom[1]
                for atom in contested
                for entity in item.entities
            )
            if resolved:
                cross_level += 1

            item.add_evidence(
                "trailguide",
                "overlap adjustment",
                f"value scaled to {factor:.0%}",
                Confidence.DERIVED,
                note=(
                    f"{len(contested)} of {len(atoms)} unit(s) of demand targeted here are "
                    f"also claimed by other opportunities in the {pool} pool; shared demand "
                    f"is split equally between claimants so the same clicks are not sold "
                    f"twice. Page-level claims are matched against keyword-level ones through "
                    f"the landing pages those keywords rank on."
                ),
            )
            adjusted += 1
        else:
            item.score_components["overlap_factor"] = 1.0

        total_after += item.projection.annual_run_rate

    contested_units = sum(1 for count in claimants.values() if count > 1)
    return {
        "opportunities_adjusted": adjusted,
        "cross_level_adjustments": cross_level,
        "contested_entities": contested_units,
        "total_entities": len(claimants),
        "keywords_mapped_to_pages": len(demand_map.keyword_pages),
        "page_demand_visibility": round(demand_map.page_visibility, 4),
        "run_rate_before": round(total_before, 2),
        "run_rate_after": round(total_after, 2),
        "value_removed": round(total_before - total_after, 2),
    }


def _claimed_demand(
    entities: Iterable[str], demand_map: DemandMap
) -> dict[tuple[str, str], float]:
    """Resolve an opportunity's entities into weighted units of contested demand.

    Each entity contributes one unit of claim, split across whatever demand it
    covers: a keyword claims itself, a page claims the keywords it ranks for,
    and anything unrecognized (a prompt cluster, ``robots.txt``) claims itself.
    Weights are normalized per entity so an opportunity naming one page does not
    outvote one naming one keyword.
    """
    atoms: dict[tuple[str, str], float] = defaultdict(float)
    for entity in {_normalize(value) for value in entities if str(value).strip()}:
        if entity in demand_map.keyword_pages:
            atoms[("keyword", entity)] += 1.0
            continue

        page_keywords = demand_map.page_keywords.get(entity)
        if page_keywords:
            visible = demand_map.page_visibility
            total = sum(page_keywords.values()) or 1.0
            for keyword, weight in page_keywords.items():
                atoms[("keyword", keyword)] += visible * weight / total
            # The unobserved remainder still contests other *page*-level claims
            # on the same page, which is how page-vs-page overlap is caught.
            if visible < 1.0:
                atoms[("page", entity)] += 1.0 - visible
            continue

        atoms[("entity", entity)] += 1.0
    return dict(atoms)


def _normalize(entity: str) -> str:
    """Normalize an entity label so the same URL or keyword matches itself."""
    return str(entity).strip().lower().rstrip("/")
