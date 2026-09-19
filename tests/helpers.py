"""Shared fixtures for the test suite."""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trailguide.config import Config                      # noqa: E402
from trailguide.core.schemas import (                     # noqa: E402
    ChannelMetric, CitationRecord, Dataset, KeywordMetric, PageMetric, SurveyResponse,
)

SAMPLE_CONFIG = ROOT / "config" / "example_client.yml"


def base_config(**overrides) -> Config:
    """A minimal but complete config for unit tests."""
    raw = {
        "client": {"name": "Test Co", "domain": "testco.com", "brand_terms": ["testco"]},
        "planning": {"horizon_months": 12, "quarters": 4, "currency": "USD",
                     "revenue_target": 500000},
        "economics": {"model": "ecommerce", "gross_margin": 0.8,
                      "ecommerce": {"conversion_rate": 0.02, "average_order_value": 100}},
        "capacity": {"per_quarter": {"seo": 20, "content": 20, "engineering": 10,
                                     "analytics": 5, "strategy": 5, "design": 5,
                                     "outreach": 5}},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(raw.get(key), dict):
            raw[key] = {**raw[key], **value}
        else:
            raw[key] = value
    return Config.from_dict(raw)


def months(count: int = 12) -> list[_dt.date]:
    """A run of month-start dates."""
    return [_dt.date(2025, 1, 1) + _dt.timedelta(days=31 * i) for i in range(count)]


def channel_dataset(
    organic: int = 10000, direct: int = 5000, llm: int = 200,
    email: int = 800, conversions_rate: float = 0.02, periods: int = 12,
) -> Dataset:
    """A dataset with a clean monthly channel series."""
    dataset = Dataset()
    for index, date in enumerate(months(periods)):
        # Direct tracks organic, which is the relationship the lift model looks for.
        organic_sessions = int(organic * (1 + 0.02 * index))
        direct_sessions = int(direct + 0.3 * organic_sessions)
        for channel, sessions, is_llm in (
            ("organic_search", organic_sessions, False),
            ("direct", direct_sessions, False),
            ("email", email, False),
            ("llm_referral", llm, True),
        ):
            dataset.channels.append(ChannelMetric(
                source="ga4", channel=channel, sessions=sessions,
                conversions=sessions * conversions_rate, revenue=0.0,
                is_llm_referral=is_llm, period_start=date, period_end=date,
            ))
    return dataset


def keyword(name: str, **kwargs) -> KeywordMetric:
    defaults = dict(source="gsc", keyword=name, impressions=10000, clicks=200,
                    position=8.0, search_volume=2000, difficulty=40.0)
    defaults.update(kwargs)
    return KeywordMetric(**defaults)


def page(url: str, **kwargs) -> PageMetric:
    defaults = dict(source="ga4", url=url)
    defaults.update(kwargs)
    return PageMetric(**defaults)


def citation(prompt: str, engine: str, cited: bool, **kwargs) -> CitationRecord:
    defaults = dict(source="llm_panel", prompt=prompt, engine=engine, brand_cited=cited,
                    monthly_prompt_volume=1000, prompt_cluster="cluster-a")
    defaults.update(kwargs)
    return CitationRecord(**defaults)


def survey(ai: float = 0.15, search: float = 0.50, n: int = 200) -> SurveyResponse:
    return SurveyResponse(source="survey", respondents=n, share_ai_assistant=ai,
                          share_search_engine=search)
