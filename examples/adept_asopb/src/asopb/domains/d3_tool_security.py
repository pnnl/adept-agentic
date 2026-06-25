"""
D3: Tool and MCP Security Domain Evaluator

Evaluates the security of tools and Model Context Protocol (MCP) servers
used by agents. Assesses tool authentication, input validation, side-effect
control, and MCP protocol security.

Controls:
  D3.1: Tool authentication (are tools authenticated before use?)
  D3.2: Tool input schema validation (does tool enforce input contracts?)
  D3.3: Tool side-effect constraints (can tools be limited to read-only?)
  D3.4: MCP server authentication (are MCP servers authenticated?)
  D3.5: MCP message integrity (are MCP messages signed/encrypted?)
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


class D3ToolSecurityEvaluator(DomainEvaluator):
    """Tool and MCP Security domain evaluator."""

    domain_id = "D3"
    domain_name = "Tool and MCP Security"
    weight = 1.0
    skill_file = "d3_tool_security.md"

    def define_controls(self) -> list[ControlDefinition]:
        """Define D3 controls for tool and MCP security."""
        return [
            ControlDefinition(
                control_id="D3.1",
                domain_id="D3",
                name="Tool Authentication",
                description=(
                    "Tools are authenticated before use by agents. Tool identity "
                    "is verified, and access to tool APIs is authenticated with "
                    "credentials or tokens."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Tool authentication strategy is documented",
                    "Credential management for tools is specified",
                ],
                t2_criteria=[
                    "Tool authentication checks in tool invocation code",
                    "API key or token validation before tool calls",
                ],
                nist_mapping=["IA-2", "IA-3"],
                owasp_mapping=["LLM01", "LLM05"],
                cwe_mapping=["CWE-287"],
                tags=["tool", "authentication", "identity"],
            ),
            ControlDefinition(
                control_id="D3.2",
                domain_id="D3",
                name="Tool Input Schema Validation",
                description=(
                    "Tools enforce input schemas. Parameter types, ranges, and "
                    "formats are validated before tool execution. Invalid inputs "
                    "are rejected with clear error messages."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Input schema for each tool is documented",
                    "Validation rules for parameters are specified",
                ],
                t2_criteria=[
                    "Schema validation code present in tool handlers",
                    "Input validation before tool execution (not after)",
                    "Rejection of invalid inputs with error response",
                ],
                nist_mapping=["SI-10", "AC-2"],
                owasp_mapping=["LLM04"],
                cwe_mapping=["CWE-20"],
                tags=["input-validation", "schema", "tool"],
            ),
            ControlDefinition(
                control_id="D3.3",
                domain_id="D3",
                name="Tool Side-Effect Constraints",
                description=(
                    "Tools are categorized by side-effect level. Read-only tools "
                    "are isolated from write operations. Tools with side effects "
                    "are tracked and constrained."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Tool categorization (read-only vs. write) is documented",
                    "Constraints on write tools are specified",
                ],
                t2_criteria=[
                    "Tool side-effect level enforced in tool registry or dispatcher",
                    "Read-only tools isolated or marked separately in code",
                    "Write tool execution tracked and audited",
                ],
                nist_mapping=["AC-2", "AC-3"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-269"],
                tags=["side-effect", "read-only", "tool-control"],
            ),
            ControlDefinition(
                control_id="D3.4",
                domain_id="D3",
                name="MCP Server Authentication",
                description=(
                    "MCP servers are authenticated. Client-side MCP connection "
                    "initialization includes credential exchange and identity verification."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "MCP server authentication mechanism is documented",
                    "Identity verification for MCP servers is specified",
                ],
                t2_criteria=[
                    "MCP client authentication handshake in code",
                    "Server identity verification before message exchange",
                ],
                nist_mapping=["IA-2", "IA-3"],
                owasp_mapping=["LLM05"],
                cwe_mapping=["CWE-295"],
                tags=["mcp", "authentication", "server"],
            ),
            ControlDefinition(
                control_id="D3.5",
                domain_id="D3",
                name="MCP Message Integrity",
                description=(
                    "MCP messages are signed or encrypted. Message integrity and "
                    "authenticity are verified. Tampering detection is implemented."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "MCP message signing or encryption strategy is documented",
                    "Message integrity verification is specified",
                ],
                t2_criteria=[
                    "Message signature or encryption in MCP protocol handlers",
                    "Integrity verification on every message received",
                    "Tampered message rejection and logging",
                ],
                nist_mapping=["SC-8", "SC-12"],
                owasp_mapping=["LLM05"],
                cwe_mapping=["CWE-347"],
                tags=["mcp", "message-integrity", "encryption"],
            ),
        ]

    def required_scanners(self) -> list[str]:
        """Scanners required for D3 evaluation."""
        return ["tools", "codebase"]

    def required_analyzers(self) -> list[str]:
        """Analyzers that enhance D3 scoring."""
        return ["semgrep", "bandit"]

    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score D3 controls using tool registry and code analysis.

        Strategy:
          1. Use tool_registry scanner to detect tool auth, schema, and categorization patterns
          2. Use codebase scanner to find validation, MCP auth, and integrity implementations
          3. Use Semgrep/Bandit for tool/MCP-related vulnerabilities
          4. Map findings to specific controls
          5. Set T2 floor based on presence of critical patterns + evidence density
        """
        controls = self.define_controls()
        scores: list[ControlScore] = []

        # Extract findings by category for quick lookup
        tool_registry_findings = self._extract_findings_by_category(
            scan_results.get("tools")
        )
        codebase_findings = self._extract_findings_by_category(
            scan_results.get("codebase")
        )
        semgrep_findings = self._extract_findings_by_category(
            analyzer_results.get("semgrep")
        )
        bandit_findings = self._extract_findings_by_category(
            analyzer_results.get("bandit")
        )

        # D3.1: Tool Authentication
        score_d31 = self._score_d31(
            controls[0],
            tool_registry_findings,
            codebase_findings,
            semgrep_findings,
            bandit_findings,
        )
        scores.append(score_d31)

        # D3.2: Tool Input Schema Validation
        score_d32 = self._score_d32(
            controls[1],
            tool_registry_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d32)

        # D3.3: Tool Side-Effect Constraints
        score_d33 = self._score_d33(
            controls[2],
            tool_registry_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d33)

        # D3.4: MCP Server Authentication
        score_d34 = self._score_d34(
            controls[3],
            tool_registry_findings,
            codebase_findings,
            semgrep_findings,
            bandit_findings,
        )
        scores.append(score_d34)

        # D3.5: MCP Message Integrity
        score_d35 = self._score_d35(
            controls[4],
            codebase_findings,
            semgrep_findings,
            bandit_findings,
        )
        scores.append(score_d35)

        return scores

    # ------------------------------------------------------------------
    # Per-Control Scoring Logic
    # ------------------------------------------------------------------

    def _score_d31(
        self,
        control_def: ControlDefinition,
        tool_registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
        bandit_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D3.1: Tool Authentication"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for tool authentication patterns in tool_registry scanner
        if tool_registry_findings.get("tool_auth"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:tool_registry",
                description="Tool authentication configuration detected in tool registry",
                confidence=0.8,
            ))

        # Check for API key / token validation in codebase before tool calls
        if codebase_findings.get("api_key_validation"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="API key or token validation before tool invocation found in code",
                confidence=0.85,
            ))

        # Check for credential exchange patterns in tool invocation
        if codebase_findings.get("tool_credential_exchange"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Credential exchange implemented in tool invocation path",
                confidence=0.8,
            ))

        # Check for unauthenticated tool access (negative evidence)
        if tool_registry_findings.get("unauth_tool_access"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:tool_registry",
                description="Unauthenticated tool access paths detected (negative evidence)",
                confidence=0.9,
            ))
            # Significantly cap T2
            t2_floor = min(t2_floor, 2.0)

        # Check for Semgrep auth warnings related to tools
        if semgrep_findings.get("tool_auth_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified tool authentication gaps",
                confidence=0.7,
            ))

        # Check for Bandit hardcoded credential warnings in tool code
        if bandit_findings.get("hardcoded_credential"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:bandit",
                description="Bandit detected hardcoded credentials in tool code (negative evidence)",
                confidence=0.75,
            ))
            t2_floor = min(t2_floor, 3.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No tool authentication mechanism found"] if t2_floor == 0 else [],
        )

    def _score_d32(
        self,
        control_def: ControlDefinition,
        tool_registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D3.2: Tool Input Schema Validation"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for schema validation in tool registry
        if tool_registry_findings.get("schema_validation"):
            t2_floor = 5.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:tool_registry",
                description="Schema validation configuration detected in tool registry",
                confidence=0.75,
            ))

        # Check for Pydantic model usage in tool handlers
        if codebase_findings.get("pydantic_model"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Pydantic model validation found in tool handlers",
                confidence=0.85,
            ))

        # Check for JSON schema validation patterns
        if codebase_findings.get("json_schema_validation"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="JSON schema validation logic found in tool input processing",
                confidence=0.8,
            ))

        # Check for input validation before execution
        if codebase_findings.get("input_validation"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Input validation enforced before tool execution",
                confidence=0.85,
            ))

        # Check for missing validation (negative evidence)
        if codebase_findings.get("missing_validation"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Tool handlers without input validation detected (negative evidence)",
                confidence=0.8,
            ))
            # Cap T2 if validation is missing in some paths
            t2_floor = min(t2_floor, 3.0)

        # Check for Semgrep input validation warnings
        if semgrep_findings.get("input_validation_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified input validation gaps in tool handlers",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No tool input schema validation found"] if t2_floor == 0 else [],
        )

    def _score_d33(
        self,
        control_def: ControlDefinition,
        tool_registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D3.3: Tool Side-Effect Constraints"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for tool read-only categorization in registry
        if tool_registry_findings.get("tool_read_only"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:tool_registry",
                description="Tool read-only categorization detected in registry",
                confidence=0.8,
            ))

        # Check for side-effect tracking in codebase
        if codebase_findings.get("side_effect_tracking"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Side-effect tracking implementation found in tool dispatcher",
                confidence=0.8,
            ))

        # Check for ACL enforcement on write tools
        if codebase_findings.get("tool_acl_enforcement"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="ACL enforcement on write-capable tools found",
                confidence=0.85,
            ))

        # Check for tool write audit logging
        if codebase_findings.get("tool_write_audit"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Write tool execution audit logging implemented",
                confidence=0.75,
            ))

        # Check for unconstrained write access (negative evidence)
        if tool_registry_findings.get("unconstrained_write"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:tool_registry",
                description="Tools with unconstrained write access detected (negative evidence)",
                confidence=0.85,
            ))
            # Cap T2 if unconstrained write tools exist
            t2_floor = min(t2_floor, 2.5)

        # Check for Semgrep side-effect warnings
        if semgrep_findings.get("side_effect_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified untracked side-effects in tool code",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No tool side-effect constraints found"] if t2_floor == 0 else [],
        )

    def _score_d34(
        self,
        control_def: ControlDefinition,
        tool_registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
        bandit_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D3.4: MCP Server Authentication"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for MCP authentication handshake patterns
        if codebase_findings.get("mcp_auth_handshake"):
            t2_floor = 6.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="MCP client authentication handshake found in connection code",
                confidence=0.85,
            ))

        # Check for MCP server identity verification
        if codebase_findings.get("mcp_server_identity"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="MCP server identity verification before message exchange",
                confidence=0.85,
            ))

        # Check for MCP credential exchange patterns in tool registry
        if tool_registry_findings.get("mcp_credential_exchange"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:tool_registry",
                description="MCP credential exchange configuration in tool registry",
                confidence=0.8,
            ))

        # Check for unauthenticated MCP connections (negative evidence)
        if codebase_findings.get("mcp_unauth_connection"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Unauthenticated MCP server connections detected (negative evidence)",
                confidence=0.9,
            ))
            # Significantly cap T2
            t2_floor = min(t2_floor, 1.5)

        # Check for Semgrep MCP auth warnings
        if semgrep_findings.get("mcp_auth_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified MCP authentication gaps",
                confidence=0.7,
            ))

        # Check for Bandit insecure connection warnings
        if bandit_findings.get("insecure_connection"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:bandit",
                description="Bandit detected insecure connection patterns in MCP code",
                confidence=0.75,
            ))
            t2_floor = min(t2_floor, 2.5)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No MCP server authentication found"] if t2_floor == 0 else [],
        )

    def _score_d35(
        self,
        control_def: ControlDefinition,
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
        bandit_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D3.5: MCP Message Integrity"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for message signing in MCP handlers
        if codebase_findings.get("mcp_message_signing"):
            t2_floor = 7.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="MCP message signing implementation found in protocol handlers",
                confidence=0.85,
            ))

        # Check for encryption in MCP message transport
        if codebase_findings.get("mcp_encryption"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="MCP message encryption implemented in transport layer",
                confidence=0.85,
            ))

        # Check for tamper detection / integrity verification
        if codebase_findings.get("mcp_tamper_detection"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="MCP message tamper detection and integrity verification found",
                confidence=0.9,
            ))

        # Check for HMAC or digest-based validation
        if codebase_findings.get("mcp_hmac_validation"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="HMAC or digest-based message validation in MCP layer",
                confidence=0.8,
            ))

        # Check for missing integrity checks (negative evidence)
        if codebase_findings.get("mcp_no_integrity_check"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="MCP message handling without integrity verification (negative evidence)",
                confidence=0.85,
            ))
            # Cap T2 if integrity checks are missing
            t2_floor = min(t2_floor, 2.0)

        # Check for Semgrep message integrity warnings
        if semgrep_findings.get("message_integrity_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified message integrity gaps in MCP handlers",
                confidence=0.7,
            ))

        # Check for Bandit crypto warnings
        if bandit_findings.get("weak_crypto"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:bandit",
                description="Bandit detected weak cryptographic patterns in MCP code",
                confidence=0.75,
            ))
            t2_floor = min(t2_floor, 3.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No MCP message integrity mechanism found"] if t2_floor == 0 else [],
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
