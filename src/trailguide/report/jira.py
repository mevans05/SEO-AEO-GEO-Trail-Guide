"""Jira tickets generated from scheduled opportunities.

A roadmap nobody can act on is a document. This turns each scheduled
opportunity into a ticket a delivery team can pick up without rewriting it:
what to do, why it is worth doing, how much it is worth, what "done" means, and
how the result will be measured.

Two shapes come out of here. :func:`render_ticket` builds the structured ticket;
:func:`write_jira_csv` writes Jira's CSV import format, and
:func:`render_appendix` writes the same content as markdown for the appendix of
a client document, where it is read rather than imported.

Epics group by surface, because that is how the work is usually staffed - the
people fixing crawl errors are not the people writing comparison pages.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.opportunity import Opportunity
from ..core.schemas import Surface
from ..pipeline import RunResult

#: Epic each surface rolls up into, keyed by surface value.
EPICS = {
    Surface.SEO.value: "Organic search growth",
    Surface.AEO.value: "Answer engine visibility",
    Surface.GEO.value: "Generative engine visibility",
    Surface.TECHNICAL.value: "Technical foundations",
    Surface.CONVERSION.value: "Conversion and measurement",
    Surface.DISTRIBUTION.value: "Owned channel distribution",
}

#: Discipline -> Jira component. Keeps ticket routing out of the analyzer code.
COMPONENTS = {
    "seo": "SEO",
    "content": "Content",
    "engineering": "Engineering",
    "design": "Design",
    "analytics": "Analytics",
    "strategy": "Strategy",
    "outreach": "Outreach",
}


@dataclass
class Ticket:
    """One Jira-ready ticket."""

    key: str
    summary: str
    issue_type: str
    epic: str
    priority: str
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    estimate_days: float = 0.0
    story_points: float = 0.0
    quarter: str = ""
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    value_statement: str = ""

    def to_row(self) -> dict[str, Any]:
        """Flatten to Jira's CSV import columns."""
        return {
            "Issue Key": self.key,
            "Summary": self.summary,
            "Issue Type": self.issue_type,
            "Epic Link": self.epic,
            "Priority": self.priority,
            "Labels": " ".join(self.labels),
            "Components": ";".join(self.components),
            "Original Estimate": f"{self.estimate_days:.1f}d",
            "Story Points": self.story_points,
            "Target Quarter": self.quarter,
            "Description": self.description,
        }


def _priority(rank: int | None) -> str:
    """Map portfolio rank onto Jira's default priority scale."""
    if rank is None:
        return "Medium"
    if rank <= 5:
        return "Highest"
    if rank <= 12:
        return "High"
    if rank <= 25:
        return "Medium"
    return "Low"


def _story_points(days: float) -> float:
    """Round effort onto a Fibonacci-ish scale delivery teams recognize."""
    for threshold, points in ((1, 1), (2, 2), (4, 3), (7, 5), (12, 8), (20, 13), (34, 21)):
        if days <= threshold:
            return points
    return 34


def _issue_type(item: Opportunity) -> str:
    """Large multi-discipline work is an Epic; a single fix is a Task."""
    if "enabling" in item.tags:
        return "Task"
    if item.effort.total_days >= 15 or len(item.effort.days_by_discipline) >= 3:
        return "Story"
    return "Task"


def render_ticket(
    item: Opportunity,
    currency: str = "USD",
    quarter: str = "",
    horizon_months: int = 12,
) -> Ticket:
    """Build the ticket for one opportunity, with its full supporting case."""
    projection = item.projection
    surface = item.surface.value

    if "enabling" in item.tags:
        value_statement = (
            "Enabling work: carries no projected revenue by design. Instrumentation "
            "does not create demand - it makes the demand that exists measurable, and "
            "every quarter it is deferred is planned on weaker evidence."
        )
    else:
        value_statement = (
            f"{projection.horizon_revenue:,.0f} {currency} projected inside the "
            f"{horizon_months}-month horizon "
            f"(range {projection.range_low:,.0f}-{projection.range_high:,.0f}), of which "
            f"{projection.dark_share:.0%} is modeled Track 2 rather than directly "
            f"attributable. Annual run rate once fully realized: "
            f"{projection.annual_run_rate:,.0f} {currency}."
        )

    lines = [
        "h2. Why this is worth doing",
        "",
        value_statement,
        "",
        f"Confidence: {item.confidence.value} "
        f"(effective {item.effective_confidence:.0%} after modifiers). "
        f"Value starts landing after {projection.lag_months:.0f} month(s) and reaches "
        f"full rate over a further {projection.ramp_months:.0f}.",
        "",
    ]

    if item.recommended_actions:
        lines += ["h2. What to do", ""]
        lines += [f"# {action}" for action in item.recommended_actions]
        lines.append("")

    if item.entities:
        shown = item.entities[:25]
        lines += ["h2. Targets", ""]
        lines += [f"* {{{{{entity}}}}}" for entity in shown]
        if len(item.entities) > len(shown):
            lines.append(f"* ...and {len(item.entities) - len(shown)} more (see the register)")
        lines.append("")

    if item.evidence:
        lines += ["h2. Evidence", ""]
        for evidence in item.evidence[:12]:
            note = f" - {evidence.note}" if getattr(evidence, "note", None) else ""
            lines.append(
                f"* *{evidence.metric}*: {evidence.value} "
                f"({evidence.source}, {evidence.confidence.value}){note}"
            )
        lines.append("")

    criteria = _acceptance_criteria(item)
    if criteria:
        lines += ["h2. Acceptance criteria", ""]
        lines += [f"* {criterion}" for criterion in criteria]
        lines.append("")

    if item.dependencies:
        lines += ["h2. Dependencies", ""]
        lines += [f"* {dependency}" for dependency in item.dependencies]
        lines.append("")

    if item.risks:
        lines += ["h2. Risks", ""]
        lines += [f"* {risk}" for risk in item.risks]
        lines.append("")

    effort_parts = ", ".join(
        f"{discipline} {days:.1f}d"
        for discipline, days in sorted(item.effort.days_by_discipline.items())
    )
    lines += [
        "h2. Effort",
        "",
        f"{item.effort.total_days:.1f} person-days ({effort_parts}), "
        f"about {item.effort.total_cost:,.0f} {currency} fully loaded.",
    ]
    if item.effort.notes:
        lines += ["", item.effort.notes]

    return Ticket(
        key=item.id,
        summary=item.title,
        issue_type=_issue_type(item),
        epic=EPICS.get(surface, "Organic search growth"),
        priority=_priority(item.rank),
        labels=_labels(item),
        components=sorted(
            {COMPONENTS.get(discipline, discipline.title())
             for discipline in item.effort.days_by_discipline}
        ),
        estimate_days=round(item.effort.total_days, 1),
        story_points=_story_points(item.effort.total_days),
        quarter=quarter,
        description="\n".join(lines).strip(),
        acceptance_criteria=criteria,
        value_statement=value_statement,
    )


def _labels(item: Opportunity) -> list[str]:
    """Labels a delivery team can filter on."""
    labels = [
        f"surface-{item.surface.value.lower()}",
        f"type-{item.opportunity_type.replace('_', '-').lower()}",
    ]
    labels += [f"tag-{tag.replace('_', '-').lower()}" for tag in item.tags]
    if item.projection.dark_share >= 0.5:
        labels.append("track2-led")
    return sorted(set(labels))


def _acceptance_criteria(item: Opportunity) -> list[str]:
    """What "done" means, stated so it can be checked rather than argued about.

    Measurement statements come first because they are the ones that hold: a
    ticket closed without the measurement in place cannot be shown to have
    worked.
    """
    criteria: list[str] = list(item.measurement)
    if not criteria:
        criteria.append(
            "Baseline captured before the change and re-measured after it, across "
            "both tracks (attributed and modeled)."
        )
    if item.entities:
        criteria.append(
            f"Change shipped for all {len(item.entities)} targeted item(s), or the "
            f"exclusions listed on the ticket with a reason."
        )
    if "enabling" not in item.tags:
        criteria.append(
            "Opportunity re-runs in the next monthly analysis with a reduced or "
            "closed gap, or the deviation is explained."
        )
    return criteria


def build_tickets(result: RunResult, include_deferred: bool = False) -> list[Ticket]:
    """Tickets for every scheduled opportunity, in roadmap order.

    Deferred work is excluded by default: it is a costed backlog for the gap
    conversation, not work anyone has been asked to start.
    """
    currency = result.config.currency
    horizon = result.config.horizon_months
    tickets = [
        render_ticket(
            scheduled.opportunity,
            currency=currency,
            quarter=f"Q{scheduled.start_quarter}",
            horizon_months=horizon,
        )
        for scheduled in result.portfolio.scheduled
    ]
    if include_deferred:
        tickets += [
            render_ticket(item, currency=currency, quarter="Backlog", horizon_months=horizon)
            for item in result.portfolio.deferred
        ]
    return tickets


def write_jira_csv(
    result: RunResult, path: str | Path, include_deferred: bool = False
) -> Path:
    """Write Jira's CSV import format: one row per ticket."""
    tickets = build_tickets(result, include_deferred)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "Issue Key", "Summary", "Issue Type", "Epic Link", "Priority", "Labels",
        "Components", "Original Estimate", "Story Points", "Target Quarter",
        "Description",
    ]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for ticket in tickets:
            writer.writerow(ticket.to_row())
    return target


def render_appendix(result: RunResult, include_deferred: bool = False) -> str:
    """Render the tickets as markdown, for the appendix of a client document."""
    tickets = build_tickets(result, include_deferred)
    currency = result.config.currency

    lines = [
        "# Appendix: delivery tickets",
        "",
        f"One ticket per scheduled opportunity, in roadmap order. {len(tickets)} tickets "
        f"across {len({ticket.epic for ticket in tickets})} epics. These are written to be "
        "imported into Jira as they are - `jira-tickets.csv` carries the same content in "
        "Jira's import format.",
        "",
        "Estimates are person-days from the effort model, with story points derived from "
        "them. Priority follows portfolio rank, so it already accounts for value, "
        "efficiency, speed and confidence together rather than value alone.",
        "",
    ]

    by_epic: dict[str, list[Ticket]] = {}
    for ticket in tickets:
        by_epic.setdefault(ticket.epic, []).append(ticket)

    lines += ["## Summary", "", "| Epic | Tickets | Person-days |", "| --- | --- | --- |"]
    for epic, group in by_epic.items():
        lines.append(
            f"| {epic} | {len(group)} | {sum(t.estimate_days for t in group):,.1f} |"
        )
    lines.append("")

    for epic, group in by_epic.items():
        lines += [f"## {epic}", ""]
        for ticket in group:
            lines += [
                f"### {ticket.key} - {ticket.summary}",
                "",
                f"**Type** {ticket.issue_type} | **Priority** {ticket.priority} | "
                f"**Estimate** {ticket.estimate_days:.1f}d ({ticket.story_points:.0f} pts) | "
                f"**Target** {ticket.quarter}",
                "",
                f"**Components** {', '.join(ticket.components) or '-'}  ",
                f"**Labels** {', '.join(ticket.labels)}",
                "",
                ticket.value_statement,
                "",
            ]
            body = _jira_markup_to_markdown(ticket.description)
            # The value statement is already shown above; drop its duplicate.
            body = body.split("## What to do", 1)
            if len(body) == 2:
                lines += ["## What to do" + body[1], ""]
            else:
                lines += [body[0], ""]

    lines += [
        "---",
        "",
        f"Effort totals {sum(t.estimate_days for t in tickets):,.1f} person-days. "
        f"Costs and the quarter-by-quarter revenue bridge are in the main report, in "
        f"{currency}.",
        "",
    ]
    return "\n".join(lines)


#: ``*bold*`` in Jira markup, ignoring the ``* `` that starts a list item.
_JIRA_BOLD = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")


def _jira_markup_to_markdown(text: str) -> str:
    """Convert the small subset of Jira wiki markup used here into markdown."""
    out: list[str] = []
    ordinal = 0
    for line in text.splitlines():
        if line.startswith("h2. "):
            out.append(f"## {line[4:]}")
            ordinal = 0
        elif line.startswith("# "):
            ordinal += 1
            out.append(f"{ordinal}. {_inline(line[2:])}")
        elif line.startswith("* "):
            out.append(f"- {_inline(line[2:])}")
            ordinal = 0
        else:
            out.append(_inline(line))
            ordinal = 0
    return "\n".join(out)


def _inline(text: str) -> str:
    """Convert inline Jira markup: ``{{code}}`` and ``*bold*``."""
    return _JIRA_BOLD.sub(r"**\1**", text.replace("{{", "`").replace("}}", "`"))
