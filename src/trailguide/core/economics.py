"""Session-to-revenue translation.

Every opportunity in this system is eventually expressed in money, because the
prioritization target is a revenue number rather than a traffic number. This
module owns that translation and nothing else.

Two funnel shapes are supported:

``ecommerce``
    sessions -> conversions -> revenue, via conversion rate and average order value.

``b2b``
    sessions -> leads -> MQL -> SQL -> closed won, via stage rates and average
    contract value. B2B also carries a sales-cycle lag, so revenue from a
    ranking win lands months after the traffic does - which the roadmap phasing
    in :mod:`trailguide.prioritize.portfolio` depends on.

Segment multipliers let one model serve traffic of very different quality:
a transactional query and a top-of-funnel explainer should not be valued at the
same rate per session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .coerce import clamp
from .schemas import Confidence, Intent

#: Fallback value-per-session multipliers by query intent.
DEFAULT_INTENT_MULTIPLIERS: dict[str, float] = {
    Intent.TRANSACTIONAL.value: 2.40,
    Intent.COMMERCIAL.value: 1.50,
    Intent.NAVIGATIONAL.value: 1.80,
    Intent.INFORMATIONAL.value: 0.35,
    Intent.UNKNOWN.value: 1.00,
}


@dataclass
class SessionValue:
    """The modeled worth of a block of sessions."""

    sessions: float
    conversions: float
    revenue: float
    gross_profit: float
    confidence: Confidence
    basis: str

    @property
    def revenue_per_session(self) -> float:
        return self.revenue / self.sessions if self.sessions else 0.0


@dataclass
class RevenueModel:
    """Converts sessions into conversions, revenue and gross profit."""

    model: str = "ecommerce"
    currency: str = "USD"
    gross_margin: float = 0.80
    # Ecommerce parameters
    conversion_rate: float = 0.02
    average_order_value: float = 120.0
    # B2B parameters
    visit_to_lead: float = 0.02
    lead_to_mql: float = 0.45
    mql_to_sql: float = 0.40
    sql_to_win: float = 0.22
    average_contract_value: float = 20000.0
    sales_cycle_days: float = 60.0
    # Modifiers
    intent_multipliers: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_INTENT_MULTIPLIERS)
    )
    template_multipliers: dict[str, float] = field(default_factory=dict)
    prefer_observed: bool = True
    #: Cap on how far an observed page RPS may exceed the site model, guarding
    #: against a single freak-converting URL dominating the whole portfolio.
    observed_rps_cap_multiple: float = 5.0
    #: Human-readable record of what CRM calibration changed, surfaced in reports.
    calibration_notes: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: dict | None) -> "RevenueModel":
        """Build from the ``economics`` block of a client config."""
        config = dict(config or {})
        model = cls()
        model.model = str(config.get("model", model.model)).lower()
        model.currency = config.get("currency", model.currency)
        model.gross_margin = float(config.get("gross_margin", model.gross_margin))
        model.prefer_observed = bool(config.get("prefer_observed", model.prefer_observed))
        if "observed_rps_cap_multiple" in config:
            model.observed_rps_cap_multiple = float(config["observed_rps_cap_multiple"])

        ecom = config.get("ecommerce") or {}
        model.conversion_rate = float(ecom.get("conversion_rate", model.conversion_rate))
        model.average_order_value = float(
            ecom.get("average_order_value", model.average_order_value)
        )

        b2b = config.get("b2b") or {}
        model.visit_to_lead = float(b2b.get("visit_to_lead", model.visit_to_lead))
        model.lead_to_mql = float(b2b.get("lead_to_mql", model.lead_to_mql))
        model.mql_to_sql = float(b2b.get("mql_to_sql", model.mql_to_sql))
        model.sql_to_win = float(b2b.get("sql_to_win", model.sql_to_win))
        model.average_contract_value = float(
            b2b.get("average_contract_value", model.average_contract_value)
        )
        model.sales_cycle_days = float(b2b.get("sales_cycle_days", model.sales_cycle_days))

        model.intent_multipliers.update(
            {str(k).lower(): float(v) for k, v in (config.get("intent_multipliers") or {}).items()}
        )
        model.template_multipliers.update(
            {str(k).lower(): float(v) for k, v in (config.get("template_multipliers") or {}).items()}
        )
        return model

    # -- rates -----------------------------------------------------------

    @property
    def base_conversion_rate(self) -> float:
        """Session-to-closed-revenue conversion rate before segment modifiers."""
        if self.model == "b2b":
            return self.visit_to_lead * self.lead_to_mql * self.mql_to_sql * self.sql_to_win
        return self.conversion_rate

    @property
    def base_deal_value(self) -> float:
        """Revenue per converted session before segment modifiers."""
        return self.average_contract_value if self.model == "b2b" else self.average_order_value

    @property
    def base_revenue_per_session(self) -> float:
        """Blended modeled revenue per session across all traffic."""
        return self.base_conversion_rate * self.base_deal_value

    @property
    def revenue_lag_months(self) -> float:
        """Months between a session arriving and its revenue closing."""
        if self.model != "b2b":
            return 0.0
        return round(self.sales_cycle_days / 30.4, 2)

    def segment_multiplier(
        self, intent: Intent | str | None = None, template: str | None = None
    ) -> float:
        """Combined intent and template multiplier for a traffic segment."""
        multiplier = 1.0
        if intent is not None:
            key = intent.value if isinstance(intent, Intent) else str(intent).lower()
            multiplier *= self.intent_multipliers.get(key, 1.0)
        if template:
            multiplier *= self.template_multipliers.get(str(template).lower(), 1.0)
        return multiplier

    # -- valuation -------------------------------------------------------

    def value_of_sessions(
        self,
        sessions: float,
        intent: Intent | str | None = None,
        template: str | None = None,
        observed_revenue_per_session: float | None = None,
        observed_conversion_rate: float | None = None,
    ) -> SessionValue:
        """Value a block of sessions, preferring first-party observed rates.

        When the destination page has its own measured revenue per session, that
        beats a site-wide model - it already encodes the page's real intent and
        audience. It is capped at :attr:`observed_rps_cap_multiple` times the
        site model so one outlier URL cannot distort the portfolio.
        """
        sessions = max(0.0, float(sessions))
        if sessions == 0:
            return SessionValue(0.0, 0.0, 0.0, 0.0, Confidence.DERIVED, "no sessions")

        multiplier = self.segment_multiplier(intent, template)

        if self.prefer_observed and observed_revenue_per_session:
            cap = self.base_revenue_per_session * self.observed_rps_cap_multiple
            rps = min(float(observed_revenue_per_session), cap) if cap > 0 else float(
                observed_revenue_per_session
            )
            revenue = sessions * rps
            rate = observed_conversion_rate if observed_conversion_rate else self.base_conversion_rate
            return SessionValue(
                sessions=sessions,
                conversions=sessions * rate,
                revenue=revenue,
                gross_profit=revenue * self.gross_margin,
                confidence=Confidence.DERIVED,
                basis="observed page revenue per session",
            )

        rate = observed_conversion_rate or (self.base_conversion_rate * multiplier)
        rate = clamp(rate, 0.0, 0.95)
        conversions = sessions * rate
        revenue = conversions * self.base_deal_value
        return SessionValue(
            sessions=sessions,
            conversions=conversions,
            revenue=revenue,
            gross_profit=revenue * self.gross_margin,
            confidence=Confidence.MODELED if multiplier != 1.0 else Confidence.DERIVED,
            basis=f"{self.model} funnel model x{multiplier:g} segment multiplier",
        )

    def sessions_needed_for_revenue(
        self,
        revenue_target: float,
        intent: Intent | str | None = None,
        template: str | None = None,
    ) -> float:
        """Inverse of :meth:`value_of_sessions`: sessions required to hit a target.

        Used by gap analysis to express an unmet revenue target in the currency
        an SEO team actually works in.
        """
        per_session = self.base_revenue_per_session * self.segment_multiplier(intent, template)
        if per_session <= 0:
            return float("inf")
        return revenue_target / per_session

    def calibrate_from_funnel(self, funnel: list) -> list[str]:
        """Replace configured assumptions with the client's observed CRM rates.

        Configured economics are a starting guess; the CRM knows the truth. Each
        stage rate is adopted only when the underlying volume supports it and the
        result is plausible, so a sparse or partially-populated export cannot
        quietly destroy the model. Every substitution is recorded and reported.

        Returns the notes describing what changed.
        """
        notes: list[str] = []
        if not funnel:
            return notes

        totals = {
            "sessions": sum(row.sessions for row in funnel),
            "leads": sum(row.leads for row in funnel),
            "mqls": sum(row.mqls for row in funnel),
            "sqls": sum(row.sqls for row in funnel),
            "closed_won": sum(row.closed_won for row in funnel),
            "closed_won_value": sum(row.closed_won_value for row in funnel),
        }

        def adopt(attribute: str, numerator: str, denominator: str, label: str,
                  min_denominator: float) -> None:
            """Adopt an observed ratio when it is both supported and sane."""
            denom = totals[denominator]
            if denom < min_denominator:
                return
            rate = totals[numerator] / denom
            if not 0.0 < rate <= 1.0:
                return
            previous = getattr(self, attribute)
            # Ignore changes inside rounding noise; only material differences
            # are worth reporting or acting on.
            if previous > 0 and abs(rate - previous) / previous < 0.01:
                return
            setattr(self, attribute, rate)
            notes.append(f"{label}: {previous:.4f} -> {rate:.4f} (observed in CRM)")

        if self.model == "b2b":
            adopt("visit_to_lead", "leads", "sessions", "visit-to-lead", 500)
            adopt("lead_to_mql", "mqls", "leads", "lead-to-MQL", 20)
            adopt("mql_to_sql", "sqls", "mqls", "MQL-to-SQL", 10)
            adopt("sql_to_win", "closed_won", "sqls", "SQL-to-win", 5)

            if totals["closed_won"] >= 5 and totals["closed_won_value"] > 0:
                observed_acv = totals["closed_won_value"] / totals["closed_won"]
                previous = self.average_contract_value
                if observed_acv > 0 and abs(observed_acv - previous) / max(previous, 1) >= 0.01:
                    self.average_contract_value = observed_acv
                    notes.append(
                        f"average contract value: {previous:,.0f} -> {observed_acv:,.0f} "
                        f"(observed in CRM)"
                    )
        else:
            if totals["sessions"] >= 500 and totals["closed_won"] > 0:
                rate = totals["closed_won"] / totals["sessions"]
                if 0.0 < rate <= 1.0:
                    previous = self.conversion_rate
                    self.conversion_rate = rate
                    notes.append(f"conversion rate: {previous:.4f} -> {rate:.4f} (observed in CRM)")
            if totals["closed_won"] >= 5 and totals["closed_won_value"] > 0:
                observed_aov = totals["closed_won_value"] / totals["closed_won"]
                previous = self.average_order_value
                self.average_order_value = observed_aov
                notes.append(
                    f"average order value: {previous:,.0f} -> {observed_aov:,.0f} (observed in CRM)"
                )

        cycles = [row.sales_cycle_days for row in funnel if row.sales_cycle_days]
        if cycles:
            observed_cycle = sum(cycles) / len(cycles)
            if observed_cycle > 0 and abs(observed_cycle - self.sales_cycle_days) > 1:
                previous = self.sales_cycle_days
                self.sales_cycle_days = observed_cycle
                notes.append(
                    f"sales cycle: {previous:.0f} -> {observed_cycle:.0f} days (observed in CRM)"
                )

        self.calibration_notes.extend(notes)
        return notes

    def describe(self) -> dict[str, float | str]:
        """Flat summary of the active model, echoed into reports for auditability."""
        return {
            "model": self.model,
            "currency": self.currency,
            "base_conversion_rate": round(self.base_conversion_rate, 6),
            "base_deal_value": round(self.base_deal_value, 2),
            "base_revenue_per_session": round(self.base_revenue_per_session, 4),
            "gross_margin": self.gross_margin,
            "revenue_lag_months": self.revenue_lag_months,
            "calibrated_from_crm": bool(self.calibration_notes),
        }
