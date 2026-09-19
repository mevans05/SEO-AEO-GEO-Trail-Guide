"""Survey connector for calibrating the dark-traffic pool.

Both POVs call for on-site and post-purchase intercepts asking how a customer
discovered the brand. Self-reported attribution is noisy in absolute terms, but
the *ratio* between what customers say and what analytics observed is a stable
calibration input - and it is the only estimator that reaches demand which left
no digital trace at all.

Accepts an aggregated export (one row per period with channel shares) or raw
responses (one row per respondent), which are aggregated on load.
"""

from __future__ import annotations

from ..core import coerce
from ..core.schemas import Dataset, SurveyResponse
from .base import Connector, IntakeColumn, IntakeSheet, register

_AI_ANSWER_TOKENS = ("ai", "chatgpt", "assistant", "llm", "copilot", "perplexity", "gemini", "claude")
_SEARCH_ANSWER_TOKENS = ("search", "google", "bing", "seo", "organic")


@register
class SurveyConnector(Connector):
    """Normalizes discovery-attribution survey results."""

    name = "survey"
    aliases = ("surveys", "intercept", "attribution_survey", "post_purchase_survey")
    description = "Discovery-attribution survey export (aggregated shares or raw responses)."
    produces = ("surveys",)

    intake = (
        IntakeSheet(
            key="discovery_survey",
            title="Discovery attribution survey",
            source_type="survey",
            priority="recommended",
            export_from=(
                "A 'How did you first hear about us?' question on the post-conversion "
                "or post-purchase flow. Aggregate to one row per month."
            ),
            unlocks=(
                "The highest-confidence Track 2 estimators for both dark organic and "
                "dark LLM influence. This is the single most valuable row in the pack."
            ),
            notes=(
                "Shares may be 0-1 or 0-100; both are handled. Set 'Converted only' to "
                "TRUE when only customers were surveyed rather than all visitors."
            ),
            columns=(
                IntakeColumn("Period start", "Month the responses cover.", "2026-08-01", True),
                IntakeColumn("Respondents", "Number of responses.", "412", True),
                IntakeColumn("Share search engine", "Share crediting a search engine.",
                             "0.38", True),
                IntakeColumn("Share AI assistant", "Share crediting an AI assistant.",
                             "0.11", True),
                IntakeColumn("Share other", "Everything else.", "0.51"),
                IntakeColumn("Converted only", "TRUE if only customers were surveyed.",
                             "TRUE"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        raw_responses: dict[tuple, dict[str, float]] = {}

        for file_path, row in self.rows():
            period_start = coerce.to_date(
                coerce.first_present(row, ("period_start", "date", "month", "period"))
            )
            period_end = coerce.to_date(
                coerce.first_present(row, ("period_end", "date", "month", "period"))
            )
            share_ai = coerce.to_float(
                coerce.first_present(
                    row, ("share_ai_assistant", "ai_share", "share_ai", "pct_ai")
                )
            )
            answer = coerce.to_str(
                coerce.first_present(
                    row, ("answer", "response", "how did you hear", "discovery_channel", "channel")
                )
            )

            if share_ai is not None or answer is None:
                # Already-aggregated row.
                dataset.surveys.append(
                    SurveyResponse(
                        source=self.source_name,
                        source_file=str(file_path),
                        period_start=period_start,
                        period_end=period_end,
                        respondents=coerce.to_int(
                            coerce.first_present(row, ("respondents", "responses", "n", "count")), 0
                        ) or 0,
                        share_ai_assistant=_as_share(share_ai),
                        share_search_engine=_as_share(
                            coerce.to_float(
                                coerce.first_present(
                                    row, ("share_search_engine", "search_share", "pct_search")
                                )
                            )
                        ),
                        share_other=_as_share(
                            coerce.to_float(coerce.first_present(row, ("share_other", "other_share")))
                        ),
                        converted_only=bool(
                            coerce.to_bool(
                                coerce.first_present(row, ("converted_only", "customers_only")), True
                            )
                        ),
                    )
                )
                continue

            # Raw response row: bucket it and aggregate after the read.
            key = (period_start, period_end, str(file_path))
            bucket = raw_responses.setdefault(key, {"n": 0.0, "ai": 0.0, "search": 0.0, "other": 0.0})
            bucket["n"] += 1
            text = answer.lower()
            if any(token in text for token in _AI_ANSWER_TOKENS):
                bucket["ai"] += 1
            elif any(token in text for token in _SEARCH_ANSWER_TOKENS):
                bucket["search"] += 1
            else:
                bucket["other"] += 1

        for (period_start, period_end, file_path), bucket in raw_responses.items():
            total = bucket["n"] or 1.0
            dataset.surveys.append(
                SurveyResponse(
                    source=self.source_name,
                    source_file=file_path,
                    period_start=period_start,
                    period_end=period_end,
                    respondents=int(bucket["n"]),
                    share_ai_assistant=bucket["ai"] / total,
                    share_search_engine=bucket["search"] / total,
                    share_other=bucket["other"] / total,
                )
            )
        return dataset


def _as_share(value: float | None) -> float | None:
    """Normalize a share to ``0-1``, accepting percentages expressed as 0-100."""
    if value is None:
        return None
    return coerce.clamp(value / 100.0 if value > 1.0 else value, 0.0, 1.0)
