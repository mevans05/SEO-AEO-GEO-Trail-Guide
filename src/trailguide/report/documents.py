"""Word and PowerPoint deliverables, for handover as Google Docs and Slides.

Uploading a ``.docx`` or ``.pptx`` to Google Drive converts it to a native
Google Doc or Slides file, so these two writers are the whole path to the
formats a client actually reads.

The document renders the markdown report rather than restating it. There is one
narrative, in :mod:`trailguide.report.markdown`, and this turns it into a Word
document with the delivery tickets appended. A second copy of the wording would
drift from the first the moment either changed.

The deck is not a compressed report - it answers the handful of questions an
executive asks in the room: how much is on the table, how sure are we, what are
we doing first, what does it cost, and what happens if we are short.

Both writers need optional dependencies (``python-docx`` and ``python-pptx``).
Core stays on PyYAML alone so the engine still runs anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..errors import TrailGuideError
from ..pipeline import RunResult
from .jira import render_appendix
from .markdown import render_markdown

#: Brand-neutral palette. One accent carries emphasis, greys carry structure;
#: a surface never gets a colour that implies good or bad on its own.
INK = "1A1A1A"
MUTED = "6B6B6B"
ACCENT = "1F3864"
ACCENT_LIGHT = "C9DAF8"
RULE = "D9D9D9"

#: Inline markdown: code, bold, italic. Order matters - code wins over emphasis.
_INLINE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|(?<![\w*])\*[^*\n]+\*(?![\w*])|_[^_\n]+_)")


def _require(module: str, package: str, extra: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise TrailGuideError(
            f"this export needs {package}. Install it with:\n"
            f'    pip install "trailguide[{extra}]"'
        ) from exc


# -- markdown -> Word ------------------------------------------------------


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_divider(line: str) -> bool:
    """A table's header divider, e.g. ``| --- | ---: |``."""
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _add_inline(paragraph: Any, text: str) -> None:
    """Write text into a paragraph, honouring bold, italic and inline code."""
    for token in _INLINE.split(text):
        if not token:
            continue
        if token.startswith("`") and token.endswith("`") and len(token) > 1:
            run = paragraph.add_run(token[1:-1])
            run.font.name = "Consolas"
        elif token.startswith("**") and token.endswith("**") and len(token) > 3:
            paragraph.add_run(token[2:-2]).bold = True
        elif (
            len(token) > 2
            and token[0] == token[-1]
            and token[0] in "*_"
        ):
            paragraph.add_run(token[1:-1]).italic = True
        else:
            paragraph.add_run(token)


def markdown_to_docx(markdown_text: str, document: Any) -> None:
    """Render the report's markdown subset into an open Word document.

    Supports what the report emits and nothing more: headings, tables, ordered
    and unordered lists, horizontal rules and inline emphasis.
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    lines = markdown_text.splitlines()
    index = 0
    ordinal = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            ordinal = 0
            continue

        # Table: a pipe row followed by a divider row.
        if (
            stripped.startswith("|")
            and index + 1 < len(lines)
            and _is_divider(lines[index + 1])
        ):
            header = _split_table_row(stripped)
            alignments = [
                WD_ALIGN_PARAGRAPH.RIGHT if cell.endswith(":") and not cell.startswith(":")
                else WD_ALIGN_PARAGRAPH.CENTER if cell.startswith(":") and cell.endswith(":")
                else WD_ALIGN_PARAGRAPH.LEFT
                for cell in _split_table_row(lines[index + 1])
            ]
            body: list[list[str]] = []
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                body.append(_split_table_row(lines[index].strip()))
                index += 1

            table = document.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            for column, title in enumerate(header):
                cell = table.rows[0].cells[column]
                cell.text = ""
                paragraph = cell.paragraphs[0]
                _add_inline(paragraph, title)
                for run in paragraph.runs:
                    run.bold = True
                    run.font.color.rgb = RGBColor.from_string(ACCENT)
                paragraph.alignment = alignments[column] if column < len(alignments) else None
            for row_cells in body:
                cells = table.add_row().cells
                for column, value in enumerate(row_cells[: len(header)]):
                    cells[column].text = ""
                    paragraph = cells[column].paragraphs[0]
                    _add_inline(paragraph, value)
                    if column < len(alignments):
                        paragraph.alignment = alignments[column]
            document.add_paragraph()
            ordinal = 0
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = document.add_heading(level=min(level, 4))
            _add_inline(heading, stripped[level:].strip())
            index += 1
            ordinal = 0
            continue

        if stripped in ("---", "***", "___"):
            rule = document.add_paragraph()
            run = rule.add_run("_" * 60)
            run.font.color.rgb = RGBColor.from_string(RULE)
            run.font.size = Pt(8)
            index += 1
            continue

        ordered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if ordered:
            ordinal += 1
            paragraph = document.add_paragraph(style="List Number")
            _add_inline(paragraph, ordered.group(2))
            index += 1
            continue

        if stripped.startswith(("- ", "* ", "+ ")):
            paragraph = document.add_paragraph(style="List Bullet")
            _add_inline(paragraph, stripped[2:])
            index += 1
            ordinal = 0
            continue

        # Plain paragraph: join soft-wrapped lines until a blank or a block start.
        buffer = [stripped]
        index += 1
        while index < len(lines):
            nxt = lines[index].strip()
            if not nxt or nxt.startswith(("#", "|", "- ", "* ", "+ ", "---")) or re.match(
                r"^\d+\.\s", nxt
            ):
                break
            buffer.append(nxt)
            index += 1
        paragraph = document.add_paragraph()
        _add_inline(paragraph, " ".join(buffer))
        ordinal = 0


def write_docx(
    result: RunResult,
    path: str | Path,
    max_detail: int = 25,
    include_appendix: bool = True,
) -> Path:
    """Write the full opportunity analysis as Word, tickets in the appendix."""
    _require("docx", "python-docx", "deliverables")
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    document = Document()

    # Body text that survives conversion to Google Docs intact.
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor.from_string(INK)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    for level in range(1, 5):
        style = document.styles[f"Heading {level}"]
        style.font.color.rgb = RGBColor.from_string(ACCENT)
        style.font.name = "Calibri"

    summary = result.summary()
    config = result.config

    # Cover
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("SEO / AEO / GEO\nOpportunity Analysis")
    run.bold = True
    run.font.size = Pt(30)
    run.font.color.rgb = RGBColor.from_string(ACCENT)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    client_run = subtitle.add_run(f"\n{config.client_name}")
    client_run.font.size = Pt(18)
    client_run.font.color.rgb = RGBColor.from_string(INK)

    meta = document.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_run = meta.add_run(
        f"{config.domain or ''}\n"
        f"{result.generated_at:%d %B %Y} - {config.horizon_months}-month planning horizon\n"
        f"Trail Guide v{summary['version']}"
    )
    meta_run.font.size = Pt(10)
    meta_run.font.color.rgb = RGBColor.from_string(MUTED)

    document.add_page_break()

    # The report itself, rendered rather than restated.
    markdown_to_docx(render_markdown(result, max_detail), document)

    if include_appendix:
        document.add_page_break()
        markdown_to_docx(render_appendix(result), document)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(target)
    return target


# -- deck ------------------------------------------------------------------


def _money(value: float, currency: str = "USD") -> str:
    """Compact money, because a deck is read from the back of a room."""
    symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency, "")
    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        return f"{symbol}{value / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"{symbol}{value / 1_000_000:.2f}M"
    if magnitude >= 1_000:
        return f"{symbol}{value / 1_000:.0f}K"
    return f"{symbol}{value:,.0f}"


def _surface_totals(result: RunResult) -> list[tuple[str, float]]:
    """Realized in-horizon revenue by surface, largest first."""
    totals: dict[str, float] = {}
    for scheduled in result.portfolio.scheduled:
        surface = scheduled.opportunity.surface.value
        totals[surface] = totals.get(surface, 0.0) + scheduled.realized_revenue
    return sorted(totals.items(), key=lambda pair: pair[1], reverse=True)


def _quarter_totals(result: RunResult) -> list[tuple[int, float, float]]:
    """(quarter, realized revenue, effort days) for each quarter in the plan."""
    revenue: dict[int, float] = {}
    days: dict[int, float] = {}
    for scheduled in result.portfolio.scheduled:
        quarter = scheduled.start_quarter
        revenue[quarter] = revenue.get(quarter, 0.0) + scheduled.realized_revenue
        days[quarter] = days.get(quarter, 0.0) + scheduled.opportunity.effort.total_days
    return [
        (quarter, revenue.get(quarter, 0.0), days.get(quarter, 0.0))
        for quarter in sorted(set(revenue) | set(days))
    ]


class _Deck:
    """Thin layout helper over python-pptx, so slide code reads as content."""

    def __init__(self, presentation: Any) -> None:
        from pptx.util import Inches

        self.presentation = presentation
        self.blank = presentation.slide_layouts[6]
        self.width = presentation.slide_width
        self.height = presentation.slide_height
        self.margin = Inches(0.6)

    def slide(self) -> Any:
        return self.presentation.slides.add_slide(self.blank)

    def textbox(
        self,
        slide: Any,
        left: Any,
        top: Any,
        width: Any,
        height: Any,
        text: str,
        size: int = 14,
        bold: bool = False,
        color: str = INK,
        align: str = "left",
        spacing: float = 1.0,
    ) -> Any:
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Pt

        box = slide.shapes.add_textbox(left, top, width, height)
        frame = box.text_frame
        frame.word_wrap = True
        alignment = {
            "left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT
        }[align]
        for offset, line in enumerate(text.split("\n")):
            paragraph = frame.paragraphs[0] if offset == 0 else frame.add_paragraph()
            paragraph.text = line
            paragraph.alignment = alignment
            paragraph.line_spacing = spacing
            for run in paragraph.runs:
                run.font.size = Pt(size)
                run.font.bold = bold
                run.font.color.rgb = RGBColor.from_string(color)
                run.font.name = "Calibri"
        return box

    def title(self, slide: Any, text: str, kicker: str = "") -> None:
        from pptx.util import Inches

        top = Inches(0.45)
        if kicker:
            self.textbox(
                slide, self.margin, top, self.width - 2 * self.margin, Inches(0.3),
                kicker.upper(), size=11, bold=True, color=MUTED,
            )
            top = Inches(0.8)
        self.textbox(
            slide, self.margin, top, self.width - 2 * self.margin, Inches(0.7),
            text, size=28, bold=True, color=ACCENT,
        )

    def footnote(self, slide: Any, text: str) -> None:
        from pptx.util import Inches

        self.textbox(
            slide, self.margin, self.height - Inches(0.75),
            self.width - 2 * self.margin, Inches(0.5),
            text, size=9, color=MUTED,
        )

    def stat(
        self, slide: Any, left: Any, top: Any, width: Any,
        value: str, label: str, note: str = "",
    ) -> None:
        """A single number, its label and an optional qualifier beneath it."""
        from pptx.util import Inches

        self.textbox(slide, left, top, width, Inches(0.8), value,
                     size=40, bold=True, color=ACCENT)
        self.textbox(slide, left, top + Inches(0.78), width, Inches(0.3), label,
                     size=12, bold=True, color=INK)
        if note:
            self.textbox(slide, left, top + Inches(1.08), width, Inches(0.6), note,
                         size=9.5, color=MUTED, spacing=1.1)

    def bar_row(
        self, slide: Any, left: Any, top: Any, width: Any,
        label: str, value: float, peak: float, caption: str,
    ) -> None:
        """One horizontal bar: label, proportional bar, value caption."""
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Inches

        label_width = Inches(1.9)
        caption_width = Inches(1.35)
        track_width = width - label_width - caption_width
        self.textbox(slide, left, top, label_width, Inches(0.3), label,
                     size=11, color=INK)
        share = (value / peak) if peak > 0 else 0.0
        bar_width = max(Inches(0.04), int(track_width * share))
        bar = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, left + label_width, top + Inches(0.03),
            bar_width, Inches(0.2),
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(ACCENT)
        bar.line.fill.background()
        bar.shadow.inherit = False
        self.textbox(
            slide, left + label_width + track_width + Inches(0.1), top,
            caption_width, Inches(0.3), caption, size=11, bold=True, color=INK,
        )


def write_pptx(result: RunResult, path: str | Path, top_n: int = 8) -> Path:
    """Write the highlights deck: the questions asked in the room, in order."""
    _require("pptx", "python-pptx", "deliverables")
    from pptx import Presentation
    from pptx.util import Inches

    summary = result.summary()
    config = result.config
    portfolio = result.portfolio
    currency = config.currency
    totals = portfolio.to_dict()["totals"]

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    deck = _Deck(presentation)
    content_width = deck.width - 2 * deck.margin

    # 1. Cover
    slide = deck.slide()
    deck.textbox(slide, deck.margin, Inches(2.4), content_width, Inches(1.2),
                 "SEO / AEO / GEO Opportunity Analysis", size=40, bold=True, color=ACCENT)
    deck.textbox(slide, deck.margin, Inches(3.6), content_width, Inches(0.6),
                 config.client_name, size=24, color=INK)
    deck.textbox(
        slide, deck.margin, Inches(4.2), content_width, Inches(0.9),
        f"{config.domain or ''}\n{result.generated_at:%d %B %Y}  -  "
        f"{config.horizon_months}-month horizon",
        size=12, color=MUTED, spacing=1.3,
    )

    # 2. The headline
    slide = deck.slide()
    deck.title(slide, "What is on the table", kicker="Headline")
    column = (content_width - Inches(0.9)) / 3
    attainment = totals.get("target_attainment") or 0.0
    deck.stat(
        slide, deck.margin, Inches(1.9), column,
        _money(totals["projected_revenue"], currency), "Incremental revenue",
        f"Inside the {config.horizon_months}-month horizon. Range "
        f"{_money(totals['projected_revenue_low'], currency)} to "
        f"{_money(totals['projected_revenue_high'], currency)}.",
    )
    deck.stat(
        slide, deck.margin + column + Inches(0.45), Inches(1.9), column,
        f"{attainment * 100:.0f}%", "Of the revenue target",
        f"Target {_money(totals['target_revenue'], currency)}. Every figure is "
        f"confidence-adjusted, so it compares to a target rather than a best case.",
    )
    deck.stat(
        slide, deck.margin + 2 * (column + Inches(0.45)), Inches(1.9), column,
        f"{totals['roi']:.1f}x", "Return on delivery cost",
        f"{_money(totals['delivery_cost'], currency)} of delivery, "
        f"{totals['effort_days']:.0f} person-days across {totals['scheduled_count']} "
        f"pieces of work.",
    )
    deck.stat(
        slide, deck.margin, Inches(4.3), column,
        f"{summary['opportunities_found']}", "Opportunities identified",
        f"{totals['scheduled_count']} scheduled, {totals['deferred_count']} deferred "
        f"for capacity.",
    )
    deck.stat(
        slide, deck.margin + column + Inches(0.45), Inches(4.3), column,
        _money(totals["projected_annual_run_rate"], currency), "Annual run rate",
        "Once every scheduled item is fully ramped - the steady state, not the "
        "in-horizon figure.",
    )
    deck.stat(
        slide, deck.margin + 2 * (column + Inches(0.45)), Inches(4.3), column,
        _money(totals["baseline_revenue"], currency), "Current baseline",
        "Attributed today across both measurement tracks.",
    )

    # 3. The measurement gap
    slide = deck.slide()
    deck.title(slide, "Half the demand never shows up in analytics",
               kicker="Why the numbers look different")
    seo, geo = result.dark.seo, result.dark.geo
    deck.textbox(
        slide, deck.margin, Inches(1.7), content_width, Inches(0.9),
        "Referrer-based analytics miss demand satisfied on the SERP, inside an "
        "assistant, or arriving later as direct traffic. Every projection here is "
        "computed across two tracks and reported separately, so you can accept the "
        "observed number and interrogate the modeled one on its own terms.",
        size=13, color=INK, spacing=1.25,
    )
    half = (content_width - Inches(0.6)) / 2
    deck.stat(
        slide, deck.margin, Inches(3.0), half, f"{seo.multiplier:.2f}x",
        "Dark organic multiplier",
        f"Modeled dark organic demand as a multiple of attributed organic. "
        f"Confidence {seo.confidence:.0%}, from {len(seo.estimates)} independent "
        f"estimator(s).",
    )
    deck.stat(
        slide, deck.margin + half + Inches(0.6), Inches(3.0), half,
        f"{geo.multiplier:.2f}x", "Dark LLM influence multiplier",
        f"Modeled assistant influence as a multiple of observed LLM referrals. "
        f"Confidence {geo.confidence:.0%}, from {len(geo.estimates)} independent "
        f"estimator(s).",
    )
    deck.footnote(
        slide,
        "Track 2 is triangulated across independent methods and reported with its "
        "spread. It is a modeled range, not a measurement - treat movement in it as "
        "the signal rather than the point estimate.",
    )

    # 4. Where the value sits
    surfaces = _surface_totals(result)
    if surfaces:
        slide = deck.slide()
        deck.title(slide, "Where the value sits", kicker="By surface")
        peak = max(value for _, value in surfaces)
        top = Inches(1.8)
        for name, value in surfaces:
            deck.bar_row(slide, deck.margin, top, content_width - Inches(0.4),
                         name, value, peak, _money(value, currency))
            top += Inches(0.52)
        deck.footnote(
            slide,
            "In-horizon revenue, after overlap deduplication. Opportunities claiming "
            "the same demand share it rather than each billing for it in full.",
        )

    # 5. The first moves
    slide = deck.slide()
    deck.title(slide, "The first moves", kicker=f"Top {top_n} by priority")
    top = Inches(1.75)
    for position, scheduled in enumerate(portfolio.scheduled[:top_n], start=1):
        item = scheduled.opportunity
        deck.textbox(
            slide, deck.margin, top, Inches(0.4), Inches(0.3), f"{position}.",
            size=12, bold=True, color=ACCENT,
        )
        deck.textbox(
            slide, deck.margin + Inches(0.4), top, Inches(7.4), Inches(0.35),
            item.title[:96], size=12, bold=True, color=INK,
        )
        deck.textbox(
            slide, deck.margin + Inches(8.0), top, Inches(1.5), Inches(0.3),
            _money(scheduled.realized_revenue, currency), size=12, bold=True, color=ACCENT,
        )
        deck.textbox(
            slide, deck.margin + Inches(9.6), top, Inches(1.2), Inches(0.3),
            f"{item.effort.total_days:.0f}d", size=12, color=MUTED,
        )
        deck.textbox(
            slide, deck.margin + Inches(10.6), top, Inches(1.4), Inches(0.3),
            f"Q{scheduled.start_quarter}  {item.surface.value}", size=11, color=MUTED,
        )
        top += Inches(0.52)
    deck.footnote(
        slide,
        "Ranked on value, value per person-day, speed to impact and confidence "
        "together - not revenue alone, which would crowd out fast work that "
        "compounds.",
    )

    # 6. Phasing
    quarters = _quarter_totals(result)
    if quarters:
        slide = deck.slide()
        deck.title(slide, "How it phases", kicker="Revenue and effort by quarter")
        peak = max(revenue for _, revenue, _ in quarters) or 1.0
        top = Inches(1.9)
        for quarter, revenue, days in quarters:
            deck.bar_row(
                slide, deck.margin, top, content_width - Inches(0.4),
                f"Q{quarter}   {days:.0f} person-days", revenue, peak,
                _money(revenue, currency),
            )
            top += Inches(0.62)
        deck.footnote(
            slide,
            "Value is in-horizon, not run rate: work starting in Q4 contributes "
            "little to a 12-month goal, and the ranking already accounts for that.",
        )

    # 7. The gap, when there is one
    gap = portfolio.to_dict().get("gap_analysis") or {}
    if gap.get("status") == "short":
        slide = deck.slide()
        deck.title(slide, "What it would take to close the gap", kicker="Gap to target")
        residual = gap.get("residual_gap_after_deferred", 0.0)
        deck.stat(
            slide, deck.margin, Inches(1.9), (content_width - Inches(0.6)) / 2,
            _money(gap.get("gap", 0.0), currency), "Short of target",
            f"{_money(totals['projected_revenue'], currency)} projected against "
            f"{_money(totals['target_revenue'], currency)}.",
        )
        deck.stat(
            slide, deck.margin + (content_width - Inches(0.6)) / 2 + Inches(0.6),
            Inches(1.9), (content_width - Inches(0.6)) / 2,
            _money(gap.get("additional_delivery_cost", 0.0), currency),
            "To fund the deferred backlog",
            "  ".join(
                f"{discipline} {days:.0f}d"
                for discipline, days in sorted(
                    (gap.get("additional_days_required") or {}).items()
                )
            ) or "No additional capacity identified.",
        )
        verdict = (
            f"Funding the entire deferred backlog still leaves "
            f"{_money(residual, currency)} outstanding. The target is not reachable "
            f"from this dataset inside the horizon - revisit the target, extend the "
            f"horizon, or widen the input data."
            if residual > 0 else
            "Funding the deferred backlog closes the gap in full."
        )
        deck.textbox(slide, deck.margin, Inches(4.5), content_width, Inches(1.2),
                     verdict, size=14, color=INK, spacing=1.25)

    # 8. How this gets proven
    slide = deck.slide()
    deck.title(slide, "How we will know it worked", kicker="Measurement")
    deck.textbox(
        slide, deck.margin, Inches(1.8), content_width, Inches(3.4),
        "1.  Baseline both tracks now - this analysis is that baseline.\n"
        "2.  Deliver the roadmap, highest priority first.\n"
        "3.  Re-measure monthly on citations and rank, quarterly on revenue.\n"
        "4.  Isolate lift by re-running against fresh exports. Opportunity IDs are\n"
        "     stable, so each item is tracked as its score moves month over month.\n"
        "5.  Report incremental revenue against programme cost, with ranges.",
        size=15, color=INK, spacing=1.7,
    )
    deck.footnote(
        slide,
        "Recalibrate the dark-traffic model quarterly as survey and panel data "
        "accumulate. Geo-holdout and pre/post tests remain the way to prove "
        "causation - this establishes correlation and sizes it.",
    )

    # 9. What this is not
    slide = deck.slide()
    deck.title(slide, "What this does not claim", kicker="Limits")
    deck.textbox(
        slide, deck.margin, Inches(1.8), content_width, Inches(3.6),
        "-  It does not replace judgement. Which clusters matter strategically and\n"
        "    what the brand can credibly claim are human calls.\n\n"
        "-  It does not prove causation. The branded-lift estimator measures\n"
        "    correlation and scales by r-squared.\n\n"
        "-  Track 2 is modeled, not measured. It is triangulated and reported with\n"
        "    its spread, and should be presented as an estimate.\n\n"
        "-  Elasticities and CTR curves are published benchmarks, not client truth.\n"
        "    Calibrate them once first-party data justifies it.",
        size=14, color=INK, spacing=1.35,
    )
    if result.warnings:
        deck.footnote(slide, f"This run raised {len(result.warnings)} warning(s); "
                             f"they are listed in full in the written analysis.")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(target)
    return target


def write_deliverables(
    result: RunResult, directory: str | Path, max_detail: int = 25
) -> list[Path]:
    """Write both handover formats into ``directory``."""
    out_dir = Path(directory)
    slug = re.sub(r"[^a-z0-9]+", "-", result.config.client_name.lower()).strip("-") or "client"
    return [
        write_docx(result, out_dir / f"{slug}-opportunity-analysis.docx", max_detail),
        write_pptx(result, out_dir / f"{slug}-highlights.pptx"),
    ]
