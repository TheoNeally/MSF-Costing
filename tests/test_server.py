from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from msf_costing.calculations import default_estimate
from msf_costing.rates import RateLibrary
from msf_costing.server import CostingServer
from msf_costing.store import EstimateStore


class ServerTestCase(unittest.TestCase):
    """Runs one isolated server per test class, with its own rate library."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_directory = tempfile.TemporaryDirectory()
        root = Path(cls.temp_directory.name)
        static = root / "static"
        static.mkdir()
        (static / "index.html").write_text("<!doctype html><title>test</title>", encoding="utf-8")
        cls.rates_path = root / "rates.json"
        cls.server = CostingServer(
            ("127.0.0.1", 0),
            static,
            EstimateStore(root / "test.db"),
            RateLibrary.load(cls.rates_path),
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp_directory.cleanup()

    def request(
        self, path: str, method: str = "GET", payload: dict | None = None
    ) -> tuple[int, dict]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            self.url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())


class ServerTests(ServerTestCase):
    def test_health_and_defaults(self) -> None:
        status, health = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])

        status, defaults = self.request("/api/defaults")
        self.assertEqual(status, 200)
        self.assertEqual(defaults["frame"]["panel_set_cost"], 1150)

    def test_calculate_save_and_reopen(self) -> None:
        payload = default_estimate()
        status, result = self.request("/api/calculate", "POST", payload)
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])

        status, saved = self.request(
            "/api/estimates", "POST", {"project_id": None, "payload": payload}
        )
        self.assertEqual(status, 201)
        record_id = saved["saved"]["id"]

        status, reopened = self.request(f"/api/estimates/{record_id}")
        self.assertEqual(status, 200)
        self.assertEqual(reopened["revision"], 1)
        self.assertEqual(reopened["payload"]["project"]["name"], "Untitled MSF Radome")

    def test_defaults_carry_the_rate_library_stamp(self) -> None:
        _, defaults = self.request("/api/defaults")
        stamp = defaults["rate_library"]
        self.assertEqual(stamp["version"], 1)
        self.assertEqual(stamp["total"], 36)
        self.assertEqual(stamp["unvalidated"], 36)
        self.assertIn("Rates v1", stamp["label"])

    def test_rate_library_listing(self) -> None:
        status, data = self.request("/api/rates")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["entries"]), 36)
        self.assertIn("Frame system", data["categories"])
        self.assertEqual(data["confidence_levels"][0]["value"], "actual")
        panel = next(e for e in data["entries"] if e["path"] == "frame.panel_set_cost")
        self.assertEqual(panel["value"], 1150)
        self.assertTrue(panel["at_seed_value"])
        self.assertTrue(panel["unvalidated"])
        self.assertFalse(panel["stale"])


class RateApiTests(ServerTestCase):
    """Mutating rate-library requests, isolated from the read-only assertions."""

    def test_update_flows_into_defaults_and_history(self) -> None:
        status, data = self.request(
            "/api/rates",
            "PUT",
            {
                "updates": {
                    "labor.shop_rate": {
                        "value": 74.5,
                        "confidence": "actual",
                        "effective_date": "2026-08-01",
                        "source": "FY26 payroll burden study",
                    }
                },
                "changed_by": "Estimator",
                "reason": "Real burdened shop rate",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(data["changes"]), 1)
        self.assertEqual(data["changes"][0]["previous_value"], 60.0)
        self.assertEqual(data["changes"][0]["value"], 74.5)
        self.assertEqual(data["library"]["version"], 2)

        _, defaults = self.request("/api/defaults")
        self.assertEqual(defaults["labor"]["shop_rate"], 74.5)
        self.assertEqual(defaults["rate_library"]["version"], 2)
        self.assertEqual(defaults["rate_library"]["unvalidated"], 35)

        _, history = self.request("/api/rates/history?path=labor.shop_rate")
        self.assertEqual(len(history["history"]), 1)
        self.assertEqual(history["history"][0]["changed_by"], "Estimator")
        self.assertEqual(history["history"][0]["reason"], "Real burdened shop rate")

    def test_update_rejects_negative_value(self) -> None:
        status, data = self.request(
            "/api/rates",
            "PUT",
            {"updates": {"membrane.fabric_rate_base": {"value": -3}}},
        )
        self.assertEqual(status, 400)
        self.assertTrue(any("at least" in detail for detail in data["details"]))
        _, current = self.request("/api/rates")
        entry = next(e for e in current["entries"] if e["path"] == "membrane.fabric_rate_base")
        self.assertEqual(entry["value"], 8.0)

    def test_update_rejects_unmanaged_path(self) -> None:
        status, data = self.request(
            "/api/rates", "PUT", {"updates": {"geometry.diameter_ft": {"value": 40}}}
        )
        self.assertEqual(status, 400)
        self.assertIn("not a library-managed rate", data["details"][0])

    def test_update_requires_a_source_for_validated_confidence(self) -> None:
        status, data = self.request(
            "/api/rates",
            "PUT",
            {"updates": {"labor.field_rate": {"value": 92, "confidence": "quoted", "source": ""}}},
        )
        self.assertEqual(status, 400)
        self.assertTrue(any("source is required" in detail for detail in data["details"]))


if __name__ == "__main__":
    unittest.main()
