from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  kind TEXT NOT NULL,
                  status TEXT NOT NULL,
                  request_json TEXT NOT NULL,
                  result_json TEXT,
                  error_text TEXT,
                  attempts INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  started_at TEXT,
                  finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS job_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  job_id TEXT NOT NULL,
                  level TEXT NOT NULL,
                  message TEXT NOT NULL,
                  data_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(job_id) REFERENCES jobs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at ON jobs(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id, id);
                """
            )

    def create_job(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, kind, status, request_json, created_at, updated_at)
                VALUES (?, ?, 'queued', ?, ?, ?)
                """,
                (job_id, kind, json.dumps(payload), now, now),
            )
        self.add_event(job_id, "info", "Job queued", {"kind": kind})
        return self.get_job(job_id)

    def add_event(self, job_id: str, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO job_events (job_id, level, message, data_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, level, message, json.dumps(data) if data is not None else None, utc_now()),
            )

    def claim_next_job(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('queued', 'retry')
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            now = utc_now()
            conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, row["id"]),
            )
            return self.get_job(row["id"])

    def complete_job(self, job_id: str, result: dict[str, Any]) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'completed',
                    result_json = ?,
                    error_text = NULL,
                    updated_at = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (json.dumps(result), now, now, job_id),
            )
        self.add_event(job_id, "info", "Job completed")

    def fail_job(self, job_id: str, error_text: str) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error_text = ?,
                    updated_at = ?,
                    finished_at = ?
                WHERE id = ?
                """,
                (error_text, now, now, job_id),
            )
        self.add_event(job_id, "error", "Job failed", {"error": error_text})

    def retry_job(self, job_id: str) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'retry',
                    error_text = NULL,
                    result_json = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
        self.add_event(job_id, "info", "Job marked for retry")
        return self.get_job(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._job_row_to_dict(row) for row in rows]

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row["id"],
                    "job_id": row["job_id"],
                    "level": row["level"],
                    "message": row["message"],
                    "data": json.loads(row["data_json"]) if row["data_json"] else None,
                    "created_at": row["created_at"],
                }
            )
        return out

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return self._job_row_to_dict(row)

    def _job_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "request": json.loads(row["request_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error_text": row["error_text"],
            "attempts": row["attempts"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

