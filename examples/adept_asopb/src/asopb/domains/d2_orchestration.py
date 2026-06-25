"""
D2: Orchestration Security Domain Evaluator

Evaluates the security of agent orchestration systems. Assesses how agents
are coordinated, scheduled, and controlled; how workflows are isolated;
and how orchestration decisions are audited.

Controls:
  D2.1: Agent isolation in orchestration (are agents isolated in execution?)
  D2.2: Workflow intent verification (is workflow intent validated?)
  D2.3: Orchestration access control (can unprivileged users trigger workflows?)
  D2.4: Agent capability constraints in orchestration (are capabilities scoped per workflow?)
  D2.5: Orchestration audit trail (are all orchestration decisions logged?)
"""

from __future__ import annotations

import re
from typing import Optional

from asopb.config import EvalConfig
from asopb.models import (
    ControlDefinition,
    ControlEvidence,
    ControlScore,
    ControlStatus,
    EvidenceSource,
    EvidenceTier,
    ScanFinding,
    ScanResult,
    Severity,
)

from .base import DomainEvaluator


class D2OrchestrationEvaluator(DomainEvaluator):
    """Orchestration Security domain evaluator."""

    domain_id = "D2"
    domain_name = "Orchestration Security"
    weight = 1.0
    skill_file = "d2_orchestration.md"

    def define_controls(self) -> list[ControlDefinition]:
        """Define D2 controls for orchestration security."""
        return [
            ControlDefinition(
                control_id="D2.1",
                domain_id="D2",
                name="Agent Isolation in Orchestration",
                description=(
                    "Agents are isolated during orchestration. Each agent execution "
                    "has separate resource allocation, memory space, and communication context. "
                    "Agent state does not leak between concurrent executions."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Orchestration architecture specifies per-agent isolation",
                    "Isolation mechanism (containers, processes, sandboxes) is defined",
                ],
                t2_criteria=[
                    "Agent isolation implemented in orchestration scheduler",
                    "Memory isolation verified in code (separate contexts)",
                ],
                nist_mapping=["SC-7", "AC-4"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-1025"],
                tags=["isolation", "orchestration", "sandboxing"],
            ),
            ControlDefinition(
                control_id="D2.2",
                domain_id="D2",
                name="Workflow Intent Verification",
                description=(
                    "Workflow intent is validated before execution. Workflow "
                    "specifications are verified for schema compliance, "
                    "and safety constraints are checked."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Workflow schema validation rules are documented",
                    "Intent verification process is defined",
                ],
                t2_criteria=[
                    "Schema validation code present in orchestration engine",
                    "Safety constraint checks executed before workflow dispatch",
                ],
                nist_mapping=["SI-10", "AC-2"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-20"],
                tags=["workflow", "validation", "intent"],
            ),
            ControlDefinition(
                control_id="D2.3",
                domain_id="D2",
                name="Orchestration Access Control",
                description=(
                    "Only authorized principals can trigger agent orchestration. "
                    "Access control is enforced at the orchestration API/interface level."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Orchestration API access control policy is defined",
                    "Authentication and authorization for workflow triggers are specified",
                ],
                t2_criteria=[
                    "Access control checks enforced in orchestration API handlers",
                    "Identity verification before accepting workflow requests",
                ],
                nist_mapping=["AC-2", "AC-3"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-287"],
                tags=["access-control", "orchestration", "authorization"],
            ),
            ControlDefinition(
                control_id="D2.4",
                domain_id="D2",
                name="Agent Capability Constraints in Orchestration",
                description=(
                    "Each agent's capabilities are scoped per workflow or task. "
                    "Agents cannot exceed their assigned permissions even if they "
                    "request additional capabilities."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Per-agent capability model is documented",
                    "Workflow-specific capability constraints are defined",
                ],
                t2_criteria=[
                    "Capability scoping enforced in orchestration dispatch",
                    "Agent capability validation before tool invocation",
                ],
                nist_mapping=["AC-2", "AC-3"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-269"],
                tags=["capability", "scoping", "least-privilege"],
            ),
            ControlDefinition(
                control_id="D2.5",
                domain_id="D2",
                name="Orchestration Audit Trail",
                description=(
                    "All orchestration decisions are logged: workflow triggers, "
                    "agent allocations, task dispatches, and completions. Audit log "
                    "is tamper-proof and queryable."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Orchestration audit event schema is defined",
                    "Log retention and tamper-evidence mechanisms are specified",
                ],
                t2_criteria=[
                    "Orchestration audit logging integrated into all decision points",
                    "Structured logging format (JSON, binary format) implemented",
                    "Audit log immutability verified (write-once, append-only)",
                ],
                nist_mapping=["AU-2", "AU-3"],
                owasp_mapping=["LLM06"],
                cwe_mapping=["CWE-778"],
                tags=["audit", "logging", "orchestration"],
            ),
        ]

    def required_scanners(self) -> list[str]:
        """Scanners required for D2 evaluation."""
        return ["sandbox", "codebase"]

    def required_analyzers(self) -> list[str]:
        """Analyzers that enhance D2 scoring."""
        return ["semgrep", "bandit"]

    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score D2 controls using orchestration and code analysis.

        Strategy:
          1. Use orchestration scanner to detect orchestration configuration patterns
          2. Use codebase scanner to find isolation, validation, and audit implementation
          3. Use Semgrep/Bandit for orchestration-related vulnerabilities
          4. Map findings to specific controls
          5. Set T2 floor based on presence of critical patterns + evidence density
        """
        controls = self.define_controls()
        scores: list[ControlScore] = []

        # Extract findings by category for quick lookup
        orchestration_findings = self._extract_findings_by_category(scan_results.get("sandbox"))
        codebase_findings = self._extract_findings_by_category(scan_results.get("codebase"))
        semgrep_findings = self._extract_findings_by_category(analyzer_results.get("semgrep"))
        bandit_findings = self._extract_findings_by_category(analyzer_results.get("bandit"))

        # D2.1: Agent Isolation in Orchestration
        score_d21 = self._score_d21(
            controls[0],
            orchestration_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d21)

        # D2.2: Workflow Intent Verification
        score_d22 = self._score_d22(
            controls[1],
            orchestration_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d22)

        # D2.3: Orchestration Access Control
        score_d23 = self._score_d23(
            controls[2],
            orchestration_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d23)

        # D2.4: Agent Capability Constraints
        score_d24 = self._score_d24(
            controls[3],
            orchestration_findings,
            codebase_findings,
        )
        scores.append(score_d24)

        # D2.5: Orchestration Audit Trail
        score_d25 = self._score_d25(
            controls[4],
            orchestration_findings,
            codebase_findings,
        )
        scores.append(score_d25)

        return scores

    # ------------------------------------------------------------------
    # Per-Control Scoring Logic
    # ------------------------------------------------------------------

    def _score_d21(
        self,
        control_def: ControlDefinition,
        orchestration_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D2.1: Agent Isolation in Orchestration"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for agent isolation patterns in orchestration scanner
        if orchestration_findings.get("agent_isolation"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:orchestration",
                description="Agent isolation configuration detected in orchestration",
                confidence=0.8,
            ))

        # Check for sandbox execution patterns in codebase
        if codebase_findings.get("sandbox_execution"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Sandbox execution implementation found in code",
                confidence=0.85,
            ))

        # Check for session isolation patterns
        if codebase_findings.get("session_isolation"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Session isolation mechanisms found",
                confidence=0.8,
            ))

        # Check for shared memory patterns (negative evidence)
        if codebase_findings.get("shared_memory"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Shared memory access detected (negative evidence)",
                confidence=0.75,
            ))
            # Cap T2 if shared memory present
            t2_floor = min(t2_floor, 2.0)

        # Check for Semgrep isolation warnings
        if semgrep_findings.get("isolation_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified potential isolation gaps",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No agent isolation mechanism found"] if t2_floor == 0 else [],
        )

    def _score_d22(
        self,
        control_def: ControlDefinition,
        orchestration_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D2.2: Workflow Intent Verification"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for schema validation in orchestration
        if orchestration_findings.get("schema_validation"):
            t2_floor = 5.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:orchestration",
                description="Workflow schema validation detected",
                confidence=0.75,
            ))

        # Check for intent verification in codebase
        if codebase_findings.get("intent_verification"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Intent verification logic found in code",
                confidence=0.8,
            ))

        # Check for workflow constraint checks
        if codebase_findings.get("workflow_constraint_check"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Safety constraint checks before workflow dispatch",
                confidence=0.8,
            ))

        # Check for unchecked workflow patterns (negative evidence)
        if semgrep_findings.get("unchecked_workflow"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified unchecked workflow execution paths",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No workflow intent verification found"] if t2_floor == 0 else [],
        )

    def _score_d23(
        self,
        control_def: ControlDefinition,
        orchestration_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D2.3: Orchestration Access Control"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for access control in orchestration
        if orchestration_findings.get("access_control"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:orchestration",
                description="Orchestration access control configuration found",
                confidence=0.8,
            ))

        # Check for auth checks in orchestration handlers
        if codebase_findings.get("auth_check_orchestration"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Authentication checks in orchestration API handlers",
                confidence=0.85,
            ))

        # Check for RBAC enforcement
        if codebase_findings.get("rbac_enforcement"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="RBAC enforcement for orchestration operations",
                confidence=0.85,
            ))

        # Check for missing auth checks (negative evidence)
        if semgrep_findings.get("missing_auth_check"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified missing authentication checks",
                confidence=0.8,
            ))
            # Significantly cap T2
            t2_floor = min(t2_floor, 3.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No orchestration access control found"] if t2_floor == 0 else [],
        )

    def _score_d24(
        self,
        control_def: ControlDefinition,
        orchestration_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D2.4: Agent Capability Constraints in Orchestration"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for capability scoping in orchestration
        if orchestration_findings.get("capability_scoping"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:orchestration",
                description="Capability scoping configuration detected",
                confidence=0.75,
            ))

        # Check for tool allowlist patterns
        if codebase_findings.get("tool_allowlist"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Tool allowlist or capability filtering found",
                confidence=0.8,
            ))

        # Check for permission boundaries
        if codebase_findings.get("permission_boundary"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Permission boundaries enforced before tool invocation",
                confidence=0.85,
            ))

        # Check for unconstrained tools (negative evidence)
        if codebase_findings.get("unconstrained_tools"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Unconstrained tool access detected (negative evidence)",
                confidence=0.8,
            ))
            # Cap T2 if unconstrained tools present
            t2_floor = min(t2_floor, 2.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No capability constraints found"] if t2_floor == 0 else [],
        )

    def _score_d25(
        self,
        control_def: ControlDefinition,
        orchestration_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D2.5: Orchestration Audit Trail"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for audit logging in orchestration
        if orchestration_findings.get("audit_logging"):
            t2_floor = 5.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:orchestration",
                description="Orchestration audit logging configuration found",
                confidence=0.75,
            ))

        # Check for structured logging in codebase
        if codebase_findings.get("structured_logging"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Structured logging implementation (JSON format) found",
                confidence=0.8,
            ))

        # Check for immutable audit patterns
        if codebase_findings.get("immutable_audit"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Immutable audit log (write-once/append-only) implementation",
                confidence=0.85,
            ))

        # Check for missing audit points (negative evidence)
        if codebase_findings.get("missing_audit"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Orchestration decision points without audit logging",
                confidence=0.75,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No orchestration audit trail found"] if t2_floor == 0 else [],
        )

    # ------------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------------

    def _extract_findings_by_category(
        self,
        scan_result: Optional[ScanResult],
    ) -> dict[str, list[ScanFinding]]:
        """Extract findings from a ScanResult and group by category."""
        if not scan_result:
            return {}
        by_category: dict[str, list[ScanFinding]] = {}
        for finding in scan_result.findings:
            if finding.category not in by_category:
                by_category[finding.category] = []
            by_category[finding.category].append(finding)
        return by_category
