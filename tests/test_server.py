from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from src.calculations import default_estimate
from src.server import CostingServer
from src.store import EstimateStore


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_directory = tempfile.TemporaryDirectory()
        root = Path(cls.temp_directory.name)
        static = root / "static"
        static.mkdir()
        (static / "index.html").write_text("<!doctype html><title>test</title>", encoding="utf-8")
        cls.server = CostingServer(
            ("127.0.0.1", 0), static, EstimateStore(root / "test.db")
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

    def request(self, path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            self.url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())

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


if __name__ == "__main__":
    unittest.main()
