"""Generic connector: load any tabular export without writing code.

This is the "other data inputs as needed" path. Point it at a file, name the
canonical collection to fill, and map the columns. Anything that does not map
onto an existing schema lands in ``Dataset.extras`` under a chosen key, where
custom analyzers and the report's appendix can still reach it.
"""

from __future__ import annotations

from typing import Any

from ..core import coerce
from ..core.classify import classify_intent, is_branded, normalize_serp_features
from ..core.schemas import (
    BotHit, ChannelMetric, CitationRecord, CrawlIssue, Dataset,
    FunnelStage, KeywordMetric, PageMetric, Severity, SurveyResponse,
)
from ..errors import ConnectorError
from .base import Connector, register

#: Canonical collections a generic source may target.
_TARGETS = {
    "keywords": KeywordMetric,
    "pages": PageMetric,
    "channels": ChannelMetric,
    "funnel": FunnelStage,
    "citations": CitationRecord,
    "crawl_issues": CrawlIssue,
    "bot_hits": BotHit,
    "surveys": SurveyResponse,
}

#: Fields needing conversion beyond a plain string.
_FIELD_COERCERS: dict[str, Any] = {
    "position": coerce.to_float, "avg_position": coerce.to_float,
    "impressions": coerce.to_int, "clicks": coerce.to_int, "sessions": coerce.to_int,
    "entrances": coerce.to_int, "users": coerce.to_int, "hits": coerce.to_int,
    "search_volume": coerce.to_int, "word_count": coerce.to_int, "status_code": coerce.to_int,
    "internal_inlinks": coerce.to_int, "respondents": coerce.to_int,
    "brand_position": coerce.to_int, "monthly_prompt_volume": coerce.to_int,
    "conversions": coerce.to_float, "revenue": coerce.to_float, "cpc": coerce.to_float,
    "difficulty": coerce.to_float, "engagement_rate": coerce.to_float,
    "bounce_rate": coerce.to_float, "lcp_ms": coerce.to_float, "inp_ms": coerce.to_float,
    "cls": coerce.to_float, "ttfb_ms": coerce.to_float, "performance_score": coerce.to_float,
    "seo_score": coerce.to_float, "accessibility_score": coerce.to_float,
    "leads": coerce.to_float, "mqls": coerce.to_float, "sqls": coerce.to_float,
    "opportunities": coerce.to_float, "closed_won": coerce.to_float,
    "pipeline_value": coerce.to_float, "closed_won_value": coerce.to_float,
    "avg_deal_size": coerce.to_float, "sales_cycle_days": coerce.to_float,
    "sentiment": coerce.to_float, "share_ai_assistant": coerce.to_float,
    "share_search_engine": coerce.to_float, "share_other": coerce.to_float,
    "indexable": coerce.to_bool, "branded": coerce.to_bool, "brand_cited": coerce.to_bool,
    "is_ai_bot": coerce.to_bool, "is_llm_referral": coerce.to_bool,
    "converted_only": coerce.to_bool, "answer_has_citations": coerce.to_bool,
    "published_at": coerce.to_date, "updated_at": coerce.to_date,
    "period_start": coerce.to_date, "period_end": coerce.to_date, "observed_at": coerce.to_date,
    "schema_types": coerce.to_list, "cited_urls": coerce.to_list,
    "competitors_cited": coerce.to_list,
    "serp_features": normalize_serp_features,
}


@register
class GenericConnector(Connector):
    """Maps an arbitrary export onto a canonical collection or into ``extras``.

    Options:
        ``target``       canonical collection name, or omit to store in extras
        ``extras_key``   key under ``Dataset.extras`` (defaults to the source name)
        ``column_map``   ``{canonical_field: source_column}``
        ``constants``    fields applied to every row
    """

    name = "generic"
    aliases = ("custom", "csv", "table")
    description = "Any tabular export, mapped onto a canonical collection via column_map."
    produces = ("*",)

    def load(self) -> Dataset:
        dataset = Dataset()
        target = coerce.to_str(self.spec.options.get("target"))
        constants = dict(self.spec.options.get("constants") or {})
        brand_terms = self.config.brand_terms

        if target and target not in _TARGETS:
            raise ConnectorError(
                f"generic source '{self.spec.label}' has unknown target '{target}'. "
                f"Valid targets: {', '.join(sorted(_TARGETS))}"
            )

        extras_key = coerce.to_str(self.spec.options.get("extras_key")) or self.spec.label

        for file_path, row in self.rows():
            merged = {**row, **constants}
            if not target:
                dataset.extras.setdefault(extras_key, []).append(dict(merged))
                continue

            record_cls = _TARGETS[target]
            fields = {
                name: field.type
                for name, field in record_cls.__dataclass_fields__.items()  # type: ignore[attr-defined]
            }
            kwargs: dict[str, Any] = {"source": self.source_name, "source_file": str(file_path)}
            for field_name in fields:
                if field_name in ("source", "source_file"):
                    continue
                value = coerce.first_present(merged, (field_name, field_name.replace("_", " ")))
                if coerce.is_null(value):
                    continue
                converter = _FIELD_COERCERS.get(field_name)
                kwargs[field_name] = converter(value) if converter else coerce.to_str(value)

            record = record_cls(**{k: v for k, v in kwargs.items() if v is not None})

            # Derive the classifications downstream analyzers rely on.
            if isinstance(record, KeywordMetric):
                if "branded" not in kwargs:
                    record.branded = is_branded(record.keyword, brand_terms)
                if "intent" not in kwargs:
                    record.intent = classify_intent(
                        record.keyword, coerce.to_str(merged.get("intent"))
                    )
            if isinstance(record, CrawlIssue) and "severity" in kwargs:
                try:
                    record.severity = Severity(str(kwargs["severity"]).lower())
                except ValueError:
                    record.severity = Severity.MEDIUM

            getattr(dataset, target).append(record)
        return dataset
