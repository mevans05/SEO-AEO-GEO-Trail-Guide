"""Analyzer behaviour: what they find, what they refuse to claim."""

from __future__ import annotations

import unittest

from helpers import base_config, channel_dataset, citation, keyword, page   # noqa: F401
from trailguide.analysis import model_dark_traffic, registered_analyzers
from trailguide.analysis.base import AnalysisContext
from trailguide.analysis.search import _target_position
from trailguide.core.ctr import CTRModel
from trailguide.core.economics import RevenueModel
from trailguide.core.schemas import (
    BotHit, CrawlIssue, Dataset, KeywordMetric, Severity, Surface,
)


def build_context(dataset: Dataset, config=None) -> AnalysisContext:
    config = config or base_config()
    revenue = RevenueModel.from_config(config.section("economics"))
    ctr = CTRModel.from_config(config.section("ctr"))
    dark = model_dark_traffic(dataset, ctr, revenue, config.section("dark_traffic"))
    return AnalysisContext.build(dataset, config, revenue, ctr, dark)


def run_analyzer(name: str, dataset: Dataset, config=None):
    analyzer = next(cls() for cls in registered_analyzers() if cls.name == name)
    context = build_context(dataset, config)
    runnable, _ = analyzer.runnable(context)
    return analyzer.analyze(context) if runnable else []


class TestTargetPosition(unittest.TestCase):
    def test_never_promises_better_than_the_difficulty_band(self):
        """A hard keyword does not get a position-1 promise."""
        self.assertGreaterEqual(_target_position(12.0, 85), 7.0)

    def test_never_moves_more_than_one_pass_plausibly_achieves(self):
        self.assertEqual(_target_position(30.0, 20), 24.0)   # capped at 6 positions

    def test_a_keyword_already_in_its_band_yields_no_gain(self):
        self.assertEqual(_target_position(4.1, 62), 4.1)

    def test_target_is_never_worse_than_current(self):
        for current in (1.0, 2.5, 5.0, 9.9, 18.0):
            for difficulty in (10, 40, 65, 90):
                self.assertLessEqual(_target_position(current, difficulty), current)


class TestStrikingDistance(unittest.TestCase):
    def test_finds_a_realistic_gain(self):
        dataset = Dataset(keywords=[
            keyword("widget software", position=9.0, impressions=20000, clicks=300,
                    difficulty=35.0, page_url="/widgets"),
        ])
        found = run_analyzer("striking_distance", dataset)
        self.assertEqual(len(found), 1)
        self.assertGreater(found[0].projection.incremental_sessions, 0)
        self.assertEqual(found[0].surface, Surface.SEO)

    def test_ignores_keywords_below_the_impression_floor(self):
        dataset = Dataset(keywords=[
            keyword("tiny", position=9.0, impressions=5, clicks=0),
        ])
        self.assertEqual(run_analyzer("striking_distance", dataset), [])

    def test_ignores_branded_demand_by_default(self):
        dataset = Dataset(keywords=[
            keyword("testco widgets", position=9.0, impressions=20000, clicks=300,
                    branded=True),
        ])
        self.assertEqual(run_analyzer("striking_distance", dataset), [])

    def test_carries_evidence_back_to_the_source(self):
        dataset = Dataset(keywords=[
            keyword("widget software", position=9.0, impressions=20000, clicks=300,
                    difficulty=35.0, page_url="/widgets"),
        ])
        found = run_analyzer("striking_distance", dataset)
        self.assertTrue(found[0].evidence)
        self.assertEqual(found[0].evidence[0].source, "gsc")


class TestCannibalization(unittest.TestCase):
    def test_detects_two_urls_on_one_query(self):
        dataset = Dataset(keywords=[
            KeywordMetric(source="gsc", keyword="widget guide", page_url="/a",
                          position=6.0, impressions=10000, clicks=300),
            KeywordMetric(source="gsc", keyword="widget guide", page_url="/b",
                          position=14.0, impressions=4000, clicks=40),
        ])
        found = run_analyzer("cannibalization", dataset)
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0].entities), 2)

    def test_single_url_is_not_cannibalization(self):
        dataset = Dataset(keywords=[
            KeywordMetric(source="gsc", keyword="widget guide", page_url="/a",
                          position=6.0, impressions=10000, clicks=300),
        ])
        self.assertEqual(run_analyzer("cannibalization", dataset), [])


class TestTechnical(unittest.TestCase):
    def test_core_web_vitals_needs_traffic_to_be_worth_fixing(self):
        slow_but_empty = Dataset(pages=[
            page("/a", sessions=10, lcp_ms=5000.0, template="blog"),
        ])
        self.assertEqual(run_analyzer("core_web_vitals", slow_but_empty), [])

    def test_core_web_vitals_values_conversion_not_new_demand(self):
        dataset = Dataset(pages=[
            page(f"/p{i}", sessions=5000, conversions=50, lcp_ms=4500.0, inp_ms=400.0,
                 template="blog") for i in range(3)
        ])
        found = run_analyzer("core_web_vitals", dataset)
        self.assertTrue(found)
        # No demand pool: a faster page does not create search demand.
        self.assertIsNone(found[0].demand_pool)
        self.assertEqual(found[0].projection.dark_revenue, 0.0)

    def test_indexation_requires_demonstrated_demand(self):
        no_demand = Dataset(pages=[page("/a", indexable=False, impressions=0)])
        self.assertEqual(run_analyzer("indexation", no_demand), [])

    def test_indexation_flags_blocked_pages_with_demand(self):
        dataset = Dataset(pages=[
            page(f"/p{i}", indexable=False, impressions=20000, avg_position=8.0)
            for i in range(4)
        ])
        found = run_analyzer("indexation", dataset)
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0].entities), 4)

    def test_crawl_health_groups_by_issue_type(self):
        dataset = Dataset(
            pages=[page(f"/p{i}", sessions=2000) for i in range(4)],
            crawl_issues=[
                CrawlIssue(source="crawl", url=f"/p{i}", issue_type="broken_page",
                           severity=Severity.HIGH) for i in range(4)
            ],
        )
        found = run_analyzer("crawl_health", dataset)
        self.assertEqual(len(found), 1)
        self.assertIn("broken page", found[0].title)
        # Recovered clicks contend with the ranking analyzers.
        self.assertEqual(found[0].demand_pool, "search")


class TestGenerative(unittest.TestCase):
    def _geo_dataset(self) -> Dataset:
        dataset = channel_dataset(periods=12)
        for month in range(3):
            for engine in ("chatgpt", "perplexity", "gemini"):
                dataset.citations.append(
                    citation("best widget", engine, cited=(engine == "perplexity"),
                             monthly_prompt_volume=5000, prompt_cluster="widgets")
                )
        return dataset

    def test_citation_gap_found_where_share_is_low(self):
        found = run_analyzer("citation_gap", self._geo_dataset())
        self.assertTrue(found)
        self.assertEqual(found[0].surface, Surface.GEO)

    def test_geo_value_never_exceeds_the_modeled_pool(self):
        """The parts cannot claim more than the whole Track 2 model estimated."""
        dataset = self._geo_dataset()
        context = build_context(dataset)
        pool = context.dark.geo.known_sessions + context.dark.geo.dark_sessions
        found = run_analyzer("citation_gap", dataset)
        claimed = sum(item.projection.incremental_sessions for item in found)
        self.assertLessEqual(claimed, pool + 1)

    def test_geo_opportunities_are_not_grossed_up_again(self):
        found = run_analyzer("citation_gap", self._geo_dataset())
        self.assertEqual(found[0].projection.dark_revenue, 0.0)

    def test_retrieval_flags_a_site_with_no_ai_crawlers(self):
        dataset = channel_dataset(periods=12)
        dataset.pages.append(page("/a", impressions=50000))
        dataset.bot_hits.append(
            BotHit(source="logs", url="/a", bot="google", hits=500, is_ai_bot=False)
        )
        found = run_analyzer("retrieval_readiness", dataset)
        self.assertTrue(any("not blocked" in item.title for item in found))


class TestMeasurement(unittest.TestCase):
    def test_reports_gaps_without_inventing_revenue(self):
        found = run_analyzer("measurement", Dataset())
        self.assertTrue(found)
        for item in found:
            self.assertEqual(item.projection.annual_run_rate, 0.0)
            self.assertIn("enabling", item.tags)
            self.assertIn("revenue_at_stake", item.score_components)

    def test_no_gaps_reported_when_everything_is_instrumented(self):
        dataset = channel_dataset(periods=12)
        dataset.citations.append(citation("p", "chatgpt", True))
        dataset.bot_hits.append(BotHit(source="logs", url="/a", bot="chatgpt",
                                       hits=10, is_ai_bot=True))
        dataset.surveys.append(
            __import__("helpers").survey()
        )
        from trailguide.core.schemas import FunnelStage
        dataset.funnel.append(FunnelStage(source="crm", sessions=1000, leads=20))
        found = run_analyzer("measurement", dataset)
        self.assertEqual(found, [])


class TestAnalyzerContract(unittest.TestCase):
    def test_every_analyzer_declares_its_metadata(self):
        for cls in registered_analyzers():
            self.assertTrue(cls.name, cls.__name__)
            self.assertTrue(cls.description, cls.__name__)
            self.assertIsInstance(cls.surface, Surface)

    def test_analyzers_skip_cleanly_without_data(self):
        """An empty dataset must produce no output and no exception."""
        context = build_context(Dataset())
        for cls in registered_analyzers():
            analyzer = cls()
            runnable, reason = analyzer.runnable(context)
            if not runnable:
                self.assertTrue(reason)
                continue
            self.assertIsInstance(analyzer.analyze(context), list)

    def test_projections_are_finite_and_non_negative(self):
        dataset = Dataset(keywords=[
            keyword("widget software", position=9.0, impressions=20000, clicks=300,
                    difficulty=35.0, page_url="/widgets"),
        ])
        for item in run_analyzer("striking_distance", dataset):
            projection = item.projection
            self.assertGreaterEqual(projection.known_revenue, 0)
            self.assertGreaterEqual(projection.horizon_revenue, 0)
            self.assertLessEqual(projection.horizon_revenue, projection.annual_run_rate + 1)


if __name__ == "__main__":
    unittest.main()
