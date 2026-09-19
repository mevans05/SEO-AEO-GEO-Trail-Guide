"""Track 2 triangulation: estimators, blending and surface routing."""

from __future__ import annotations

import unittest

from helpers import channel_dataset, citation, keyword, survey   # noqa: F401
from trailguide.analysis import dark_traffic as dt
from trailguide.core.ctr import CTRModel
from trailguide.core.economics import RevenueModel
from trailguide.core.schemas import BotHit, Dataset


class TestEstimators(unittest.TestCase):
    def setUp(self):
        self.ctr = CTRModel()
        self.revenue = RevenueModel.from_config(
            {"model": "ecommerce", "ecommerce": {"conversion_rate": 0.02,
                                                 "average_order_value": 100}}
        )
        self.settings = dict(dt.DEFAULTS)

    def test_zero_click_uses_underperforming_keywords(self):
        dataset = Dataset(keywords=[
            keyword("widget guide", position=2.0, impressions=10000, clicks=200,
                    serp_features=["ai_overview"]),
        ])
        estimate = dt.estimate_zero_click(dataset, self.ctr, self.settings)
        self.assertIsNotNone(estimate)
        self.assertGreater(estimate.dark_sessions, 0)

    def test_zero_click_is_annualized(self):
        """A one-month keyword window must be put on an annual basis."""
        dataset = Dataset(keywords=[
            keyword("widget guide", position=2.0, impressions=10000, clicks=200),
        ])
        monthly = dict(self.settings, keyword_periods_per_year=1.0)
        annual = dict(self.settings, keyword_periods_per_year=12.0)
        self.assertAlmostEqual(
            dt.estimate_zero_click(dataset, self.ctr, annual).dark_sessions,
            dt.estimate_zero_click(dataset, self.ctr, monthly).dark_sessions * 12.0,
        )

    def test_zero_click_skips_branded_demand(self):
        """Branded demand is the downstream signal, not the dark pool."""
        dataset = Dataset(keywords=[
            keyword("testco", position=1.0, impressions=10000, clicks=100, branded=True),
        ])
        self.assertIsNone(dt.estimate_zero_click(dataset, self.ctr, self.settings))

    def test_branded_lift_requires_enough_periods(self):
        series = dt.build_channel_series(channel_dataset(periods=3))
        self.assertIsNone(dt.estimate_branded_lift(series, self.settings))

    def test_branded_lift_finds_a_positive_relationship(self):
        series = dt.build_channel_series(channel_dataset(periods=12))
        estimate = dt.estimate_branded_lift(series, self.settings)
        self.assertIsNotNone(estimate)
        self.assertGreater(estimate.inputs["r_squared"], 0.5)

    def test_branded_lift_is_capped(self):
        """Dark organic cannot exceed the configured share of direct traffic."""
        series = dt.build_channel_series(channel_dataset(periods=12))
        capped = dict(self.settings, max_branded_direct_share=0.05)
        estimate = dt.estimate_branded_lift(series, capped)
        mean_direct = sum(series.direct.values()) / len(series.direct)
        self.assertLessEqual(estimate.dark_sessions, mean_direct * 0.05 * 12 + 1)

    def test_survey_ai_uses_the_observed_conversion_rate(self):
        """Analytics conversions are leads; dividing by a closed-won rate mixes units."""
        dataset = channel_dataset(periods=12)
        dataset.surveys.append(survey(ai=0.15))
        series = dt.build_channel_series(dataset)
        estimate = dt.estimate_survey_ai(dataset, series, self.revenue, self.settings)
        self.assertIsNotNone(estimate)
        self.assertAlmostEqual(
            estimate.inputs["observed_conversion_rate"],
            round(series.observed_conversion_rate, 5),
        )

    def test_survey_ai_cannot_exceed_total_traffic(self):
        """An AI-influenced session is still a session."""
        dataset = channel_dataset(periods=12)
        dataset.surveys.append(survey(ai=0.99))
        series = dt.build_channel_series(dataset)
        estimate = dt.estimate_survey_ai(dataset, series, self.revenue, self.settings)
        total = series.total_sessions * series.annualization
        self.assertLessEqual(estimate.dark_sessions, total)

    def test_citation_share_needs_prompt_volume(self):
        dataset = Dataset(citations=[
            citation("best crm", "chatgpt", True, monthly_prompt_volume=None),
        ])
        self.assertIsNone(dt.estimate_citation_share(dataset, self.settings))

    def test_citation_share_weights_prominence(self):
        """Being named first is worth more than being listed fifth."""
        prominent = Dataset(citations=[
            citation("best crm", "chatgpt", True, brand_position=1),
        ])
        buried = Dataset(citations=[
            citation("best crm", "chatgpt", True, brand_position=5),
        ])
        self.assertGreater(
            dt.estimate_citation_share(prominent, self.settings).dark_sessions,
            dt.estimate_citation_share(buried, self.settings).dark_sessions,
        )

    def test_crawler_estimate_counts_only_ai_bots(self):
        dataset = Dataset(bot_hits=[
            BotHit(source="logs", url="/a", bot="googlebot", hits=1000, is_ai_bot=False),
        ])
        self.assertIsNone(dt.estimate_crawler_retrieval(dataset, self.settings))
        dataset.bot_hits.append(
            BotHit(source="logs", url="/a", bot="chatgpt", hits=500, is_ai_bot=True)
        )
        self.assertIsNotNone(dt.estimate_crawler_retrieval(dataset, self.settings))


class TestBlending(unittest.TestCase):
    def _track(self, values_and_confidence):
        track = dt.TrackEstimate(track="seo", known_sessions=10000)
        for value, confidence in values_and_confidence:
            track.estimates.append(
                dt.Estimate("m", "seo", value, confidence, "note")
            )
        return track

    def test_blend_is_confidence_weighted(self):
        track = self._track([(1000, 1.0), (3000, 0.0)])
        self.assertAlmostEqual(track.dark_sessions, 1000.0)

    def test_agreement_raises_confidence(self):
        """Independent methods converging is itself evidence."""
        tight = self._track([(1000, 0.5), (1050, 0.5)])
        wide = self._track([(200, 0.5), (5000, 0.5)])
        self.assertGreater(tight.confidence, wide.confidence)

    def test_disagreement_widens_uncertainty(self):
        tight = self._track([(1000, 0.5), (1050, 0.5)])
        wide = self._track([(200, 0.5), (5000, 0.5)])
        self.assertGreater(wide.uncertainty, tight.uncertainty)

    def test_no_estimates_is_zero_not_a_guess(self):
        track = self._track([])
        self.assertEqual(track.dark_sessions, 0.0)
        self.assertEqual(track.multiplier, 0.0)


class TestSurfaceRouting(unittest.TestCase):
    def setUp(self):
        self.result = dt.DarkTrafficResult(
            seo=dt.TrackEstimate("seo", 10000, [dt.Estimate("m", "seo", 2000, 0.6, "")]),
            geo=dt.TrackEstimate("geo", 1000, [dt.Estimate("m", "geo", 6000, 0.6, "")]),
        )

    def test_aeo_uses_the_organic_track(self):
        """Answer features are won on the SERP and earn organic clicks."""
        self.assertEqual(
            self.result.multiplier_for("AEO"), self.result.seo.multiplier
        )
        self.assertNotEqual(
            self.result.multiplier_for("AEO"), self.result.geo.multiplier
        )

    def test_geo_uses_the_llm_track(self):
        self.assertEqual(self.result.multiplier_for("GEO"), self.result.geo.multiplier)

    def test_other_surfaces_default_to_organic(self):
        self.assertEqual(
            self.result.multiplier_for("TECHNICAL"), self.result.seo.multiplier
        )


class TestOrchestration(unittest.TestCase):
    def test_missing_inputs_are_reported_not_guessed(self):
        result = dt.model_dark_traffic(Dataset(), CTRModel(), RevenueModel())
        self.assertEqual(result.seo.dark_sessions, 0.0)
        self.assertTrue(result.seo.skipped)
        self.assertTrue(all("reason" in item for item in result.seo.skipped))

    def test_b2b_revenue_falls_back_to_the_funnel_model(self):
        """B2B analytics carries no revenue; the baseline must not collapse to zero."""
        dataset = channel_dataset(periods=12)   # revenue is 0 on every channel
        result = dt.model_dark_traffic(dataset, CTRModel(), RevenueModel())
        self.assertGreater(result.known_organic_revenue, 0.0)


if __name__ == "__main__":
    unittest.main()
