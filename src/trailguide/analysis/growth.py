"""Growth analyzers: conversion, distribution and measurement instrumentation.

Search work competes for the same capacity as conversion and distribution work,
so all three are sized here on the same revenue basis. Measurement gaps are
handled differently and deliberately: they are given no projected revenue at
all, because instrumentation does not create demand. They are tagged
``enabling`` and the portfolio reserves capacity for them, which keeps them
fundable without inventing revenue to justify them.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from ..core.opportunity import Opportunity, ValueProjection
from ..core.schemas import Confidence, Surface
from .base import AnalysisContext, Analyzer, register_analyzer


@register_analyzer
class ConversionRateAnalyzer(Analyzer):
    """Landing pages converting below their template's median.

    Converting existing traffic better is often cheaper than winning more of it,
    and the evidence is entirely first-party. The gap is measured against peers
    of the same template so a blog post is not held to a pricing page's rate.
    """

    name = "conversion_rate"
    surface = Surface.CONVERSION
    description = "High-traffic pages converting below their template peers."
    required_inputs = ("pages",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        min_sessions = self.setting(context, "min_annual_sessions", 500)
        capture_rate = self.setting(context, "gap_capture_rate", 0.35)
        min_gap = self.setting(context, "min_relative_gap", 0.25)
        min_peers = self.setting(context, "min_template_peers", 3)

        lag, ramp = context.timing(self.name)
        by_template: dict[str, list] = defaultdict(list)
        for url, page in context.pages.items():
            if page.sessions < min_sessions or page.conversion_rate is None:
                continue
            by_template[page.template or "other"].append((url, page))

        opportunities: list[Opportunity] = []
        for template, entries in by_template.items():
            if len(entries) < min_peers:
                continue
            rates = [page.conversion_rate for _, page in entries if page.conversion_rate]
            if not rates:
                continue
            benchmark = median(rates)
            if benchmark <= 0:
                continue

            under = [
                (url, page) for url, page in entries
                if page.conversion_rate is not None
                and (benchmark - page.conversion_rate) / benchmark >= min_gap
            ]
            if not under:
                continue

            recovered_conversions = sum(
                page.sessions * (benchmark - (page.conversion_rate or 0.0)) * capture_rate
                for _, page in under
            )
            if recovered_conversions <= 0:
                continue

            # Express the gain as the equivalent sessions that would produce it,
            # so it is valued on the same scale as every other opportunity.
            equivalent_sessions = recovered_conversions / benchmark
            revenue_rates = [
                page.revenue_per_session for _, page in under if page.revenue_per_session
            ]
            observed_rps = (
                sum(revenue_rates) / len(revenue_rates) if revenue_rates else None
            )

            projection = context.project(
                equivalent_sessions,
                self.surface,
                template=template,
                observed_revenue_per_session=observed_rps,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.40,
                include_dark=False,     # better conversion, not more demand
            )
            opportunity = Opportunity(
                title=(
                    f"Close the conversion gap on {len(under)} '{template}' page"
                    f"{'s' if len(under) != 1 else ''}"
                ),
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=min(float(len(under)), 6.0)),
                confidence=Confidence.OBSERVED,
                confidence_modifier=0.65,
                entities=[url for url, _ in under],
                owner_role=context.owner(self.name),
                tags=["cro"],
                recommended_actions=[
                    f"Compare the underperformers against the '{template}' pages converting at "
                    f"{benchmark:.2%}: offer placement, form length, proof and page intent.",
                    "Check intent alignment - a page ranking for informational queries will "
                    "under-convert against a commercial benchmark and may need a different CTA.",
                    "Instrument scroll depth and form abandonment before redesigning, so the fix "
                    "targets the actual drop-off.",
                    "Run the change as a test where traffic supports it rather than shipping blind.",
                ],
                risks=[
                    "A conversion gap can reflect query intent rather than page quality; "
                    "confirm before investing in a redesign.",
                ],
                measurement=[
                    f"Conversion rate for the affected URLs moving toward the {benchmark:.2%} "
                    f"template median",
                ],
            )
            for url, page in sorted(under, key=lambda item: item[1].sessions, reverse=True)[:8]:
                opportunity.add_evidence(
                    "ga4", url,
                    f"{page.sessions:,} sessions at {page.conversion_rate:.2%} vs "
                    f"{benchmark:.2%} template median",
                    Confidence.OBSERVED,
                )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class DistributionAnalyzer(Analyzer):
    """Owned-channel amplification of search and generative assets.

    Distribution earns its place here because newsletter and social activity
    seeds the third-party mentions and engagement signals generative engines
    retrieve. Value is modeled from the channel's own observed performance, not
    from a benchmark.
    """

    name = "distribution"
    surface = Surface.DISTRIBUTION
    description = "Owned channel amplification, sized from observed per-send performance."
    required_inputs = ()
    optional_inputs = ("channels",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        extra_units = self.setting(context, "incremental_units_per_month", 2)
        min_observations = self.setting(context, "min_observations", 4)
        # Incremental sends and posts reach a more saturated audience than the
        # existing cadence does, so they are valued below the observed average.
        marginal_performance = self.setting(context, "marginal_performance", 0.60)
        lag, ramp = context.timing(self.name)

        opportunities: list[Opportunity] = []
        for extras_key, label, channel_name in (
            ("newsletter", "newsletter sends", "email"),
            ("linkedin", "LinkedIn posts", "organic_social"),
        ):
            rows = context.dataset.extras.get(extras_key) or []
            if len(rows) < min_observations:
                continue

            clicks = [float(row.get("clicks") or 0) for row in rows]
            total_clicks = sum(clicks)
            if total_clicks <= 0:
                continue
            per_unit = total_clicks / len(rows)
            annual_sessions = per_unit * extra_units * 12.0 * marginal_performance

            projection = context.project(
                annual_sessions,
                self.surface,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.45,
                include_dark=False,     # owned-channel clicks are directly attributed
            )
            opportunity = Opportunity(
                title=f"Increase {label} by {extra_units}/month to amplify priority content",
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=float(extra_units)),
                confidence=Confidence.DERIVED,
                confidence_modifier=0.6,
                entities=[extras_key],
                owner_role=context.owner(self.name),
                tags=["distribution"],
                recommended_actions=[
                    "Prioritize the assets created for the top-ranked SEO and GEO opportunities; "
                    "distribution should follow the roadmap, not run parallel to it.",
                    "Publish the underlying data or point of view natively on the channel, not "
                    "just a link - native engagement is what earns third-party citation.",
                    "Track which sends and posts precede movement in branded search and direct "
                    "traffic; that relationship feeds the Track 2 model.",
                ],
                risks=[
                    "Owned-channel traffic inflates direct sessions and must be controlled for in "
                    "the dark-traffic model, which this system already does.",
                ],
                measurement=[
                    f"Sessions and conversions from {label} against the "
                    f"{per_unit:,.0f} clicks/unit baseline",
                ],
            )
            opportunity.add_evidence(
                extras_key, f"observed {label}",
                f"{len(rows)} units averaging {per_unit:,.0f} clicks each",
                Confidence.OBSERVED,
            )
            opportunity.add_evidence(
                "trailguide", "sizing basis",
                f"{extra_units} extra units/month valued at {marginal_performance:.0%} of the "
                f"observed average, for audience saturation",
                Confidence.MODELED,
            )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class MeasurementAnalyzer(Analyzer):
    """Missing inputs that leave part of the two-track model unmeasured.

    Emits zero-revenue, ``enabling``-tagged opportunities. Instrumentation does
    not create demand, so attaching a revenue projection to it would be
    dishonest. Instead each item states the revenue currently estimated without
    it and the estimators it would unlock, and the portfolio funds these from
    reserved capacity.
    """

    name = "measurement"
    surface = Surface.CONVERSION
    description = "Measurement gaps leaving Track 1 or Track 2 estimators unavailable."
    required_inputs = ()

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        dataset = context.dataset
        dark = context.dark
        gaps: list[tuple[str, str, float, list[str], list[str]]] = []

        if not dataset.surveys:
            at_stake = dark.dark_organic_revenue + dark.dark_llm_revenue
            gaps.append((
                "Deploy discovery-attribution surveys",
                "survey_calibration is unavailable on both tracks, so the dark pool rests "
                "entirely on modeled and third-party methods.",
                at_stake,
                [
                    "Add a one-question on-site intercept: 'How did you first hear about us?'",
                    "Add the same question to the post-purchase or post-demo flow, where "
                    "response quality is highest.",
                    "Include an explicit 'an AI assistant (ChatGPT, Perplexity, Copilot)' option - "
                    "without it, AI-influenced discovery is invisible.",
                    "Target 100+ responses per quarter to support the calibration estimator.",
                ],
                ["Survey response volume", "Calibration ratio vs analytics attribution"],
            ))

        if not dataset.citations:
            gaps.append((
                "Stand up a recurring LLM prompt and citation panel",
                "No citation data: share of model cannot be measured and the GEO track has no "
                "leading indicator.",
                dark.dark_llm_revenue,
                [
                    "Define 50-150 priority prompts across the buying journey, mapped to revenue.",
                    "Run them monthly across ChatGPT, Perplexity, Gemini and Copilot, recording "
                    "citation, position, sentiment and cited URLs.",
                    "Log competitor citations in the same run - relative share matters more than "
                    "absolute presence.",
                    "Hold the prompt set stable so month-over-month movement is comparable.",
                ],
                ["Citation rate and prominence by cluster", "Share of model versus competitors"],
            ))

        if not dataset.bot_hits:
            gaps.append((
                "Enable server log analysis for AI and search crawlers",
                "No log data: retrieval by AI crawlers cannot be confirmed, so retrieval "
                "readiness is unverifiable.",
                dark.dark_llm_revenue * 0.5,
                [
                    "Export or stream access logs from the CDN or origin.",
                    "Segment by user agent: Googlebot, Bingbot, GPTBot, OAI-SearchBot, "
                    "PerplexityBot, ClaudeBot, Google-Extended.",
                    "Report monthly crawl coverage of priority URLs by bot family.",
                ],
                ["AI crawler hits on priority URLs", "Crawl coverage of the priority page set"],
            ))

        if not dataset.funnel:
            gaps.append((
                "Connect CRM revenue data to the analysis",
                "No CRM feed: opportunities are valued on configured assumptions rather than "
                "the client's own stage-conversion rates and deal values.",
                dark.total_attributed_revenue * 0.25,
                [
                    "Export monthly sessions, leads, MQL, SQL and closed-won by original source.",
                    "Confirm the source taxonomy matches the analytics channel grouping.",
                    "Feed observed stage rates back into the economics config each quarter.",
                ],
                ["Stage conversion rates by source", "Closed-won revenue attributed to organic"],
            ))

        if not any(record.is_llm_referral for record in dataset.channels):
            gaps.append((
                "Instrument LLM referral tracking in analytics",
                "No LLM referral sessions observed: Track 1 for the generative surface is "
                "missing entirely, and the benchmark estimator has nothing to scale from.",
                dark.known_llm_revenue + dark.dark_llm_revenue,
                [
                    "Add a channel group matching chatgpt.com, perplexity.ai, gemini.google.com, "
                    "copilot.microsoft.com and claude.ai referrers.",
                    "Confirm referrer data is not stripped by consent or redirect handling.",
                    "Report LLM referral sessions, conversions and revenue as a standing metric.",
                ],
                ["LLM referral sessions and conversions", "Track 1 GEO revenue"],
            ))

        lag, ramp = context.timing(self.name)
        opportunities: list[Opportunity] = []
        for title, rationale, at_stake, actions, measures in gaps:
            projection = ValueProjection(
                incremental_sessions=0.0,
                known_revenue=0.0,
                dark_revenue=0.0,
                gross_margin=context.revenue.gross_margin,
                lag_months=lag,
                ramp_months=ramp,
                horizon_months=context.horizon_months,
                uncertainty=0.0,
                currency=context.revenue.currency,
            )
            opportunity = Opportunity(
                title=title,
                opportunity_type="measurement",
                surface=self.surface,
                projection=projection,
                effort=context.effort("measurement", units=1.0),
                confidence=Confidence.ASSUMED,
                entities=["measurement"],
                owner_role=context.owner("measurement"),
                tags=["enabling"],
                recommended_actions=actions,
                risks=[rationale],
                measurement=measures,
            )
            # Ordering signal for enabling work, preserved by the scoring engine.
            opportunity.score_components["revenue_at_stake"] = round(at_stake, 2)
            opportunity.add_evidence(
                "trailguide", "revenue currently estimated without this input",
                f"{at_stake:,.0f} {context.revenue.currency}",
                Confidence.MODELED,
                note=rationale,
            )
            opportunities.append(opportunity)

        return opportunities
