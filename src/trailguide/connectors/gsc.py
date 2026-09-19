"""Google Search Console connector.

Search Console is the highest-confidence input in the system: impressions,
clicks and average position are directly observed. It anchors Track 1, and its
impression data is the denominator for the zero-click estimate that anchors
Track 2.

Handles the Performance report's query, page, and combined query+page exports,
plus the per-date export used for trend and dark-traffic modeling.
"""

from __future__ import annotations

from ..core import coerce
from ..core.classify import classify_intent, is_branded, normalize_serp_features
from ..core.schemas import Dataset, KeywordMetric, PageMetric
from .base import Connector, IntakeColumn, IntakeSheet, register

QUERY_COLUMNS = ("query", "queries", "search query", "top queries", "keyword")
PAGE_COLUMNS = ("page", "pages", "landing page", "url", "top pages", "address")
CLICK_COLUMNS = ("clicks", "url clicks", "total clicks")
IMPRESSION_COLUMNS = ("impressions", "total impressions")
POSITION_COLUMNS = ("position", "average position", "avg position", "avg. position")
DATE_COLUMNS = ("date", "day", "week", "month")


@register
class SearchConsoleConnector(Connector):
    """Normalizes Search Console Performance exports."""

    name = "gsc"
    aliases = ("search_console", "google_search_console", "searchconsole")
    description = "Google Search Console performance export (query / page / date)."
    produces = ("keywords", "pages")

    intake = (
        IntakeSheet(
            key="search_console_queries",
            title="Search Console - queries",
            source_type="gsc",
            priority="core",
            export_from=(
                "Search Console > Performance > Search results. Set the date range to the "
                "last full month, add the Query and Page dimensions, then Export > CSV."
            ),
            unlocks=(
                "Striking distance, cannibalization, answer capture, and the zero-click "
                "estimator that anchors Track 2."
            ),
            notes=(
                "Export one full month. If you change the window, set "
                "analysis.settings.dark_traffic.keyword_periods_per_year to match "
                "(12 for one month, 4 for a quarter)."
            ),
            columns=(
                IntakeColumn("Query", "The search query.", "trail running shoes", True),
                IntakeColumn("Page", "Landing page that ranked for the query.",
                             "https://example.com/shoes", True),
                IntakeColumn("Clicks", "Clicks in the period.", "128", True),
                IntakeColumn("Impressions", "Impressions in the period.", "4210", True),
                IntakeColumn("CTR", "Click-through rate. Optional; recomputed if absent.", "3.04%"),
                IntakeColumn("Position", "Average position.", "8.4", True),
            ),
        ),
        IntakeSheet(
            key="search_console_pages_monthly",
            title="Search Console - pages by month",
            source_type="gsc",
            priority="core",
            export_from=(
                "Search Console > Performance > Search results > Pages tab, with the Date "
                "dimension added. Export 12-16 months so decay and trend are visible."
            ),
            unlocks="Content decay, indexation value, and the branded/direct lift estimator.",
            columns=(
                IntakeColumn("Page", "Page URL.", "https://example.com/shoes", True),
                IntakeColumn("Date", "Month or day the row covers.", "2026-08-01", True),
                IntakeColumn("Clicks", "Clicks in the period.", "512", True),
                IntakeColumn("Impressions", "Impressions in the period.", "18400", True),
                IntakeColumn("Position", "Average position.", "6.1"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        brand_terms = self.config.brand_terms
        country = self.spec.options.get("country")
        device = self.spec.options.get("device")

        for file_path, row in self.rows():
            keyword = coerce.to_str(coerce.first_present(row, QUERY_COLUMNS))
            url = coerce.to_str(coerce.first_present(row, PAGE_COLUMNS))
            clicks = coerce.to_int(coerce.first_present(row, CLICK_COLUMNS), 0) or 0
            impressions = coerce.to_int(coerce.first_present(row, IMPRESSION_COLUMNS), 0) or 0
            position = coerce.to_float(coerce.first_present(row, POSITION_COLUMNS))
            date = coerce.to_date(coerce.first_present(row, DATE_COLUMNS))

            if keyword:
                dataset.keywords.append(
                    KeywordMetric(
                        source=self.source_name,
                        source_file=str(file_path),
                        keyword=keyword,
                        page_url=url,
                        position=position,
                        impressions=impressions,
                        clicks=clicks,
                        branded=is_branded(keyword, brand_terms),
                        intent=classify_intent(keyword, coerce.to_str(row.get("intent"))),
                        serp_features=normalize_serp_features(
                            coerce.first_present(row, ("serp features", "serp_features"))
                        ),
                        country=coerce.to_str(row.get("country"), country),
                        device=coerce.to_str(row.get("device"), device),
                        period_start=date,
                        period_end=date,
                    )
                )
            elif url:
                # A page-level export carries no query, so it lands as a page record.
                dataset.pages.append(
                    PageMetric(
                        source=self.source_name,
                        source_file=str(file_path),
                        url=url,
                        impressions=impressions,
                        clicks=clicks,
                        avg_position=position,
                        period_start=date,
                        period_end=date,
                    )
                )
        return dataset
