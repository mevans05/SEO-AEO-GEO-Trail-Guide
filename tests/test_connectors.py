"""Connector normalization and the generic escape hatch."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import base_config                                   # noqa: F401
from trailguide.config import SourceSpec
from trailguide.connectors import get_connector, registered_connectors
from trailguide.errors import ConnectorError, UnknownSourceError


class ConnectorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.config = base_config()
        self.config.base_dir = self.dir

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, content: str) -> str:
        (self.dir / name).write_text(content, encoding="utf-8")
        return name

    def load(self, source_type: str, path: str, **options):
        spec = SourceSpec(type=source_type, path=path, options=options)
        return get_connector(source_type)(spec, self.config).load()


class TestRegistry(unittest.TestCase):
    def test_aliases_resolve_to_the_same_connector(self):
        self.assertIs(get_connector("gsc"), get_connector("search_console"))
        self.assertIs(get_connector("webflow"), get_connector("cms"))

    def test_unknown_type_names_the_alternatives(self):
        with self.assertRaises(UnknownSourceError) as ctx:
            get_connector("not_a_real_tool")
        self.assertIn("generic", str(ctx.exception))

    def test_every_connector_declares_metadata(self):
        for cls in registered_connectors():
            self.assertTrue(cls.name, cls.__name__)
            self.assertTrue(cls.description, cls.__name__)


class TestSearchConsole(ConnectorTestCase):
    def test_query_export_becomes_keywords(self):
        path = self.write("gsc.csv",
            "Query,Page,Clicks,Impressions,CTR,Position\n"
            "testco widgets,https://x.com/a,120,4000,3.00%,4.2\n"
            "widget guide,https://x.com/b,80,9000,0.89%,11.4\n")
        dataset = self.load("gsc", path)
        self.assertEqual(len(dataset.keywords), 2)
        branded = {record.keyword: record.branded for record in dataset.keywords}
        self.assertTrue(branded["testco widgets"])
        self.assertFalse(branded["widget guide"])
        self.assertAlmostEqual(dataset.keywords[0].position, 4.2)

    def test_page_export_without_queries_becomes_pages(self):
        path = self.write("pages.csv",
            "Page,Clicks,Impressions,Position\nhttps://x.com/a,120,4000,4.2\n")
        dataset = self.load("gsc", path)
        self.assertEqual(len(dataset.pages), 1)
        self.assertEqual(dataset.pages[0].clicks, 120)


class TestSemrush(ConnectorTestCase):
    def test_serp_features_are_normalized(self):
        path = self.write("sr.csv",
            "Keyword,Position,Search Volume,Keyword Difficulty,CPC,URL,"
            "Keyword Intents,SERP Features by Keyword\n"
            "widget software,7,2400,55,12.50,https://x.com/a,Commercial,"
            '"AI Overview, People also ask"\n')
        dataset = self.load("semrush", path)
        record = dataset.keywords[0]
        self.assertEqual(record.serp_features, ["ai_overview", "people_also_ask"])
        self.assertEqual(record.search_volume, 2400)
        self.assertEqual(record.intent.value, "commercial")

    def test_gap_export_separates_client_from_competitors(self):
        path = self.write("gap.csv",
            "Keyword,Search Volume,Keyword Difficulty,testco.com,rival-a.com,rival-b.com\n"
            "widget guide,3000,40,,4,9\n"
            "widget pricing,1200,30,6,2,\n")
        dataset = self.load("semrush_gap", path, client_column="testco.com")
        by_keyword = {record.keyword: record for record in dataset.keywords}
        self.assertIsNone(by_keyword["widget guide"].position)
        self.assertEqual(by_keyword["widget guide"].competitor_positions,
                         {"rival-a.com": 4.0, "rival-b.com": 9.0})
        self.assertEqual(by_keyword["widget pricing"].position, 6.0)
        self.assertEqual(by_keyword["widget pricing"].best_competitor_position, 2.0)


class TestAnalyticsAndCRM(ConnectorTestCase):
    def test_llm_referrals_are_identified(self):
        path = self.write("ga4.csv",
            "Session default channel group,Date,Sessions,Key events,Total revenue\n"
            "Organic Search,2026-01-01,1000,20,0\n"
            "chatgpt.com / referral,2026-01-01,50,3,0\n")
        dataset = self.load("ga4", path)
        llm = [record for record in dataset.channels if record.is_llm_referral]
        self.assertEqual(len(llm), 1)
        self.assertEqual(llm[0].sessions, 50)

    def test_crm_funnel_normalizes(self):
        path = self.write("crm.csv",
            "Original source,Date,Sessions,Contacts,MQLs,SQLs,Closed Won,Closed won value\n"
            "Organic Search,2026-01-01,5000,110,50,20,5,120000\n")
        dataset = self.load("hubspot", path)
        stage = dataset.funnel[0]
        self.assertEqual(stage.sessions, 5000)
        self.assertEqual(stage.closed_won_value, 120000)


class TestTechnicalConnectors(ConnectorTestCase):
    def test_crawl_detects_issues(self):
        path = self.write("crawl.csv",
            "Address,Content Type,Status Code,Indexability,Indexability Status,Title 1,"
            "Meta Description 1,H1-1,Word Count,Crawl Depth,Unique Inlinks,Response Time\n"
            "https://x.com/a,text/html,404,Non-Indexable,Client Error,,,,0,3,4,0.2\n"
            "https://x.com/b,text/html,200,Indexable,,Title,Desc,H1,150,2,0,0.3\n")
        dataset = self.load("screaming_frog", path)
        kinds = {issue.issue_type for issue in dataset.crawl_issues}
        self.assertIn("broken_page", kinds)
        self.assertIn("thin_content", kinds)
        self.assertIn("orphan_page", kinds)

    def test_lighthouse_json_is_parsed(self):
        report = {
            "requestedUrl": "https://x.com/a",
            "finalUrl": "https://x.com/a",
            "categories": {"performance": {"score": 0.42}},
            "audits": {"largest-contentful-paint": {"numericValue": 4100.0},
                       "cumulative-layout-shift": {"numericValue": 0.21}},
        }
        (self.dir / "lh.json").write_text(json.dumps(report))
        dataset = self.load("pagespeed", "lh.json")
        page = dataset.pages[0]
        self.assertAlmostEqual(page.performance_score, 42.0)
        self.assertAlmostEqual(page.lcp_ms, 4100.0)

    def test_server_logs_classify_ai_crawlers(self):
        path = self.write("logs.csv",
            "URL,Bot,Hits,Date\n"
            "/a,GPTBot,40,2026-01-01\n"
            "/a,Googlebot,200,2026-01-01\n")
        dataset = self.load("server_logs", path)
        ai = [hit for hit in dataset.bot_hits if hit.is_ai_bot]
        self.assertEqual(len(ai), 1)
        self.assertEqual(ai[0].bot, "chatgpt")


class TestLLMPanelAndSurvey(ConnectorTestCase):
    def test_spaced_headers_resolve(self):
        """The panel export uses spaced headers; volume must still be read."""
        path = self.write("panel.csv",
            "Date,Prompt,Cluster,Engine,Brand cited,Brand position,Sentiment,"
            "Competitors cited,Monthly prompt volume\n"
            "2026-01-15,best widget,widgets,ChatGPT,yes,2,positive,\"rival-a, rival-b\",4800\n")
        dataset = self.load("llm_panel", path)
        record = dataset.citations[0]
        self.assertEqual(record.monthly_prompt_volume, 4800)
        self.assertEqual(record.brand_position, 2)
        self.assertEqual(record.engine, "chatgpt")
        self.assertEqual(record.competitors_cited, ["rival-a", "rival-b"])
        self.assertAlmostEqual(record.sentiment, 1.0)

    def test_raw_survey_responses_are_aggregated(self):
        path = self.write("survey.csv",
            "Period start,Answer\n"
            "2026-01-01,I found you through ChatGPT\n"
            "2026-01-01,Google search\n"
            "2026-01-01,A colleague told me\n"
            "2026-01-01,Searched on Google\n")
        dataset = self.load("survey", path)
        response = dataset.surveys[0]
        self.assertEqual(response.respondents, 4)
        self.assertAlmostEqual(response.share_ai_assistant, 0.25)
        self.assertAlmostEqual(response.share_search_engine, 0.50)


class TestGenericConnector(ConnectorTestCase):
    def test_maps_an_unknown_export_onto_a_canonical_collection(self):
        path = self.write("odd.csv",
            "term,rank,views,visits\nwidget thing,5,9000,300\n")
        dataset = self.load(
            "generic", path, target="keywords",
            column_map={"keyword": "term", "position": "rank",
                        "impressions": "views", "clicks": "visits"},
        )
        record = dataset.keywords[0]
        self.assertEqual(record.keyword, "widget thing")
        self.assertEqual(record.position, 5.0)
        self.assertEqual(record.impressions, 9000)
        # Classification is derived even for a mapped source.
        self.assertFalse(record.branded)

    def test_unmapped_data_lands_in_extras(self):
        path = self.write("misc.csv", "a,b\n1,2\n")
        dataset = self.load("generic", path, extras_key="misc")
        self.assertEqual(dataset.extras["misc"], [{"a": "1", "b": "2"}])

    def test_bad_target_is_rejected_clearly(self):
        path = self.write("x.csv", "a\n1\n")
        with self.assertRaises(ConnectorError):
            self.load("generic", path, target="not_a_collection")


class TestErrorHandling(ConnectorTestCase):
    def test_missing_file_raises_a_clear_error(self):
        with self.assertRaises(ConnectorError):
            self.load("gsc", "nope.csv")

    def test_malformed_rows_degrade_to_nulls(self):
        """One bad cell must not abort an entire export."""
        path = self.write("gsc.csv",
            "Query,Clicks,Impressions,Position\n"
            "good,100,5000,4.2\n"
            "bad,n/a,not-a-number,--\n")
        dataset = self.load("gsc", path)
        self.assertEqual(len(dataset.keywords), 2)
        self.assertIsNone(dataset.keywords[1].position)
        self.assertEqual(dataset.keywords[1].clicks, 0)


if __name__ == "__main__":
    unittest.main()
