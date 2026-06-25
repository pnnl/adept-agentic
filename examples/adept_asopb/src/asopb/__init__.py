"""
ASOPB: Agentic Security and Operations Performance Benchmark

A comprehensive evaluation framework for assessing the security posture of agentic systems.
"""

from __future__ import annotations
from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("asopb")
__author__ = "ASOPB Team"

# Configuration
from asopb.config import (
    EvalConfig,
    LLMConfig,
    AnalyzerConfig,
    ScoringConfig,
    EvidenceStoreConfig,
    RedTeamConfig,
)

# Models
from asopb.models import (
    EvaluationReport,
    DomainResult,
    ControlScore,
    ControlDefinition,
    ControlEvidence,
    ControlStatus,
    Applicability,
    EvidenceTier,
    EvidenceSource,
    Severity,
    ScanResult,
    ScanFinding,
    RedTeamReport,
    RedTeamScenario,
    FrameworkVersion,
)

# Evaluator
from asopb.evaluator import (
    Evaluator,
    ASPICalculator,
    FrameworkVersionDetector,
)

# Domain base
from asopb.domains.base import DomainEvaluator

# AIVSS integration
from asopb.aivss import (
    AIVSSCalculator,
    AIVSSScore,
    AIVSSReport,
    AgentProfile,
    AgentProfileBuilder,
    AARFAssessment,
    AARFCategory,
    AARFLevel,
    ExploitMaturity,
)

# Evidence store (SQLite-backed)
try:
    from asopb.evidence_store import EvidenceStore
except ImportError:
    EvidenceStore = None


__all__ = [
    # Core
    "Evaluator",
    "EvalConfig",
    "EvaluationReport",

    # Models
    "DomainResult",
    "ControlScore",
    "ControlDefinition",
    "ControlEvidence",
    "ControlStatus",
    "Applicability",
    "EvidenceTier",
    "EvidenceSource",
    "Severity",
    "ScanResult",
    "ScanFinding",
    "RedTeamReport",
    "RedTeamScenario",
    "FrameworkVersion",

    # Configuration
    "LLMConfig",
    "AnalyzerConfig",
    "ScoringConfig",
    "EvidenceStoreConfig",
    "RedTeamConfig",

    # AIVSS
    "AIVSSCalculator",
    "AIVSSScore",
    "AIVSSReport",
    "AgentProfile",
    "AgentProfileBuilder",
    "AARFAssessment",
    "AARFCategory",
    "AARFLevel",
    "ExploitMaturity",

    # Utilities
    "ASPICalculator",
    "FrameworkVersionDetector",
    "DomainEvaluator",
    "EvidenceStore",
]
