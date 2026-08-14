from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from msf_costing.calculations import calculate_estimate, default_estimate
from msf_costing.store import EstimateStore


class StoreTests(unittest.TestCase):
    def test_save_creates_immutable_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EstimateStore(Path(directory) / "test.db")
            payload = default_estimate()
            first = store.save(payload, calculate_estimate(payload))

            payload["project"]["name"] = "Updated name"
            second = store.save(
                payload, calculate_estimate(payload), project_id=first["project_id"]
            )

            self.assertEqual(first["revision"], 1)
            self.assertEqual(second["revision"], 2)
            self.assertEqual(first["project_id"], second["project_id"])
            self.assertEqual(len(store.list()), 2)
            self.assertEqual(store.get(first["id"])["payload"]["project"]["name"], "Untitled MSF Radome")
            self.assertEqual(store.get(second["id"])["payload"]["project"]["name"], "Updated name")


if __name__ == "__main__":
    unittest.main()
