"""Scoring, overlap deduplication and capacity-constrained scheduling."""

from __future__ import annotations

import unittest

from helpers import base_config                                   # noqa: F401
from trailguide.core.opportunity import EffortEstimate, Opportunity, ValueProjection
from trailguide.core.schemas import Confidence, Dataset, KeywordMetric, Surface
from trailguide.prioritize import build_portfolio, score_opportunities
from trailguide.prioritize.overlap import (
    DemandMap, build_demand_map, deduplicate_overlap,
)


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


class TestCrossLevelOverlap(unittest.TestCase):
    """A keyword-level and a page-level claim on the same page are the same clicks."""

    def demand_map(self, visibility=1.0, **pages):
        """Build a map directly: {page: {keyword: weight}}."""
        keyword_pages = {kw: page for page, kws in pages.items() for kw in kws}
        return DemandMap(
            keyword_pages=keyword_pages,
            page_keywords={page: dict(kws) for page, kws in pages.items()},
            page_visibility=visibility,
        )

    def test_page_and_keyword_claims_contend(self):
        """The case limitation 1 described: neither used to see the other."""
        page = make("decay", 100000, 5, entities=["/shoes"])
        keyword = make("striking", 100000, 5, entities=["trail shoes"])
        demand = self.demand_map(**{"/shoes": {"trail shoes": 1.0}})
        deduplicate_overlap([page, keyword], demand)
        self.assertAlmostEqual(page.projection.known_revenue, 50000)
        self.assertAlmostEqual(keyword.projection.known_revenue, 50000)

    def test_contention_is_proportional_to_the_keyword_share(self):
        """Contesting one query of many barely touches a page-level projection."""
        page = make("decay", 100000, 5, entities=["/shoes"])
        keyword = make("striking", 100000, 5, entities=["minor"])
        demand = self.demand_map(**{"/shoes": {"head": 90.0, "minor": 10.0}})
        deduplicate_overlap([page, keyword], demand)
        # 90% of the page's demand is uncontested; 10% is split in half.
        self.assertAlmostEqual(page.projection.known_revenue, 95000)
        self.assertAlmostEqual(keyword.projection.known_revenue, 50000)

    def test_unobserved_long_tail_is_not_contested(self):
        """Keywords nobody can see cannot be double-claimed by a keyword opportunity."""
        page = make("decay", 100000, 5, entities=["/shoes"])
        keyword = make("striking", 100000, 5, entities=["trail shoes"])
        demand = self.demand_map(visibility=0.5, **{"/shoes": {"trail shoes": 1.0}})
        deduplicate_overlap([page, keyword], demand)
        # Half the page's demand is visible and split; half is long tail it keeps.
        self.assertAlmostEqual(page.projection.known_revenue, 75000)
        self.assertAlmostEqual(keyword.projection.known_revenue, 50000)

    def test_page_versus_page_is_unchanged_by_the_expansion(self):
        """Two claims on one page still split evenly, however its demand resolves."""
        a = make("a", 100000, 5, entities=["/shoes"])
        b = make("b", 100000, 5, entities=["/shoes"])
        demand = self.demand_map(visibility=0.5, **{"/shoes": {"trail shoes": 1.0}})
        deduplicate_overlap([a, b], demand)
        self.assertAlmostEqual(a.projection.known_revenue, 50000)
        self.assertAlmostEqual(b.projection.known_revenue, 50000)

    def test_unmapped_entities_fall_back_to_exact_matching(self):
        """Prompts and robots.txt have no landing page and keep the old behaviour."""
        a = make("a", 100000, 5, entities=["robots.txt"])
        b = make("b", 100000, 5, entities=["robots.txt"])
        deduplicate_overlap([a, b], self.demand_map(**{"/shoes": {"trail shoes": 1.0}}))
        self.assertAlmostEqual(a.projection.known_revenue, 50000)

    def test_no_demand_map_reproduces_exact_entity_matching(self):
        """Without keyword-to-page data the result is the pre-existing behaviour."""
        page = make("decay", 100000, 5, entities=["/shoes"])
        keyword = make("striking", 100000, 5, entities=["trail shoes"])
        deduplicate_overlap([page, keyword])
        self.assertAlmostEqual(page.projection.known_revenue, 100000)
        self.assertAlmostEqual(keyword.projection.known_revenue, 100000)

    def test_build_demand_map_attributes_a_keyword_to_its_strongest_page(self):
        """A query splits across URLs; the one earning most impressions owns it."""
        dataset = Dataset(keywords=[
            KeywordMetric(source="gsc", keyword="trail shoes",
                          page_url="https://x.com/weak", impressions=100),
            KeywordMetric(source="gsc", keyword="trail shoes",
                          page_url="https://x.com/strong", impressions=900),
        ])
        demand = build_demand_map(dataset)
        self.assertEqual(demand.keyword_pages["trail shoes"], "https://x.com/strong")
        self.assertNotIn("https://x.com/weak", demand.page_keywords)

    def test_build_demand_map_ignores_keywords_with_no_page(self):
        dataset = Dataset(keywords=[
            KeywordMetric(source="semrush", keyword="orphan", impressions=500),
        ])
        self.assertFalse(build_demand_map(dataset))


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


class TestJiraTickets(unittest.TestCase):
    """Tickets a delivery team can pick up without rewriting them."""

    def ticket(self, **kwargs):
        from trailguide.report.jira import render_ticket
        item = make(kwargs.pop("title", "Fix the thing"), kwargs.pop("revenue", 120000),
                    kwargs.pop("days", 4), **kwargs)
        item.rank = kwargs.pop("rank", 1)
        return render_ticket(item, currency="USD", quarter="Q1")

    def test_priority_follows_portfolio_rank(self):
        from trailguide.report.jira import _priority
        self.assertEqual(_priority(1), "Highest")
        self.assertEqual(_priority(10), "High")
        self.assertEqual(_priority(20), "Medium")
        self.assertEqual(_priority(99), "Low")
        self.assertEqual(_priority(None), "Medium")

    def test_estimate_maps_onto_story_points(self):
        from trailguide.report.jira import _story_points
        self.assertEqual(_story_points(0.5), 1)
        self.assertEqual(_story_points(4), 3)
        self.assertEqual(_story_points(100), 34)

    def test_enabling_work_states_it_carries_no_revenue(self):
        """Attaching revenue to instrumentation would be dishonest, so it says so."""
        ticket = self.ticket(tags=("enabling",))
        self.assertIn("no projected revenue", ticket.value_statement)

    def test_acceptance_criteria_always_include_a_measurement(self):
        ticket = self.ticket()
        self.assertTrue(ticket.acceptance_criteria)
        self.assertTrue(
            any("measure" in c.lower() or "baseline" in c.lower()
                for c in ticket.acceptance_criteria)
        )

    def test_jira_markup_converts_to_markdown(self):
        from trailguide.report.jira import _jira_markup_to_markdown
        converted = _jira_markup_to_markdown(
            "h2. Heading\n\n# first\n# second\n\n* {{code}}\n* *bold* here"
        )
        self.assertIn("## Heading", converted)
        self.assertIn("1. first", converted)
        self.assertIn("2. second", converted)
        self.assertIn("- `code`", converted)
        self.assertIn("**bold**", converted)
        self.assertNotIn("h2.", converted)

    def test_bold_conversion_leaves_list_markers_alone(self):
        from trailguide.report.jira import _jira_markup_to_markdown
        self.assertEqual(_jira_markup_to_markdown("* plain item"), "- plain item")
