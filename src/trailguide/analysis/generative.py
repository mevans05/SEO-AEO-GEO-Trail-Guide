"""Generative engine analyzers: citation share and retrieval readiness.

The AEO/GEO point of view treats citation volume, prominence and sentiment as
the leading indicator for downstream demand. These analyzers act on that
directly: find the priority prompts where competitors are cited and the brand is
not, and find the pages that generative engines cannot or do not retrieve.

Both surfaces carry the GEO dark-traffic multiplier, because most of the value
of being cited never appears as a referral.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from ..core.coerce import clamp
from ..core.opportunity import Opportunity
from ..core.schemas import Confidence, Surface
from .base import AnalysisContext, Analyzer, register_analyzer


@register_analyzer
class CitationGapAnalyzer(Analyzer):
    """Priority prompts where competitors are cited and the brand is not.

    Share of model is measured per prompt cluster across engines, so the output
    distinguishes "invisible everywhere" from "strong on Perplexity, absent on
    ChatGPT" - which are different problems with different fixes.
    """

    name = "citation_gap"
    surface = Surface.GEO
    description = "Prompt clusters where competitors own the answer and the brand does not."
    required_inputs = ("citations",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        max_citation_rate = self.setting(context, "max_brand_citation_rate", 0.60)
        min_volume = self.setting(context, "min_cluster_volume", 100)
        target_prominence = self.setting(context, "target_prominence", 0.60)
        min_observations = self.setting(context, "min_observations", 3)

        lag, ramp = context.timing(self.name)
        clusters: dict[str, list] = defaultdict(list)
        for record in context.dataset.citations:
            key = (record.prompt_cluster or record.prompt or "uncategorized").strip().lower()
            clusters[key].append(record)

        # Generative opportunities are sized as shares of the LLM-influenced pool
        # the Track 2 model actually estimated, rather than from an independent
        # visit rate. That keeps the analyzers and the measurement model
        # internally consistent: the parts can never claim more than the whole.
        generative_pool = context.dark.geo.known_sessions + context.dark.geo.dark_sessions
        cluster_volumes = {
            name: _cluster_volume(records) for name, records in clusters.items()
        }
        total_prompt_volume = sum(cluster_volumes.values())
        if generative_pool <= 0 or total_prompt_volume <= 0:
            return []

        opportunities: list[Opportunity] = []
        for cluster, records in clusters.items():
            if len(records) < min_observations:
                continue

            prompts = {record.prompt.strip().lower(): record for record in records}
            monthly_volume = cluster_volumes.get(cluster, 0)
            if monthly_volume < min_volume:
                continue

            citation_rate = sum(1 for r in records if r.brand_cited) / len(records)
            current_prominence = fmean(record.prominence for record in records)
            if citation_rate > max_citation_rate and current_prominence >= target_prominence:
                continue    # already winning this cluster

            prominence_gain = max(0.0, target_prominence - current_prominence)
            if prominence_gain <= 0:
                continue

            # This cluster's share of total prompt demand, multiplied by the
            # prominence the brand stands to gain within it.
            cluster_share = monthly_volume / total_prompt_volume
            annual_sessions = generative_pool * cluster_share * prominence_gain

            by_engine = _engine_breakdown(records)
            competitors = _competitor_counts(records)
            sentiments = [r.sentiment for r in records if r.sentiment is not None]
            avg_sentiment = fmean(sentiments) if sentiments else None

            projection = context.project(
                annual_sessions,
                self.surface,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.55,
                # Prompt volume x prominence already estimates total generative
                # influence, most of which is dark. Applying the Track 2
                # multiplier on top would count that pool twice.
                include_dark=False,
            )
            prompts_needing_work = max(1.0, round(len(prompts) / 4.0))

            opportunity = Opportunity(
                title=(
                    f"Win share of model for '{cluster}' "
                    f"(cited in {citation_rate:.0%} of answers)"
                ),
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=prompts_needing_work),
                confidence=Confidence.MODELED,
                confidence_modifier=clamp(0.35 + 0.05 * len(records), 0.35, 0.75),
                entities=sorted(prompts),
                owner_role=context.owner(self.name),
                strategic_multiplier=context.cluster_multiplier(cluster),
                tags=["geo"],
                recommended_actions=[
                    f"Publish a directly citable answer for each of the {len(prompts)} prompts: "
                    f"a clear claim, a first-party statistic, and a named source.",
                    "Structure with question-shaped headings, short self-contained paragraphs and "
                    "Article/FAQ schema so passages can be retrieved independently.",
                    f"Earn third-party citations where {', '.join(list(competitors)[:3]) or 'competitors'} "
                    f"are already referenced - review sites, industry roundups, comparison pages.",
                    "Keep entity data consistent across the site, LinkedIn and third-party "
                    "profiles; generative engines reconcile brand identity across sources.",
                    "Re-run the prompt panel monthly and track citation rate and prominence "
                    "as the primary KPI.",
                ],
                risks=[
                    "Generative visibility converts to measured sessions at a low, modeled rate; "
                    "most of the projected value sits in Track 2.",
                    "Engine behaviour shifts without notice; re-baseline the panel quarterly.",
                ],
                measurement=[
                    f"Citation rate for '{cluster}' rising from {citation_rate:.0%}",
                    f"Brand prominence rising from {current_prominence:.2f} toward "
                    f"{target_prominence:.2f}",
                    "LLM referral sessions and assisted conversions in analytics",
                ],
            )
            opportunity.add_evidence(
                "llm_panel", f"'{cluster}' share of model",
                f"cited in {citation_rate:.0%} of {len(records)} observations across "
                f"{len(by_engine)} engines; prominence {current_prominence:.2f}",
                Confidence.OBSERVED,
                note=f"{monthly_volume:,} estimated monthly prompt volume",
            )
            opportunity.add_evidence(
                "trailguide", "sizing basis",
                f"{cluster_share:.0%} of prompt demand x {prominence_gain:.2f} prominence gain "
                f"against a {generative_pool:,.0f}-session modeled LLM-influenced pool",
                Confidence.MODELED,
            )
            for engine, (rate, count) in sorted(by_engine.items()):
                opportunity.add_evidence(
                    "llm_panel", f"{engine} citation rate",
                    f"{rate:.0%} of {count} observations", Confidence.OBSERVED,
                )
            for competitor, count in sorted(
                competitors.items(), key=lambda item: item[1], reverse=True
            )[:5]:
                opportunity.add_evidence(
                    "llm_panel", f"competitor cited: {competitor}",
                    f"{count} of {len(records)} answers", Confidence.OBSERVED,
                )
            if avg_sentiment is not None:
                opportunity.add_evidence(
                    "llm_panel", "average sentiment when cited", f"{avg_sentiment:+.2f}",
                    Confidence.OBSERVED,
                    note="negative sentiment needs a narrative fix, not more content"
                    if avg_sentiment < 0 else None,
                )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class RetrievalReadinessAnalyzer(Analyzer):
    """Pages generative engines cannot or do not retrieve.

    Retrieval is the precondition for citation. A page that AI crawlers never
    fetch cannot be quoted no matter how good it is, which makes this the
    cheapest structural fix available on the GEO surface.
    """

    name = "retrieval_readiness"
    surface = Surface.GEO
    description = "Pages with demand that AI crawlers do not retrieve."
    required_inputs = ("pages",)
    optional_inputs = ("bot_hits", "citations")

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        min_impressions = self.setting(context, "min_impressions", 200)
        # Retrieval is a precondition for citation rather than a win in itself,
        # so it claims a deliberately modest slice of the pool it unlocks.
        capture_rate = self.setting(context, "retrieval_capture_rate", 0.15)
        min_sessions_gain = self.setting(context, "min_sessions_gain", 25.0)

        lag, ramp = context.timing(self.name)
        bot_hits = context.dataset.bot_hits
        ai_retrieved = {record.url for record in bot_hits if record.is_ai_bot}
        search_retrieved = {record.url for record in bot_hits if not record.is_ai_bot}
        opportunities: list[Opportunity] = []

        # A site crawled by search engines but by no AI crawler is blocking them.
        if bot_hits and not ai_retrieved and search_retrieved:
            opportunities.append(self._blocked_opportunity(context, len(search_retrieved), lag, ramp))

        if not bot_hits:
            return opportunities

        candidates = []
        for url, page in context.pages.items():
            if url in ai_retrieved:
                continue
            if (page.impressions or 0) < min_impressions:
                continue
            if page.indexable is False:
                continue
            candidates.append((url, page))

        if not candidates:
            return opportunities

        # Size by the share of site demand these unreachable pages represent,
        # against the modeled generative pool.
        generative_pool = context.dark.geo.known_sessions + context.dark.geo.dark_sessions
        total_impressions = sum(page.impressions or 0 for page in context.pages.values())
        blocked_impressions = sum(page.impressions or 0 for _, page in candidates)
        if generative_pool <= 0 or total_impressions <= 0:
            return opportunities

        demand_share = blocked_impressions / total_impressions
        annual_sessions = generative_pool * demand_share * capture_rate
        if annual_sessions < min_sessions_gain:
            return opportunities

        projection = context.project(
            annual_sessions,
            self.surface,
            lag_months=lag,
            ramp_months=ramp,
            base_uncertainty=0.60,
            # Modeled directly as generative influence, which is already dark.
            include_dark=False,
        )
        opportunity = Opportunity(
            title=f"Make {len(candidates)} high-demand pages retrievable by AI crawlers",
            opportunity_type=self.name,
            surface=self.surface,
            projection=projection,
            effort=context.effort(self.name, units=min(float(len(candidates)), 20.0)),
            confidence=Confidence.MODELED,
            confidence_modifier=0.5,
            entities=[url for url, _ in candidates],
            owner_role=context.owner(self.name),
            tags=["geo", "technical"],
            recommended_actions=[
                "Confirm robots.txt allows GPTBot, OAI-SearchBot, PerplexityBot, ClaudeBot and "
                "Google-Extended, and that no CDN rule blocks them at the edge.",
                "Serve the primary content server-side; most AI crawlers do not execute "
                "JavaScript, so client-rendered content is invisible to them.",
                "Add Article, FAQ and Organization schema, and keep author and publish-date "
                "metadata current.",
                "Structure pages into self-contained, question-shaped passages that can be "
                "retrieved and quoted without surrounding context.",
                "Re-check server logs after 30 days to confirm AI crawler hits on these URLs.",
            ],
            risks=[
                "Allowing AI crawlers grants training and retrieval access; confirm the "
                "commercial position with the client before changing robots.txt.",
                "Retrieval enables citation but does not guarantee it; this is a precondition, "
                "not a win.",
            ],
            measurement=[
                "Server logs: AI crawler hits on the target URLs",
                "Citation panel: brand cited for prompts these pages answer",
            ],
        )
        for url, page in sorted(
            candidates, key=lambda item: item[1].impressions or 0, reverse=True
        )[:10]:
            opportunity.add_evidence(
                "server_logs", url,
                f"{page.impressions:,} search impressions, no AI crawler retrieval observed",
                Confidence.OBSERVED,
            )
        opportunity.add_evidence(
            "trailguide", "sizing basis",
            f"{demand_share:.0%} of site demand is unreachable by AI crawlers; "
            f"{capture_rate:.0%} of that share of a {generative_pool:,.0f}-session modeled "
            f"pool is treated as recoverable",
            Confidence.MODELED,
        )
        opportunities.append(opportunity)
        return opportunities

    def _blocked_opportunity(
        self, context: AnalysisContext, search_pages: int, lag: float, ramp: float
    ) -> Opportunity:
        """Flag a site that search engines crawl but AI crawlers never touch."""
        geo_dark = context.dark.geo.dark_sessions
        projection = context.project(
            geo_dark * self.setting(context, "unblock_capture_rate", 0.25),
            self.surface,
            lag_months=lag,
            ramp_months=ramp,
            base_uncertainty=0.65,
            include_dark=False,     # the GEO dark pool is already the basis here
        )
        return Opportunity(
            title="No AI crawler activity detected - verify AI crawlers are not blocked",
            opportunity_type=self.name,
            surface=self.surface,
            projection=projection,
            effort=context.effort(self.name, units=2.0),
            confidence=Confidence.MODELED,
            confidence_modifier=0.45,
            entities=["robots.txt", "CDN/WAF configuration"],
            owner_role=context.owner(self.name),
            tags=["geo", "technical", "quick-win"],
            recommended_actions=[
                "Audit robots.txt for disallow rules covering GPTBot, OAI-SearchBot, "
                "ChatGPT-User, PerplexityBot, ClaudeBot and Google-Extended.",
                "Check CDN/WAF bot-management rules; these block AI crawlers more often than "
                "robots.txt does, and silently.",
                "Confirm with the client whether the block is deliberate before changing it.",
                "Re-check logs 14 days after any change.",
            ],
            risks=["The block may be an intentional content-licensing decision."],
            measurement=["Server logs: AI crawler hits appearing where there are currently none"],
        ).add_evidence(
            "server_logs", "AI crawler retrievals",
            f"0 across the log window, against {search_pages:,} URLs retrieved by search crawlers",
            Confidence.OBSERVED,
        )


def _cluster_volume(records) -> int:
    """Total monthly prompt volume for a cluster, counting each prompt once."""
    per_prompt: dict[str, int] = {}
    for record in records:
        key = record.prompt.strip().lower()
        volume = record.monthly_prompt_volume or 0
        per_prompt[key] = max(per_prompt.get(key, 0), volume)
    return sum(per_prompt.values())


def _engine_breakdown(records) -> dict[str, tuple[float, int]]:
    """Citation rate and observation count per engine."""
    by_engine: dict[str, list] = defaultdict(list)
    for record in records:
        by_engine[record.engine or "unknown"].append(record)
    return {
        engine: (sum(1 for r in items if r.brand_cited) / len(items), len(items))
        for engine, items in by_engine.items()
    }


def _competitor_counts(records) -> dict[str, int]:
    """How often each competitor is cited across the observation set."""
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        for name in record.competitors_cited:
            counts[name.strip()] += 1
    return dict(counts)
