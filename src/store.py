"""SQLite persistence for revisioned estimates."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class EstimateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS estimates (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    customer TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, revision)
                );
                CREATE INDEX IF NOT EXISTS idx_estimates_project
                    ON estimates(project_id, revision DESC);
                """
            )

    def save(
        self,
        payload: dict[str, Any],
        results: dict[str, Any],
        project_id: str | None = None,
    ) -> dict[str, Any]:
        project_id = project_id or str(uuid.uuid4())
        record_id = str(uuid.uuid4())
        project = payload.get("project", {}) if isinstance(payload, dict) else {}
        name = str(project.get("name") or "Untitled MSF Radome")
        customer = str(project.get("customer") or "")
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 AS revision "
                "FROM estimates WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            revision = int(row["revision"])
            connection.execute(
                """
                INSERT INTO estimates (
                    id, project_id, revision, name, customer,
                    payload_json, results_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    project_id,
                    revision,
                    name,
                    customer,
                    json.dumps(payload, separators=(",", ":")),
                    json.dumps(results, separators=(",", ":")),
                    created_at,
                ),
            )
        return {
            "id": record_id,
            "project_id": project_id,
            "revision": revision,
            "name": name,
            "customer": customer,
            "created_at": created_at,
        }

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 500)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, project_id, revision, name, customer, created_at
                FROM estimates
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, record_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM estimates WHERE id = ?", (record_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "revision": row["revision"],
            "name": row["name"],
            "customer": row["customer"],
            "payload": json.loads(row["payload_json"]),
            "results": json.loads(row["results_json"]),
            "created_at": row["created_at"],
        }
