"""Track 2: modeling dark traffic for both SEO and AEO/GEO.

This module implements the measurement model at the centre of both points of
view. Referrer-based analytics capture only part of search and LLM influence;
the rest is satisfied on the SERP, satisfied inside the assistant, or arrives
later as direct and branded search. Track 2 sizes that missing pool.

The design commitment is triangulation, not a single model. Five independent
estimator families run against whatever inputs exist, each returning its own
number, its own confidence and its own assumptions. The blended point estimate
is a confidence-weighted mean and the reported range is the spread between
estimators - so when methods disagree, the output says so instead of hiding it.

Every estimator degrades to "unavailable" rather than guessing when its inputs
are missing, and the run reports which ones were skipped.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..core import stats
from ..core.coerce import clamp
from ..core.ctr import CTRModel
from ..core.economics import RevenueModel
from ..core.schemas import Dataset

#: Default assumptions, all overridable under ``dark_traffic`` in client config.
DEFAULTS: dict[str, float] = {
    # Share of zero-click impressions that still generate later demand.
    "zero_click_assist_rate": 0.12,
    # Cap on the share of direct + branded traffic attributable to dark organic.
    "max_branded_direct_share": 0.50,
    # Third-party benchmark: dark organic as a multiple of known organic sessions.
    "benchmark_dark_organic_multiplier": 0.22,
    # Third-party benchmark: total LLM influence as a multiple of LLM referrals.
    "benchmark_llm_multiplier": 6.0,
    # Share of LLM answers citing the brand that produce a site visit.
    "citation_visit_rate": 0.14,
    # Sessions implied per AI crawler retrieval.
    "crawler_session_ratio": 0.015,
    # Minimum monthly periods required for the branded-lift regression.
    "min_periods_for_lift": 6,
    # Periods per year in the keyword export, so the zero-click estimate is
    # annualized onto the same basis as every other estimator. A one-month
    # Search Console window is 12; a full-year export is 1.
    "keyword_periods_per_year": 12.0,
    # Survey respondents needed before the survey estimator is fully weighted.
    "survey_confidence_n": 100,
}

#: Confidence assigned to each method, reflecting how far it sits from observation.
METHOD_CONFIDENCE: dict[str, float] = {
    "zero_click_ctr_gap": 0.60,
    "branded_direct_lift": 0.55,
    "third_party_benchmark": 0.35,
    "survey_calibration": 0.60,
    "citation_share": 0.45,
    "crawler_retrieval": 0.30,
}


@dataclass
class Estimate:
    """One estimator's view of the dark pool."""

    method: str
    track: str                      # "seo" or "geo"
    dark_sessions: float            # annualized
    confidence: float               # 0-1
    note: str
    inputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "track": self.track,
            "dark_sessions": round(self.dark_sessions, 1),
            "confidence": round(self.confidence, 3),
            "note": self.note,
            "inputs": self.inputs,
        }


@dataclass
class TrackEstimate:
    """Blended result for one track, retaining every contributing estimate."""

    track: str
    known_sessions: float
    estimates: list[Estimate] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def dark_sessions(self) -> float:
        """Confidence-weighted blend across the available estimators."""
        if not self.estimates:
            return 0.0
        return stats.weighted_mean(
            [(item.dark_sessions, item.confidence) for item in self.estimates]
        )

    @property
    def low(self) -> float:
        return min((item.dark_sessions for item in self.estimates), default=0.0)

    @property
    def high(self) -> float:
        return max((item.dark_sessions for item in self.estimates), default=0.0)

    @property
    def multiplier(self) -> float:
        """Dark sessions per known session - the factor used to gross up value."""
        if self.known_sessions <= 0:
            return 0.0
        return self.dark_sessions / self.known_sessions

    @property
    def confidence(self) -> float:
        """Blended confidence, lifted when independent methods agree.

        Agreement between methods is itself evidence. Two estimators landing
        within a tight band earn a modest bonus; a wide spread does not.
        """
        if not self.estimates:
            return 0.0
        base = stats.weighted_mean(
            [(item.confidence, item.confidence) for item in self.estimates]
        )
        if len(self.estimates) < 2:
            return clamp(base, 0.0, 1.0)
        point = self.dark_sessions
        spread = (self.high - self.low) / point if point > 0 else 1.0
        convergence_bonus = clamp(0.20 * (1.0 - clamp(spread, 0.0, 1.0)), 0.0, 0.20)
        return clamp(base + convergence_bonus, 0.0, 1.0)

    @property
    def uncertainty(self) -> float:
        """Relative half-width of the estimator spread, used for value ranges."""
        point = self.dark_sessions
        if point <= 0 or len(self.estimates) < 2:
            return 0.50
        return clamp((self.high - self.low) / (2.0 * point), 0.15, 0.90)

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "known_sessions": round(self.known_sessions, 1),
            "dark_sessions": round(self.dark_sessions, 1),
            "dark_sessions_low": round(self.low, 1),
            "dark_sessions_high": round(self.high, 1),
            "multiplier": round(self.multiplier, 4),
            "confidence": round(self.confidence, 3),
            "uncertainty": round(self.uncertainty, 3),
            "estimates": [item.to_dict() for item in self.estimates],
            "skipped": self.skipped,
        }


@dataclass
class DarkTrafficResult:
    """The full two-track picture, ready for both valuation and reporting."""

    seo: TrackEstimate
    geo: TrackEstimate
    known_organic_revenue: float = 0.0
    known_llm_revenue: float = 0.0
    dark_organic_revenue: float = 0.0
    dark_llm_revenue: float = 0.0
    currency: str = "USD"

    @property
    def total_attributed_revenue(self) -> float:
        """Track 1 + Track 2, the POV's total attributed value."""
        return (
            self.known_organic_revenue + self.known_llm_revenue
            + self.dark_organic_revenue + self.dark_llm_revenue
        )

    def multiplier_for(self, surface: str) -> float:
        """Dark-traffic gross-up factor for an opportunity on a given surface.

        Only GEO draws on the LLM track. AEO work - featured snippets, People
        Also Ask, AI Overviews - happens on the Google SERP and earns organic
        sessions, so its dark traffic is zero-click suppression, which the SEO
        track already models. Applying the LLM referral multiplier to it would
        value an organic click as though it were an assistant referral.
        """
        return self.geo.multiplier if str(surface).upper() == "GEO" else self.seo.multiplier

    def uncertainty_for(self, surface: str) -> float:
        """Estimator dispersion for the track backing this surface."""
        return self.geo.uncertainty if str(surface).upper() == "GEO" else self.seo.uncertainty

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "seo": self.seo.to_dict(),
            "geo": self.geo.to_dict(),
            "revenue": {
                "known_organic": round(self.known_organic_revenue, 2),
                "known_llm": round(self.known_llm_revenue, 2),
                "dark_organic": round(self.dark_organic_revenue, 2),
                "dark_llm": round(self.dark_llm_revenue, 2),
                "total_attributed": round(self.total_attributed_revenue, 2),
            },
        }


# --------------------------------------------------------------------------
# Channel aggregation
# --------------------------------------------------------------------------


@dataclass
class ChannelSeries:
    """Monthly channel sessions, the shared input for the lift estimators."""

    months: list[str] = field(default_factory=list)
    organic: dict[str, float] = field(default_factory=dict)
    direct: dict[str, float] = field(default_factory=dict)
    llm: dict[str, float] = field(default_factory=dict)
    email_social: dict[str, float] = field(default_factory=dict)
    organic_revenue: float = 0.0
    llm_revenue: float = 0.0
    total_conversions: float = 0.0
    total_sessions: float = 0.0
    organic_conversions: float = 0.0
    llm_conversions: float = 0.0
    #: Months covered, used to annualize partial-period inputs.
    month_count: int = 0

    @property
    def annualization(self) -> float:
        """Factor converting the observed window to an annual run rate."""
        return 12.0 / self.month_count if self.month_count else 1.0

    @property
    def observed_conversion_rate(self) -> float:
        """Site-wide sessions-to-conversion rate as analytics actually measured it.

        This is the rate to use when converting a count of conversions back into
        sessions. The funnel model's rate runs all the way to closed-won revenue,
        but an analytics "conversion" is usually a lead or other key event -
        dividing one by the other mixes units and inflates the result by orders
        of magnitude.
        """
        if self.total_sessions <= 0:
            return 0.0
        return self.total_conversions / self.total_sessions


def build_channel_series(dataset: Dataset) -> ChannelSeries:
    """Aggregate channel records into monthly series by channel family."""
    series = ChannelSeries()
    buckets: dict[str, dict[str, float]] = {
        "organic": defaultdict(float),
        "direct": defaultdict(float),
        "llm": defaultdict(float),
        "email_social": defaultdict(float),
    }
    months: set[str] = set()

    for record in dataset.channels:
        date = record.period_start or record.period_end
        month = date.strftime("%Y-%m") if date else "unknown"
        months.add(month)
        channel = (record.channel or "").lower()

        if record.is_llm_referral or channel == "llm_referral":
            buckets["llm"][month] += record.sessions
            series.llm_revenue += record.revenue
            series.llm_conversions += record.conversions
        elif channel == "organic_search":
            buckets["organic"][month] += record.sessions
            series.organic_revenue += record.revenue
            series.organic_conversions += record.conversions
        elif channel == "direct":
            buckets["direct"][month] += record.sessions
        elif channel in ("email", "organic_social", "paid_social", "referral"):
            buckets["email_social"][month] += record.sessions
        series.total_conversions += record.conversions
        series.total_sessions += record.sessions

    series.months = sorted(month for month in months if month != "unknown")
    series.month_count = len(series.months) or 1
    series.organic = dict(buckets["organic"])
    series.direct = dict(buckets["direct"])
    series.llm = dict(buckets["llm"])
    series.email_social = dict(buckets["email_social"])
    return series


# --------------------------------------------------------------------------
# SEO estimators
# --------------------------------------------------------------------------


def estimate_zero_click(
    dataset: Dataset, ctr_model: CTRModel, settings: dict[str, float]
) -> Estimate | None:
    """Size dark organic from the gap between expected and observed CTR.

    For every non-branded keyword, compare the clicks an unobstructed SERP would
    have delivered at the observed position against the clicks actually
    received. The shortfall is demand that saw the brand and did not click -
    zero-click visibility. Only a fraction converts into later demand, set by
    ``zero_click_assist_rate``.
    """
    keywords = [
        record for record in dataset.keyword_index().values()
        if record.impressions > 0 and record.position is not None and not record.branded
    ]
    if not keywords:
        return None

    suppressed = 0.0
    impressions = 0.0
    with_features = 0
    for record in keywords:
        suppressed += ctr_model.suppressed_clicks(
            impressions=record.impressions,
            position=record.position,
            observed_clicks=record.clicks,
            branded=False,
            serp_features=record.serp_features,
        )
        impressions += record.impressions
        if record.serp_features:
            with_features += 1

    assist_rate = settings["zero_click_assist_rate"]
    periods_per_year = settings["keyword_periods_per_year"]
    return Estimate(
        method="zero_click_ctr_gap",
        track="seo",
        dark_sessions=suppressed * assist_rate * periods_per_year,
        confidence=METHOD_CONFIDENCE["zero_click_ctr_gap"],
        note=(
            f"{suppressed:,.0f} suppressed clicks per period across {len(keywords):,} "
            f"non-branded keywords ({impressions:,.0f} impressions); {assist_rate:.0%} assumed "
            f"to generate later demand, annualized over {periods_per_year:g} periods."
        ),
        inputs={
            "keywords": len(keywords),
            "impressions": round(impressions),
            "suppressed_clicks_per_period": round(suppressed),
            "assist_rate": assist_rate,
            "periods_per_year": periods_per_year,
            "keywords_with_serp_features": with_features,
        },
    )


def estimate_branded_lift(
    series: ChannelSeries, settings: dict[str, float]
) -> Estimate | None:
    """Size dark organic from co-movement of non-branded visibility and direct traffic.

    Regresses monthly direct sessions on monthly non-branded organic sessions
    after removing email and social sessions, which are the main confound - a
    newsletter send drives direct traffic that has nothing to do with search.
    The attributable share is scaled by r-squared, so a weak relationship
    produces a small estimate rather than a confident one.
    """
    months = [month for month in series.months if month in series.organic and month in series.direct]
    if len(months) < settings["min_periods_for_lift"]:
        return None

    organic = [series.organic.get(month, 0.0) for month in months]
    direct_adjusted = [
        max(0.0, series.direct.get(month, 0.0) - series.email_social.get(month, 0.0))
        for month in months
    ]

    correlation = stats.pearson(organic, direct_adjusted)
    fit = stats.linear_fit(organic, direct_adjusted)
    if correlation is None or fit is None or correlation <= 0:
        return None

    slope, _ = fit
    if slope <= 0:
        return None

    r_squared = correlation ** 2
    mean_organic = sum(organic) / len(organic)
    mean_direct = sum(direct_adjusted) / len(direct_adjusted)

    # Monthly direct sessions explained by non-branded organic volume.
    explained_monthly = slope * mean_organic * r_squared
    cap = mean_direct * settings["max_branded_direct_share"]
    explained_monthly = min(explained_monthly, cap)

    # More periods means a more trustworthy fit.
    sample_factor = clamp(len(months) / 12.0, 0.4, 1.0)
    return Estimate(
        method="branded_direct_lift",
        track="seo",
        dark_sessions=explained_monthly * 12.0,
        confidence=METHOD_CONFIDENCE["branded_direct_lift"] * r_squared * sample_factor,
        note=(
            f"r={correlation:.2f} (r2={r_squared:.2f}) between non-branded organic and "
            f"email/social-adjusted direct sessions over {len(months)} months; "
            f"{explained_monthly:,.0f} direct sessions/month attributed to organic discovery."
        ),
        inputs={
            "months": len(months),
            "correlation": round(correlation, 4),
            "r_squared": round(r_squared, 4),
            "slope": round(slope, 4),
            "mean_direct_sessions": round(mean_direct),
            "capped_at_share": settings["max_branded_direct_share"],
        },
    )


def estimate_benchmark(
    known_sessions: float, track: str, settings: dict[str, float]
) -> Estimate | None:
    """Ground the estimate in published third-party baselines.

    The weakest method and weighted as such, but it is the sanity check that
    keeps a first-party model from drifting far from what the industry observes.
    """
    if known_sessions <= 0:
        return None
    if track == "seo":
        multiplier = settings["benchmark_dark_organic_multiplier"]
        note = f"Third-party benchmark: dark organic at {multiplier:.0%} of known organic sessions."
    else:
        multiplier = settings["benchmark_llm_multiplier"]
        note = (
            f"Third-party benchmark: total LLM influence at {multiplier:.1f}x observed "
            f"LLM referral sessions."
        )
    return Estimate(
        method="third_party_benchmark",
        track=track,
        dark_sessions=known_sessions * multiplier,
        confidence=METHOD_CONFIDENCE["third_party_benchmark"],
        note=note,
        inputs={"known_sessions": round(known_sessions), "multiplier": multiplier},
    )


def estimate_survey_seo(
    dataset: Dataset, series: ChannelSeries, settings: dict[str, float]
) -> Estimate | None:
    """Calibrate dark organic against self-reported discovery.

    When customers credit search more often than analytics credits organic, the
    difference is organic influence that lost its referrer. The ratio between
    the two is applied to known organic sessions.
    """
    surveys = [item for item in dataset.surveys if item.share_search_engine is not None]
    if not surveys or series.total_conversions <= 0:
        return None

    total_respondents = sum(item.respondents for item in surveys) or 1
    reported_share = stats.weighted_mean(
        [(item.share_search_engine or 0.0, float(item.respondents or 1)) for item in surveys]
    )
    observed_share = series.organic_conversions / series.total_conversions
    if observed_share <= 0 or reported_share <= observed_share:
        return None

    known_sessions = sum(series.organic.values()) * series.annualization
    uplift = (reported_share / observed_share) - 1.0
    confidence = METHOD_CONFIDENCE["survey_calibration"] * clamp(
        total_respondents / settings["survey_confidence_n"], 0.3, 1.0
    )
    return Estimate(
        method="survey_calibration",
        track="seo",
        dark_sessions=known_sessions * uplift,
        confidence=confidence,
        note=(
            f"{reported_share:.0%} of {total_respondents:,} respondents credited search "
            f"vs {observed_share:.0%} of conversions attributed to organic; "
            f"implies {uplift:.0%} unassigned organic influence."
        ),
        inputs={
            "respondents": total_respondents,
            "reported_share": round(reported_share, 4),
            "observed_share": round(observed_share, 4),
            "uplift": round(uplift, 4),
        },
    )


# --------------------------------------------------------------------------
# AEO / GEO estimators
# --------------------------------------------------------------------------


def estimate_citation_share(
    dataset: Dataset, settings: dict[str, float]
) -> Estimate | None:
    """Size LLM-influenced demand from the citation panel.

    Weights each cited answer by prominence - being named first is worth more
    than being listed fifth - and converts prompt volume into visits using
    ``citation_visit_rate``. This is the estimator that improves fastest as the
    panel grows, which is why the POV treats citations as the leading indicator.
    """
    if not dataset.citations:
        return None

    by_prompt: dict[str, list] = defaultdict(list)
    for record in dataset.citations:
        by_prompt[record.prompt.strip().lower()].append(record)

    weighted_volume = 0.0
    prompts_with_volume = 0
    total_observations = 0
    cited_observations = 0

    for records in by_prompt.values():
        volumes = [item.monthly_prompt_volume for item in records if item.monthly_prompt_volume]
        volume = max(volumes) if volumes else None
        total_observations += len(records)
        cited_observations += sum(1 for item in records if item.brand_cited)
        if not volume:
            continue
        prompts_with_volume += 1
        # Average prominence across engines is the brand's share of this answer.
        prominence = sum(item.prominence for item in records) / len(records)
        weighted_volume += volume * prominence

    if prompts_with_volume == 0 or weighted_volume <= 0:
        return None

    visit_rate = settings["citation_visit_rate"]
    citation_rate = cited_observations / total_observations if total_observations else 0.0
    return Estimate(
        method="citation_share",
        track="geo",
        dark_sessions=weighted_volume * visit_rate * 12.0,
        confidence=METHOD_CONFIDENCE["citation_share"],
        note=(
            f"Prominence-weighted exposure of {weighted_volume:,.0f} monthly prompts across "
            f"{prompts_with_volume:,} sized prompts (brand cited in {citation_rate:.0%} of "
            f"{total_observations:,} observations); {visit_rate:.0%} assumed to visit."
        ),
        inputs={
            "prompts_sized": prompts_with_volume,
            "prompts_total": len(by_prompt),
            "observations": total_observations,
            "citation_rate": round(citation_rate, 4),
            "weighted_monthly_volume": round(weighted_volume),
            "visit_rate": visit_rate,
        },
    )


def estimate_crawler_retrieval(
    dataset: Dataset, settings: dict[str, float]
) -> Estimate | None:
    """Size LLM influence from AI crawler retrieval volume in server logs.

    Retrieval is a precondition for citation, so crawl volume bounds how much
    generative exposure is even possible. Directional by design and weighted
    lowest of the GEO methods.
    """
    ai_hits = sum(record.hits for record in dataset.bot_hits if record.is_ai_bot)
    if ai_hits <= 0:
        return None
    pages_crawled = len({record.url for record in dataset.bot_hits if record.is_ai_bot})
    engines = sorted({record.bot for record in dataset.bot_hits if record.is_ai_bot})
    ratio = settings["crawler_session_ratio"]
    return Estimate(
        method="crawler_retrieval",
        track="geo",
        dark_sessions=ai_hits * ratio,
        confidence=METHOD_CONFIDENCE["crawler_retrieval"],
        note=(
            f"{ai_hits:,} AI crawler retrievals across {pages_crawled:,} URLs "
            f"({', '.join(engines)}); {ratio:.1%} assumed to yield an influenced session."
        ),
        inputs={
            "ai_crawler_hits": ai_hits,
            "pages_retrieved": pages_crawled,
            "engines": engines,
            "session_ratio": ratio,
        },
    )


def estimate_survey_ai(
    dataset: Dataset,
    series: ChannelSeries,
    revenue_model: RevenueModel,
    settings: dict[str, float],
) -> Estimate | None:
    """Calibrate the LLM dark pool against self-reported AI influence.

    Converts the share of customers crediting an AI assistant into implied
    sessions, then subtracts the LLM referrals analytics already captured so the
    estimate covers only the dark remainder.
    """
    surveys = [item for item in dataset.surveys if item.share_ai_assistant is not None]
    if not surveys or series.total_conversions <= 0:
        return None

    total_respondents = sum(item.respondents for item in surveys) or 1
    ai_share = stats.weighted_mean(
        [(item.share_ai_assistant or 0.0, float(item.respondents or 1)) for item in surveys]
    )
    if ai_share <= 0:
        return None

    annualized_conversions = series.total_conversions * series.annualization
    ai_influenced_conversions = annualized_conversions * ai_share

    # Convert conversions back to sessions at the rate analytics observed, not
    # the funnel model's session-to-closed-won rate: the two count different
    # things and mixing them inflates the estimate by orders of magnitude.
    conversion_rate = series.observed_conversion_rate or revenue_model.base_conversion_rate
    if conversion_rate <= 0:
        return None

    implied_sessions = ai_influenced_conversions / conversion_rate
    known_llm_sessions = sum(series.llm.values()) * series.annualization

    # An AI-influenced session is still a session: the estimate cannot exceed
    # total measured traffic.
    total_sessions = series.total_sessions * series.annualization
    if total_sessions > 0:
        implied_sessions = min(implied_sessions, total_sessions)

    dark_sessions = max(0.0, implied_sessions - known_llm_sessions)

    confidence = METHOD_CONFIDENCE["survey_calibration"] * clamp(
        total_respondents / settings["survey_confidence_n"], 0.3, 1.0
    )
    return Estimate(
        method="survey_calibration",
        track="geo",
        dark_sessions=dark_sessions,
        confidence=confidence,
        note=(
            f"{ai_share:.0%} of {total_respondents:,} respondents said an AI assistant "
            f"informed their decision, implying {implied_sessions:,.0f} influenced sessions "
            f"at the observed {conversion_rate:.2%} conversion rate, vs "
            f"{known_llm_sessions:,.0f} observed LLM referrals."
        ),
        inputs={
            "respondents": total_respondents,
            "ai_share": round(ai_share, 4),
            "observed_conversion_rate": round(conversion_rate, 5),
            "implied_sessions": round(implied_sessions),
            "known_llm_sessions": round(known_llm_sessions),
        },
    )


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def _record_skip(track: TrackEstimate, method: str, reason: str) -> None:
    track.skipped.append({"method": method, "reason": reason})


def model_dark_traffic(
    dataset: Dataset,
    ctr_model: CTRModel,
    revenue_model: RevenueModel,
    settings: dict[str, Any] | None = None,
) -> DarkTrafficResult:
    """Run every available estimator and blend them into a two-track result."""
    resolved: dict[str, float] = dict(DEFAULTS)
    resolved.update({key: float(value) for key, value in (settings or {}).items()
                     if key in DEFAULTS})

    series = build_channel_series(dataset)
    annualization = series.annualization
    known_organic_sessions = sum(series.organic.values()) * annualization
    known_llm_sessions = sum(series.llm.values()) * annualization

    seo = TrackEstimate(track="seo", known_sessions=known_organic_sessions)
    geo = TrackEstimate(track="geo", known_sessions=known_llm_sessions)

    # --- SEO Track 2 ---
    zero_click = estimate_zero_click(dataset, ctr_model, resolved)
    if zero_click:
        seo.estimates.append(zero_click)
    else:
        _record_skip(seo, "zero_click_ctr_gap",
                     "no non-branded keywords with impressions and position (needs Search Console)")

    lift = estimate_branded_lift(series, resolved)
    if lift:
        seo.estimates.append(lift)
    else:
        _record_skip(seo, "branded_direct_lift",
                     f"needs >= {int(resolved['min_periods_for_lift'])} months of organic and "
                     f"direct channel data with a positive relationship")

    benchmark_seo = estimate_benchmark(known_organic_sessions, "seo", resolved)
    if benchmark_seo:
        seo.estimates.append(benchmark_seo)
    else:
        _record_skip(seo, "third_party_benchmark", "no known organic sessions to scale from")

    survey_seo = estimate_survey_seo(dataset, series, resolved)
    if survey_seo:
        seo.estimates.append(survey_seo)
    else:
        _record_skip(seo, "survey_calibration",
                     "no survey data reporting a search-discovery share above observed attribution")

    # --- GEO Track 2 ---
    citation = estimate_citation_share(dataset, resolved)
    if citation:
        geo.estimates.append(citation)
    else:
        _record_skip(geo, "citation_share",
                     "no citation panel records carrying monthly prompt volume")

    crawler = estimate_crawler_retrieval(dataset, resolved)
    if crawler:
        geo.estimates.append(crawler)
    else:
        _record_skip(geo, "crawler_retrieval", "no AI crawler hits in server logs")

    benchmark_geo = estimate_benchmark(known_llm_sessions, "geo", resolved)
    if benchmark_geo:
        geo.estimates.append(benchmark_geo)
    else:
        _record_skip(geo, "third_party_benchmark",
                     "no observed LLM referral sessions to scale from")

    survey_geo = estimate_survey_ai(dataset, series, revenue_model, resolved)
    if survey_geo:
        geo.estimates.append(survey_geo)
    else:
        _record_skip(geo, "survey_calibration", "no survey data reporting an AI-assistant share")

    # --- Revenue conversion ---
    # B2B analytics usually carries no revenue at all (the money lands in the
    # CRM), so fall back to the funnel model rather than reporting zero.
    organic_sessions_window = sum(series.organic.values())
    llm_sessions_window = sum(series.llm.values())

    organic_rps = (
        series.organic_revenue / organic_sessions_window
        if organic_sessions_window > 0 and series.organic_revenue > 0
        else revenue_model.base_revenue_per_session
    )
    llm_rps = (
        series.llm_revenue / llm_sessions_window
        if llm_sessions_window > 0 and series.llm_revenue > 0
        else revenue_model.base_revenue_per_session
    )

    known_organic_revenue = (
        series.organic_revenue * annualization
        if series.organic_revenue > 0
        else known_organic_sessions * organic_rps
    )
    known_llm_revenue = (
        series.llm_revenue * annualization
        if series.llm_revenue > 0
        else known_llm_sessions * llm_rps
    )

    return DarkTrafficResult(
        seo=seo,
        geo=geo,
        known_organic_revenue=known_organic_revenue,
        known_llm_revenue=known_llm_revenue,
        dark_organic_revenue=seo.dark_sessions * organic_rps,
        dark_llm_revenue=geo.dark_sessions * llm_rps,
        currency=revenue_model.currency,
    )
