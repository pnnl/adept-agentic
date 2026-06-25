"""Compensating Control Fingerprint Integrity — generic library module.

Provides Pydantic-based fingerprint tracking for false-positive suppression rules.
Each compensating control is anchored to a specific file + location + entity pattern,
with SHA-256 integrity hashes that detect when the underlying file changes.

This module contains the codebase-agnostic logic: data models, hash computation,
and validation. The CLI layer lives in scripts/release/compensating_controls.py.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


SCHEMA_VERSION = "2.0"
DEFAULT_EXPIRY_DAYS = 90


# ─── Pydantic Models ──────────────────────────────────────────────────────────


class LineRange(BaseModel):
    start: int
    end: int

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"


class CompensatingControlFingerprint(BaseModel):
    version: str = SCHEMA_VERSION
    control_id: str
    domain: Literal["D5", "D7", "D8"]
    rule_description: str
    file_path: str
    location: Union[LineRange, str]
    entity_pattern: str
    justification: str
    compensating_control: str = ""
    file_sha256: str
    fingerprint_hash: str
    accepted_by: str = ""
    accepted_date: date = Field(default_factory=date.today)
    expiration_date: date = Field(
        default_factory=lambda: date.today() + timedelta(days=DEFAULT_EXPIRY_DAYS)
    )
    status: Literal["active", "stale", "expired", "invalidated"] = "active"
    invalidation_reason: Optional[str] = None


class ControlManifest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    controls: list[CompensatingControlFingerprint] = []
    last_validated: Optional[date] = None


# ─── Hash Computation ─────────────────────────────────────────────────────────


def compute_file_sha256(file_path: Path) -> str:
    """SHA-256 of file contents."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_fingerprint_hash(
    file_path: str, location: str, entity_pattern: str, version: str = SCHEMA_VERSION
) -> str:
    """Deterministic composite hash of the suppression's identity tuple."""
    payload = f"{version}|{file_path}|{location}|{entity_pattern}"
    return hashlib.sha256(payload.encode()).hexdigest()


# ─── Validation ───────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    control_id: str
    status: Literal["active", "stale", "expired", "invalidated"]
    severity: Literal["OK", "WARNING", "CRITICAL"]
    reason: str


def validate_control(
    control: CompensatingControlFingerprint, repo_root: Path
) -> ValidationResult:
    """Validate a single control against the current codebase state."""
    file_path = repo_root / control.file_path

    if not file_path.exists():
        return ValidationResult(
            control.control_id, "invalidated", "CRITICAL",
            f"File no longer exists: {control.file_path}"
        )

    if control.expiration_date < date.today():
        return ValidationResult(
            control.control_id, "expired", "WARNING",
            f"Expired on {control.expiration_date}"
        )

    current_hash = compute_file_sha256(file_path)
    if current_hash != control.file_sha256:
        return ValidationResult(
            control.control_id, "stale", "CRITICAL",
            f"File modified (hash mismatch). "
            f"Stored: {control.file_sha256[:12]}... "
            f"Current: {current_hash[:12]}..."
        )

    if isinstance(control.location, LineRange):
        try:
            lines = file_path.read_text().splitlines()
            start_idx = max(0, control.location.start - 1)
            end_idx = min(len(lines), control.location.end)
            region = "\n".join(lines[start_idx:end_idx])
            if control.entity_pattern not in region:
                return ValidationResult(
                    control.control_id, "invalidated", "CRITICAL",
                    f"Entity pattern '{control.entity_pattern}' "
                    f"no longer found at lines {control.location.start}-{control.location.end}"
                )
        except OSError as e:
            return ValidationResult(
                control.control_id, "invalidated", "CRITICAL",
                f"Cannot read file: {e}"
            )

    return ValidationResult(control.control_id, "active", "OK", "All checks passed")


def validate_all(
    manifest_path: Path,
    repo_root: Path,
) -> list[ValidationResult]:
    """Validate all controls in a manifest file."""
    manifest = load_manifest(manifest_path)
    if manifest is None:
        return []
    return [validate_control(c, repo_root) for c in manifest.controls]


# ─── Manifest I/O ─────────────────────────────────────────────────────────────


def load_manifest(manifest_path: Path) -> Optional[ControlManifest]:
    """Load and parse a manifest.json file."""
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text())
        return ControlManifest.model_validate(data)
    except (json.JSONDecodeError, Exception):
        return None


def save_manifest(manifest: ControlManifest, manifest_path: Path):
    """Write manifest to disk."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, default=str) + "\n"
    )


# ─── ID Generation ────────────────────────────────────────────────────────────


def next_control_id(manifest: ControlManifest, domain: str) -> str:
    """Generate the next sequential control ID for a domain."""
    domain_prefix = domain.replace("D", "")
    existing = [
        c.control_id for c in manifest.controls
        if c.control_id.startswith(f"D{domain_prefix}-")
    ]
    if not existing:
        return f"{domain}-001"
    max_num = max(int(cid.split("-")[-1]) for cid in existing)
    return f"{domain}-{max_num + 1:03d}"
