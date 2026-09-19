"""Semrush connectors: organic positions and keyword gap.

Semrush supplies the market context Search Console cannot: search volume for
demand the site has never ranked for, keyword difficulty, CPC as a commercial-
value proxy, SERP features, and competitor positions. Its metrics are
third-party estimates, so records are marked accordingly and analyzers weight
them below first-party data.
"""

from __future__ import annotations

from ..core import coerce
from ..core.classify import classify_intent, is_branded, normalize_serp_features
from ..core.schemas import Dataset, KeywordMetric
from .base import Connector, IntakeColumn, IntakeSheet, register

#: Columns in a gap export that are metrics rather than competitor domains.
_GAP_METRIC_COLUMNS = {
    "keyword", "search volume", "volume", "keyword difficulty", "difficulty", "kd",
    "cpc", "competition", "competitive density", "results", "number of results",
    "keyword intents", "intent", "serp features", "serp features by keyword",
    "timestamp", "trends", "position type",
}


@register
class SemrushPositionsConnector(Connector):
    """Normalizes the Semrush Organic Research -> Positions export."""

    name = "semrush"
    aliases = ("semrush_positions", "semrush_organic")
    description = "Semrush organic positions export (keyword, position, volume, KD, SERP features)."
    produces = ("keywords",)

    intake = (
        IntakeSheet(
            key="semrush_positions",
            title="Rank tracking - brand positions",
            source_type="semrush",
            priority="recommended",
            export_from=(
                "Semrush > Organic Research > Positions > Export (or the Ahrefs/"
                "similar equivalent) for your own domain."
            ),
            unlocks=(
                "Keyword difficulty banding, CPC-based value, and the SERP feature "
                "data behind answer-capture opportunities."
            ),
            notes=(
                "Difficulty matters: striking-distance targets are banded by KD so a "
                "hard term is not assumed to reach position 1."
            ),
            columns=(
                IntakeColumn("Keyword", "The keyword.", "trail running shoes", True),
                IntakeColumn("Position", "Current position.", "8", True),
                IntakeColumn("Previous position", "Position last period.", "11"),
                IntakeColumn("Search Volume", "Monthly search volume.", "9900", True),
                IntakeColumn("Keyword Difficulty", "KD, 0-100.", "41", True),
                IntakeColumn("CPC", "Cost per click in your currency.", "1.85"),
                IntakeColumn("URL", "Ranking URL.", "https://example.com/shoes", True),
                IntakeColumn("Traffic", "Estimated traffic from the keyword.", "120"),
                IntakeColumn("Keyword Intents", "Intent label.", "commercial"),
                IntakeColumn("SERP Features by Keyword", "Features present on the SERP.",
                             "featured snippet, people also ask"),
                IntakeColumn("Timestamp", "Date of the snapshot.", "2026-08-31"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        brand_terms = self.config.brand_terms
        for file_path, row in self.rows():
            keyword = coerce.to_str(coerce.first_present(row, ("keyword", "keywords")))
            if not keyword:
                continue
            dataset.keywords.append(
                KeywordMetric(
                    source=self.source_name,
                    source_file=str(file_path),
                    keyword=keyword,
                    page_url=coerce.to_str(coerce.first_present(row, ("url", "landing page", "page"))),
                    position=coerce.to_float(coerce.first_present(row, ("position", "pos"))),
                    search_volume=coerce.to_int(
                        coerce.first_present(row, ("search volume", "volume", "sv")), 0
                    ),
                    difficulty=coerce.to_float(
                        coerce.first_present(row, ("keyword difficulty", "difficulty", "kd"))
                    ),
                    cpc=coerce.to_float(coerce.first_present(row, ("cpc", "cpc (usd)"))),
                    impressions=coerce.to_int(coerce.first_present(row, ("impressions",)), 0) or 0,
                    clicks=coerce.to_int(coerce.first_present(row, ("traffic", "clicks")), 0) or 0,
                    branded=is_branded(keyword, brand_terms),
                    intent=classify_intent(
                        keyword,
                        coerce.to_str(coerce.first_present(row, ("keyword intents", "intent"))),
                    ),
                    serp_features=normalize_serp_features(
                        coerce.first_present(
                            row, ("serp features by keyword", "serp features", "serp_features")
                        )
                    ),
                    country=coerce.to_str(row.get("country"), self.spec.options.get("country")),
                    period_end=coerce.to_date(coerce.first_present(row, ("timestamp", "date"))),
                )
            )
        return dataset


@register
class SemrushGapConnector(Connector):
    """Normalizes the Semrush Keyword Gap export into competitor position maps.

    The client's own column is named via the ``client_column`` option (defaulting
    to the configured domain); every other domain-shaped column is treated as a
    competitor. That is what lets the content-gap analyzer see demand where
    competitors rank and the client does not.
    """

    name = "semrush_gap"
    aliases = ("keyword_gap", "semrush_keyword_gap")
    description = "Semrush keyword gap export (one position column per competing domain)."
    produces = ("keywords",)

    intake = (
        IntakeSheet(
            key="keyword_gap",
            title="Keyword gap vs competitors",
            source_type="semrush_gap",
            priority="recommended",
            export_from=(
                "Semrush > Keyword Gap. Put your domain first, then up to four "
                "competitors, and export. One position column per domain."
            ),
            unlocks="Content gap analysis - keywords competitors own and you do not.",
            notes=(
                "Name the competitor columns with their domains exactly as in the "
                "client.competitors config list, so they are matched automatically."
            ),
            columns=(
                IntakeColumn("Keyword", "The keyword.", "best trail shoes", True),
                IntakeColumn("Search Volume", "Monthly search volume.", "4400", True),
                IntakeColumn("Keyword Difficulty", "KD, 0-100.", "38", True),
                IntakeColumn("CPC", "Cost per click.", "1.40"),
                IntakeColumn("Keyword Intents", "Intent label.", "commercial"),
                IntakeColumn("SERP Features", "Features present on the SERP.",
                             "people also ask"),
                IntakeColumn("yourdomain.com", "Your position. Rename to your domain.", ""),
                IntakeColumn("competitor-a.com", "Competitor position. Rename per column.",
                             "4"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        brand_terms = self.config.brand_terms
        client_column = str(
            self.spec.options.get("client_column") or self.config.domain or ""
        ).strip().lower()
        configured_competitors = [
            str(name).strip().lower()
            for name in (self.spec.options.get("competitor_columns") or [])
        ]

        for file_path, row in self.rows():
            keyword = coerce.to_str(coerce.first_present(row, ("keyword", "keywords")))
            if not keyword:
                continue
            client_position: float | None = None
            competitor_positions: dict[str, float] = {}

            for column, value in row.items():
                column_key = str(column).strip().lower()
                if column_key in _GAP_METRIC_COLUMNS or not column_key:
                    continue
                is_domain_column = (
                    column_key in configured_competitors
                    or column_key == client_column
                    or "." in column_key
                )
                if not is_domain_column:
                    continue
                position = coerce.to_float(value)
                if position is None or position <= 0:
                    continue  # "not ranking" is encoded as blank, 0 or "-"
                if column_key == client_column:
                    client_position = position
                else:
                    competitor_positions[str(column).strip()] = position

            dataset.keywords.append(
                KeywordMetric(
                    source=self.source_name,
                    source_file=str(file_path),
                    keyword=keyword,
                    position=client_position,
                    search_volume=coerce.to_int(
                        coerce.first_present(row, ("search volume", "volume")), 0
                    ),
                    difficulty=coerce.to_float(
                        coerce.first_present(row, ("keyword difficulty", "difficulty", "kd"))
                    ),
                    cpc=coerce.to_float(coerce.first_present(row, ("cpc",))),
                    competitor_positions=competitor_positions,
                    branded=is_branded(keyword, brand_terms),
                    intent=classify_intent(
                        keyword,
                        coerce.to_str(coerce.first_present(row, ("keyword intents", "intent"))),
                    ),
                    serp_features=normalize_serp_features(
                        coerce.first_present(row, ("serp features", "serp features by keyword"))
                    ),
                )
            )
        return dataset
