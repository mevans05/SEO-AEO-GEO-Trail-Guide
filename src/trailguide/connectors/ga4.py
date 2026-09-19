"""GA4 (or equivalent analytics) connector.

Emits page records from landing-page reports and channel records from
acquisition reports. The channel series is what the dark-traffic model reads:
it needs direct and branded-organic sessions over time to test whether they
move with non-branded and LLM visibility.

Any analytics platform exporting the same columns (Adobe, Matomo, Piwik,
Amplitude) works through this connector - the ``column_map`` option remaps
headers without touching code.
"""

from __future__ import annotations

from ..core import coerce
from ..core.ai_engines import is_llm_referral
from ..core.classify import is_branded, url_template
from ..core.schemas import ChannelMetric, Dataset, PageMetric
from .base import Connector, IntakeColumn, IntakeSheet, register

PAGE_COLUMNS = ("landing page", "landing page + query string", "page path", "page",
                "page path and screen class", "url", "address")
CHANNEL_COLUMNS = ("session default channel group", "default channel group", "channel",
                   "session source / medium", "session source/medium", "source / medium",
                   "source/medium", "first user source / medium")
SESSION_COLUMNS = ("sessions", "total sessions", "visits")
USER_COLUMNS = ("users", "total users", "active users")
CONVERSION_COLUMNS = ("conversions", "key events", "total conversions", "goal completions")
REVENUE_COLUMNS = ("total revenue", "revenue", "purchase revenue", "event value")
ENGAGEMENT_COLUMNS = ("engagement rate", "engaged sessions rate")
BOUNCE_COLUMNS = ("bounce rate",)
DATE_COLUMNS = ("date", "day", "week", "month", "year month", "nth month")


@register
class GA4Connector(Connector):
    """Normalizes GA4 landing-page and acquisition exports."""

    name = "ga4"
    aliases = ("analytics", "google_analytics", "adobe_analytics", "matomo")
    description = "GA4 or equivalent analytics export (landing pages and/or channels)."
    produces = ("pages", "channels")

    intake = (
        IntakeSheet(
            key="ga4_landing_pages",
            title="GA4 - landing pages",
            source_type="ga4",
            priority="core",
            export_from=(
                "GA4 > Reports > Engagement > Landing page. Add Sessions, Engagement rate, "
                "Key events and Total revenue, then Share > Download CSV."
            ),
            unlocks=(
                "Observed revenue per session, conversion-rate opportunities, and the "
                "page-level economics that keep projections grounded in real behaviour."
            ),
            notes="Same date window as the Search Console pages export, so the two line up.",
            columns=(
                IntakeColumn("Landing page", "Landing page path or URL.", "/shoes", True),
                IntakeColumn("Sessions", "Sessions to the page.", "3120", True),
                IntakeColumn("Engagement rate", "Engagement rate.", "0.62"),
                IntakeColumn("Key events", "Conversions / key events.", "48"),
                IntakeColumn("Total revenue", "Revenue attributed to the page.", "18400"),
            ),
        ),
        IntakeSheet(
            key="ga4_channels_monthly",
            title="GA4 - channels by month",
            source_type="ga4",
            priority="core",
            export_from=(
                "GA4 > Reports > Acquisition > Traffic acquisition, with Month as a "
                "secondary dimension. Export 12-16 months."
            ),
            unlocks=(
                "Track 1 baseline, the branded/direct lift estimator, and the observed "
                "conversion rate the survey estimator calibrates against."
            ),
            notes=(
                "Keep Direct, Organic Search, Email and Organic Social as separate rows - "
                "the lift estimator removes email and social before correlating."
            ),
            columns=(
                IntakeColumn("Session default channel group", "Channel name.",
                             "Organic Search", True),
                IntakeColumn("Date", "Month the row covers.", "2026-08-01", True),
                IntakeColumn("Sessions", "Sessions in the period.", "41200", True),
                IntakeColumn("Total users", "Users in the period.", "33800"),
                IntakeColumn("Key events", "Conversions / key events.", "610"),
                IntakeColumn("Total revenue", "Revenue for the channel.", "240000"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        brand_terms = self.config.brand_terms
        template_rules = self.spec.options.get("template_rules") or {}

        for file_path, row in self.rows():
            url = coerce.to_str(coerce.first_present(row, PAGE_COLUMNS))
            channel = coerce.to_str(coerce.first_present(row, CHANNEL_COLUMNS))
            sessions = coerce.to_int(coerce.first_present(row, SESSION_COLUMNS), 0) or 0
            users = coerce.to_int(coerce.first_present(row, USER_COLUMNS), 0) or 0
            conversions = coerce.to_float(coerce.first_present(row, CONVERSION_COLUMNS), 0.0) or 0.0
            revenue = coerce.to_float(coerce.first_present(row, REVENUE_COLUMNS), 0.0) or 0.0
            date = coerce.to_date(coerce.first_present(row, DATE_COLUMNS))

            if url and not _looks_like_channel(url):
                dataset.pages.append(
                    PageMetric(
                        source=self.source_name,
                        source_file=str(file_path),
                        url=url,
                        sessions=sessions,
                        entrances=sessions,
                        conversions=conversions,
                        revenue=revenue,
                        engagement_rate=coerce.to_float(
                            coerce.first_present(row, ENGAGEMENT_COLUMNS)
                        ),
                        bounce_rate=coerce.to_float(coerce.first_present(row, BOUNCE_COLUMNS)),
                        template=url_template(url, template_rules),
                        period_start=date,
                        period_end=date,
                    )
                )

            if channel:
                # "Organic Search" with a branded query set behaves very
                # differently from non-branded; the branded flag is only set
                # when the export actually carries a query or campaign hint.
                query_hint = coerce.to_str(
                    coerce.first_present(row, ("query", "keyword", "campaign", "session campaign"))
                )
                dataset.channels.append(
                    ChannelMetric(
                        source=self.source_name,
                        source_file=str(file_path),
                        channel=_normalize_channel(channel),
                        source_medium=channel,
                        sessions=sessions,
                        users=users,
                        conversions=conversions,
                        revenue=revenue,
                        branded=is_branded(query_hint, brand_terms) if query_hint else None,
                        is_llm_referral=is_llm_referral(channel),
                        period_start=date,
                        period_end=date,
                    )
                )
        return dataset


def _looks_like_channel(value: str) -> bool:
    """Guard against a channel label being read as a page path."""
    text = value.strip().lower()
    return text in {
        "organic search", "direct", "paid search", "referral", "organic social",
        "paid social", "email", "display", "affiliates", "unassigned", "(other)",
    }


def _normalize_channel(raw: str) -> str:
    """Collapse GA4's channel spellings into a stable canonical label."""
    text = str(raw).strip().lower()
    if is_llm_referral(text):
        return "llm_referral"
    if "organic search" in text or "google / organic" in text or "/ organic" in text:
        return "organic_search"
    if "direct" in text or "(none)" in text:
        return "direct"
    if "paid search" in text or "cpc" in text or "ppc" in text:
        return "paid_search"
    if "organic social" in text:
        return "organic_social"
    if "paid social" in text:
        return "paid_social"
    if "email" in text:
        return "email"
    if "referral" in text:
        return "referral"
    if "display" in text:
        return "display"
    return text.replace(" ", "_").replace("/", "_").strip("_") or "unassigned"
