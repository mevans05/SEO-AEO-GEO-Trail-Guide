"""Scoring, overlap deduplication and capacity-constrained scheduling."""

from __future__ import annotations

import unittest

from helpers import base_config                                   # noqa: F401
from trailguide.core.opportunity import EffortEstimate, Opportunity, ValueProjection
from trailguide.core.schemas import Confidence, Surface
from trailguide.prioritize import build_portfolio, score_opportunities
from trailguide.prioritize.overlap import deduplicate_overlap


def make(title, revenue, days, *, lag=1.0, ramp=3.0, confidence=Confidence.OBSERVED,
         surface=Surface.SEO, entities=None, tags=(), discipline="seo", sessions=0.0,
         pool_override=None):
    return Opportunity(
        title=title, opportunity_type="test", surface=surface,
        projection=ValueProjection(
            incremental_sessions=sessions, known_revenue=revenue, gross_margin=0.8,
            lag_months=lag, ramp_months=ramp, horizon_months=12,
        ),
        effort=EffortEstimate(days_by_discipline={discipline: days},
                              cost_per_day={discipline: 1000.0}),
        confidence=confidence, entities=list(entities or []), tags=list(tags),
        demand_pool_override=pool_override,
    )


class TestValueProjection(unittest.TestCase):
    def test_lag_delays_all_value(self):
        projection = ValueProjection(known_revenue=120000, lag_months=3, ramp_months=1,
                                     horizon_months=12)
        self.assertEqual(projection.monthly_revenue[0], 0.0)
        self.assertEqual(projection.monthly_revenue[2], 0.0)
        self.assertGreater(projection.monthly_revenue[3], 0.0)

    def test_horizon_revenue_is_below_run_rate_when_ramping(self):
        projection = ValueProjection(known_revenue=120000, lag_months=2, ramp_months=4,
                                     horizon_months=12)
        self.assertLess(projection.horizon_revenue, projection.annual_run_rate)

    def test_ramp_reaches_full_run_rate(self):
        projection = ValueProjection(known_revenue=120000, lag_months=0, ramp_months=1,
                                     horizon_months=12)
        self.assertAlmostEqual(projection.horizon_revenue, 120000, delta=1)


class TestScoring(unittest.TestCase):
    def test_efficiency_beats_raw_size(self):
        """A small fast win can outrank a large slow one."""
        big_slow = make("big slow", 900000, 120, lag=6, ramp=6)
        small_fast = make("small fast", 300000, 6)
        ranked = score_opportunities([big_slow, small_fast])
        self.assertEqual(ranked[0].title, "small fast")

    def test_confidence_breaks_ties(self):
        observed = make("observed", 200000, 10, confidence=Confidence.OBSERVED)
        modeled = make("modeled", 200000, 10, confidence=Confidence.MODELED)
        ranked = score_opportunities([observed, modeled])
        self.assertEqual(ranked[0].title, "observed")

    def test_ranks_are_assigned_in_order(self):
        ranked = score_opportunities([make(f"o{i}", 100000 * i, 10) for i in range(1, 5)])
        self.assertEqual([item.rank for item in ranked], [1, 2, 3, 4])
        scores = [item.score for item in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_scoring_preserves_analyzer_set_components(self):
        """Enabling work carries its own ordering signal into scoring."""
        item = make("enabling", 0, 5, tags=("enabling",))
        item.score_components["revenue_at_stake"] = 12345.0
        score_opportunities([item])
        self.assertEqual(item.score_components["revenue_at_stake"], 12345.0)


class TestOverlap(unittest.TestCase):
    def test_shared_entities_split_value(self):
        a = make("a", 100000, 5, entities=["kw1", "kw2"])
        b = make("b", 100000, 5, entities=["kw1"])
        deduplicate_overlap([a, b])
        self.assertAlmostEqual(a.projection.known_revenue, 75000)   # (1/2 + 1/1) / 2
        self.assertAlmostEqual(b.projection.known_revenue, 50000)

    def test_sessions_are_scaled_with_revenue(self):
        a = make("a", 100000, 5, entities=["kw1"], sessions=1000)
        b = make("b", 100000, 5, entities=["kw1"], sessions=1000)
        deduplicate_overlap([a, b])
        self.assertAlmostEqual(a.projection.incremental_sessions, 500)

    def test_different_pools_do_not_contend(self):
        """Search clicks and assistant answers are different pools of demand."""
        seo = make("seo", 100000, 5, surface=Surface.SEO, entities=["topic"])
        geo = make("geo", 100000, 5, surface=Surface.GEO, entities=["topic"])
        deduplicate_overlap([seo, geo])
        self.assertAlmostEqual(seo.projection.known_revenue, 100000)
        self.assertAlmostEqual(geo.projection.known_revenue, 100000)

    def test_conversion_work_is_exempt(self):
        """Converting existing traffic better claims no additional demand."""
        ranking = make("ranking", 100000, 5, surface=Surface.SEO, entities=["/a"])
        cro = make("cro", 100000, 5, surface=Surface.CONVERSION, entities=["/a"])
        deduplicate_overlap([ranking, cro])
        self.assertAlmostEqual(ranking.projection.known_revenue, 100000)
        self.assertAlmostEqual(cro.projection.known_revenue, 100000)

    def test_summary_reports_what_was_removed(self):
        a = make("a", 100000, 5, entities=["kw1"])
        b = make("b", 100000, 5, entities=["kw1"])
        summary = deduplicate_overlap([a, b])
        self.assertEqual(summary["opportunities_adjusted"], 2)
        self.assertEqual(summary["contested_entities"], 1)
        self.assertAlmostEqual(summary["value_removed"], 100000)


class TestPortfolio(unittest.TestCase):
    def test_capacity_constrains_selection(self):
        items = score_opportunities([make(f"o{i}", 100000, 30) for i in range(6)])
        portfolio = build_portfolio(items, {"seo": 20}, quarters=4)
        self.assertTrue(portfolio.deferred)
        self.assertLessEqual(
            sum(portfolio.capacity_used[1].values()), 20.0001
        )

    def test_later_starts_realize_less_in_horizon(self):
        items = score_opportunities([make(f"o{i}", 240000, 40) for i in range(4)])
        portfolio = build_portfolio(items, {"seo": 40}, quarters=4)
        by_quarter = {}
        for item in portfolio.scheduled:
            by_quarter.setdefault(item.start_quarter, []).append(item.realized_revenue)
        self.assertGreater(max(by_quarter[1]), max(by_quarter[max(by_quarter)]))

    def test_unconstrained_runs_without_capacity_config(self):
        items = score_opportunities([make("o", 100000, 10)])
        portfolio = build_portfolio(items, {})
        self.assertTrue(portfolio.unconstrained)
        self.assertEqual(len(portfolio.scheduled), 1)

    def test_unknown_discipline_is_not_scheduled(self):
        """Work needing a skill the team does not have cannot be planned."""
        items = score_opportunities([make("o", 100000, 5, discipline="legal")])
        portfolio = build_portfolio(items, {"seo": 20}, quarters=4)
        self.assertEqual(len(portfolio.deferred), 1)

    def test_rejected_item_releases_its_capacity(self):
        """A partially-allocated item that cannot finish must not strand capacity."""
        huge = make("huge", 100000, 500)
        small = make("small", 90000, 10)
        items = score_opportunities([huge, small])
        portfolio = build_portfolio(items, {"seo": 20}, quarters=4)
        titles = [item.opportunity.title for item in portfolio.scheduled]
        self.assertIn("small", titles)

    def test_enabling_work_is_funded_from_reserved_capacity(self):
        enabling = make("instrumentation", 0, 4, tags=("enabling",))
        revenue_work = [make(f"o{i}", 200000, 20) for i in range(5)]
        items = score_opportunities([enabling, *revenue_work])
        portfolio = build_portfolio(items, {"seo": 20}, quarters=4,
                                    reserved_for_enabling=0.25)
        titles = [item.opportunity.title for item in portfolio.scheduled]
        self.assertIn("instrumentation", titles)

    def test_gap_analysis_identifies_the_constraint(self):
        items = score_opportunities([make(f"o{i}", 200000, 30) for i in range(6)])
        portfolio = build_portfolio(items, {"seo": 20}, quarters=4,
                                    target_revenue=1_000_000)
        gap = portfolio.gap_analysis()
        self.assertIn(gap["status"], ("short", "closable_with_capacity"))
        self.assertGreater(gap["gap"], 0)

    def test_surplus_is_reported_when_target_is_beaten(self):
        items = score_opportunities([make("o", 500000, 5)])
        portfolio = build_portfolio(items, {"seo": 20}, quarters=4, target_revenue=1000)
        self.assertEqual(portfolio.gap_analysis()["status"], "on_target")

    def test_revenue_is_confidence_adjusted_consistently(self):
        """Immediate and delayed starts must apply the same risk adjustment."""
        item = make("o", 400000, 5, confidence=Confidence.MODELED)
        items = score_opportunities([item])
        portfolio = build_portfolio(items, {"seo": 20}, quarters=4)
        self.assertAlmostEqual(
            portfolio.scheduled[0].realized_revenue, item.expected_value, places=4
        )


if __name__ == "__main__":
    unittest.main()
