"""
ASOPB Analyzers Layer (Layer 2)

External security tool runners that parse results into structured ScanFinding objects.
Includes SAST (Semgrep), Python security (Bandit), dependency scanning (pip-audit),
Git repository analysis (GitXRay), and custom domain-specific analyzers.
"""

from __future__ import annotations

from asopb.analyzers.bandit import BanditAnalyzer
from asopb.analyzers.base import AnalyzerBase
from asopb.analyzers.dockerfile import DockerfileAnalyzer
from asopb.analyzers.gitxray import GitXRayAnalyzer
from asopb.analyzers.pip_audit import PipAuditAnalyzer
from asopb.analyzers.registry import AnalyzerRegistry
from asopb.analyzers.semgrep import SemgrepAnalyzer
from asopb.analyzers.tls import TLSAnalyzer

__all__ = [
    "AnalyzerBase",
    "GitXRayAnalyzer",
    "SemgrepAnalyzer",
    "BanditAnalyzer",
    "PipAuditAnalyzer",
    "DockerfileAnalyzer",
    "TLSAnalyzer",
    "AnalyzerRegistry",
]
