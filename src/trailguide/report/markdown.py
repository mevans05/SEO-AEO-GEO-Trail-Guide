"""The analyst-facing opportunity analysis.

Written to be handed to a client with light editing rather than rebuilt from
scratch. It leads with the revenue bridge because that is the question being
asked, separates observed from modeled value everywhere, and states what the
data could not support - a report that hides its gaps is not reusable.
"""

from __future__ import annotations

from ..core.schemas import Surface
from ..pipeline import RunResult

_SURFACE_NOTES = {
    Surface.SEO.value: "Classic organic search: ranking, clicking, converting.",
    Surface.AEO.value: "Answer engines: snippets, People Also Ask, AI Overviews on the SERP.",
    Surface.GEO.value: "Generative engines: ChatGPT, Perplexity, Gemini, Copilot.",
    Surface.TECHNICAL.value: "Site health and performance.",
    Surface.CONVERSION.value: "Converting the traffic that already arrives.",
    Surface.DISTRIBUTION.value: "Owned channels that seed discovery and citation.",
}


def _money(value: float, currency: str = "USD") -> str:
    """Format a currency amount compactly, without false precision."""
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency, f"{currency} ")
    if abs(value) >= 1_000_000:
        return f"{symbol}{value / 1_000_000:,.2f}M"
    if abs(value) >= 1_000:
        return f"{symbol}{value / 1_000:,.0f}K"
    return f"{symbol}{value:,.0f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:,.0f}%"


def render_markdown(result: RunResult, max_detailed: int = 25) -> str:
    """Render the full opportunity analysis as markdown."""
    config = result.config
    currency = config.currency
    portfolio = result.portfolio
    lines: list[str] = []

    def write(text: str = "") -> None:
        lines.append(text)

    # -- Header ---------------------------------------------------------
    write(f"# SEO / AEO / GEO Opportunity Analysis: {config.client_name}")
    write()
    write(
        f"_Generated {result.generated_at:%Y-%m-%d %H:%M} by Trail Guide v{result.version} - "
        f"{config.horizon_months}-month planning horizon, {config.quarters} quarters._"
    )
    if config.domain:
        write(f"_Domain: {config.domain}_")
    write()

    # -- Executive summary ----------------------------------------------
    write("## Executive summary")
    write()
    attainment = portfolio.target_attainment
    if config.revenue_target > 0:
        verdict = (
            "**on track**" if attainment and attainment >= 1.0
            else "**short of target**" if attainment and attainment < 0.9
            else "**close to target**"
        )
        write(
            f"The prioritized portfolio projects **{_money(portfolio.projected_revenue, currency)}** "
            f"of incremental revenue inside the {config.horizon_months}-month horizon against a "
            f"target of **{_money(config.revenue_target, currency)}** - "
            f"{_pct(attainment)} of goal, {verdict}."
        )
    else:
        write(
            f"The prioritized portfolio projects "
            f"**{_money(portfolio.projected_revenue, currency)}** of incremental revenue inside "
            f"the {config.horizon_months}-month horizon. No revenue target is configured, so this "
            f"is a ranked plan rather than a measured commitment."
        )
    write()
    write(
        f"Range: {_money(portfolio.projected_revenue_low, currency)} to "
        f"{_money(portfolio.projected_revenue_high, currency)}. All portfolio figures are "
        f"confidence-adjusted: each opportunity's projection is discounted by how much of it is "
        f"observed rather than modeled, so this total is comparable to a target rather than a "
        f"best case."
    )
    write()

    write(f"| Metric | Value |")
    write(f"| --- | --- |")
    write(f"| Opportunities identified | {len(result.opportunities)} |")
    write(f"| Scheduled within capacity | {len(portfolio.scheduled)} |")
    write(f"| Deferred (capacity-constrained) | {len(portfolio.deferred)} |")
    write(f"| Projected incremental revenue (horizon) | {_money(portfolio.projected_revenue, currency)} |")
    write(f"| Projected annual run rate once ramped | {_money(portfolio.projected_run_rate, currency)} |")
    write(f"| Delivery cost | {_money(portfolio.total_cost, currency)} |")
    write(f"| Effort | {portfolio.total_days:,.0f} person-days |")
    if portfolio.roi is not None:
        write(f"| Return on delivery cost (gross profit) | {portfolio.roi:,.1f}x |")
    write(f"| Value left unfunded | {_money(portfolio.deferred_value, currency)} |")
    write()

    top = portfolio.scheduled[:5]
    if top:
        write("### The five moves that matter most")
        write()
        for index, item in enumerate(top, start=1):
            opportunity = item.opportunity
            write(
                f"{index}. **{opportunity.title}** - "
                f"{_money(item.realized_revenue, currency)} in horizon, "
                f"{opportunity.effort.total_days:,.0f} days, "
                f"Q{item.start_quarter} start, {opportunity.surface.value}. "
                f"_{opportunity.recommended_actions[0] if opportunity.recommended_actions else ''}_"
            )
        write()

    # -- Revenue bridge -------------------------------------------------
    write("## Revenue bridge")
    write()
    write("| Step | Amount |")
    write("| --- | ---: |")
    for step in portfolio.revenue_bridge():
        prefix = "**" if step["kind"] in ("subtotal", "target", "gap", "surplus") else ""
        write(f"| {prefix}{step['label']}{prefix} | {_money(step['value'], currency)} |")
    write()

    gap = portfolio.gap_analysis()
    if gap.get("status") == "closable_with_capacity":
        days = ", ".join(
            f"{days:,.0f} {discipline}"
            for discipline, days in gap["additional_days_required"].items()
        )
        write(
            f"**Closing the gap.** The identified backlog covers the "
            f"{_money(gap['gap'], currency)} shortfall, but needs {days} person-days beyond "
            f"current capacity, at roughly "
            f"{_money(gap['additional_delivery_cost'], currency)} of additional delivery cost. "
            f"This is a capacity decision, not a strategy decision."
        )
        write()
    elif gap.get("status") == "short":
        write(
            f"**The target is not reachable from this dataset.** A "
            f"{_money(gap['gap'], currency)} gap remains, and "
            f"{_money(gap['residual_gap_after_deferred'], currency)} of it survives even if the "
            f"entire deferred backlog is funded. {gap['note']}"
        )
        write()
    elif gap.get("status") == "on_target":
        write(
            f"**The portfolio clears the target** by "
            f"{_money(gap['surplus'], currency)}, leaving headroom for slippage."
        )
        write()

    # -- Two-track measurement ------------------------------------------
    write("## Measurement baseline: the two-track model")
    write()
    write(
        "Referrer-based analytics capture only part of search and LLM influence. Track 1 is what "
        "was directly observed; Track 2 is the modeled demand that was satisfied on the SERP or "
        "inside an assistant, or that arrived later as direct and branded search. Every "
        "opportunity in this report is valued across both."
    )
    write()
    dark = result.dark
    write("| Track | Sessions (annualized) | Revenue | Confidence |")
    write("| --- | ---: | ---: | --- |")
    write(
        f"| Track 1 - organic search (observed) | {dark.seo.known_sessions:,.0f} | "
        f"{_money(dark.known_organic_revenue, currency)} | Observed |"
    )
    write(
        f"| Track 2 - dark organic (modeled) | {dark.seo.dark_sessions:,.0f} | "
        f"{_money(dark.dark_organic_revenue, currency)} | {_pct(dark.seo.confidence)} |"
    )
    write(
        f"| Track 1 - LLM referrals (observed) | {dark.geo.known_sessions:,.0f} | "
        f"{_money(dark.known_llm_revenue, currency)} | Observed |"
    )
    write(
        f"| Track 2 - dark LLM influence (modeled) | {dark.geo.dark_sessions:,.0f} | "
        f"{_money(dark.dark_llm_revenue, currency)} | {_pct(dark.geo.confidence)} |"
    )
    write(
        f"| **Total attributed value** | | "
        f"**{_money(dark.total_attributed_revenue, currency)}** | |"
    )
    write()
    if dark.seo.known_sessions > 0:
        write(
            f"Dark organic is modeled at **{dark.seo.multiplier:.2f}x** known organic sessions; "
            f"dark LLM influence at **{dark.geo.multiplier:.2f}x** observed LLM referrals."
        )
        write()
        write(
            "The organic multiplier grosses up every SEO and AEO opportunity below, since answer "
            "features are won on the search results page and earn organic clicks. Generative "
            "opportunities are not grossed up: they are sized directly as shares of the modeled "
            "LLM-influenced pool, so the parts can never claim more than the whole."
        )
        write()

    for track, label in (
        (dark.seo, "Dark organic (SEO and AEO)"),
        (dark.geo, "Dark LLM influence (GEO)"),
    ):
        write(f"### {label} - estimator triangulation")
        write()
        if track.estimates:
            write("| Method | Annual sessions | Weight | Basis |")
            write("| --- | ---: | ---: | --- |")
            for estimate in sorted(
                track.estimates, key=lambda item: item.confidence, reverse=True
            ):
                write(
                    f"| {estimate.method.replace('_', ' ')} | {estimate.dark_sessions:,.0f} | "
                    f"{estimate.confidence:.2f} | {estimate.note} |"
                )
            write(
                f"| **Blended (confidence-weighted)** | **{track.dark_sessions:,.0f}** | | "
                f"range {track.low:,.0f} - {track.high:,.0f} |"
            )
            write()
        else:
            write("_No estimator could run for this track._")
            write()
        if track.skipped:
            write("Unavailable methods:")
            write()
            for item in track.skipped:
                write(f"- `{item['method']}` - {item['reason']}")
            write()

    # -- Roadmap ---------------------------------------------------------
    write("## Prioritized roadmap")
    write()
    if portfolio.unconstrained:
        write(
            "_No delivery capacity is configured, so every opportunity is shown as startable "
            "immediately. Set `capacity.per_quarter` to produce a realistic sequence._"
        )
        write()
    for quarter, items in portfolio.by_quarter().items():
        if not items:
            continue
        quarter_revenue = sum(item.realized_revenue for item in items)
        quarter_days = sum(item.opportunity.effort.total_days for item in items)
        write(
            f"### Q{quarter} - {len(items)} initiatives, {quarter_days:,.0f} days, "
            f"{_money(quarter_revenue, currency)} in-horizon"
        )
        write()
        write("| # | Opportunity | Surface | Owner | Days | In-horizon revenue | Confidence |")
        write("| --- | --- | --- | --- | ---: | ---: | --- |")
        for item in items:
            opportunity = item.opportunity
            write(
                f"| {opportunity.rank} | {opportunity.title} | {opportunity.surface.value} | "
                f"{opportunity.owner_role} | {opportunity.effort.total_days:,.1f} | "
                f"{_money(item.realized_revenue, currency)} | "
                f"{opportunity.confidence.value} ({_pct(opportunity.effective_confidence)}) |"
            )
        write()

    # -- Capacity --------------------------------------------------------
    if not portfolio.unconstrained:
        write("## Capacity utilization")
        write()
        write("| Quarter | Discipline | Used | Available | Utilization |")
        write("| --- | --- | ---: | ---: | ---: |")
        for quarter, disciplines in portfolio.capacity_utilization().items():
            for discipline, values in disciplines.items():
                if values["total"] <= 0:
                    continue
                write(
                    f"| Q{quarter} | {discipline} | {values['used']:,.1f} | "
                    f"{values['total']:,.1f} | {values['utilization'] * 100:,.0f}% |"
                )
        write()

    # -- Opportunity register -------------------------------------------
    write("## Opportunity register")
    write()
    by_surface: dict[str, list] = {}
    for opportunity in result.opportunities:
        by_surface.setdefault(opportunity.surface.value, []).append(opportunity)
    write("| Surface | Count | Expected value (horizon) | What it covers |")
    write("| --- | ---: | ---: | --- |")
    for surface, items in sorted(
        by_surface.items(), key=lambda kv: sum(o.expected_value for o in kv[1]), reverse=True
    ):
        total = sum(item.expected_value for item in items)
        write(
            f"| {surface} | {len(items)} | {_money(total, currency)} | "
            f"{_SURFACE_NOTES.get(surface, '')} |"
        )
    write()

    write(f"### Ranked detail (top {min(max_detailed, len(result.opportunities))})")
    write()
    for opportunity in result.opportunities[:max_detailed]:
        projection = opportunity.projection
        write(f"#### {opportunity.rank}. {opportunity.title}")
        write()
        write(
            f"`{opportunity.id}` · **{opportunity.surface.value}** · "
            f"{opportunity.opportunity_type.replace('_', ' ')} · owner: {opportunity.owner_role} · "
            f"score {opportunity.score:.1f}"
        )
        write()
        write(
            f"- **Value:** {_money(projection.horizon_revenue, currency)} in horizon "
            f"({_money(projection.range_low, currency)} - "
            f"{_money(projection.range_high, currency)}), "
            f"{_money(projection.annual_run_rate, currency)} annual run rate once ramped"
        )
        write(
            f"- **Split:** {_money(projection.known_revenue, currency)} Track 1 (observed) + "
            f"{_money(projection.dark_revenue, currency)} Track 2 (modeled, "
            f"{_pct(projection.dark_share)} of total)"
        )
        write(
            f"- **Effort:** {opportunity.effort.total_days:,.1f} days "
            f"({', '.join(f'{days:g} {name}' for name, days in opportunity.effort.days_by_discipline.items())}), "
            f"{_money(opportunity.effort.total_cost, currency)}"
        )
        write(
            f"- **Timing:** {projection.lag_months:.1f} month lag, "
            f"{projection.ramp_months:.1f} month ramp · "
            f"**Confidence:** {opportunity.confidence.value} "
            f"({_pct(opportunity.effective_confidence)})"
            + (f" · **Strategic weight:** {opportunity.strategic_multiplier:g}x"
               if opportunity.strategic_multiplier != 1.0 else "")
        )
        if opportunity.roi is not None:
            write(f"- **Return on delivery cost:** {opportunity.roi:,.1f}x")
        write(f"- **Scope:** {len(opportunity.entities)} item(s)")
        write()

        if opportunity.recommended_actions:
            write("**Do this:**")
            write()
            for action in opportunity.recommended_actions:
                write(f"- {action}")
            write()
        if opportunity.evidence:
            write("**Evidence:**")
            write()
            write("| Source | Metric | Value |")
            write("| --- | --- | --- |")
            for item in opportunity.evidence[:10]:
                note = f" _({item.note})_" if item.note else ""
                write(f"| `{item.source}` | {item.metric} | {item.value}{note} |")
            write()
        if opportunity.risks:
            write("**Risks and caveats:**")
            write()
            for risk in opportunity.risks:
                write(f"- {risk}")
            write()
        if opportunity.measurement:
            write("**How we will know it worked:**")
            write()
            for measure in opportunity.measurement:
                write(f"- {measure}")
            write()
        write("---")
        write()

    if len(result.opportunities) > max_detailed:
        write(
            f"_{len(result.opportunities) - max_detailed} further opportunities are in "
            f"`opportunities.csv`._"
        )
        write()

    # -- Data coverage ---------------------------------------------------
    write("## Data coverage and confidence")
    write()
    write("| Source | Type | Status | Records |")
    write("| --- | --- | --- | ---: |")
    for entry in result.manifest:
        status = entry["status"]
        marker = {"ok": "loaded", "error": "**FAILED**", "disabled": "disabled"}.get(status, status)
        detail = f" - {entry['error']}" if entry.get("error") else ""
        write(f"| {entry['source']} | `{entry['type']}` | {marker}{detail} | {entry['records']:,} |")
    write()
    write("| Canonical collection | Records |")
    write("| --- | ---: |")
    for name, count in result.dataset.coverage().items():
        write(f"| {name} | {count:,} |")
    write()

    skipped = [entry for entry in result.analyzer_log if entry["status"] != "ok"]
    if skipped:
        write("### Analyses that could not run")
        write()
        for entry in skipped:
            write(f"- **{entry['analyzer']}** - {entry['reason']}")
        write()

    if result.warnings:
        write("### Warnings")
        write()
        for warning in result.warnings:
            write(f"- {warning}")
        write()

    # -- Methodology -----------------------------------------------------
    write("## Method and assumptions")
    write()
    economics = result.revenue.describe()
    write("| Assumption | Value |")
    write("| --- | --- |")
    write(f"| Revenue model | {economics['model']} |")
    write(f"| Blended conversion rate | {economics['base_conversion_rate'] * 100:.3f}% |")
    write(f"| Value per conversion | {_money(economics['base_deal_value'], currency)} |")
    write(f"| Revenue per session | {_money(economics['base_revenue_per_session'], currency)} |")
    write(f"| Gross margin | {_pct(economics['gross_margin'])} |")
    write(f"| Revenue lag (sales cycle) | {economics['revenue_lag_months']} months |")
    write(f"| Planning horizon | {config.horizon_months} months |")
    write()
    if result.revenue.calibration_notes:
        write(
            "These economics were calibrated against the client's own CRM data rather than "
            "taken from config:"
        )
        write()
        for note in result.revenue.calibration_notes:
            write(f"- {note}")
        write()
    else:
        write(
            "_No CRM calibration was applied; these are configured assumptions. Connecting a "
            "CRM export replaces them with the client's observed stage rates._"
        )
        write()
    write(
        "Opportunity value is ranked on confidence-adjusted revenue realized inside the horizon, "
        "divided by the person-days required - so a fast, well-evidenced win can outrank a larger "
        "but slower or more speculative one. Scheduling shifts each value curve by the time an "
        "item waits for capacity, which is why later quarters contribute less to this year's "
        "number."
    )
    write()
    write(
        "Track 2 figures are modeled, not observed. They are triangulated across independent "
        "methods and reported with their spread; where methods disagree, the range widens rather "
        "than the estimate hardening. Recalibrate quarterly as the POV prescribes, and treat "
        "movement in the estimators - not the point estimate alone - as the signal."
    )
    write()

    return "\n".join(lines)
