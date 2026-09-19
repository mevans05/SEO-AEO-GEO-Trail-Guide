"""LLM citation panel connector.

This is the AEO/GEO leading indicator the POV describes: recurring, structured
queries run across the major engines that record how often, how prominently and
how favorably the brand is cited for priority prompts.

The export shape is deliberately tool-agnostic (one row per prompt x engine x
run) so an in-house harness, a vendor panel, or a spreadsheet an analyst
maintains by hand all load through the same connector.
"""

from __future__ import annotations

from ..core import coerce
from ..core.ai_engines import normalize_engine
from ..core.schemas import CitationRecord, Dataset
from .base import Connector, register


@register
class LLMPanelConnector(Connector):
    """Normalizes prompt/citation panel observations."""

    name = "llm_panel"
    aliases = ("citations", "llm_citations", "aeo_panel", "geo_panel", "share_of_model")
    description = "LLM prompt/citation panel export (prompt x engine x run observations)."
    produces = ("citations",)

    def load(self) -> Dataset:
        dataset = Dataset()
        brand_names = [
            name.lower()
            for name in (self.spec.options.get("brand_names") or self.config.brand_terms)
        ]
        for file_path, row in self.rows():
            prompt = coerce.to_str(coerce.first_present(row, ("prompt", "query", "question")))
            if not prompt:
                continue

            cited_flag = coerce.to_bool(
                coerce.first_present(row, ("brand_cited", "brand cited", "cited", "mentioned"))
            )
            cited_urls = coerce.to_list(
                coerce.first_present(row, ("cited_urls", "cited urls", "citations", "sources")),
                separator=self.spec.options.get("list_separator", ","),
            )
            competitors = coerce.to_list(
                coerce.first_present(
                    row, ("competitors_cited", "competitors cited", "competitors", "other_brands")
                ),
                separator=self.spec.options.get("list_separator", ","),
            )
            if cited_flag is None:
                # Fall back to inferring the citation from the cited URLs/brands.
                haystack = " ".join(cited_urls).lower()
                cited_flag = any(name in haystack for name in brand_names if name)

            dataset.citations.append(
                CitationRecord(
                    source=self.source_name,
                    source_file=str(file_path),
                    prompt=prompt,
                    prompt_cluster=coerce.to_str(
                        coerce.first_present(row, ("cluster", "prompt_cluster", "topic", "theme"))
                    ),
                    engine=normalize_engine(
                        coerce.to_str(coerce.first_present(row, ("engine", "model", "platform", "llm")))
                    ),
                    observed_at=coerce.to_date(
                        coerce.first_present(row, ("date", "observed_at", "run_date", "timestamp"))
                    ),
                    brand_cited=bool(cited_flag),
                    brand_position=coerce.to_int(
                        coerce.first_present(
                            row, ("brand_position", "position", "rank", "mention_position")
                        )
                    ),
                    sentiment=_normalize_sentiment(
                        coerce.first_present(row, ("sentiment", "tone", "sentiment_score"))
                    ),
                    cited_urls=cited_urls,
                    competitors_cited=competitors,
                    monthly_prompt_volume=coerce.to_int(
                        coerce.first_present(
                            row, ("monthly_prompt_volume", "volume", "search_volume", "est_volume")
                        )
                    ),
                    buying_stage=coerce.to_str(
                        coerce.first_present(row, ("buying_stage", "stage", "funnel_stage", "intent"))
                    ),
                    answer_has_citations=bool(
                        coerce.to_bool(
                            coerce.first_present(row, ("answer_has_citations", "has_citations")), True
                        )
                    ),
                )
            )
        return dataset


_SENTIMENT_WORDS = {
    "positive": 1.0, "favorable": 1.0, "very positive": 1.0,
    "neutral": 0.0, "mixed": 0.0,
    "negative": -1.0, "unfavorable": -1.0, "very negative": -1.0,
}


def _normalize_sentiment(raw: object) -> float | None:
    """Accept either a -1..1 score or a word label, returning a -1..1 score."""
    if coerce.is_null(raw):
        return None
    text = str(raw).strip().lower()
    if text in _SENTIMENT_WORDS:
        return _SENTIMENT_WORDS[text]
    value = coerce.to_float(raw)
    if value is None:
        return None
    # A 0-100 or 1-5 scale is rescaled onto -1..1.
    if value > 1.0:
        return coerce.clamp((value / 50.0) - 1.0 if value > 5 else (value / 2.5) - 1.0, -1.0, 1.0)
    return coerce.clamp(value, -1.0, 1.0)
