"""JSON and CSV exports.

The markdown report is for people; these are for everything else - a dashboard,
a diff against last month's run, or an analyst who wants to sort the register in
a spreadsheet.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ..pipeline import RunResult


def write_json(result: RunResult, path: str | Path) -> Path:
    """Write the complete machine-readable result."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    return target


def write_csvs(result: RunResult, directory: str | Path) -> list[Path]:
    """Write the opportunity register, roadmap, evidence and estimator tables."""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    currency = result.config.currency

    # Opportunity register: one row per opportunity, sortable in a spreadsheet.
    register_rows: list[dict[str, Any]] = []
    for item in result.opportunities:
        projection = item.projection
        register_rows.append({
            "rank": item.rank,
            "id": item.id,
            "title": item.title,
            "surface": item.surface.value,
            "type": item.opportunity_type,
            "score": round(item.score, 2),
            "owner_role": item.owner_role,
            "confidence": item.confidence.value,
            "effective_confidence": round(item.effective_confidence, 3),
            "expected_value": round(item.expected_value, 2),
            "horizon_revenue": round(projection.horizon_revenue, 2),
            "horizon_revenue_low": round(projection.range_low, 2),
            "horizon_revenue_high": round(projection.range_high, 2),
            "annual_run_rate": round(projection.annual_run_rate, 2),
            "track1_known_revenue": round(projection.known_revenue, 2),
            "track2_dark_revenue": round(projection.dark_revenue, 2),
            "dark_share": round(projection.dark_share, 4),
            "incremental_sessions": round(projection.incremental_sessions, 1),
            "effort_days": round(item.effort.total_days, 2),
            "delivery_cost": round(item.effort.total_cost, 2),
            "value_per_day": round(item.value_per_day, 2),
            "roi": round(item.roi, 3) if item.roi is not None else "",
            "lag_months": projection.lag_months,
            "ramp_months": projection.ramp_months,
            "strategic_multiplier": item.strategic_multiplier,
            "entity_count": len(item.entities),
            "entities_sample": "; ".join(item.entities[:5]),
            "tags": "; ".join(item.tags),
            "currency": currency,
        })
    written.append(_write_csv(out_dir / "opportunities.csv", register_rows))

    # Roadmap: the scheduled plan, quarter by quarter.
    roadmap_rows = [
        {
            "quarter": item.start_quarter,
            "end_quarter": item.end_quarter,
            **{
                key: value for key, value in item.to_dict().items()
                if key not in ("start_quarter", "end_quarter", "tags")
            },
            "tags": "; ".join(item.opportunity.tags),
        }
        for item in result.portfolio.scheduled
    ]
    written.append(_write_csv(out_dir / "roadmap.csv", roadmap_rows))

    # Evidence: every supporting datapoint, traceable to its source.
    evidence_rows = [
        {
            "opportunity_id": item.id,
            "opportunity_rank": item.rank,
            "opportunity_title": item.title,
            "source": evidence.source,
            "metric": evidence.metric,
            "value": evidence.value,
            "confidence": evidence.confidence.value,
            "note": evidence.note or "",
        }
        for item in result.opportunities
        for evidence in item.evidence
    ]
    written.append(_write_csv(out_dir / "evidence.csv", evidence_rows))

    # Dark traffic estimators: the Track 2 audit trail.
    estimator_rows = [
        {
            "track": track.track,
            "known_sessions": round(track.known_sessions, 1),
            "method": estimate.method,
            "dark_sessions": round(estimate.dark_sessions, 1),
            "confidence": round(estimate.confidence, 3),
            "note": estimate.note,
            "inputs": json.dumps(estimate.inputs, default=str),
        }
        for track in (result.dark.seo, result.dark.geo)
        for estimate in track.estimates
    ]
    written.append(_write_csv(out_dir / "dark_traffic_estimators.csv", estimator_rows))

    return written


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    """Write rows to CSV, emitting a header-only file when there are no rows."""
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path
