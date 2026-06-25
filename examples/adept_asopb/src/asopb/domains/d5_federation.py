"""
D5: Federation and Trust Domain Evaluator

Evaluates federated agent systems and cross-organizational trust boundaries.
Assesses inter-domain communication, trust establishment, delegation across
organizational boundaries, and conflict resolution in federated scenarios.

Controls:
  D5.1: Federated agent discovery (can agents discover trusted partners?)
  D5.2: Trust boundary enforcement (are org boundaries enforced?)
  D5.3: Cross-org delegation (can agents delegate across orgs safely?)
  D5.4: Federated consensus (how are conflicts resolved in federation?)
  D5.5: Federation audit (are cross-org interactions audited?)
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


class D5FederationEvaluator(DomainEvaluator):
    """Federation and Trust domain evaluator."""

    domain_id = "D5"
    domain_name = "Federation and Trust"
    weight = 1.0
    skill_file = "d5_federation.md"

    def define_controls(self) -> list[ControlDefinition]:
        """Define D5 controls for federation and trust."""
        return [
            ControlDefinition(
                control_id="D5.1",
                domain_id="D5",
                name="Federated Agent Discovery",
                description=(
                    "Agents can securely discover and identify trusted federation "
                    "partners. Discovery is audited and authenticated."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Agent discovery mechanism is documented",
                    "Trust establishment process for federation partners is specified",
                ],
                t2_criteria=[
                    "Agent discovery service or protocol implemented",
                    "Partner identity verification in discovery process",
                ],
                nist_mapping=["SC-7", "IA-2"],
                owasp_mapping=["LLM05"],
                cwe_mapping=["CWE-295"],
                tags=["federation", "discovery", "trust"],
            ),
            ControlDefinition(
                control_id="D5.2",
                domain_id="D5",
                name="Trust Boundary Enforcement",
                description=(
                    "Organizational boundaries are enforced. Agents cannot bypass "
                    "trust boundaries even with valid credentials. Cross-org data "
                    "access requires explicit authorization."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Organizational trust boundaries are documented",
                    "Data access policies across org boundaries are specified",
                ],
                t2_criteria=[
                    "Boundary enforcement in agent orchestration logic",
                    "Data labeling with org identity in shared systems",
                    "Access control checks that verify org membership",
                ],
                nist_mapping=["AC-2", "AC-3", "SC-7"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-284"],
                tags=["boundary", "trust", "isolation"],
            ),
            ControlDefinition(
                control_id="D5.3",
                domain_id="D5",
                name="Cross-Organization Delegation",
                description=(
                    "Agents can delegate work across organizational boundaries safely. "
                    "Delegation includes capability constraints and audit trails that "
                    "span organizations."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Cross-org delegation policy is documented",
                    "Capability constraints for cross-org delegation are specified",
                ],
                t2_criteria=[
                    "Cross-org delegation mechanism with scope enforcement",
                    "Delegation tokens include issuing org identity",
                    "Receiving org validates delegation authority",
                ],
                nist_mapping=["AC-2", "IA-4"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-269"],
                tags=["delegation", "cross-org", "trust"],
            ),
            ControlDefinition(
                control_id="D5.4",
                domain_id="D5",
                name="Federated Consensus and Conflict Resolution",
                description=(
                    "Federated agents reach consensus on shared state. Conflicts "
                    "are resolved deterministically and verifiably. No single org can "
                    "impose unilateral state changes."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Consensus mechanism (voting, merkle tree, ledger) is documented",
                    "Conflict resolution rules are specified",
                ],
                t2_criteria=[
                    "Consensus algorithm implemented in federation protocol",
                    "Conflict detection and resolution in shared state management",
                ],
                nist_mapping=["SI-12"],
                owasp_mapping=["LLM02"],
                cwe_mapping=["CWE-362"],
                tags=["consensus", "federation", "conflict-resolution"],
            ),
            ControlDefinition(
                control_id="D5.5",
                domain_id="D5",
                name="Federation Audit Trail",
                description=(
                    "Cross-organizational interactions are audited. Audit logs "
                    "include: agent actions, data access, delegation decisions, "
                    "and conflict resolutions. Audit trails are preserved across "
                    "org boundaries."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Federation audit event schema is defined",
                    "Org identity and actor identity are recorded in audit logs",
                ],
                t2_criteria=[
                    "Audit logging in federation interaction points",
                    "Cross-org audit trail aggregation mechanism",
                    "Tamper evidence for federation audit logs",
                ],
                nist_mapping=["AU-2", "AU-3"],
                owasp_mapping=["LLM06"],
                cwe_mapping=["CWE-778"],
                tags=["audit", "federation", "logging"],
            ),
        ]

    def check_applicability(self, scan_results: dict[str, ScanResult]) -> Applicability:
        """D5 is only applicable if federation patterns are detected in the codebase."""
        # Placeholder: could check for federation keywords in scan results
        # For now, always applicable (can be overridden by config)
        return Applicability.APPLICABLE

    def required_scanners(self) -> list[str]:
        """Scanners required for D5 evaluation."""
        return ["federation", "codebase"]

    def required_analyzers(self) -> list[str]:
        """Analyzers that enhance D5 scoring."""
        return ["semgrep"]

    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score D5 controls using federation-specific analysis.

        Strategy:
          1. Use federation scanner to detect federation protocols, trust policies,
             and cross-org communication patterns
          2. Use codebase scanner to find discovery, boundary, delegation, consensus,
             and audit implementations
          3. Use Semgrep analyzer for federation-related vulnerability patterns
          4. Map findings to specific controls
          5. Set T2 floor based on presence of critical patterns + evidence density
        """
        controls = self.define_controls()
        scores: list[ControlScore] = []

        # Extract findings by category for quick lookup
        federation_findings = self._extract_findings_by_category(scan_results.get("federation"))
        codebase_findings = self._extract_findings_by_category(scan_results.get("codebase"))
        semgrep_findings = self._extract_findings_by_category(analyzer_results.get("semgrep"))

        # D5.1: Federated Agent Discovery
        score_d51 = self._score_d51(
            controls[0],
            federation_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d51)

        # D5.2: Trust Boundary Enforcement
        score_d52 = self._score_d52(
            controls[1],
            federation_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d52)

        # D5.3: Cross-Organization Delegation
        score_d53 = self._score_d53(
            controls[2],
            federation_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d53)

        # D5.4: Federated Consensus and Conflict Resolution
        score_d54 = self._score_d54(
            controls[3],
            federation_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d54)

        # D5.5: Federation Audit Trail
        score_d55 = self._score_d55(
            controls[4],
            federation_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d55)

        return scores

    # ------------------------------------------------------------------
    # Per-Control Scoring Logic
    # ------------------------------------------------------------------

    def _score_d51(
        self,
        control_def: ControlDefinition,
        federation_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D5.1: Federated Agent Discovery"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for agent discovery protocol in federation scanner
        if federation_findings.get("agent_discovery"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Agent discovery protocol detected in federation configuration",
                confidence=0.8,
            ))

        # Check for service registry patterns in codebase
        if codebase_findings.get("service_registry"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Service registry or discovery service implementation found",
                confidence=0.85,
            ))

        # Check for partner identity verification in discovery
        if federation_findings.get("discovery_authentication"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Partner identity verification in discovery process",
                confidence=0.8,
            ))

        # Check for unauthenticated discovery (negative evidence)
        if federation_findings.get("unauthenticated_discovery"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Unauthenticated agent discovery endpoint detected (negative evidence)",
                confidence=0.85,
            ))
            # Cap T2 if unauthenticated discovery present
            t2_floor = min(t2_floor, 2.0)

        # Check for Semgrep discovery-related issues
        if semgrep_findings.get("discovery_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified potential discovery security gaps",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No federated agent discovery mechanism found"] if t2_floor == 0 else [],
        )

    def _score_d52(
        self,
        control_def: ControlDefinition,
        federation_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D5.2: Trust Boundary Enforcement"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for trust boundary enforcement in federation scanner
        if federation_findings.get("trust_boundary"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Trust boundary enforcement configuration detected",
                confidence=0.8,
            ))

        # Check for org boundary enforcement patterns in codebase
        if codebase_findings.get("org_boundary_enforcement"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Organizational boundary enforcement logic found in code",
                confidence=0.85,
            ))

        # Check for data labeling with org identity
        if codebase_findings.get("data_labeling"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Data labeling with org identity in shared systems",
                confidence=0.8,
            ))

        # Check for cross-org access control checks
        if federation_findings.get("cross_org_access_control"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Cross-org access control checks verify org membership",
                confidence=0.85,
            ))

        # Check for missing boundary enforcement (negative evidence)
        if federation_findings.get("missing_boundary"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Missing trust boundary enforcement at federation points (negative evidence)",
                confidence=0.9,
            ))
            # Significantly cap T2 for critical control
            t2_floor = min(t2_floor, 1.5)

        # Check for Semgrep boundary-related issues
        if semgrep_findings.get("boundary_bypass"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified potential trust boundary bypass patterns",
                confidence=0.75,
            ))
            t2_floor = min(t2_floor, 3.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No trust boundary enforcement found"] if t2_floor == 0 else [],
        )

    def _score_d53(
        self,
        control_def: ControlDefinition,
        federation_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D5.3: Cross-Organization Delegation"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for cross-org delegation mechanisms in federation scanner
        if federation_findings.get("cross_org_delegation"):
            t2_floor = 5.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Cross-organization delegation mechanism detected",
                confidence=0.75,
            ))

        # Check for delegation scope enforcement in codebase
        if codebase_findings.get("delegation_scope"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Delegation scope enforcement logic found in code",
                confidence=0.8,
            ))

        # Check for delegation tokens with org identity
        if federation_findings.get("delegation_token_org_identity"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Delegation tokens include issuing org identity",
                confidence=0.8,
            ))

        # Check for receiving org validation
        if codebase_findings.get("receiving_org_validation"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Receiving organization validates delegation authority",
                confidence=0.85,
            ))

        # Check for unbounded delegation (negative evidence)
        if federation_findings.get("unbounded_delegation"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Unbounded cross-org delegation without scope constraints (negative evidence)",
                confidence=0.85,
            ))
            # Cap T2 if unbounded delegation present
            t2_floor = min(t2_floor, 2.0)

        # Check for Semgrep delegation-related issues
        if semgrep_findings.get("delegation_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified cross-org delegation security gaps",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No cross-organization delegation mechanism found"] if t2_floor == 0 else [],
        )

    def _score_d54(
        self,
        control_def: ControlDefinition,
        federation_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D5.4: Federated Consensus and Conflict Resolution"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for consensus algorithm in federation scanner
        if federation_findings.get("consensus_algorithm"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Consensus algorithm detected in federation protocol",
                confidence=0.8,
            ))

        # Check for conflict resolution patterns in codebase
        if codebase_findings.get("conflict_resolution"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Conflict resolution logic found in code",
                confidence=0.8,
            ))

        # Check for shared state management patterns
        if codebase_findings.get("shared_state_management"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Shared state management with conflict detection found",
                confidence=0.75,
            ))

        # Check for voting/merkle/ledger patterns
        if federation_findings.get("verifiable_consensus"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Verifiable consensus mechanism (voting, merkle tree, or ledger) found",
                confidence=0.85,
            ))

        # Check for race conditions in shared state (negative evidence)
        if semgrep_findings.get("race_condition"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified race conditions in shared state management",
                confidence=0.75,
            ))
            t2_floor = min(t2_floor, 3.0)

        # Check for unilateral state mutation (negative evidence)
        if federation_findings.get("unilateral_state_change"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Unilateral state changes possible without consensus (negative evidence)",
                confidence=0.8,
            ))
            t2_floor = min(t2_floor, 2.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No federated consensus mechanism found"] if t2_floor == 0 else [],
        )

    def _score_d55(
        self,
        control_def: ControlDefinition,
        federation_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D5.5: Federation Audit Trail"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for federation audit logging in federation scanner
        if federation_findings.get("federation_audit"):
            t2_floor = 5.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Federation audit logging configuration detected",
                confidence=0.75,
            ))

        # Check for cross-org logging patterns in codebase
        if codebase_findings.get("cross_org_logging"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Cross-organization interaction logging found in code",
                confidence=0.8,
            ))

        # Check for audit aggregation mechanisms
        if codebase_findings.get("audit_aggregation"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Cross-org audit trail aggregation mechanism implemented",
                confidence=0.8,
            ))

        # Check for tamper evidence in audit logs
        if federation_findings.get("tamper_evidence"):
            t2_floor = max(t2_floor, 8.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Tamper evidence mechanisms (signatures, hash chains) for federation audit logs",
                confidence=0.85,
            ))

        # Check for missing audit at federation points (negative evidence)
        if federation_findings.get("missing_federation_audit"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:federation",
                description="Federation interaction points without audit logging (negative evidence)",
                confidence=0.8,
            ))

        # Check for Semgrep audit-related issues
        if semgrep_findings.get("audit_gap"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified audit logging gaps in federation paths",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No federation audit trail found"] if t2_floor == 0 else [],
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
