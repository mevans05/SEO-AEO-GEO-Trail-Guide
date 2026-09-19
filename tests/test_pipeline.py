"""End-to-end run against the bundled sample dataset."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from helpers import SAMPLE_CONFIG, base_config                    # noqa: F401
from trailguide.cli import main
from trailguide.config import Config
from trailguide.core.schemas import Dataset
from trailguide.pipeline import run
from trailguide.report import render_markdown, write_csvs, write_json


class TestSampleRun(unittest.TestCase):
    """The sample config must stay runnable; it is the system's own regression test."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config.load(SAMPLE_CONFIG)
        cls.result = run(cls.config)

    def test_every_configured_source_loads(self):
        failures = [entry for entry in self.result.manifest if entry["status"] == "error"]
        self.assertEqual(failures, [], msg=f"sources failed: {failures}")

    def test_all_canonical_collections_are_populated(self):
        coverage = self.result.dataset.coverage()
        for name in Dataset.COLLECTIONS:
            self.assertGreater(coverage[name], 0, msg=f"{name} is empty")

    def test_opportunities_span_every_surface(self):
        surfaces = {item.surface.value for item in self.result.opportunities}
        for expected in ("SEO", "AEO", "GEO", "TECHNICAL", "CONVERSION", "DISTRIBUTION"):
            self.assertIn(expected, surfaces)

    def test_both_tracks_are_estimated(self):
        self.assertTrue(self.result.dark.seo.estimates)
        self.assertTrue(self.result.dark.geo.estimates)
        self.assertGreater(self.result.dark.total_attributed_revenue, 0)

    def test_track2_triangulates_across_several_methods(self):
        """A single-method estimate is not triangulation."""
        self.assertGreaterEqual(len(self.result.dark.seo.estimates), 3)
        self.assertGreaterEqual(len(self.result.dark.geo.estimates), 3)

    def test_ranking_is_ordered_and_complete(self):
        ranks = [item.rank for item in self.result.opportunities]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    def test_portfolio_respects_capacity(self):
        capacity = self.config.capacity_per_quarter
        for quarter, used in self.result.portfolio.capacity_used.items():
            for discipline, days in used.items():
                self.assertLessEqual(
                    days, capacity[discipline] + 1e-6,
                    msg=f"Q{quarter} {discipline} over capacity",
                )

    def test_scheduled_and_deferred_account_for_everything(self):
        total = len(self.result.portfolio.scheduled) + len(self.result.portfolio.deferred)
        self.assertEqual(total, len(self.result.opportunities))

    def test_projection_never_exceeds_the_organic_baseline_implausibly(self):
        search_sessions = sum(
            item.projection.incremental_sessions
            for item in self.result.opportunities
            if item.demand_pool == "search"
        )
        baseline = self.result.dark.seo.known_sessions
        self.assertLess(search_sessions, baseline * 0.60)

    def test_generative_claims_stay_inside_the_modeled_pool(self):
        generative = sum(
            item.projection.incremental_sessions
            for item in self.result.opportunities
            if item.demand_pool == "generative"
        )
        pool = self.result.dark.geo.known_sessions + self.result.dark.geo.dark_sessions
        self.assertLessEqual(generative, pool)

    def test_overlap_deduplication_ran(self):
        self.assertIn("opportunities_adjusted", self.result.overlap)

    def test_economics_were_calibrated_from_the_crm(self):
        self.assertTrue(self.result.revenue.describe()["calibrated_from_crm"])

    def test_every_number_is_finite(self):
        payload = json.dumps(self.result.to_dict(), default=str)
        for token in ("Infinity", "-Infinity", "NaN"):
            self.assertNotIn(token, payload)

    def test_every_opportunity_carries_evidence_and_actions(self):
        for item in self.result.opportunities:
            self.assertTrue(item.evidence, msg=f"{item.title} has no evidence")
            self.assertTrue(item.recommended_actions, msg=f"{item.title} has no actions")
            self.assertTrue(item.id)

    def test_run_is_deterministic(self):
        """Same inputs, same plan - otherwise month-over-month tracking is noise."""
        again = run(Config.load(SAMPLE_CONFIG))
        self.assertEqual(
            [item.id for item in again.opportunities],
            [item.id for item in self.result.opportunities],
        )
        self.assertAlmostEqual(
            again.portfolio.projected_revenue,
            self.result.portfolio.projected_revenue,
            places=2,
        )


class TestOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run(Config.load(SAMPLE_CONFIG))

    def test_markdown_contains_the_key_sections(self):
        report = render_markdown(self.result)
        for heading in ("Executive summary", "Revenue bridge",
                        "Measurement baseline: the two-track model",
                        "Prioritized roadmap", "Opportunity register",
                        "Data coverage and confidence", "Method and assumptions"):
            self.assertIn(heading, report)

    def test_exports_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_json(self.result, out / "analysis.json")
            paths = write_csvs(self.result, out)
            self.assertTrue((out / "analysis.json").is_file())
            names = {path.name for path in paths}
            self.assertEqual(
                names,
                {"opportunities.csv", "roadmap.csv", "evidence.csv",
                 "dark_traffic_estimators.csv"},
            )
            for path in paths:
                self.assertGreater(path.stat().st_size, 0, msg=f"{path.name} is empty")


class TestDegradedInputs(unittest.TestCase):
    def test_run_survives_an_empty_dataset(self):
        """No sources should produce a warning-rich report, not a crash."""
        result = run(base_config(sources=[]))
        # Only measurement-gap findings are possible with no data at all.
        self.assertTrue(
            all("enabling" in item.tags for item in result.opportunities)
        )
        self.assertTrue(result.warnings)
        self.assertIsInstance(render_markdown(result), str)

    def test_run_survives_a_broken_source(self):
        config = base_config(sources=[{"type": "gsc", "path": "does-not-exist.csv"}])
        result = run(config)
        self.assertTrue(any("failed to load" in warning for warning in result.warnings))
        self.assertEqual(
            [entry["status"] for entry in result.manifest], ["error"]
        )


class TestCLI(unittest.TestCase):
    def test_run_command_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["run", "--config", str(SAMPLE_CONFIG), "--out", tmp, "--quiet"])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "opportunity-analysis.md").is_file())

    def test_validate_command_passes_on_the_sample(self):
        self.assertEqual(main(["validate", "--config", str(SAMPLE_CONFIG)]), 0)

    def test_listing_commands_work(self):
        self.assertEqual(main(["sources"]), 0)
        self.assertEqual(main(["analyzers"]), 0)

    def test_missing_config_exits_cleanly(self):
        self.assertEqual(main(["run", "--config", "/nope/missing.yml"]), 2)


if __name__ == "__main__":
    unittest.main()
