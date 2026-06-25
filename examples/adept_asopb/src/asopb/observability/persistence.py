"""SQLite persistence layer for token utilization trend data."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import UtilizationReport

SCHEMA_VERSION = 1

_DEFAULT_DB_DIR = str(Path.home() / ".asopb" / "token_utilization.db")


def _resolve_db_path() -> str:
    return os.environ.get("ASOPB_TOKEN_DB", _DEFAULT_DB_DIR)

CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS token_utilization_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    backend TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    filters_json TEXT,
    cost_model TEXT,
    total_generations INTEGER,
    dast_probe_count INTEGER,
    regular_call_count INTEGER,
    dast_input_tokens INTEGER,
    dast_output_tokens INTEGER,
    dast_total_cost REAL,
    regular_input_tokens INTEGER,
    regular_output_tokens INTEGER,
    regular_total_cost REAL,
    total_cost REAL,
    report_json TEXT
);
"""

CREATE_DAILY_TABLE = """
CREATE TABLE IF NOT EXISTS token_utilization_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    date TEXT NOT NULL,
    model TEXT NOT NULL,
    count INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost REAL,
    FOREIGN KEY (run_id) REFERENCES token_utilization_runs(run_id)
);
"""

CREATE_DAILY_INDEX = """
CREATE INDEX IF NOT EXISTS idx_daily_run_id ON token_utilization_daily(run_id);
"""


class TokenUtilizationStore:
    """SQLite-backed persistence for token utilization reports.

    Stores each aggregation run with full report JSON and per-date/model
    breakdowns for trend analysis.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _resolve_db_path()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_RUNS_TABLE)
            conn.execute(CREATE_DAILY_TABLE)
            conn.execute(CREATE_DAILY_INDEX)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save_report(self, report: UtilizationReport) -> str:
        """Persist a report and return the generated run_id."""
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO token_utilization_runs
                   (run_id, schema_version, backend, generated_at, filters_json,
                    cost_model, total_generations, dast_probe_count, regular_call_count,
                    dast_input_tokens, dast_output_tokens, dast_total_cost,
                    regular_input_tokens, regular_output_tokens, regular_total_cost,
                    total_cost, report_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    SCHEMA_VERSION,
                    report.backend_name,
                    report.generated_at.isoformat(),
                    json.dumps(report.filters_applied.to_dict()) if report.filters_applied else None,
                    report.cost_model_name,
                    report.total_generations,
                    report.dast_probe_count,
                    report.regular_call_count,
                    report.dast_input_tokens,
                    report.dast_output_tokens,
                    report.dast_cost,
                    report.regular_input_tokens,
                    report.regular_output_tokens,
                    report.regular_cost,
                    report.total_cost,
                    report.to_json(),
                ),
            )

            # Insert daily breakdowns cross-referenced with model breakdowns
            for d in report.by_date:
                conn.execute(
                    """INSERT INTO token_utilization_daily
                       (run_id, date, model, count, input_tokens, output_tokens, cost)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, d.date, "all", d.count, d.input_tokens, d.output_tokens, d.cost),
                )

            for m in report.by_model:
                conn.execute(
                    """INSERT INTO token_utilization_daily
                       (run_id, date, model, count, input_tokens, output_tokens, cost)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, "all", m.model, m.count, m.input_tokens, m.output_tokens, m.cost),
                )

        return run_id

    def list_runs(self, limit: int = 20) -> list[dict]:
        """List recent aggregation runs."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT run_id, backend, generated_at, cost_model,
                          total_generations, dast_probe_count, total_cost
                   FROM token_utilization_runs
                   ORDER BY generated_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> Optional[dict]:
        """Get full report JSON for a specific run."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM token_utilization_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row:
            result = dict(row)
            if result.get("report_json"):
                result["report"] = json.loads(result["report_json"])
            return result
        return None

    def get_trends(self, last_n: int = 10) -> list[dict]:
        """Get cost trends across the last N runs."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT run_id, generated_at, backend, total_cost,
                          dast_total_cost, regular_total_cost,
                          dast_probe_count, total_generations
                   FROM token_utilization_runs
                   ORDER BY generated_at DESC
                   LIMIT ?""",
                (last_n,),
            ).fetchall()
        trends = [dict(r) for r in rows]
        trends.reverse()
        return trends

    def get_daily_breakdown(self, run_id: str) -> list[dict]:
        """Get per-date breakdown for a specific run."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT date, model, count, input_tokens, output_tokens, cost
                   FROM token_utilization_daily
                   WHERE run_id = ? AND date != 'all'
                   ORDER BY date""",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]
