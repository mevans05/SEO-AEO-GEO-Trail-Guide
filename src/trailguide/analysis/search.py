"""Search analyzers: ranking, gap, cannibalization, decay and answer capture.

These are the analyses a growth analyst assembles by hand from Search Console
and Semrush exports. Each one here is expressed as an explicit, auditable model
so the output is reproducible and the assumptions are visible in config rather
than buried in a spreadsheet formula.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from ..core.classify import assign_cluster
from ..core.coerce import clamp
from ..core.opportunity import Opportunity
from ..core.schemas import Confidence, Intent, Surface
from ..core.stats import trend_ratio
from .base import AnalysisContext, Analyzer, register_analyzer

#: Realistic ceiling by keyword difficulty band: the best position worth
#: projecting, and the most positions a single optimization pass should be
#: assumed to move. Promising every keyword position 1 is the fastest way to
#: lose credibility with a client, so both limits bind.
_DIFFICULTY_TARGETS: tuple[tuple[float, float, float], ...] = (
    # (max_difficulty, best_realistic_position, max_positions_gained)
    (30.0, 2.0, 6.0),
    (50.0, 3.0, 5.0),
    (70.0, 5.0, 4.0),
    (101.0, 7.0, 3.0),
)


def _target_position(current: float, difficulty: float | None) -> float:
    """Pick a defensible target position given current rank and difficulty.

    Two limits apply together: a keyword is never projected past the best
    position its difficulty band supports, and never moved further than one
    optimization pass plausibly achieves. A keyword already inside its band
    returns its current position, which yields no modeled gain - the honest
    answer for a term that is already performing as well as the data supports.
    """
    kd = 50.0 if difficulty is None else float(difficulty)
    best_position, max_gain = _DIFFICULTY_TARGETS[-1][1], _DIFFICULTY_TARGETS[-1][2]
    for max_difficulty, band_best, band_gain in _DIFFICULTY_TARGETS:
        if kd < max_difficulty:
            best_position, max_gain = band_best, band_gain
            break
    target = max(best_position, current - max_gain)
    return max(1.0, min(target, current))


def _page_context(context: AnalysisContext, url: str | None):
    """Observed revenue-per-session and template for a URL, when analytics saw it."""
    if not url:
        return None, None
    page = context.pages.get(url)
    if page is None:
        return None, None
    return page.revenue_per_session, page.template


@register_analyzer
class StrikingDistanceAnalyzer(Analyzer):
    """Keywords ranking just below the positions that earn meaningful clicks.

    The highest-confidence opportunity type in the system: demand is proven by
    observed impressions, the page already ranks, and the only modeled step is
    the CTR gain from a position change.
    """

    name = "striking_distance"
    surface = Surface.SEO
    description = "Keywords on page 1-2 where a realistic rank gain converts to clicks."
    required_inputs = ("keywords",)
    optional_inputs = ("pages",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        min_position = self.setting(context, "min_position", 3.0)
        max_position = self.setting(context, "max_position", 20.0)
        min_impressions = self.setting(context, "min_impressions", 50)
        include_branded = self.setting(context, "include_branded", False)
        min_sessions_gain = self.setting(context, "min_sessions_gain", 25.0)
        cluster_rules = self.settings(context).get("cluster_rules")

        lag, ramp = context.timing(self.name)
        grouped: dict[str, list] = defaultdict(list)

        for record in context.keywords.values():
            if record.position is None or record.impressions < min_impressions:
                continue
            if not (min_position <= record.position <= max_position):
                continue
            if record.branded and not include_branded:
                continue
            grouped[record.page_url or f"keyword::{record.keyword}"].append(record)

        opportunities: list[Opportunity] = []
        for group_key, records in grouped.items():
            url = None if group_key.startswith("keyword::") else group_key
            total_gain = 0.0
            details: list[tuple] = []

            for record in records:
                target = _target_position(record.position, record.difficulty)
                gain = context.ctr.click_delta(
                    impressions=record.impressions,
                    current_position=record.position,
                    target_position=target,
                    branded=record.branded,
                    serp_features=record.serp_features,
                )
                if gain <= 0:
                    continue
                total_gain += gain
                details.append((record, target, gain))

            if total_gain < min_sessions_gain or not details:
                continue

            # Annualize: Search Console click deltas are for the export window.
            annual_gain = total_gain * self.setting(context, "annualization_factor", 12.0)
            details.sort(key=lambda item: item[2], reverse=True)
            dominant = details[0][0]
            observed_rps, template = _page_context(context, url)

            projection = context.project(
                annual_gain,
                self.surface,
                intent=dominant.intent,
                template=template,
                observed_revenue_per_session=observed_rps,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.25,
            )
            units = 1.0 + 0.2 * (len(details) - 1)
            cluster = assign_cluster(dominant.keyword, cluster_rules)

            opportunity = Opportunity(
                title=(
                    f"Lift {len(details)} striking-distance keyword"
                    f"{'s' if len(details) != 1 else ''} on "
                    f"{url or dominant.keyword}"
                ),
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=units),
                confidence=Confidence.OBSERVED,
                confidence_modifier=clamp(0.75 + 0.25 * min(len(details) / 5.0, 1.0), 0.6, 1.0),
                entities=[record.keyword for record, _, _ in details],
                owner_role=context.owner(self.name),
                strategic_multiplier=context.cluster_multiplier(cluster, template, dominant.intent.value),
                tags=["quick-win"] if lag <= 2 else [],
                recommended_actions=[
                    f"Rewrite the title and H1 on {url or 'the target page'} around "
                    f"'{dominant.keyword}' and its top variants.",
                    "Expand the section that answers the query directly; add a concise "
                    "summary block in the first 150 words for snippet and AI Overview eligibility.",
                    "Add 3-5 internal links from high-authority pages using the target phrasing.",
                    "Re-check position and CTR 30 days after publish; escalate to a link or "
                    "distribution play if position moves but CTR does not.",
                ],
                measurement=[
                    "Search Console: average position and clicks for the tracked keyword set",
                    "Track 2: impression-weighted zero-click gap for the same keywords",
                ],
            )
            for record, target, gain in details[:8]:
                opportunity.add_evidence(
                    "gsc",
                    f"'{record.keyword}' position {record.position:.1f} -> {target:.1f}",
                    f"{record.impressions:,} impressions, +{gain:,.0f} clicks/period",
                    Confidence.OBSERVED,
                    note=(
                        f"SERP features: {', '.join(record.serp_features)}"
                        if record.serp_features else None
                    ),
                )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class ContentGapAnalyzer(Analyzer):
    """Demand where competitors rank and the brand does not.

    Valued more conservatively than striking distance: search volume is a
    third-party estimate and ranking is assumed rather than observed, so the
    projection is marked modeled and discounted by keyword difficulty.
    """

    name = "content_gap"
    surface = Surface.SEO
    description = "Keywords with competitor coverage and no meaningful brand presence."
    required_inputs = ("keywords",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        competitor_max_position = self.setting(context, "competitor_max_position", 10.0)
        client_min_position = self.setting(context, "client_min_position", 20.0)
        min_volume = self.setting(context, "min_volume", 100)
        max_difficulty = self.setting(context, "max_difficulty", 75.0)
        target_position = self.setting(context, "target_position", 6.0)
        min_cluster_volume = self.setting(context, "min_cluster_volume", 500)
        cluster_rules = self.settings(context).get("cluster_rules")

        lag, ramp = context.timing(self.name)
        clusters: dict[str, list] = defaultdict(list)

        for record in context.keywords.values():
            if record.branded or not record.search_volume or record.search_volume < min_volume:
                continue
            if record.difficulty is not None and record.difficulty > max_difficulty:
                continue
            best_competitor = record.best_competitor_position
            if best_competitor is None or best_competitor > competitor_max_position:
                continue
            if record.position is not None and record.position <= client_min_position:
                continue
            cluster = (
                assign_cluster(record.keyword, cluster_rules)
                or _head_term(record.keyword)
            )
            clusters[cluster].append(record)

        opportunities: list[Opportunity] = []
        for cluster, records in clusters.items():
            total_volume = sum(record.search_volume or 0 for record in records)
            if total_volume < min_cluster_volume:
                continue

            annual_sessions = 0.0
            for record in records:
                ctr = context.ctr.expected_ctr(
                    target_position, branded=False, serp_features=record.serp_features
                )
                annual_sessions += (record.search_volume or 0) * ctr * 12.0

            difficulties = [r.difficulty for r in records if r.difficulty is not None]
            avg_difficulty = fmean(difficulties) if difficulties else 50.0
            # Harder clusters are less likely to reach the target position at all.
            capture_probability = clamp(1.0 - (avg_difficulty / 140.0), 0.25, 0.85)
            annual_sessions *= capture_probability

            intents = [r.intent for r in records if r.intent != Intent.UNKNOWN]
            dominant_intent = max(set(intents), key=intents.count) if intents else Intent.UNKNOWN

            projection = context.project(
                annual_sessions,
                self.surface,
                intent=dominant_intent,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.45,
            )
            pages_needed = max(1.0, round(len(records) / 6.0))
            competitors = sorted({
                name for record in records for name in record.competitor_positions
            })

            opportunity = Opportunity(
                title=f"Build coverage for the '{cluster}' cluster ({len(records)} keywords)",
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=pages_needed),
                confidence=Confidence.MODELED,
                confidence_modifier=capture_probability,
                entities=[record.keyword for record in records],
                owner_role=context.owner(self.name),
                strategic_multiplier=context.cluster_multiplier(cluster, dominant_intent.value),
                recommended_actions=[
                    f"Produce {int(pages_needed)} asset(s) covering the cluster, structured to "
                    f"answer the top queries directly in the opening section.",
                    "Mark up with FAQ/HowTo/Article schema so the pages are eligible for "
                    "answer features and retrievable by AI crawlers.",
                    f"Study how {', '.join(competitors[:3]) or 'competitors'} structure their "
                    f"coverage; match depth, then differentiate with first-party data.",
                    "Seed via newsletter and LinkedIn within 14 days of publish to build the "
                    "early engagement and citation signals generative engines retrieve.",
                ],
                risks=[
                    f"Average difficulty {avg_difficulty:.0f}/100; modeled capture probability "
                    f"{capture_probability:.0%}.",
                    "Volume is a third-party estimate and is not validated by first-party impressions.",
                ],
                measurement=[
                    "New-page impressions and position in Search Console at 30/60/90 days",
                    "Citation panel coverage for the cluster's prompts",
                ],
            )
            for record in sorted(records, key=lambda r: r.search_volume or 0, reverse=True)[:8]:
                best = record.best_competitor_position
                opportunity.add_evidence(
                    "semrush",
                    f"'{record.keyword}'",
                    f"{record.search_volume:,}/mo, KD {record.difficulty or 0:.0f}, "
                    f"best competitor position {best:.0f}",
                    Confidence.DERIVED,
                    note=f"brand position: {record.position or 'not ranking'}",
                )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class CannibalizationAnalyzer(Analyzer):
    """Multiple URLs competing for the same query.

    Needs a Search Console export carrying both query and page. Consolidation is
    cheap and fast relative to new content, which usually places these high on a
    value-per-day ranking.
    """

    name = "cannibalization"
    surface = Surface.SEO
    description = "Queries where several URLs split impressions and suppress each other."
    required_inputs = ("keywords",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        min_impressions = self.setting(context, "min_impressions_per_url", 30)
        min_urls = self.setting(context, "min_competing_urls", 2)
        expected_gain = self.setting(context, "expected_positions_gained", 2.0)
        min_sessions_gain = self.setting(context, "min_sessions_gain", 15.0)

        lag, ramp = context.timing(self.name)
        by_keyword: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for record in context.dataset.keywords:
            if record.page_url and record.impressions >= min_impressions:
                by_keyword[record.keyword.strip().lower()][record.page_url].append(record)

        opportunities: list[Opportunity] = []
        for keyword, pages in by_keyword.items():
            if len(pages) < min_urls:
                continue

            merged = []
            for url, records in pages.items():
                impressions = sum(r.impressions for r in records)
                clicks = sum(r.clicks for r in records)
                positions = [r.position for r in records if r.position is not None]
                if not positions:
                    continue
                merged.append((url, impressions, clicks, fmean(positions), records[0]))
            if len(merged) < min_urls:
                continue

            merged.sort(key=lambda item: item[3])   # best position first
            primary_url, _, _, best_position, sample = merged[0]
            total_impressions = sum(item[1] for item in merged)
            total_clicks = sum(item[2] for item in merged)

            target = max(1.0, best_position - expected_gain)
            consolidated_ctr = context.ctr.expected_ctr(
                target, branded=sample.branded, serp_features=sample.serp_features
            )
            gain = max(0.0, total_impressions * consolidated_ctr - total_clicks)
            annual_gain = gain * self.setting(context, "annualization_factor", 12.0)
            if annual_gain < min_sessions_gain * 12:
                continue

            observed_rps, template = _page_context(context, primary_url)
            projection = context.project(
                annual_gain,
                self.surface,
                intent=sample.intent,
                template=template,
                observed_revenue_per_session=observed_rps,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.30,
            )
            opportunity = Opportunity(
                title=f"Consolidate {len(merged)} URLs competing for '{keyword}'",
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=float(len(merged))),
                confidence=Confidence.OBSERVED,
                confidence_modifier=0.8,
                entities=[item[0] for item in merged],
                owner_role=context.owner(self.name),
                strategic_multiplier=context.cluster_multiplier(template, sample.intent.value),
                tags=["quick-win"],
                recommended_actions=[
                    f"Designate {primary_url} as the canonical answer for '{keyword}'.",
                    "Merge the unique value from the secondary URLs into the primary page.",
                    "301 the retired URLs to the primary and update internal links to point there.",
                    "Differentiate any page that must stay live by retargeting it to a distinct query.",
                ],
                measurement=[
                    f"Search Console: impressions and clicks for '{keyword}' consolidating onto "
                    f"one URL within 60 days",
                ],
            )
            for url, impressions, clicks, position, _ in merged:
                opportunity.add_evidence(
                    "gsc", url,
                    f"position {position:.1f}, {impressions:,} impressions, {clicks:,} clicks",
                    Confidence.OBSERVED,
                )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class ContentDecayAnalyzer(Analyzer):
    """Pages losing search traffic that a refresh can recover.

    Recovering a page that already ranked is materially cheaper and faster than
    winning a new one, and the evidence is first-party, so decay work usually
    outranks net-new content on value per day.
    """

    name = "content_decay"
    surface = Surface.SEO
    description = "Pages in sustained click decline where a refresh can recover traffic."
    required_inputs = ("pages",)
    optional_inputs = ("crawl_issues",)

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        decline_threshold = self.setting(context, "decline_threshold", 0.85)
        min_clicks = self.setting(context, "min_prior_clicks", 100)
        recovery_rate = self.setting(context, "recovery_rate", 0.60)
        window = self.setting(context, "window_months", 3)
        stale_months = self.setting(context, "stale_after_months", 12)

        lag, ramp = context.timing(self.name)
        by_url: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for page in context.dataset.pages:
            date = page.period_start or page.period_end
            if not page.url or not date:
                continue
            metric = page.clicks or page.sessions
            if metric:
                by_url[page.url][date.strftime("%Y-%m")] += metric

        opportunities: list[Opportunity] = []
        for url, monthly in by_url.items():
            months = sorted(monthly)
            if len(months) < window * 2:
                continue
            series = [monthly[month] for month in months]
            ratio = trend_ratio(series, window=window)
            prior = sum(series[-window * 2 : -window])
            if ratio is None or ratio >= decline_threshold or prior < min_clicks:
                continue

            recent = sum(series[-window:])
            lost_per_window = prior - recent
            annual_recovery = (lost_per_window * recovery_rate) * (12.0 / window)

            page = context.pages.get(url)
            observed_rps = page.revenue_per_session if page else None
            template = page.template if page else None

            stale = False
            if page and page.updated_at:
                months_since = (max(months) and _months_between(page.updated_at, months[-1])) or 0
                stale = months_since >= stale_months

            projection = context.project(
                annual_recovery,
                self.surface,
                template=template,
                observed_revenue_per_session=observed_rps,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.30,
            )
            opportunity = Opportunity(
                title=f"Refresh decaying page: {url}",
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=1.0),
                confidence=Confidence.OBSERVED,
                confidence_modifier=0.85 if stale else 0.75,
                entities=[url],
                owner_role=context.owner(self.name),
                strategic_multiplier=context.cluster_multiplier(template),
                tags=["quick-win", "decay"],
                recommended_actions=[
                    "Audit the SERP for this page's primary queries: check whether an AI Overview, "
                    "a new competitor, or a format change absorbed the clicks.",
                    "Refresh statistics, examples and dates; restructure the opening to answer the "
                    "primary query in the first 150 words.",
                    "Re-promote through newsletter and social once updated, and resubmit in "
                    "Search Console.",
                ]
                + (["Content has not been updated in over a year - prioritize a substantive rewrite."]
                   if stale else []),
                measurement=[
                    f"Clicks for {url} returning toward the {prior:,.0f}-click prior baseline",
                ],
            )
            opportunity.add_evidence(
                "gsc", url,
                f"{recent:,.0f} clicks in the last {window} months vs {prior:,.0f} in the prior "
                f"{window} ({(ratio - 1) * 100:+.0f}%)",
                Confidence.OBSERVED,
                note=f"{recovery_rate:.0%} of the loss modeled as recoverable",
            )
            if page and page.updated_at:
                opportunity.add_evidence(
                    "cms", url, f"last updated {page.updated_at.isoformat()}", Confidence.OBSERVED
                )
            opportunities.append(opportunity)

        return opportunities


@register_analyzer
class AnswerCaptureAnalyzer(Analyzer):
    """SERP answer features the brand ranks near but does not own.

    This is AEO on the classic SERP: featured snippets, People Also Ask and AI
    Overviews. Winning the answer both recovers suppressed clicks and increases
    the chance of being the source a generative engine quotes, so it is scored
    on the AEO surface and picks up the AEO dark-traffic multiplier.
    """

    name = "answer_capture"
    surface = Surface.AEO
    description = "Answer features (snippets, PAA, AI Overviews) the brand is positioned to win."
    required_inputs = ("keywords",)

    #: Features worth contesting, with the share of the suppressed clicks that
    #: owning the answer is modeled to recover.
    _TARGET_FEATURES = {
        "featured_snippet": 0.60,
        "ai_overview": 0.35,
        "people_also_ask": 0.25,
    }

    def analyze(self, context: AnalysisContext) -> list[Opportunity]:
        max_position = self.setting(context, "max_position", 10.0)
        min_impressions = self.setting(context, "min_impressions", 100)
        min_sessions_gain = self.setting(context, "min_sessions_gain", 20.0)

        lag, ramp = context.timing(self.name)
        grouped: dict[str, list] = defaultdict(list)

        for record in context.keywords.values():
            if record.position is None or record.position > max_position:
                continue
            if record.impressions < min_impressions or record.branded:
                continue
            features = set(record.serp_features or [])
            if "featured_snippet_owned" in features:
                continue    # already owned
            targets = features & set(self._TARGET_FEATURES)
            if not targets:
                continue
            grouped[record.page_url or f"keyword::{record.keyword}"].append((record, targets))

        opportunities: list[Opportunity] = []
        for group_key, entries in grouped.items():
            url = None if group_key.startswith("keyword::") else group_key
            total_gain = 0.0
            for record, targets in entries:
                suppressed = context.ctr.suppressed_clicks(
                    impressions=record.impressions,
                    position=record.position,
                    observed_clicks=record.clicks,
                    branded=False,
                    serp_features=record.serp_features,
                )
                recovery = max(self._TARGET_FEATURES[name] for name in targets)
                total_gain += suppressed * recovery

            annual_gain = total_gain * self.setting(context, "annualization_factor", 12.0)
            if annual_gain < min_sessions_gain * 12:
                continue

            sample = entries[0][0]
            observed_rps, template = _page_context(context, url)
            all_features = sorted({name for _, targets in entries for name in targets})

            projection = context.project(
                annual_gain,
                self.surface,
                intent=sample.intent,
                template=template,
                observed_revenue_per_session=observed_rps,
                lag_months=lag,
                ramp_months=ramp,
                base_uncertainty=0.40,
            )
            opportunity = Opportunity(
                title=(
                    f"Capture {', '.join(f.replace('_', ' ') for f in all_features)} for "
                    f"{len(entries)} quer{'ies' if len(entries) != 1 else 'y'} on "
                    f"{url or sample.keyword}"
                ),
                opportunity_type=self.name,
                surface=self.surface,
                projection=projection,
                effort=context.effort(self.name, units=1.0 + 0.2 * (len(entries) - 1)),
                confidence=Confidence.DERIVED,
                confidence_modifier=0.7,
                entities=[record.keyword for record, _ in entries],
                owner_role=context.owner(self.name),
                strategic_multiplier=context.cluster_multiplier(template, sample.intent.value),
                recommended_actions=[
                    "Add a 40-60 word direct answer immediately under a heading that matches the "
                    "query phrasing.",
                    "Use the format the current answer uses - list, table or definition - and make "
                    "it self-contained so it can be lifted whole.",
                    "Add FAQ or HowTo schema and ensure the answer is in the server-rendered HTML, "
                    "not injected client-side.",
                    "Add a citable statistic or first-party datapoint; generative engines "
                    "disproportionately quote sourced specifics.",
                ],
                risks=[
                    "AI Overview presence suppresses clicks even when the brand is cited; part of "
                    "the return lands in Track 2 rather than as measured sessions.",
                ],
                measurement=[
                    "Rank tracker: snippet/answer ownership for the tracked queries",
                    "Search Console: CTR at stable position for the same queries",
                    "Citation panel: brand cited for the equivalent prompts",
                ],
            )
            for record, targets in entries[:8]:
                observed_ctr = record.ctr or 0.0
                expected = context.ctr.base_ctr(record.position)
                opportunity.add_evidence(
                    "gsc", f"'{record.keyword}'",
                    f"position {record.position:.1f}, CTR {observed_ctr:.1%} vs {expected:.1%} "
                    f"expected; features: {', '.join(sorted(targets))}",
                    Confidence.OBSERVED,
                )
            opportunities.append(opportunity)

        return opportunities


def _head_term(keyword: str) -> str:
    """Crude cluster label: the first two tokens of the keyword."""
    tokens = str(keyword).lower().split()
    return " ".join(tokens[:2]) if tokens else "uncategorized"


def _months_between(start, end_month: str) -> int:
    """Whole months between a date and a ``YYYY-MM`` label."""
    try:
        year, month = (int(part) for part in end_month.split("-"))
    except (ValueError, AttributeError):
        return 0
    return max(0, (year - start.year) * 12 + (month - start.month))
