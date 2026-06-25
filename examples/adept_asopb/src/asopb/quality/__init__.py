"""ASOPB Quality Tools — codebase-agnostic utilities for release quality gates."""

from asopb.quality.allowlist import (
    SCHEMA_VERSION as ALLOWLIST_SCHEMA_VERSION,
    Allowlist,
    AllowlistCategory,
    AllowlistRule,
    MatchResult,
    ValidationIssue,
    compute_allowlist_hash,
    load_allowlist,
    matches_finding,
    validate_allowlist,
)
from asopb.quality.compensating_controls import (
    CompensatingControlFingerprint,
    ControlManifest,
    LineRange,
    ValidationResult,
    compute_file_sha256,
    compute_fingerprint_hash,
    next_control_id,
    validate_control,
    validate_all,
    load_manifest,
    save_manifest,
)
from asopb.quality.dead_imports import (
    ParsedImport,
    ImportClassification,
    ScanResult,
    collect_unused_imports,
    classify_import,
    format_json,
    format_text,
    run_analysis,
)

__all__ = [
    # Allowlist
    "ALLOWLIST_SCHEMA_VERSION",
    "Allowlist",
    "AllowlistCategory",
    "AllowlistRule",
    "MatchResult",
    "ValidationIssue",
    "compute_allowlist_hash",
    "load_allowlist",
    "matches_finding",
    "validate_allowlist",
    # Compensating controls
    "CompensatingControlFingerprint",
    "ControlManifest",
    "LineRange",
    "ValidationResult",
    "compute_file_sha256",
    "compute_fingerprint_hash",
    "next_control_id",
    "validate_control",
    "validate_all",
    "load_manifest",
    "save_manifest",
    # Dead imports
    "ParsedImport",
    "ImportClassification",
    "ScanResult",
    "collect_unused_imports",
    "classify_import",
    "format_json",
    "format_text",
    "run_analysis",
]
