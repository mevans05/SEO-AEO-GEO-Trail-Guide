"""Coercion, CTR, economics and schema-merge behaviour."""

from __future__ import annotations

import unittest

from helpers import base_config, keyword, page            # noqa: F401
from trailguide.core import coerce
from trailguide.core.ctr import CTRModel
from trailguide.core.economics import RevenueModel
from trailguide.core.schemas import Dataset, FunnelStage, Intent, KeywordMetric, PageMetric


class TestCoerce(unittest.TestCase):
    def test_numeric_formats(self):
        self.assertEqual(coerce.to_float("1,200"), 1200.0)
        self.assertEqual(coerce.to_float("$1,250.00"), 1250.0)
        self.assertAlmostEqual(coerce.to_float("12.4%"), 0.124)
        self.assertEqual(coerce.to_float("(500)"), -500.0)

    def test_nullish_values_fall_back(self):
        for value in ("", "-", "N/A", "(not set)", None):
            self.assertEqual(coerce.to_float(value, 0.0), 0.0, msg=repr(value))

    def test_column_matching_ignores_separators_and_case(self):
        """Vendors vary separators between exports; one alias must cover all."""
        row = {"Monthly Prompt Volume": "4,800", "avg_position": "3.2", "Avg. Position": "9"}
        self.assertEqual(coerce.first_present(row, ["monthly_prompt_volume"]), "4,800")
        self.assertEqual(coerce.first_present(row, ["Monthly prompt volume"]), "4,800")
        self.assertIsNone(coerce.first_present(row, ["absent_column"]))

    def test_dates_and_booleans(self):
        self.assertEqual(coerce.to_date("20240115").isoformat(), "2024-01-15")
        self.assertEqual(coerce.to_date("2024-01-15").isoformat(), "2024-01-15")
        self.assertIsNone(coerce.to_date("not a date"))
        self.assertTrue(coerce.to_bool("Indexable"))
        self.assertFalse(coerce.to_bool("Non-Indexable"))


class TestCTRModel(unittest.TestCase):
    def setUp(self):
        self.model = CTRModel()

    def test_curve_is_monotonic(self):
        values = [self.model.base_ctr(position) for position in range(1, 21)]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_fractional_positions_interpolate(self):
        middle = self.model.base_ctr(4.5)
        self.assertLess(middle, self.model.base_ctr(4))
        self.assertGreater(middle, self.model.base_ctr(5))

    def test_serp_features_suppress_clicks(self):
        plain = self.model.expected_ctr(3)
        with_overview = self.model.expected_ctr(3, serp_features=["ai_overview"])
        self.assertLess(with_overview, plain)

    def test_feature_multiplier_has_a_floor(self):
        """Stacked features must never model away every click."""
        stacked = ["ai_overview", "featured_snippet", "local_pack", "shopping", "top_ads"]
        self.assertGreaterEqual(self.model.feature_multiplier(stacked), 0.25)

    def test_click_delta_never_negative(self):
        """Moving to a worse position is not an opportunity."""
        self.assertEqual(self.model.click_delta(10000, 3.0, 8.0), 0.0)
        self.assertEqual(self.model.click_delta(10000, 3.0, 3.0), 0.0)
        self.assertGreater(self.model.click_delta(10000, 8.0, 3.0), 0.0)

    def test_suppressed_clicks_measures_the_shortfall(self):
        # Position 2 on 10k impressions should earn ~1,570 clicks.
        suppressed = self.model.suppressed_clicks(10000, 2.0, 500)
        self.assertGreater(suppressed, 1000)
        # Over-performing pages have no shortfall.
        self.assertEqual(self.model.suppressed_clicks(10000, 2.0, 5000), 0.0)


class TestRevenueModel(unittest.TestCase):
    def test_b2b_chains_stage_rates(self):
        model = RevenueModel.from_config({
            "model": "b2b",
            "b2b": {"visit_to_lead": 0.02, "lead_to_mql": 0.5, "mql_to_sql": 0.4,
                    "sql_to_win": 0.25, "average_contract_value": 20000},
        })
        self.assertAlmostEqual(model.base_conversion_rate, 0.02 * 0.5 * 0.4 * 0.25)
        self.assertAlmostEqual(model.base_revenue_per_session, 0.001 * 20000)

    def test_intent_multipliers_differentiate_traffic_quality(self):
        model = RevenueModel.from_config({"model": "ecommerce",
                                          "ecommerce": {"conversion_rate": 0.02,
                                                        "average_order_value": 100}})
        commercial = model.value_of_sessions(1000, intent=Intent.TRANSACTIONAL).revenue
        informational = model.value_of_sessions(1000, intent=Intent.INFORMATIONAL).revenue
        self.assertGreater(commercial, informational)

    def test_observed_rps_is_capped(self):
        """One freak-converting URL must not dominate the portfolio."""
        model = RevenueModel.from_config({"model": "ecommerce",
                                          "ecommerce": {"conversion_rate": 0.02,
                                                        "average_order_value": 100}})
        value = model.value_of_sessions(1000, observed_revenue_per_session=10_000)
        self.assertEqual(value.revenue, 1000 * model.base_revenue_per_session * 5.0)

    def test_sessions_needed_inverts_valuation(self):
        model = RevenueModel.from_config({"model": "ecommerce",
                                          "ecommerce": {"conversion_rate": 0.02,
                                                        "average_order_value": 100}})
        needed = model.sessions_needed_for_revenue(10_000)
        self.assertAlmostEqual(model.value_of_sessions(needed).revenue, 10_000, places=4)

    def test_crm_calibration_adopts_observed_rates(self):
        model = RevenueModel.from_config({
            "model": "b2b",
            "b2b": {"visit_to_lead": 0.01, "average_contract_value": 10000,
                    "sales_cycle_days": 30},
        })
        notes = model.calibrate_from_funnel([
            FunnelStage(sessions=10000, leads=300, mqls=150, sqls=60,
                        closed_won=15, closed_won_value=450000, sales_cycle_days=90)
        ])
        self.assertTrue(notes)
        self.assertAlmostEqual(model.visit_to_lead, 0.03)
        self.assertAlmostEqual(model.average_contract_value, 30000.0)
        self.assertAlmostEqual(model.sales_cycle_days, 90.0)

    def test_crm_calibration_ignores_thin_data(self):
        """A sparse export must not overwrite a considered assumption."""
        model = RevenueModel()
        before = model.visit_to_lead
        model.calibrate_from_funnel([FunnelStage(sessions=10, leads=1)])
        self.assertEqual(model.visit_to_lead, before)

    def test_calibration_ignores_rounding_noise(self):
        model = RevenueModel.from_config({"model": "b2b", "b2b": {"visit_to_lead": 0.0300}})
        model.calibrate_from_funnel([
            FunnelStage(sessions=100000, leads=3001, mqls=1000, sqls=400,
                        closed_won=100, closed_won_value=2000000)
        ])
        self.assertNotIn("visit-to-lead", " ".join(model.calibration_notes))


class TestDatasetMerging(unittest.TestCase):
    def test_pages_merge_without_overwriting(self):
        dataset = Dataset(pages=[
            PageMetric(source="ga4", url="/a", sessions=100, revenue=500.0),
            PageMetric(source="crawl", url="/a", word_count=800, lcp_ms=3200.0),
        ])
        merged = dataset.page_index()["/a"]
        self.assertEqual(merged.sessions, 100)
        self.assertEqual(merged.word_count, 800)
        self.assertEqual(merged.lcp_ms, 3200.0)

    def test_page_additive_metrics_accumulate(self):
        dataset = Dataset(pages=[
            PageMetric(source="ga4", url="/a", sessions=100),
            PageMetric(source="ga4", url="/a", sessions=50),
        ])
        self.assertEqual(dataset.page_index()["/a"].sessions, 150)

    def test_keywords_prefer_first_party_position(self):
        """An observed Search Console position beats a third-party sample."""
        dataset = Dataset(keywords=[
            KeywordMetric(source="gsc", keyword="Best CRM", impressions=5000,
                          clicks=120, position=6.4),
            KeywordMetric(source="semrush", keyword="best crm", position=9.9,
                          search_volume=9900, difficulty=71.0,
                          competitor_positions={"rival.com": 3.0}),
        ])
        merged = dataset.keyword_index()["best crm"]
        self.assertEqual(merged.position, 6.4)
        self.assertEqual(merged.search_volume, 9900)
        self.assertEqual(merged.competitor_positions, {"rival.com": 3.0})

    def test_keyword_impressions_sum_across_sources(self):
        dataset = Dataset(keywords=[
            KeywordMetric(source="gsc", keyword="a", impressions=100, clicks=10, position=5.0),
            KeywordMetric(source="gsc", keyword="a", impressions=200, clicks=20, position=5.0),
        ])
        merged = dataset.keyword_index()["a"]
        self.assertEqual(merged.impressions, 300)
        self.assertEqual(merged.clicks, 30)


if __name__ == "__main__":
    unittest.main()
