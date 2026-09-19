"""Canonical schemas shared by every connector, analyzer and report.

Connectors translate vendor-specific exports into these types; analyzers only
ever read these types. That boundary is what lets a new data source be added
without touching analysis code (see ``docs/ADDING_A_SOURCE.md``).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Surface(str, Enum):
    """Where an opportunity is realized."""

    SEO = "SEO"           # classic ranked-and-clicked organic search
    AEO = "AEO"           # answer engines: snippets, AI Overviews, People Also Ask
    GEO = "GEO"           # generative engines: ChatGPT, Perplexity, Gemini, Copilot
    TECHNICAL = "TECHNICAL"
    CONVERSION = "CONVERSION"
    DISTRIBUTION = "DISTRIBUTION"


class Intent(str, Enum):
    """Query intent, which drives which conversion rate the economics model uses."""

    TRANSACTIONAL = "transactional"
    COMMERCIAL = "commercial"
    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    """Crawl/technical issue severity as normalized from crawler exports."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Confidence(str, Enum):
    """Evidence tier, mirroring the POV's Track 1 / Track 2 confidence split."""

    OBSERVED = "observed"        # directly measured (Track 1)
    DERIVED = "derived"          # arithmetic on observed data
    MODELED = "modeled"          # triangulated estimate (Track 2)
    ASSUMED = "assumed"          # config default, no supporting data

    @property
    def weight(self) -> float:
        """Numeric confidence weight used when blending and scoring."""
        return {
            Confidence.OBSERVED: 1.00,
            Confidence.DERIVED: 0.85,
            Confidence.MODELED: 0.55,
            Confidence.ASSUMED: 0.30,
        }[self]


def _as_dict(value: Any) -> Any:
    """Recursively convert dataclasses/enums/dates into JSON-ready primitives."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _as_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_dict(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {key: _as_dict(item) for key, item in asdict(value).items()}
    return value


@dataclass
class Record:
    """Base for canonical records, carrying provenance back to the source file."""

    source: str = "unknown"
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _as_dict(self)


@dataclass
class KeywordMetric(Record):
    """One keyword, on one page, for one period.

    Merged from Search Console (impressions, clicks, position - observed) and
    Semrush (volume, difficulty, competitor positions - third-party estimates).
    """

    keyword: str = ""
    page_url: str | None = None
    position: float | None = None
    impressions: int = 0
    clicks: int = 0
    search_volume: int | None = None
    difficulty: float | None = None          # 0-100 keyword difficulty
    cpc: float | None = None                 # paid CPC, a proxy for commercial value
    intent: Intent = Intent.UNKNOWN
    branded: bool = False
    serp_features: list[str] = field(default_factory=list)
    competitor_positions: dict[str, float] = field(default_factory=dict)
    country: str | None = None
    device: str | None = None
    period_start: _dt.date | None = None
    period_end: _dt.date | None = None

    @property
    def ctr(self) -> float | None:
        """Observed click-through rate, or None when there are no impressions."""
        if self.impressions <= 0:
            return None
        return self.clicks / self.impressions

    @property
    def best_competitor_position(self) -> float | None:
        """Strongest (lowest) competitor position seen for this keyword."""
        if not self.competitor_positions:
            return None
        return min(self.competitor_positions.values())


@dataclass
class PageMetric(Record):
    """One URL, blending analytics, search, CMS and performance signals.

    Fields are populated opportunistically: a page seen only by the crawler has
    technical fields and null analytics, and analyzers guard accordingly.
    """

    url: str = ""
    sessions: int = 0
    entrances: int = 0
    conversions: float = 0.0
    revenue: float = 0.0
    engagement_rate: float | None = None
    bounce_rate: float | None = None
    impressions: int = 0
    clicks: int = 0
    avg_position: float | None = None
    # Content / CMS
    title: str | None = None
    word_count: int | None = None
    published_at: _dt.date | None = None
    updated_at: _dt.date | None = None
    template: str | None = None           # e.g. "blog", "product", "docs"
    author: str | None = None
    # Technical
    status_code: int | None = None
    indexable: bool | None = None
    canonical_url: str | None = None
    schema_types: list[str] = field(default_factory=list)
    internal_inlinks: int | None = None
    # Core Web Vitals / Lighthouse
    lcp_ms: float | None = None
    inp_ms: float | None = None
    cls: float | None = None
    ttfb_ms: float | None = None
    performance_score: float | None = None   # 0-100
    seo_score: float | None = None
    accessibility_score: float | None = None
    device: str | None = None
    period_start: _dt.date | None = None
    period_end: _dt.date | None = None

    @property
    def revenue_per_session(self) -> float | None:
        """Observed revenue per session, when analytics supplied both."""
        if self.sessions <= 0:
            return None
        return self.revenue / self.sessions

    @property
    def conversion_rate(self) -> float | None:
        """Observed session-to-conversion rate for this page."""
        if self.sessions <= 0:
            return None
        return self.conversions / self.sessions


@dataclass
class ChannelMetric(Record):
    """Traffic and revenue for a channel/source-medium in one period.

    This is the series the dark-traffic model reads to separate branded search
    and direct sessions from non-branded organic.
    """

    channel: str = ""
    source_medium: str | None = None
    period_start: _dt.date | None = None
    period_end: _dt.date | None = None
    sessions: int = 0
    users: int = 0
    conversions: float = 0.0
    revenue: float = 0.0
    branded: bool | None = None
    is_llm_referral: bool = False


@dataclass
class FunnelStage(Record):
    """A CRM funnel snapshot for one segment/source in one period.

    Sourced from HubSpot (or equivalent) so B2B opportunities are valued on
    pipeline and closed-won rather than on raw sessions.
    """

    segment: str = "all"
    source: str | None = None
    period_start: _dt.date | None = None
    period_end: _dt.date | None = None
    sessions: int = 0
    leads: float = 0.0
    mqls: float = 0.0
    sqls: float = 0.0
    opportunities: float = 0.0
    closed_won: float = 0.0
    pipeline_value: float = 0.0
    closed_won_value: float = 0.0
    avg_deal_size: float | None = None
    sales_cycle_days: float | None = None


@dataclass
class CitationRecord(Record):
    """One observation from the LLM prompt/citation panel.

    This is the AEO/GEO leading indicator described in the POV: recurring,
    structured queries across major engines recording whether, how prominently
    and how favorably the brand is cited.
    """

    prompt: str = ""
    prompt_cluster: str | None = None
    engine: str = ""                       # chatgpt | perplexity | gemini | copilot
    observed_at: _dt.date | None = None
    brand_cited: bool = False
    brand_position: int | None = None      # 1 = first brand mentioned
    sentiment: float | None = None         # -1..1
    cited_urls: list[str] = field(default_factory=list)
    competitors_cited: list[str] = field(default_factory=list)
    monthly_prompt_volume: int | None = None
    buying_stage: str | None = None
    answer_has_citations: bool = True

    @property
    def prominence(self) -> float:
        """Prominence weight in ``[0, 1]``: cited first is worth more than cited fifth."""
        if not self.brand_cited:
            return 0.0
        if self.brand_position is None:
            return 0.5
        return max(0.15, 1.0 / float(self.brand_position))


@dataclass
class CrawlIssue(Record):
    """A technical finding for one URL, normalized from crawler exports."""

    url: str = ""
    issue_type: str = ""
    severity: Severity = Severity.MEDIUM
    detail: str | None = None
    status_code: int | None = None
    indexable: bool | None = None


@dataclass
class BotHit(Record):
    """Crawler activity for one URL and one bot in one period.

    Server-log evidence of which pages AI assistants and search engines actually
    retrieve - the retrieval-side check on AEO/GEO coverage.
    """

    url: str = ""
    bot: str = ""                          # googlebot | gptbot | perplexitybot | ...
    hits: int = 0
    period_start: _dt.date | None = None
    period_end: _dt.date | None = None
    is_ai_bot: bool = False


@dataclass
class SurveyResponse(Record):
    """Aggregated survey result used to calibrate the dark-traffic pool.

    One row per period: how many respondents, and what share credited each
    discovery channel. This is the POV's survey-based attribution input.
    """

    period_start: _dt.date | None = None
    period_end: _dt.date | None = None
    respondents: int = 0
    share_ai_assistant: float | None = None   # 0-1, "an AI assistant informed my decision"
    share_search_engine: float | None = None
    share_other: float | None = None
    converted_only: bool = True


@dataclass
class Evidence:
    """A single supporting datapoint attached to an opportunity.

    Every number surfaced in a report traces back through these records to the
    source system and file, which is what makes the output auditable by an
    analyst and defensible in a client conversation.
    """

    source: str
    metric: str
    value: Any
    confidence: Confidence = Confidence.OBSERVED
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _as_dict(self)


@dataclass
class Dataset:
    """The normalized bundle handed to every analyzer.

    Collections are always present (possibly empty) so analyzers can be written
    without defensive ``getattr`` checks; each one declares the inputs it
    genuinely requires via ``Analyzer.required_inputs``.
    """

    keywords: list[KeywordMetric] = field(default_factory=list)
    pages: list[PageMetric] = field(default_factory=list)
    channels: list[ChannelMetric] = field(default_factory=list)
    funnel: list[FunnelStage] = field(default_factory=list)
    citations: list[CitationRecord] = field(default_factory=list)
    crawl_issues: list[CrawlIssue] = field(default_factory=list)
    bot_hits: list[BotHit] = field(default_factory=list)
    surveys: list[SurveyResponse] = field(default_factory=list)
    extras: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    #: Collection attribute names, used for merging and coverage reporting.
    COLLECTIONS = (
        "keywords", "pages", "channels", "funnel",
        "citations", "crawl_issues", "bot_hits", "surveys",
    )

    def extend(self, other: "Dataset") -> "Dataset":
        """Merge another dataset into this one in place."""
        for name in self.COLLECTIONS:
            getattr(self, name).extend(getattr(other, name))
        for key, rows in other.extras.items():
            self.extras.setdefault(key, []).extend(rows)
        return self

    def coverage(self) -> dict[str, int]:
        """Record counts per collection, reported as input coverage."""
        counts = {name: len(getattr(self, name)) for name in self.COLLECTIONS}
        for key, rows in self.extras.items():
            counts[f"extras.{key}"] = len(rows)
        return counts

    def sources(self) -> set[str]:
        """Distinct source identifiers that contributed records."""
        found: set[str] = set()
        for name in self.COLLECTIONS:
            found.update(record.source for record in getattr(self, name))
        return found

    def page_index(self) -> dict[str, PageMetric]:
        """Merge page records by URL so one URL yields one consolidated view.

        Later records fill gaps left by earlier ones rather than overwriting
        them, so an analytics export and a crawl export compose into a single
        page rather than competing.
        """
        merged: dict[str, PageMetric] = {}
        for page in self.pages:
            if not page.url:
                continue
            existing = merged.get(page.url)
            if existing is None:
                merged[page.url] = PageMetric(**{**page.__dict__})
                continue
            for key, value in page.__dict__.items():
                if key in ("url", "source", "source_file"):
                    continue
                current = getattr(existing, key)
                if _is_empty(current) and not _is_empty(value):
                    setattr(existing, key, value)
                elif key in ("sessions", "entrances", "impressions", "clicks",
                             "conversions", "revenue") and value:
                    # Additive metrics accumulate across periods/devices.
                    setattr(existing, key, (current or 0) + value)
        return merged


    def keyword_index(self, key_country: bool = False) -> dict[str, KeywordMetric]:
        """Merge keyword records across sources into one view per keyword.

        Search Console contributes observed impressions, clicks and position;
        Semrush contributes volume, difficulty, CPC, SERP features and
        competitor positions. Position is taken from the first-party source
        whenever one is present, because an observed average position beats a
        third-party sample.
        """
        merged: dict[str, KeywordMetric] = {}
        observed_position: set[str] = set()
        for record in self.keywords:
            if not record.keyword:
                continue
            key = record.keyword.strip().lower()
            if key_country and record.country:
                key = f"{key}|{record.country.lower()}"
            existing = merged.get(key)
            has_first_party = record.impressions > 0
            if existing is None:
                merged[key] = KeywordMetric(**{**record.__dict__})
                if has_first_party and record.position is not None:
                    observed_position.add(key)
                continue

            existing.impressions += record.impressions
            existing.clicks += record.clicks

            if record.position is not None:
                if has_first_party and key not in observed_position:
                    existing.position = record.position
                    observed_position.add(key)
                elif existing.position is None:
                    existing.position = record.position

            for field_name in ("search_volume", "difficulty", "cpc", "country", "device",
                               "period_start", "period_end"):
                if _is_empty(getattr(existing, field_name)):
                    value = getattr(record, field_name)
                    if not _is_empty(value):
                        setattr(existing, field_name, value)

            if not existing.page_url and record.page_url:
                existing.page_url = record.page_url
            if not existing.serp_features and record.serp_features:
                existing.serp_features = list(record.serp_features)
            if record.competitor_positions:
                existing.competitor_positions.update(record.competitor_positions)
            if existing.intent.value == "unknown" and record.intent.value != "unknown":
                existing.intent = record.intent
            existing.branded = existing.branded or record.branded
        return merged


def _is_empty(value: Any) -> bool:
    """True when a field carries no information and may be filled from elsewhere."""
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
        return True
    return False
