"""HubSpot (or equivalent CRM) connector.

Turns sessions into pipeline. Without a CRM feed the engine values organic
traffic with configured assumptions; with one, it can use the client's actual
stage-conversion rates and deal sizes, which moves those opportunities from
modeled to derived confidence.
"""

from __future__ import annotations

from ..core import coerce
from ..core.schemas import Dataset, FunnelStage
from .base import Connector, IntakeColumn, IntakeSheet, register

SEGMENT_COLUMNS = ("segment", "source", "original source", "latest source",
                   "source / medium", "lifecycle stage", "channel")
DATE_COLUMNS = ("date", "month", "period", "create date", "close date")


@register
class HubSpotConnector(Connector):
    """Normalizes a HubSpot funnel/source export into canonical funnel stages."""

    name = "hubspot"
    aliases = ("crm", "salesforce", "pipedrive", "funnel")
    description = "CRM funnel export (sessions -> leads -> MQL -> SQL -> closed won)."
    produces = ("funnel",)

    intake = (
        IntakeSheet(
            key="funnel",
            title="CRM funnel",
            source_type="hubspot",
            priority="recommended",
            export_from=(
                "HubSpot/Salesforce sources report, one row per source per month, "
                "covering sessions through closed won."
            ),
            unlocks=(
                "Replaces configured funnel assumptions with observed stage rates and "
                "deal values, and reports every substitution it makes."
            ),
            notes=(
                "Organic Search is the row that matters most. Rates are only adopted "
                "when volume supports them, so a sparse export cannot wreck the model."
            ),
            columns=(
                IntakeColumn("Original source", "Channel / source name.",
                             "Organic Search", True),
                IntakeColumn("Date", "Month the row covers.", "2026-08-01", True),
                IntakeColumn("Sessions", "Sessions from the source.", "41200"),
                IntakeColumn("Contacts", "Leads created.", "910", True),
                IntakeColumn("MQLs", "Marketing qualified leads.", "410"),
                IntakeColumn("SQLs", "Sales qualified leads.", "165"),
                IntakeColumn("Deals", "Opportunities created.", "120"),
                IntakeColumn("Closed Won", "Deals won.", "36", True),
                IntakeColumn("Pipeline value", "Open pipeline value.", "2400000"),
                IntakeColumn("Closed won value", "Revenue from won deals.", "864000"),
                IntakeColumn("Avg deal size", "Average contract value.", "24000"),
                IntakeColumn("Days to close", "Average sales cycle in days.", "75"),
            ),
        ),
    )


    def load(self) -> Dataset:
        dataset = Dataset()
        for file_path, row in self.rows():
            segment = coerce.to_str(coerce.first_present(row, SEGMENT_COLUMNS), "all") or "all"
            date = coerce.to_date(coerce.first_present(row, DATE_COLUMNS))
            dataset.funnel.append(
                FunnelStage(
                    source=self.source_name,
                    source_file=str(file_path),
                    segment=segment,
                    period_start=date,
                    period_end=date,
                    sessions=coerce.to_int(coerce.first_present(row, ("sessions", "visits")), 0) or 0,
                    leads=coerce.to_float(
                        coerce.first_present(row, ("leads", "contacts", "new contacts")), 0.0
                    ) or 0.0,
                    mqls=coerce.to_float(
                        coerce.first_present(row, ("mqls", "marketing qualified leads", "mql")), 0.0
                    ) or 0.0,
                    sqls=coerce.to_float(
                        coerce.first_present(row, ("sqls", "sales qualified leads", "sql")), 0.0
                    ) or 0.0,
                    opportunities=coerce.to_float(
                        coerce.first_present(row, ("opportunities", "deals", "deals created")), 0.0
                    ) or 0.0,
                    closed_won=coerce.to_float(
                        coerce.first_present(row, ("closed won", "deals won", "customers", "wins")), 0.0
                    ) or 0.0,
                    pipeline_value=coerce.to_float(
                        coerce.first_present(row, ("pipeline value", "pipeline", "deal amount", "amount")), 0.0
                    ) or 0.0,
                    closed_won_value=coerce.to_float(
                        coerce.first_present(
                            row, ("closed won value", "revenue", "closed won amount", "won amount")
                        ), 0.0
                    ) or 0.0,
                    avg_deal_size=coerce.to_float(
                        coerce.first_present(row, ("avg deal size", "average deal size", "acv"))
                    ),
                    sales_cycle_days=coerce.to_float(
                        coerce.first_present(row, ("sales cycle days", "days to close", "avg days to close"))
                    ),
                )
            )
        return dataset
