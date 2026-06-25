"""
ASOPB Core Data Models

Pydantic models for the Agentic Security & Operations Performance Benchmark.
Supports version-tracked evaluations, evidence bundles, custom control definitions,
and STIG-style scoring with T1/T2/T3 evidence tiers.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EvidenceTier(str, Enum):
    """Three-tier evidence rubric per ASOPB Section 5.3."""
    T1_DESIGN = "T1"           # Architectural design evidence
    T2_IMPLEMENTATION = "T2"   # Deployed implementation evidence
    T3_ADVERSARIAL = "T3"      # Adversarial validation evidence


class Applicability(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "n/a"


class Severity(str, Enum):
    """STIG-style severity categorization for controls."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class EvidenceSource(str, Enum):
    """Where evidence originated."""
    SCANNER = "scanner"
    ANALYZER = "analyzer"
    LLM = "llm"
    RED_TEAM = "red_team"
    SIMULATOR = "simulator"
    MANUAL = "manual"


class ControlStatus(str, Enum):
    """STIG-inspired control compliance status."""
    NOT_APPLICABLE = "not_applicable"
    NOT_REVIEWED = "not_reviewed"
    NOT_A_FINDING = "not_a_finding"    # Control is properly implemented
    OPEN = "open"                       # Control gap exists
    PARTIALLY_IMPLEMENTED = "partial"   # Some evidence, incomplete


# ---------------------------------------------------------------------------
# Version Tracking
# ---------------------------------------------------------------------------

class FrameworkVersion(BaseModel):
    """Tracks the version/snapshot of the framework being evaluated.

    Supports both tagged releases and arbitrary git commits, enabling
    longitudinal analysis across the version history of a framework.
    """
    name: str                                    # e.g., "adept-agentic-framework-core"
    version: Optional[str] = None                # Semantic version if available
    git_commit: Optional[str] = None             # Full SHA
    git_branch: Optional[str] = None
    git_tag: Optional[str] = None
    snapshot_date: Optional[datetime] = None     # When the snapshot was taken
    source_url: Optional[str] = None             # Clone URL or download link
    source_hash: Optional[str] = None            # SHA-256 of the repo archive

    @computed_field
    @property
    def version_key(self) -> str:
        """Unique key for this framework version (for evidence store lookups)."""
        parts = [self.name]
        if self.git_commit:
            parts.append(self.git_commit[:12])
        elif self.version:
            parts.append(self.version)
        elif self.git_tag:
            parts.append(self.git_tag)
        else:
            parts.append(datetime.now(timezone.utc).strftime("%Y%m%d"))
        return ":".join(parts)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class ControlEvidence(BaseModel):
    """A single piece of evidence for or against a control.

    Evidence is collected by scanners, analyzers, LLM assessments,
    red-team reports, or manual annotation.  Each piece is hashed
    for integrity verification in the evidence store.
    """
    tier: EvidenceTier
    source: EvidenceSource
    source_tool: str                              # e.g., "scanner:auth", "analyzer:semgrep"
    file_path: Optional[str] = None               # Relative to repo root
    line_range: Optional[tuple[int, int]] = None
    description: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    raw_data: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @computed_field
    @property
    def evidence_hash(self) -> str:
        """CRC/SHA-256 hash of evidence content for deduplication and integrity."""
        content = json.dumps({
            "tier": self.tier.value,
            "source_tool": self.source_tool,
            "file_path": self.file_path,
            "line_range": self.line_range,
            "description": self.description,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Control Definitions (STIG-style, user-extensible)
# ---------------------------------------------------------------------------

class ControlDefinition(BaseModel):
    """Definition of a single ASOPB control.

    Controls can be loaded from built-in YAML or user-provided YAML files,
    enabling STIG-style customization of the evaluation framework.
    """
    control_id: str                        # e.g., "D4.1"
    domain_id: str                         # e.g., "D4"
    name: str                              # e.g., "Agent identity attestation"
    description: str                       # Full description of what the control requires
    severity: Severity = Severity.MEDIUM
    applicable_stages: list[str] = Field(default_factory=lambda: ["S1", "S2", "S3", "S4"])

    # Scoring guidance
    t1_criteria: list[str] = Field(default_factory=list)   # What qualifies for T1 credit
    t2_criteria: list[str] = Field(default_factory=list)   # What qualifies for T2 credit
    t3_criteria: list[str] = Field(default_factory=list)   # What qualifies for T3 credit

    # Scanner hints — what patterns indicate this control
    positive_patterns: list[str] = Field(default_factory=list)   # Regex patterns that indicate presence
    negative_patterns: list[str] = Field(default_factory=list)   # Regex patterns that indicate gaps
    required_files: list[str] = Field(default_factory=list)      # Glob patterns for expected files

    # Mapping to external standards
    nist_mapping: list[str] = Field(default_factory=list)        # e.g., ["AC-2", "IA-5"]
    owasp_mapping: list[str] = Field(default_factory=list)       # e.g., ["LLM01", "LLM05"]
    cwe_mapping: list[str] = Field(default_factory=list)         # e.g., ["CWE-287"]

    # User-extensible metadata
    tags: list[str] = Field(default_factory=list)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------

class ControlScore(BaseModel):
    """Score for a single ASOPB control within a domain."""
    control_id: str
    control_name: str
    status: ControlStatus = ControlStatus.NOT_REVIEWED

    t1_score: float = Field(ge=0, le=10, default=0.0)
    t2_score: float = Field(ge=0, le=10, default=0.0)
    t3_score: float = Field(ge=0, le=10, default=0.0)

    # Deterministic floor from scanners/analyzers (LLM cannot lower below this)
    t1_floor: float = Field(ge=0, le=10, default=0.0)
    t2_floor: float = Field(ge=0, le=10, default=0.0)

    evidence: list[ControlEvidence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    remediation: list[str] = Field(default_factory=list)
    notes: str = ""

    @computed_field
    @property
    def composite(self) -> float:
        """Average across all three tiers, scaled to 0–100."""
        return round((self.t1_score + self.t2_score + self.t3_score) / 3.0 * 10, 1)

    @model_validator(mode="after")
    def enforce_floor(self) -> "ControlScore":
        """LLM assessments cannot lower scores below the deterministic floor."""
        if self.t1_score < self.t1_floor:
            self.t1_score = self.t1_floor
        if self.t2_score < self.t2_floor:
            self.t2_score = self.t2_floor
        return self


class DomainResult(BaseModel):
    """Complete evaluation result for one ASOPB domain."""
    domain_id: str
    domain_name: str
    applicability: Applicability = Applicability.APPLICABLE
    weight: float = 1.0
    controls: list[ControlScore] = Field(default_factory=list)
    summary: str = ""       # LLM-generated narrative summary
    scan_metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def t1_aggregate(self) -> float:
        if not self.controls:
            return 0.0
        return round(sum(c.t1_score for c in self.controls) / len(self.controls), 2)

    @computed_field
    @property
    def t2_aggregate(self) -> float:
        if not self.controls:
            return 0.0
        return round(sum(c.t2_score for c in self.controls) / len(self.controls), 2)

    @computed_field
    @property
    def t3_aggregate(self) -> float:
        if not self.controls:
            return 0.0
        return round(sum(c.t3_score for c in self.controls) / len(self.controls), 2)

    @computed_field
    @property
    def domain_score(self) -> Optional[float]:
        """Domain score on 0–100 scale, or None if N/A."""
        if self.applicability == Applicability.NOT_APPLICABLE:
            return None
        if not self.controls:
            return 0.0
        raw = sum(c.composite for c in self.controls) / len(self.controls)
        return round(raw, 1)


# ---------------------------------------------------------------------------
# Scan/Analyzer Results
# ---------------------------------------------------------------------------

class ScanFinding(BaseModel):
    """A single finding from a scanner or analyzer."""
    finding_id: str
    category: str                       # e.g., "auth_module_present", "verify_false"
    severity: Severity = Severity.MEDIUM
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    line_range: Optional[tuple[int, int]] = None
    message: str
    snippet: Optional[str] = None       # Code snippet
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScanResult(BaseModel):
    """Output from a scanner or analyzer run."""
    tool_name: str
    tool_version: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    findings: list[ScanFinding] = Field(default_factory=list)
    summary_stats: dict[str, Any] = Field(default_factory=dict)
    raw_output: Optional[str] = None    # Full tool output for debugging

    @computed_field
    @property
    def finding_count(self) -> int:
        return len(self.findings)


# ---------------------------------------------------------------------------
# Red-Team / Simulator Plugin Results
# ---------------------------------------------------------------------------

class RedTeamScenario(BaseModel):
    """Result from a red-team exercise or automated attack simulation."""
    scenario_id: str                     # e.g., "RT-1"
    scenario_name: str                   # e.g., "Federated Prompt Injection"
    attack_vector: str
    target_domain: str                   # e.g., "D3", "D4"
    target_controls: list[str] = Field(default_factory=list)  # e.g., ["D3.2", "D3.5"]

    # Outcome
    outcome: str                         # "defense_held", "partial_bypass", "full_bypass"
    outcome_description: str
    severity: Severity = Severity.HIGH

    # Evidence
    evidence: list[ControlEvidence] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)   # Paths to attack logs, screenshots, etc.

    # Scoring impact
    t3_score_contribution: float = Field(ge=0, le=10, default=0.0)


class RedTeamReport(BaseModel):
    """Container for red-team or simulator results."""
    report_id: str
    source: str                         # Tool or team that produced this
    framework_version: FrameworkVersion
    scenarios: list[RedTeamScenario] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Top-Level Evaluation Report
# ---------------------------------------------------------------------------

class EvaluationReport(BaseModel):
    """Complete ASOPB evaluation report for a single framework version.

    This is the primary output artifact.  It contains all evidence,
    scores, and metadata needed for reproducibility and longitudinal
    comparison.
    """
    # Identity
    report_id: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("asopb-%Y%m%d-%H%M%S"))
    framework: FrameworkVersion
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    asopb_version: str = "1.0.0"

    # Configuration snapshot
    config_snapshot: dict[str, Any] = Field(default_factory=dict)

    # Layer results
    scan_results: dict[str, ScanResult] = Field(default_factory=dict)
    analyzer_results: dict[str, ScanResult] = Field(default_factory=dict)
    red_team_reports: list[RedTeamReport] = Field(default_factory=list)

    # Domain scores
    domains: dict[str, DomainResult] = Field(default_factory=dict)

    # AIVSS (populated if AIVSS scoring ran)
    aivss_summary: Optional[dict[str, Any]] = None

    # Metadata
    profile: Optional[str] = None
    scoring_mode: Optional[str] = None
    evaluation_duration_seconds: Optional[float] = None
    llm_calls_made: int = 0
    llm_tokens_used: int = 0
    analyzers_skipped: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def aspi(self) -> float:
        """Weighted Agentic Security Posture Index (0–100).

        ASPI = Σ(weight × domain_score) / Σ(weight)
        N/A domains excluded from both numerator and denominator.
        """
        numerator = 0.0
        denominator = 0.0
        for d in self.domains.values():
            if d.applicability == Applicability.NOT_APPLICABLE:
                continue
            score = d.domain_score
            if score is None:
                continue
            numerator += d.weight * score
            denominator += d.weight
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 1)

    @computed_field
    @property
    def t1_t2_gap_ratio(self) -> float:
        """Fraction of controls with T1 > 0 but T2 = 0.

        Higher ratio = more design claims without deployment evidence.
        """
        t1_positive = 0
        t1_only = 0
        for d in self.domains.values():
            if d.applicability == Applicability.NOT_APPLICABLE:
                continue
            for c in d.controls:
                if c.t1_score > 0:
                    t1_positive += 1
                    if c.t2_score == 0:
                        t1_only += 1
        if t1_positive == 0:
            return 0.0
        return round(t1_only / t1_positive, 3)

    @computed_field
    @property
    def report_hash(self) -> str:
        """SHA-256 hash of the full report for integrity verification."""
        content = self.model_dump_json(exclude={"report_hash"})
        return hashlib.sha256(content.encode()).hexdigest()[:20]

    def to_evidence_bundle(self, output_dir: Path) -> Path:
        """Export the complete report + evidence as a directory bundle."""
        bundle_dir = output_dir / self.report_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # Main report JSON
        report_path = bundle_dir / "report.json"
        report_path.write_text(self.model_dump_json(indent=2))

        # Per-domain evidence files
        evidence_dir = bundle_dir / "evidence"
        evidence_dir.mkdir(exist_ok=True)
        for domain_id, domain in self.domains.items():
            domain_file = evidence_dir / f"{domain_id}.json"
            domain_file.write_text(domain.model_dump_json(indent=2))

        # Scan results
        scans_dir = bundle_dir / "scans"
        scans_dir.mkdir(exist_ok=True)
        for name, result in {**self.scan_results, **self.analyzer_results}.items():
            scan_file = scans_dir / f"{name}.json"
            scan_file.write_text(result.model_dump_json(indent=2))

        # Red-team reports
        if self.red_team_reports:
            rt_dir = bundle_dir / "red_team"
            rt_dir.mkdir(exist_ok=True)
            for rt in self.red_team_reports:
                rt_file = rt_dir / f"{rt.report_id}.json"
                rt_file.write_text(rt.model_dump_json(indent=2))

        return bundle_dir
