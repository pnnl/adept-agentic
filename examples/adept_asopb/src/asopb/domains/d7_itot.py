"""
D7: IT/OT Convergence Domain Evaluator

Evaluates agentic systems that interact with operational technology (OT)
and industrial control systems (ICS). Assesses risk isolation, safety
constraints, reversibility, and human oversight in OT-impacting decisions.

Controls:
  D7.1: OT impact isolation (can OT impact be constrained?)
  D7.2: Safety state machine (does OT system have safety constraints?)
  D7.3: Reversibility (can OT decisions be undone?)
  D7.4: Human-in-the-loop for OT (are critical OT actions human-approved?)
  D7.5: OT-IT boundary enforcement (is the OT-IT boundary enforced?)
"""

from __future__ import annotations

import re
from typing import Optional

from asopb.config import EvalConfig
from asopb.models import (
    Applicability,
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


class D7ItOtEvaluator(DomainEvaluator):
    """IT/OT Convergence domain evaluator."""

    domain_id = "D7"
    domain_name = "IT/OT Convergence"
    weight = 1.5
    skill_file = "d7_itot.md"

    def define_controls(self) -> list[ControlDefinition]:
        """Define D7 controls for IT/OT convergence."""
        return [
            ControlDefinition(
                control_id="D7.1",
                domain_id="D7",
                name="OT Impact Isolation",
                description=(
                    "OT-impacting operations are isolated and constrained. "
                    "Agent capabilities that affect operational technology are "
                    "explicitly scoped and cannot exceed predetermined limits."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "OT-capable agents are explicitly identified",
                    "OT operation scope and constraints are documented",
                ],
                t2_criteria=[
                    "Agent capability restrictions enforced for OT operations",
                    "Rate limiting or quota enforcement on OT-impacting actions",
                    "OT operation approval workflows in code",
                ],
                nist_mapping=["SI-4", "AC-3"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-1025"],
                tags=["ot", "isolation", "constraints"],
            ),
            ControlDefinition(
                control_id="D7.2",
                domain_id="D7",
                name="Safety State Machine",
                description=(
                    "OT system enforces a safety state machine. Valid state "
                    "transitions are predefined and verified. Invalid transitions "
                    "are rejected. Safety constraints are immutable at runtime."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "OT state machine and valid transitions are documented",
                    "Safety constraints are formally specified",
                ],
                t2_criteria=[
                    "State machine implementation with transition validation",
                    "Safety constraint enforcement at state transition points",
                    "Immutable safety constraint storage",
                ],
                nist_mapping=["SI-12", "SC-5"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-1025"],
                tags=["safety", "state-machine", "ot"],
            ),
            ControlDefinition(
                control_id="D7.3",
                domain_id="D7",
                name="Reversibility of OT Decisions",
                description=(
                    "OT-impacting decisions are reversible. Undo operations are "
                    "available and tested. Rollback procedures are documented and "
                    "can be triggered manually or automatically."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Reversible OT operations are identified",
                    "Rollback/undo procedures are documented",
                ],
                t2_criteria=[
                    "Undo operation implementation for OT actions",
                    "Rollback procedure availability and testing",
                    "Automatic rollback on anomaly or timeout",
                ],
                nist_mapping=["SI-13", "SI-16"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-1025"],
                tags=["reversibility", "rollback", "ot"],
            ),
            ControlDefinition(
                control_id="D7.4",
                domain_id="D7",
                name="Human-in-the-Loop for Critical OT Actions",
                description=(
                    "Critical OT-impacting actions require human approval before "
                    "execution. Human review includes decision rationale and "
                    "system recommendations."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Critical OT operations are defined",
                    "Human approval workflow is documented",
                ],
                t2_criteria=[
                    "Human approval requirement enforced in code for critical OT ops",
                    "Human review interface with decision context and recommendations",
                    "Approval logs linked to OT operation execution",
                ],
                nist_mapping=["AC-2", "AC-3"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-1025"],
                tags=["human-oversight", "approval", "ot"],
            ),
            ControlDefinition(
                control_id="D7.5",
                domain_id="D7",
                name="OT-IT Boundary Enforcement",
                description=(
                    "The boundary between IT and OT systems is enforced. OT systems "
                    "cannot be accessed by generic IT tools. IT agents cannot "
                    "directly invoke OT operations without proper mediation."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "OT-IT boundary is architecturally documented",
                    "Mediation layer for OT access is specified",
                ],
                t2_criteria=[
                    "Firewall or network isolation between IT and OT",
                    "OT-specific authentication and authorization in mediation layer",
                    "IT-OT gateway or proxy with policy enforcement",
                ],
                nist_mapping=["SC-7", "AC-3"],
                owasp_mapping=["LLM05"],
                cwe_mapping=["CWE-284"],
                tags=["boundary", "isolation", "ot-it"],
            ),
        ]

    def check_applicability(self, scan_results: dict[str, ScanResult]) -> Applicability:
        """D7 is only applicable if OT interfaces are detected."""
        # Placeholder: could check for OT/ICS keywords
        # For now, always applicable (can be overridden by config)
        return Applicability.APPLICABLE

    def required_scanners(self) -> list[str]:
        """Scanners required for D7 evaluation."""
        return ["itot", "codebase"]

    def required_analyzers(self) -> list[str]:
        """Analyzers that enhance D7 scoring."""
        return ["semgrep"]

    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score D7 controls using OT interface scanner, codebase, and Semgrep findings.

        Strategy:
          1. Use ot_interface scanner to detect OT interaction patterns and isolation
          2. Use codebase scanner for implementation evidence (state machines, rollback, approval)
          3. Use Semgrep analyzer for OT-related vulnerabilities
          4. Map findings to specific controls
          5. Set T2 floor based on presence of critical patterns + evidence density
        """
        controls = self.define_controls()
        scores: list[ControlScore] = []

        # Extract findings by category for quick lookup
        ot_findings = self._extract_findings_by_category(scan_results.get("itot"))
        codebase_findings = self._extract_findings_by_category(scan_results.get("codebase"))
        semgrep_findings = self._extract_findings_by_category(analyzer_results.get("semgrep"))

        # D7.1: OT Impact Isolation
        score_d71 = self._score_d71(
            controls[0],
            ot_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d71)

        # D7.2: Safety State Machine
        score_d72 = self._score_d72(
            controls[1],
            ot_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d72)

        # D7.3: Reversibility of OT Decisions
        score_d73 = self._score_d73(
            controls[2],
            ot_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d73)

        # D7.4: Human-in-the-Loop for Critical OT Actions
        score_d74 = self._score_d74(
            controls[3],
            ot_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d74)

        # D7.5: OT-IT Boundary Enforcement
        score_d75 = self._score_d75(
            controls[4],
            ot_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d75)

        return scores

    # ------------------------------------------------------------------
    # Per-Control Scoring Logic
    # ------------------------------------------------------------------

    def _score_d71(
        self,
        control_def: ControlDefinition,
        ot_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D7.1: OT Impact Isolation"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for OT isolation patterns in ot_interface scanner
        if ot_findings.get("ot_isolation"):
            t2_floor = 5.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:ot_interface",
                description="OT impact isolation patterns detected in codebase",
                confidence=0.8,
            ))

        # Check for rate limiting or quota enforcement on OT operations
        if codebase_findings.get("ot_rate_limiting"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Rate limiting or quota enforcement on OT-impacting actions",
                confidence=0.8,
            ))

        # Check for OT operation approval workflows
        if codebase_findings.get("ot_approval_workflow"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="OT operation approval workflow implementation found",
                confidence=0.85,
            ))

        # Check for unrestricted OT access (negative evidence)
        if ot_findings.get("unrestricted_ot_access"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:ot_interface",
                description="Unrestricted OT access paths detected (negative evidence)",
                confidence=0.85,
            ))
            # Cap T2 if unrestricted access present
            t2_floor = min(t2_floor, 2.0)

        # Check for Semgrep OT isolation warnings
        if semgrep_findings.get("ot_isolation_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified potential OT isolation gaps",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline for OT isolation
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No OT impact isolation mechanism found"] if t2_floor == 0 else [],
        )

    def _score_d72(
        self,
        control_def: ControlDefinition,
        ot_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D7.2: Safety State Machine"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for state machine implementation
        if ot_findings.get("safety_state_machine") or codebase_findings.get("safety_state_machine"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:ot_interface",
                description="Safety state machine implementation detected",
                confidence=0.8,
            ))

        # Check for state transition validation
        if codebase_findings.get("state_transition_validation"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="State transition validation logic found in code",
                confidence=0.85,
            ))

        # Check for immutable safety constraints
        if codebase_findings.get("immutable_constraints"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Immutable safety constraint storage implemented",
                confidence=0.85,
            ))

        # Check for invalid state transition handling (negative evidence if missing)
        if semgrep_findings.get("unsafe_state_transition"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified unsafe or unvalidated state transitions",
                confidence=0.75,
            ))
            # Cap T2 if unsafe transitions detected
            t2_floor = min(t2_floor, 3.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline for safety state machine
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No safety state machine implementation found"] if t2_floor == 0 else [],
        )

    def _score_d73(
        self,
        control_def: ControlDefinition,
        ot_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D7.3: Reversibility of OT Decisions"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for undo/rollback operations in OT interface
        if ot_findings.get("ot_rollback"):
            t2_floor = 5.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:ot_interface",
                description="OT rollback capability detected in interface",
                confidence=0.75,
            ))

        # Check for undo operation implementations in codebase
        if codebase_findings.get("undo_operation"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Undo operation implementation for OT actions found",
                confidence=0.8,
            ))

        # Check for automatic rollback on anomaly
        if codebase_findings.get("automatic_rollback"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Automatic rollback on anomaly or timeout implemented",
                confidence=0.85,
            ))

        # Check for tested rollback procedures
        if codebase_findings.get("rollback_test"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Rollback procedures have associated test coverage",
                confidence=0.8,
            ))

        # Check for irreversible operations without safeguards (negative evidence)
        if semgrep_findings.get("irreversible_ot_operation"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified irreversible OT operations without rollback safeguards",
                confidence=0.75,
            ))
            # Cap T2 if irreversible operations found without protection
            t2_floor = min(t2_floor, 2.5)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline for reversibility
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No OT decision reversibility mechanism found"] if t2_floor == 0 else [],
        )

    def _score_d74(
        self,
        control_def: ControlDefinition,
        ot_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D7.4: Human-in-the-Loop for Critical OT Actions"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for human approval requirements in OT interface
        if ot_findings.get("human_approval"):
            t2_floor = 5.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:ot_interface",
                description="Human approval requirement detected for OT operations",
                confidence=0.8,
            ))

        # Check for approval workflow implementation in codebase
        if codebase_findings.get("approval_workflow"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Human approval workflow with decision context and recommendations",
                confidence=0.85,
            ))

        # Check for approval logging linked to OT execution
        if codebase_findings.get("approval_logging"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Approval logs linked to OT operation execution",
                confidence=0.8,
            ))

        # Check for missing approval on critical OT operations (negative evidence)
        if ot_findings.get("missing_approval") or semgrep_findings.get("missing_approval"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:ot_interface",
                description="Critical OT operations found without human approval gate (negative evidence)",
                confidence=0.85,
            ))
            # Cap T2 if critical actions bypass human approval
            t2_floor = min(t2_floor, 2.0)

        # Check for Semgrep human oversight warnings
        if semgrep_findings.get("human_oversight_gap"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified gaps in human oversight for OT actions",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline for human-in-the-loop
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No human-in-the-loop enforcement for critical OT actions"] if t2_floor == 0 else [],
        )

    def _score_d75(
        self,
        control_def: ControlDefinition,
        ot_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D7.5: OT-IT Boundary Enforcement"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for OT-IT boundary definition in ot_interface scanner
        if ot_findings.get("ot_it_boundary"):
            t2_floor = 5.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:ot_interface",
                description="OT-IT boundary definition detected in system architecture",
                confidence=0.75,
            ))

        # Check for firewall or network isolation
        if codebase_findings.get("network_isolation"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Firewall or network isolation between IT and OT zones",
                confidence=0.8,
            ))

        # Check for mediation layer (IT-OT gateway/proxy)
        if codebase_findings.get("mediation_layer"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="IT-OT mediation layer or gateway with policy enforcement",
                confidence=0.85,
            ))

        # Check for OT-specific authentication
        if codebase_findings.get("ot_auth"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="OT-specific authentication and authorization in mediation layer",
                confidence=0.85,
            ))

        # Check for direct IT-to-OT access bypassing mediation (negative evidence)
        if semgrep_findings.get("direct_it_ot_access"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified direct IT-to-OT access bypassing mediation layer",
                confidence=0.8,
            ))
            # Significantly cap T2
            t2_floor = min(t2_floor, 2.0)

        # Check for missing OT boundary enforcement
        if ot_findings.get("missing_boundary_enforcement"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:ot_interface",
                description="OT boundary enforcement missing or incomplete (negative evidence)",
                confidence=0.8,
            ))
            # Cap T2 for missing enforcement
            t2_floor = min(t2_floor, 1.5)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline for boundary enforcement
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No OT-IT boundary enforcement found"] if t2_floor == 0 else [],
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
