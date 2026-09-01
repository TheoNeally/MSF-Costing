from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from msf_costing.calculations import calculate_estimate, default_estimate
from msf_costing.rates import (
    RATE_FIELDS,
    RATE_FIELDS_BY_PATH,
    RateLibrary,
    RateValidationError,
    seed_library,
)


class RateLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_directory.name) / "rates.json"
        self.library = RateLibrary.load(self.path)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_seeds_the_file_on_first_load(self) -> None:
        self.assertTrue(self.path.exists())
        self.assertIsNone(self.library.load_error)
        self.assertEqual(self.library.version, 1)
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(stored["rates"]), len(RATE_FIELDS))

    def test_seed_values_match_the_engine_defaults(self) -> None:
        estimate = default_estimate()
        for path, value in self.library.values().items():
            section, key = path.split(".")
            self.assertEqual(estimate[section][key], value, msg=path)

    def test_apply_to_overlays_values_and_stamps_the_estimate(self) -> None:
        self.library.update(
            {
                "frame.panel_set_cost": {
                    "value": 1290,
                    "confidence": "quoted",
                    "effective_date": "2026-08-15",
                    "source": "Quote 4471, BK-1 frame set",
                }
            }
        )
        estimate = self.library.apply_to(default_estimate())
        self.assertEqual(estimate["frame"]["panel_set_cost"], 1290)
        self.assertEqual(estimate["rate_library"]["version"], 2)
        self.assertEqual(estimate["rate_library"]["unvalidated"], len(RATE_FIELDS) - 1)

        result = calculate_estimate(estimate)
        self.assertTrue(result["ok"])
        self.assertEqual(result["frame"]["cost"], 1290 * 80)

    def test_update_records_history_and_bumps_the_version(self) -> None:
        changes = self.library.update(
            {
                "labor.field_rate": {
                    "value": 96.25,
                    "confidence": "actual",
                    "effective_date": "2026-07-01",
                    "source": "2025 installation job cost roll-up",
                    "note": "Includes fringe and per-crew supervision",
                }
            },
            changed_by="Estimator",
            reason="Field payroll data now available",
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(self.library.version, 2)

        history = self.library.history()
        self.assertEqual(len(history), 1)
        record = history[0]
        self.assertEqual(record["path"], "labor.field_rate")
        self.assertEqual(record["previous_value"], 85.0)
        self.assertEqual(record["value"], 96.25)
        self.assertEqual(record["previous_confidence"], "placeholder")
        self.assertEqual(record["confidence"], "actual")
        self.assertEqual(record["changed_by"], "Estimator")

        reloaded = RateLibrary.load(self.path)
        self.assertEqual(reloaded.entry("labor.field_rate")["value"], 96.25)
        self.assertEqual(reloaded.version, 2)

    def test_history_is_append_only_across_updates(self) -> None:
        self.library.update(
            {"other.contingency_pct": {"value": 12, "confidence": "benchmark", "source": "Prior ROM accuracy"}}
        )
        self.library.update(
            {"other.contingency_pct": {"value": 10, "confidence": "benchmark", "source": "Prior ROM accuracy"}}
        )
        history = self.library.history(path="other.contingency_pct")
        self.assertEqual([record["value"] for record in history], [10.0, 12.0])
        self.assertEqual(self.library.version, 3)

    def test_no_op_update_changes_nothing(self) -> None:
        changes = self.library.update({"labor.shop_rate": {"value": 60.0}})
        self.assertEqual(changes, [])
        self.assertEqual(self.library.version, 1)
        self.assertEqual(self.library.history(), [])

    def test_rejected_batch_leaves_every_rate_untouched(self) -> None:
        with self.assertRaises(RateValidationError) as caught:
            self.library.update(
                {
                    "labor.shop_rate": {"value": 72, "confidence": "actual", "source": "Payroll"},
                    "membrane.fabric_rate_base": {"value": -1},
                }
            )
        self.assertTrue(any("at least" in detail for detail in caught.exception.details))
        self.assertEqual(self.library.entry("labor.shop_rate")["value"], 60.0)
        self.assertEqual(self.library.version, 1)

    def test_validation_rules(self) -> None:
        cases = {
            "unknown path": ({"labor.nonexistent": {"value": 1}}, "not a library-managed rate"),
            "bad confidence": (
                {"labor.shop_rate": {"value": 60, "confidence": "vibes"}},
                "confidence must be one of",
            ),
            "bad date": (
                {"labor.shop_rate": {"value": 60, "effective_date": "August 2026"}},
                "effective date must be YYYY-MM-DD",
            ),
            "bad review date": (
                {"labor.shop_rate": {"value": 60, "review_by": "soon"}},
                "review date must be YYYY-MM-DD",
            ),
            "source required": (
                {"labor.shop_rate": {"value": 60, "confidence": "quoted", "source": "  "}},
                "source is required",
            ),
            "factor floor": (
                {"frame.complexity_factor": {"value": 0}},
                "must be at least 0.01",
            ),
            "margin ceiling": (
                {"pricing.target_margin_pct": {"value": 100}},
                "must not exceed 99.99",
            ),
            "non-numeric": (
                {"labor.shop_rate": {"value": "sixty"}},
                "value must be a number",
            ),
        }
        for name, (updates, expected) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(RateValidationError) as caught:
                    self.library.update(updates)
                self.assertTrue(
                    any(expected in detail for detail in caught.exception.details),
                    msg=f"{name}: {caught.exception.details}",
                )

    def test_placeholder_confidence_does_not_require_a_source(self) -> None:
        changes = self.library.update(
            {"labor.per_diem": {"value": 165, "confidence": "placeholder", "source": ""}}
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(self.library.entry("labor.per_diem")["source"], "")

    def test_stale_and_unvalidated_flags(self) -> None:
        self.library.update(
            {
                "membrane.fabric_rate_base": {
                    "value": 9.4,
                    "confidence": "quoted",
                    "effective_date": "2026-03-01",
                    "review_by": "2026-06-01",
                    "source": "Supplier quote 8812",
                }
            }
        )
        entries = {row["path"]: row for row in self.library.entries(today=date(2026, 9, 1))}
        fabric = entries["membrane.fabric_rate_base"]
        self.assertFalse(fabric["unvalidated"])
        self.assertTrue(fabric["stale"])
        self.assertFalse(fabric["at_seed_value"])
        self.assertEqual(fabric["seed_value"], 8.0)

        fresh = self.library.entries(today=date(2026, 5, 1))
        self.assertFalse(next(r for r in fresh if r["path"] == "membrane.fabric_rate_base")["stale"])

        stamp = self.library.stamp(today=date(2026, 9, 1))
        self.assertEqual(stamp["stale"], 1)
        self.assertEqual(stamp["unvalidated"], len(RATE_FIELDS) - 1)
        self.assertEqual(stamp["newest_effective_date"], "2026-03-01")

    def test_malformed_file_falls_back_without_overwriting(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        library = RateLibrary.load(self.path)
        self.assertIsNotNone(library.load_error)
        self.assertIn("could not be read", library.load_error)
        self.assertEqual(library.entry("frame.panel_set_cost")["value"], 1150.0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{not json")

    def test_missing_and_unknown_paths_are_reconciled_on_load(self) -> None:
        data = seed_library()
        data["rates"].pop("labor.shop_rate")
        data["rates"]["labor.retired_rate"] = {"value": 5, "confidence": "actual"}
        self.path.write_text(json.dumps(data), encoding="utf-8")

        library = RateLibrary.load(self.path)
        self.assertEqual(library.entry("labor.shop_rate")["value"], 60.0)
        self.assertNotIn("labor.retired_rate", library.values())
        self.assertIn("outside the catalog", library.load_error)

    def test_every_catalog_path_exists_in_the_engine_defaults(self) -> None:
        estimate = default_estimate()
        for field in RATE_FIELDS:
            section, key = field.path.split(".")
            self.assertIn(section, estimate, msg=field.path)
            self.assertIn(key, estimate[section], msg=field.path)
            self.assertIsInstance(estimate[section][key], (int, float), msg=field.path)

    def test_catalog_has_no_duplicate_paths(self) -> None:
        self.assertEqual(len(RATE_FIELDS_BY_PATH), len(RATE_FIELDS))


if __name__ == "__main__":
    unittest.main()
