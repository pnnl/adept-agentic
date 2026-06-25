"""
ASOPB Evidence Store

SQLite-backed persistent storage for evaluation reports, evidence bundles,
version history, and longitudinal analysis of framework security posture.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from asopb.models import EvaluationReport, FrameworkVersion


class EvidenceStore:
    """SQLite-backed evidence store for ASOPB evaluations.

    Stores evaluation reports, evidence, version history, and supports
    integrity verification and delta analysis.

    Schema:
        evaluations:
            id TEXT PRIMARY KEY
            framework_version_key TEXT
            timestamp DATETIME
            aspi REAL
            report_hash TEXT
            report_json TEXT

        evidence:
            id TEXT PRIMARY KEY
            evaluation_id TEXT FOREIGN KEY
            domain_id TEXT
            control_id TEXT
            tier TEXT
            source TEXT
            evidence_hash TEXT
            description TEXT
            file_path TEXT
            raw_data TEXT
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize the evidence store.

        Args:
            db_path: Path to SQLite database file. None means in-memory.
        """
        if db_path is None:
            self.db_path = ":memory:"
        else:
            self.db_path = str(db_path)

        self.conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                framework_version_key TEXT NOT NULL,
                framework_name TEXT,
                timestamp DATETIME NOT NULL,
                aspi REAL,
                report_hash TEXT,
                report_json TEXT NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL,
                domain_id TEXT,
                control_id TEXT,
                tier TEXT,
                source TEXT,
                evidence_hash TEXT,
                description TEXT,
                file_path TEXT,
                raw_data TEXT,
                FOREIGN KEY (evaluation_id) REFERENCES evaluations(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_evidence_eval
            ON evidence(evaluation_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_evidence_hash
            ON evidence(evidence_hash)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_eval_framework
            ON evaluations(framework_version_key)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_eval_timestamp
            ON evaluations(timestamp)
            """
        )

        conn.commit()

    def save_evaluation(self, report: EvaluationReport) -> None:
        """Save an evaluation report to the store.

        Args:
            report: EvaluationReport to persist
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        framework_key = report.framework.version_key
        report_json = report.model_dump_json()

        cursor.execute(
            """
            INSERT OR REPLACE INTO evaluations
            (id, framework_version_key, framework_name, timestamp, aspi, report_hash, report_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.report_id,
                framework_key,
                report.framework.name,
                report.timestamp.isoformat(),
                report.aspi,
                report.report_hash,
                report_json,
            ),
        )

        # Store evidence items
        for domain_id, domain in report.domains.items():
            for control in domain.controls:
                for evidence in control.evidence:
                    evidence_id = f"{report.report_id}:{domain_id}:{control.control_id}:{evidence.evidence_hash}"
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO evidence
                        (id, evaluation_id, domain_id, control_id, tier, source, evidence_hash, description, file_path, raw_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            evidence_id,
                            report.report_id,
                            domain_id,
                            control.control_id,
                            evidence.tier.value,
                            evidence.source.value,
                            evidence.evidence_hash,
                            evidence.description,
                            evidence.file_path,
                            json.dumps(evidence.raw_data)
                            if evidence.raw_data
                            else None,
                        ),
                    )

        conn.commit()

    def load_evaluation(self, report_id: str) -> Optional[EvaluationReport]:
        """Load an evaluation report by ID.

        Args:
            report_id: Report identifier

        Returns:
            EvaluationReport or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT report_json FROM evaluations WHERE id = ?",
            (report_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return EvaluationReport.model_validate_json(row["report_json"])

    def list_evaluations(self, framework_name: str) -> list[dict[str, Any]]:
        """List all evaluations for a framework.

        Args:
            framework_name: Framework name to filter by

        Returns:
            List of evaluation metadata dicts with keys:
                id, timestamp, aspi, report_hash
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, timestamp, aspi, report_hash
            FROM evaluations
            WHERE framework_name = ?
            ORDER BY timestamp DESC
            """,
            (framework_name,),
        )

        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "aspi": row["aspi"],
                "report_hash": row["report_hash"],
            }
            for row in cursor.fetchall()
        ]

    def get_history(self, framework_name: str) -> list[tuple[str, float, str]]:
        """Get version history (version_key, aspi, timestamp).

        Args:
            framework_name: Framework name to filter by

        Returns:
            List of (framework_version_key, aspi, timestamp) tuples,
            ordered by timestamp ascending
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT DISTINCT framework_version_key, aspi, timestamp
            FROM evaluations
            WHERE framework_name = ?
            ORDER BY timestamp ASC
            """,
            (framework_name,),
        )

        return [
            (row["framework_version_key"], row["aspi"], row["timestamp"])
            for row in cursor.fetchall()
        ]

    def check_duplicate(self, evidence_hash: str) -> bool:
        """Check if evidence with given hash already exists.

        Args:
            evidence_hash: Evidence hash to check

        Returns:
            True if evidence exists, False otherwise
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM evidence WHERE evidence_hash = ? LIMIT 1",
            (evidence_hash,),
        )

        return cursor.fetchone() is not None

    def verify_report_integrity(self, report_id: str) -> bool:
        """Verify report integrity via hash.

        Re-computes the report hash and compares against stored hash.

        Args:
            report_id: Report identifier

        Returns:
            True if hash matches, False if mismatch or report not found
        """
        report = self.load_evaluation(report_id)
        if report is None:
            return False

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT report_hash FROM evaluations WHERE id = ?",
            (report_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return False

        stored_hash = row["report_hash"]
        computed_hash = report.report_hash

        return stored_hash == computed_hash

    def get_version_delta(
        self, version_a: str, version_b: str
    ) -> dict[str, Any]:
        """Get delta between two framework versions.

        Compares the latest evaluation for each version.

        Args:
            version_a: First framework version key
            version_b: Second framework version key

        Returns:
            Dict with:
                {
                    "version_a": str,
                    "version_b": str,
                    "report_a_id": str | None,
                    "report_b_id": str | None,
                    "aspi_delta": float | None,
                    "report_a_hash": str | None,
                    "report_b_hash": str | None,
                }
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get latest for version_a
        cursor.execute(
            """
            SELECT id, aspi, report_hash, timestamp
            FROM evaluations
            WHERE framework_version_key = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (version_a,),
        )
        row_a = cursor.fetchone()

        # Get latest for version_b
        cursor.execute(
            """
            SELECT id, aspi, report_hash, timestamp
            FROM evaluations
            WHERE framework_version_key = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (version_b,),
        )
        row_b = cursor.fetchone()

        aspi_a = row_a["aspi"] if row_a else None
        aspi_b = row_b["aspi"] if row_b else None
        aspi_delta = None
        if aspi_a is not None and aspi_b is not None:
            aspi_delta = round(aspi_b - aspi_a, 1)

        return {
            "version_a": version_a,
            "version_b": version_b,
            "report_a_id": row_a["id"] if row_a else None,
            "report_b_id": row_b["id"] if row_b else None,
            "aspi_delta": aspi_delta,
            "report_a_hash": row_a["report_hash"] if row_a else None,
            "report_b_hash": row_b["report_hash"] if row_b else None,
        }

    def close(self) -> None:
        """Close database connection."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> EvidenceStore:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
