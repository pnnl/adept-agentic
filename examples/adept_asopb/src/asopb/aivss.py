"""
OWASP AIVSS (AI Vulnerability Scoring System) v0.8 Integration

Extends CVSS v4.0 with Agentic Risk Amplification Factors (AARFs) to
produce contextualised vulnerability scores for agentic AI systems.

Formula:  AIVSS = ((CVSS_Base + AARS) / 2) × ThM
          where  AARS  = Σ(AARF_i)      — sum of 10 amplification factors
                 ThM   = threat multiplier (exploit maturity)

Each AARF is scored on a three‑point scale:  0.0 | 0.5 | 1.0

Reference:  OWASP AIVSS v0.8  (March 19, 2026)
            https://aivss.owasp.org/
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field, model_validator

from asopb.logging import get_logger
from asopb.models import ScanFinding, ScanResult, Severity

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AARFLevel(float, Enum):
    """Three‑point scale for each Agentic Risk Amplification Factor."""
    NONE = 0.0
    PARTIAL = 0.5
    FULL = 1.0


class ExploitMaturity(float, Enum):
    """CVSS v4 Exploit Maturity mapped to AIVSS Threat Multiplier."""
    NOT_DEFINED = 1.0
    UNREPORTED = 0.91
    PROOF_OF_CONCEPT = 0.94
    ATTACKED = 1.0


class AARFCategory(str, Enum):
    """The ten Agentic Risk Amplification Factors from AIVSS v0.8."""
    AUTONOMY_LEVEL = "autonomy_level"
    TOOL_USE_SCOPE = "tool_use_scope"
    MULTI_AGENT = "multi_agent_interactions"
    NON_DETERMINISM = "non_determinism"
    SELF_MODIFICATION = "self_modification"
    DATA_SENSITIVITY = "data_sensitivity"
    PERSISTENCE = "persistence"
    PRIVILEGE_LEVEL = "privilege_level"
    BLAST_RADIUS = "blast_radius"
    RECOVERY_COMPLEXITY = "recovery_complexity"


# ASOPB domain crosswalk — which domain does each AARF primarily affect?
AARF_DOMAIN_CROSSWALK: dict[AARFCategory, tuple[str, Optional[str]]] = {
    AARFCategory.AUTONOMY_LEVEL:      ("D1", "D3"),
    AARFCategory.TOOL_USE_SCOPE:      ("D3", None),
    AARFCategory.MULTI_AGENT:         ("D5", "D2"),
    AARFCategory.NON_DETERMINISM:     ("D1", "D6"),
    AARFCategory.SELF_MODIFICATION:   ("D1", None),
    AARFCategory.DATA_SENSITIVITY:    ("D4", "D6"),
    AARFCategory.PERSISTENCE:         ("D2", "D6"),
    AARFCategory.PRIVILEGE_LEVEL:     ("D3", "D4"),
    AARFCategory.BLAST_RADIUS:        ("D8", "D5"),
    AARFCategory.RECOVERY_COMPLEXITY: ("D8", "D6"),
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class AARFAssessment(BaseModel):
    """Assessment of a single Agentic Risk Amplification Factor."""
    category: AARFCategory
    level: AARFLevel
    rationale: str = ""
    evidence_refs: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def score(self) -> float:
        return float(self.level.value)


class AgentProfile(BaseModel):
    """Characterisation of an agentic system's architecture, auto‑derived
    from ASOPB scanner results.  Each field maps to one or more AARFs.

    The profile can be constructed manually, or via
    ``AgentProfileBuilder.from_scan_results()``.
    """
    # Metadata
    framework_name: str = ""
    service_count: int = 1

    # AARF‑relevant characteristics
    autonomous_decisions: bool = False        # AARF 1
    tool_count: int = 0                       # AARF 2
    multi_agent: bool = False                 # AARF 3
    llm_backed: bool = True                   # AARF 4  (non‑determinism)
    self_modifying: bool = False              # AARF 5
    handles_pii: bool = False                 # AARF 6
    handles_secrets: bool = False             # AARF 6
    stateful: bool = False                    # AARF 7
    docker_socket: bool = False               # AARF 8
    privileged_containers: bool = False       # AARF 8
    host_network: bool = False                # AARF 8
    env_var_secrets: bool = False             # AARF 8
    shared_dependency_ratio: float = 0.0      # AARF 9  (fraction of services sharing critical dep)
    requires_host_remediation: bool = False   # AARF 10

    def assess_aarfs(self) -> list[AARFAssessment]:
        """Derive the 10 AARF assessments from the profile."""
        assessments: list[AARFAssessment] = []

        # 1. Autonomy Level
        if self.autonomous_decisions:
            lvl = AARFLevel.FULL
            rat = "System makes autonomous decisions without human gates"
        else:
            lvl = AARFLevel.PARTIAL if self.llm_backed else AARFLevel.NONE
            rat = "LLM‑backed but human‑in‑the‑loop" if self.llm_backed else "No autonomous capability"
        assessments.append(AARFAssessment(
            category=AARFCategory.AUTONOMY_LEVEL, level=lvl, rationale=rat,
        ))

        # 2. Tool Use Scope
        if self.tool_count >= 20:
            lvl, rat = AARFLevel.FULL, f"{self.tool_count} tools registered — broad scope"
        elif self.tool_count >= 5:
            lvl, rat = AARFLevel.PARTIAL, f"{self.tool_count} tools registered — moderate scope"
        else:
            lvl, rat = AARFLevel.NONE, f"{self.tool_count} tools — minimal scope"
        assessments.append(AARFAssessment(
            category=AARFCategory.TOOL_USE_SCOPE, level=lvl, rationale=rat,
        ))

        # 3. Multi‑Agent Interactions
        if self.multi_agent and self.service_count > 5:
            lvl, rat = AARFLevel.FULL, f"Multi‑agent with {self.service_count} services"
        elif self.multi_agent:
            lvl, rat = AARFLevel.PARTIAL, "Multi‑agent with limited services"
        else:
            lvl, rat = AARFLevel.NONE, "Single‑agent architecture"
        assessments.append(AARFAssessment(
            category=AARFCategory.MULTI_AGENT, level=lvl, rationale=rat,
        ))

        # 4. Non‑Determinism
        if self.llm_backed:
            lvl, rat = AARFLevel.PARTIAL, "LLM outputs are inherently non‑deterministic"
        else:
            lvl, rat = AARFLevel.NONE, "Deterministic pipeline"
        assessments.append(AARFAssessment(
            category=AARFCategory.NON_DETERMINISM, level=lvl, rationale=rat,
        ))

        # 5. Self‑Modification
        if self.self_modifying:
            lvl, rat = AARFLevel.FULL, "System can modify its own code or prompts"
        else:
            lvl, rat = AARFLevel.NONE, "No self‑modification capability"
        assessments.append(AARFAssessment(
            category=AARFCategory.SELF_MODIFICATION, level=lvl, rationale=rat,
        ))

        # 6. Data Sensitivity
        if self.handles_secrets and self.handles_pii:
            lvl, rat = AARFLevel.FULL, "Handles both PII and secrets/credentials"
        elif self.handles_secrets or self.handles_pii:
            lvl, rat = AARFLevel.PARTIAL, "Handles secrets or PII"
        else:
            lvl, rat = AARFLevel.NONE, "No sensitive data handled"
        assessments.append(AARFAssessment(
            category=AARFCategory.DATA_SENSITIVITY, level=lvl, rationale=rat,
        ))

        # 7. Persistence
        if self.stateful:
            lvl, rat = AARFLevel.PARTIAL, "Stateful sessions/caching"
        else:
            lvl, rat = AARFLevel.NONE, "Stateless operation"
        assessments.append(AARFAssessment(
            category=AARFCategory.PERSISTENCE, level=lvl, rationale=rat,
        ))

        # 8. Privilege Level
        if self.docker_socket or self.privileged_containers:
            lvl, rat = AARFLevel.FULL, "Docker socket or privileged containers"
        elif self.host_network or self.env_var_secrets:
            lvl, rat = AARFLevel.PARTIAL, "Host network or env‑var secrets"
        else:
            lvl, rat = AARFLevel.NONE, "Least‑privilege deployment"
        assessments.append(AARFAssessment(
            category=AARFCategory.PRIVILEGE_LEVEL, level=lvl, rationale=rat,
        ))

        # 9. Blast Radius
        if self.shared_dependency_ratio >= 0.8:
            lvl = AARFLevel.FULL
            rat = f"Critical dependency shared by {self.shared_dependency_ratio*100:.0f}% of services"
        elif self.shared_dependency_ratio >= 0.4:
            lvl = AARFLevel.PARTIAL
            rat = f"Dependency shared by {self.shared_dependency_ratio*100:.0f}% of services"
        else:
            lvl = AARFLevel.NONE
            rat = "Dependencies are well‑isolated"
        assessments.append(AARFAssessment(
            category=AARFCategory.BLAST_RADIUS, level=lvl, rationale=rat,
        ))

        # 10. Recovery Complexity
        if self.requires_host_remediation:
            lvl, rat = AARFLevel.FULL, "Compromise requires host‑level remediation"
        elif self.docker_socket:
            lvl, rat = AARFLevel.PARTIAL, "Docker socket could enable host persistence"
        else:
            lvl, rat = AARFLevel.NONE, "Container rebuild sufficient for recovery"
        assessments.append(AARFAssessment(
            category=AARFCategory.RECOVERY_COMPLEXITY, level=lvl, rationale=rat,
        ))

        return assessments


class AIVSSScore(BaseModel):
    """Result of an AIVSS v0.8 calculation for a single finding."""
    # Inputs
    finding_id: str = ""
    finding_description: str = ""
    cvss_base: float = Field(ge=0.0, le=10.0)
    cvss_severity: Optional[Severity] = None

    # AARF breakdown
    aarfs: list[AARFAssessment] = Field(default_factory=list)

    # Threat multiplier
    threat_multiplier: float = Field(ge=0.0, le=1.0, default=1.0)

    @computed_field
    @property
    def aars(self) -> float:
        """Agentic AI Risk Score — sum of all AARF scores."""
        return sum(a.score for a in self.aarfs)

    @computed_field
    @property
    def aivss_score(self) -> float:
        """AIVSS = ((CVSS_Base + AARS) / 2) × ThM, clamped to [0, 10]."""
        raw = ((self.cvss_base + self.aars) / 2.0) * self.threat_multiplier
        return round(min(max(raw, 0.0), 10.0), 1)

    @computed_field
    @property
    def aivss_severity(self) -> Severity:
        """Map AIVSS score to severity label."""
        s = self.aivss_score
        if s >= 9.0:
            return Severity.CRITICAL
        elif s >= 7.0:
            return Severity.HIGH
        elif s >= 4.0:
            return Severity.MEDIUM
        elif s >= 0.1:
            return Severity.LOW
        else:
            return Severity.INFORMATIONAL

    @computed_field
    @property
    def amplification_delta(self) -> float:
        """How much the agentic context changes the score vs raw CVSS."""
        return round(self.aivss_score - self.cvss_base, 1)

    @computed_field
    @property
    def primary_domain(self) -> str:
        """The ASOPB domain most affected by the highest‑scoring AARF."""
        if not self.aarfs:
            return "D8"
        top = max(self.aarfs, key=lambda a: a.score)
        crosswalk = AARF_DOMAIN_CROSSWALK.get(top.category, ("D8", None))
        return crosswalk[0]


class AIVSSReport(BaseModel):
    """Collection of AIVSS scores for all findings in an evaluation."""
    framework_name: str = ""
    agent_profile: AgentProfile = Field(default_factory=AgentProfile)
    scores: list[AIVSSScore] = Field(default_factory=list)

    @computed_field
    @property
    def max_aivss(self) -> float:
        if not self.scores:
            return 0.0
        return max(s.aivss_score for s in self.scores)

    @computed_field
    @property
    def mean_aivss(self) -> float:
        if not self.scores:
            return 0.0
        return round(sum(s.aivss_score for s in self.scores) / len(self.scores), 1)

    @computed_field
    @property
    def critical_count(self) -> int:
        return sum(1 for s in self.scores if s.aivss_severity == Severity.CRITICAL)

    @computed_field
    @property
    def high_count(self) -> int:
        return sum(1 for s in self.scores if s.aivss_severity == Severity.HIGH)

    def domain_impact_summary(self) -> dict[str, list[AIVSSScore]]:
        """Group scores by their primary ASOPB domain impact."""
        result: dict[str, list[AIVSSScore]] = {}
        for s in self.scores:
            domain = s.primary_domain
            result.setdefault(domain, []).append(s)
        return result


# ---------------------------------------------------------------------------
# Agent Profile Builder
# ---------------------------------------------------------------------------

class AgentProfileBuilder:
    """Construct an AgentProfile from ASOPB scanner/analyzer results.

    This bridges the ASOPB scanner layer to the AIVSS scoring layer by
    deriving agentic characteristics from concrete code evidence.
    """

    @staticmethod
    def from_scan_results(
        scan_results: dict[str, ScanResult],
        analyzer_results: Optional[dict[str, ScanResult]] = None,
        framework_name: str = "",
    ) -> AgentProfile:
        """Build profile from scanner findings.

        Args:
            scan_results: Mapping of scanner_name → ScanResult
            analyzer_results: Mapping of analyzer_name → ScanResult
            framework_name: Name of the framework being evaluated

        Returns:
            Populated AgentProfile
        """
        analyzer_results = analyzer_results or {}
        all_results = {**scan_results, **analyzer_results}

        profile = AgentProfile(framework_name=framework_name)

        # ---------------------------------------------------------------
        # Derive characteristics from scanner findings
        # ---------------------------------------------------------------

        # Tools scanner → tool_count, multi_agent
        tools_result = all_results.get("tools")
        if tools_result and tools_result.success:
            tool_findings = [
                f for f in tools_result.findings
                if f.category in ("mcp_tool_registration", "tool_registration")
            ]
            profile.tool_count = len(tool_findings)
            # Multi‑agent detection from tool/orchestration patterns
            multi_agent_findings = [
                f for f in tools_result.findings
                if "multi_agent" in f.category or "orchestrat" in f.message.lower()
            ]
            if multi_agent_findings:
                profile.multi_agent = True

        # Sandbox scanner → docker_socket, privileged_containers
        sandbox_result = all_results.get("sandbox")
        if sandbox_result and sandbox_result.success:
            for f in sandbox_result.findings:
                if "docker.sock" in f.message.lower() or "docker_socket" in f.category:
                    profile.docker_socket = True
                if "privileged" in f.message.lower():
                    profile.privileged_containers = True

        # Auth scanner → handles_secrets, env_var_secrets
        auth_result = all_results.get("auth")
        if auth_result and auth_result.success:
            for f in auth_result.findings:
                if any(kw in f.message.lower() for kw in ("secret", "token", "api_key", "credential")):
                    profile.handles_secrets = True
                if "optional" in f.category and "none" in f.message.lower():
                    profile.env_var_secrets = True

        # Supply chain scanner → shared_dependency_ratio, service_count
        supply_result = all_results.get("supply_chain")
        if supply_result and supply_result.success:
            stats = supply_result.summary_stats
            # Service count from stats if available
            if "service_count" in stats:
                profile.service_count = stats["service_count"]

        # Codebase scanner → autonomous_decisions, self_modifying, stateful
        codebase_result = all_results.get("codebase")
        if codebase_result and codebase_result.success:
            stats = codebase_result.summary_stats
            # Check for LLM framework presence
            if "frameworks" in stats:
                frameworks = stats["frameworks"]
                if isinstance(frameworks, list):
                    profile.llm_backed = any(
                        fw in str(frameworks).lower()
                        for fw in ("langchain", "litellm", "openai", "anthropic", "llama")
                    )

        # Dockerfile analyzer → host_network, privileged
        dockerfile_result = all_results.get("dockerfile")
        if dockerfile_result and dockerfile_result.success:
            for f in dockerfile_result.findings:
                if "host_network" in f.category or "hostNetwork" in f.message:
                    profile.host_network = True
                if "privileged" in f.category:
                    profile.privileged_containers = True
                if "docker.sock" in f.message:
                    profile.docker_socket = True

        # Observability scanner → stateful detection
        obs_result = all_results.get("observability")
        if obs_result and obs_result.success:
            for f in obs_result.findings:
                if any(kw in f.message.lower() for kw in ("session", "state", "cache", "redis")):
                    profile.stateful = True

        return profile


# ---------------------------------------------------------------------------
# AIVSS Calculator
# ---------------------------------------------------------------------------

class AIVSSCalculator:
    """Calculate OWASP AIVSS v0.8 scores for vulnerability findings
    in the context of an agentic system.

    Typical usage::

        profile = AgentProfileBuilder.from_scan_results(scan_results)
        calculator = AIVSSCalculator(profile)

        # Score individual findings
        score = calculator.score_finding(
            finding_id="CVE-2026-1234",
            cvss_base=9.8,
            description="RCE via malicious package",
            exploit_maturity=ExploitMaturity.ATTACKED,
        )

        # Score all findings from pip‑audit / Bandit / Semgrep
        report = calculator.score_all_findings(analyzer_results)
    """

    def __init__(self, agent_profile: AgentProfile):
        self.profile = agent_profile
        self._aarfs = agent_profile.assess_aarfs()

    def score_finding(
        self,
        finding_id: str = "",
        description: str = "",
        cvss_base: float = 5.0,
        cvss_severity: Optional[Severity] = None,
        exploit_maturity: ExploitMaturity = ExploitMaturity.NOT_DEFINED,
    ) -> AIVSSScore:
        """Compute AIVSS score for a single finding.

        Args:
            finding_id: Identifier (e.g., CVE ID, finding hash)
            description: Human‑readable description
            cvss_base: CVSS v4.0 base score (0.0–10.0)
            cvss_severity: Optional CVSS severity label
            exploit_maturity: Current exploit maturity

        Returns:
            AIVSSScore with full AARF breakdown
        """
        return AIVSSScore(
            finding_id=finding_id,
            finding_description=description,
            cvss_base=cvss_base,
            cvss_severity=cvss_severity,
            aarfs=self._aarfs,
            threat_multiplier=float(exploit_maturity.value),
        )

    def score_all_findings(
        self,
        analyzer_results: dict[str, ScanResult],
        min_severity: Severity = Severity.MEDIUM,
    ) -> AIVSSReport:
        """Score all findings from analyzer results that meet min severity.

        Extracts CVSS scores from finding metadata where available,
        falls back to severity‑based estimates otherwise.

        Args:
            analyzer_results: Mapping of analyzer_name → ScanResult
            min_severity: Only score findings at or above this severity

        Returns:
            AIVSSReport with all scored findings
        """
        severity_order = {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1,
            Severity.INFORMATIONAL: 0,
        }
        min_level = severity_order.get(min_severity, 0)

        scores: list[AIVSSScore] = []

        for analyzer_name, result in analyzer_results.items():
            if not result.success:
                continue

            for finding in result.findings:
                finding_level = severity_order.get(finding.severity, 0)
                if finding_level < min_level:
                    continue

                # Extract CVSS from metadata or estimate from severity
                cvss_base = self._extract_cvss(finding)

                # Determine exploit maturity from metadata
                maturity = self._extract_maturity(finding)

                score = self.score_finding(
                    finding_id=finding.finding_id,
                    description=finding.message,
                    cvss_base=cvss_base,
                    cvss_severity=finding.severity,
                    exploit_maturity=maturity,
                )
                scores.append(score)

        return AIVSSReport(
            framework_name=self.profile.framework_name,
            agent_profile=self.profile,
            scores=scores,
        )

    @staticmethod
    def _extract_cvss(finding: ScanFinding) -> float:
        """Extract CVSS base score from finding metadata.

        Falls back to severity‑based estimate if not present.
        """
        meta = finding.metadata or {}

        # Try direct CVSS fields
        for key in ("cvss", "cvss_base", "cvss_score", "cvssScore", "base_score"):
            if key in meta:
                try:
                    return float(meta[key])
                except (ValueError, TypeError):
                    continue

        # Fall back to severity estimate
        severity_map = {
            Severity.CRITICAL: 9.5,
            Severity.HIGH: 7.5,
            Severity.MEDIUM: 5.0,
            Severity.LOW: 3.0,
            Severity.INFORMATIONAL: 1.0,
        }
        return severity_map.get(finding.severity, 5.0)

    @staticmethod
    def _extract_maturity(finding: ScanFinding) -> ExploitMaturity:
        """Extract exploit maturity from finding metadata."""
        meta = finding.metadata or {}
        maturity_str = str(meta.get("exploit_maturity", "")).lower()

        if "attacked" in maturity_str or "active" in maturity_str:
            return ExploitMaturity.ATTACKED
        elif "poc" in maturity_str or "proof" in maturity_str:
            return ExploitMaturity.PROOF_OF_CONCEPT
        elif "unreported" in maturity_str:
            return ExploitMaturity.UNREPORTED

        return ExploitMaturity.NOT_DEFINED
