"""
D4: Identity and Authentication Domain Evaluator

"The sharpest application-platform boundary marker" per ASOPB paper.
Assesses how agents prove identity, validate sessions, and authenticate
service-to-service communication in agentic systems.

Controls:
  D4.1: Agent identity attestation (do agents have verifiable identities?)
  D4.2: Workload identity (SPIFFE/SPIRE or equivalent)
  D4.3: JWKS/JWT federation (cross-service token validation)
  D4.4: Delegation chain authentication (authenticated task delegation)
  D4.5: Session token validation (session params validated vs Optional[str]=None)
  D4.6: mTLS internal communication (service-to-service encryption)
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


class D4IdentityEvaluator(DomainEvaluator):
    """Identity and Authentication domain evaluator."""

    domain_id = "D4"
    domain_name = "Identity and Authentication"
    weight = 1.0
    skill_file = "d4_identity.md"

    def define_controls(self) -> list[ControlDefinition]:
        """Define D4 controls for identity and authentication."""
        return [
            ControlDefinition(
                control_id="D4.1",
                domain_id="D4",
                name="Agent Identity Attestation",
                description=(
                    "Agents have cryptographically verifiable identities through "
                    "certificates, key material, or attestation tokens. Each agent can prove "
                    "its identity to other components in the system without relying solely "
                    "on network-based authentication."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S1", "S2", "S3", "S4"],
                t1_criteria=[
                    "Architecture document describes agent identity scheme (cert-based, key-based, or token-based)",
                    "Agent identity is distinct from user identity in design",
                    "Attestation/proof mechanism is defined (e.g., X.509 cert, key material, signed claims)",
                ],
                t2_criteria=[
                    "Agent identity implementation found in code (cert loading, key initialization)",
                    "Identity proof is performed in initialization or handshake code",
                    "Evidence of identity validation in inter-agent communication",
                ],
                t3_criteria=[
                    "Red-team confirms agent identity cannot be spoofed",
                    "Attacker cannot impersonate an agent without access to identity material",
                ],
                positive_patterns=[
                    r"agent.*identity|agent.*cert|agent.*key",
                    r"spiffe|spire",
                    r"agent.*attestation|agent.*proof",
                    r"certificate.*agent|cert.*identity",
                ],
                negative_patterns=[
                    r"agent.*=.*None|agent.*identity.*=.*None",
                    r"skip.*identity|bypass.*identity",
                    r"TODO.*identity|FIXME.*identity",
                ],
                nist_mapping=["IA-2", "IA-3", "IA-5"],
                owasp_mapping=["LLM01", "LLM05"],
                cwe_mapping=["CWE-287", "CWE-295"],
                tags=["authentication", "agent", "identity", "critical"],
            ),
            ControlDefinition(
                control_id="D4.2",
                domain_id="D4",
                name="Workload Identity (SPIFFE/SPIRE)",
                description=(
                    "Agents obtain and maintain workload identities via standard protocols "
                    "(SPIFFE/SPIRE, cloud provider workload identity, etc.). Identities are "
                    "automatically provisioned, rotated, and verified without manual secret management."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Design specifies workload identity mechanism (SPIFFE/SPIRE, AWS IAM, GCP Workload Identity, etc.)",
                    "Automatic identity provisioning and rotation is described",
                    "No manual secret or API key management for agent identity",
                ],
                t2_criteria=[
                    "SPIFFE/SPIRE client library initialization found in code",
                    "Workload identity API calls present (e.g., SPIFFE socket, cloud metadata service)",
                    "Evidence of automatic credential refresh or rotation",
                ],
                t3_criteria=[
                    "Red-team confirms workload identity cannot be hijacked",
                    "Credential rotation under attack conditions works correctly",
                ],
                positive_patterns=[
                    r"spiffe|spire",
                    r"workload.*identity|workload.*cred",
                    r"auto.*provision|auto.*rotate",
                    r"x-spiffe-trust-domain",
                ],
                negative_patterns=[
                    r"static.*secret|hardcoded.*key|hardcoded.*token",
                    r"manual.*provision|manual.*rotate",
                ],
                nist_mapping=["IA-3", "IA-5", "SC-7"],
                owasp_mapping=["LLM05"],
                cwe_mapping=["CWE-798"],
                tags=["workload-identity", "spiffe", "spire", "provisioning"],
            ),
            ControlDefinition(
                control_id="D4.3",
                domain_id="D4",
                name="JWKS/JWT Federation",
                description=(
                    "Cross-service token validation uses JWKS (JSON Web Key Sets) "
                    "and JWT (JSON Web Tokens) for federated identity. Token validators "
                    "fetch public keys from issuer JWKS endpoints; tokens carry claims "
                    "that are cryptographically verified."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "JWT token format is specified for inter-agent communication",
                    "Token issuer (STS, Keycloak, etc.) is defined",
                    "JWKS endpoint or key distribution mechanism is documented",
                    "Token claims (sub, aud, iss) are defined per RFC 7519",
                ],
                t2_criteria=[
                    "JWT validation library imported and initialized (e.g., PyJWT, jose, golang jwt)",
                    "JWKS endpoint fetch logic found in code",
                    "Token signature verification implemented",
                    "Token claims validation (exp, aud, iss) in code",
                ],
                t3_criteria=[
                    "Red-team cannot forge or tamper with tokens",
                    "Token validators correctly reject invalid/expired tokens",
                    "JWKS key rotation does not allow token replay",
                ],
                positive_patterns=[
                    r"jwt|jwks|json.*web.*key",
                    r"jwt.*verify|jwt.*validate|jwt.*decode",
                    r"keycloak|auth0|okta",
                    r'claims.*["\']aud["\']|claims.*["\']iss["\']|claims.*["\']sub["\']',
                ],
                negative_patterns=[
                    r"jwt.*=.*None|skip.*verify|skip.*validation",
                    r"verify.*=.*False|verify.*=.*None",
                    r"token.*optional|Optional\[.*token",
                ],
                nist_mapping=["IA-2", "IA-5", "SA-3"],
                owasp_mapping=["LLM01", "LLM05"],
                cwe_mapping=["CWE-347", "CWE-295"],
                tags=["jwt", "federation", "token-validation", "jwks"],
            ),
            ControlDefinition(
                control_id="D4.4",
                domain_id="D4",
                name="Delegation Chain Authentication",
                description=(
                    "When an agent delegates work to another agent or tool, the delegation "
                    "is authenticated and traceable. The receiving agent can verify who initiated "
                    "the delegation and what authority was delegated (e.g., via delegation tokens "
                    "or scoped credentials)."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Delegation mechanism is explicitly designed (scoped tokens, delegation claims, etc.)",
                    "Delegation chain traceability is documented (audit trail)",
                    "Authority/scope constraints on delegation are defined",
                ],
                t2_criteria=[
                    "Delegation token or credential passing found in code",
                    "Original agent identity preserved in delegation chain (via claims or headers)",
                    "Scope/permission constraints enforced before accepting delegated work",
                ],
                t3_criteria=[
                    "Red-team cannot escalate privileges via delegation",
                    "Agent cannot delegate more authority than it possesses",
                ],
                positive_patterns=[
                    r"delegation|delegate",
                    r"scope.*token|scoped.*cred",
                    r"delegation.*chain|chain.*delegation",
                    r"forward.*auth|proxy.*auth|impersonate",
                ],
                negative_patterns=[
                    r"delegation.*Optional|delegate.*=.*None",
                    r"skip.*scope|bypass.*scope",
                    r"TODO.*delegation|FIXME.*delegation",
                ],
                nist_mapping=["IA-4", "IA-5", "AC-2"],
                owasp_mapping=["LLM01"],
                cwe_mapping=["CWE-269", "CWE-284"],
                tags=["delegation", "authority", "traceability"],
            ),
            ControlDefinition(
                control_id="D4.5",
                domain_id="D4",
                name="Session Token Validation",
                description=(
                    "Session tokens are validated for: presence, expiration, signature, "
                    "and claims. Session parameters are never optional strings; token handling "
                    "includes proper error handling for invalid/missing tokens."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Session token format is defined (JWT, opaque token, etc.)",
                    "Validation rules for token expiration, signature, and claims are specified",
                    "Invalid/missing token handling is defined (reject vs. challenge)",
                ],
                t2_criteria=[
                    "Session token parameters are NOT Optional[str] (strongly typed)",
                    "Token validation called on every request/operation (no skip paths)",
                    "Token expiration checked in code (not just at load time)",
                    "Error handling for invalid tokens (400/403 response or exception)",
                ],
                t3_criteria=[
                    "Red-team cannot bypass token validation",
                    "Expired or tampered tokens are rejected",
                    "Session fixation attacks are prevented",
                ],
                positive_patterns=[
                    r"session.*token|token.*session",
                    r"validate.*token|check.*token|verify.*token",
                    r"token.*expir|expir.*token",
                    r"required.*token|mandatory.*token",
                ],
                negative_patterns=[
                    r"Optional\[.*token|token.*=.*None",
                    r"skip.*token|bypass.*token",
                    r"token.*optional",
                    r"session.*Optional",
                ],
                nist_mapping=["IA-2", "IA-5", "IA-8"],
                owasp_mapping=["LLM01", "LLM05"],
                cwe_mapping=["CWE-613", "CWE-384"],
                tags=["session", "token-validation", "expiration"],
            ),
            ControlDefinition(
                control_id="D4.6",
                domain_id="D4",
                name="mTLS Internal Communication",
                description=(
                    "Service-to-service (internal) communication is encrypted and "
                    "authenticated via mutual TLS (mTLS). Both client and server "
                    "authenticate using certificates; certificate verification is mandatory."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "mTLS is specified for all internal service-to-service communication",
                    "Client and server certificate verification is required",
                    "Certificate pinning or issuer trust is defined",
                ],
                t2_criteria=[
                    "TLS client initialization with verify=True (or equivalent enforcement)",
                    "Server TLS configuration enforces mutual authentication (require_client_cert)",
                    "No verify=False or InsecureSkipVerify in internal communication paths",
                    "Certificate loading and validation in code",
                ],
                t3_criteria=[
                    "Red-team cannot establish internal connections without valid certificates",
                    "MITM attacks are prevented via certificate verification",
                    "Certificate rotation does not break service communication",
                ],
                positive_patterns=[
                    r"mtls|mutual.*tls|mTLS",
                    r"verify.*=.*True|verify.*cert",
                    r"client.*cert|tls.*cert",
                    r"require.*client.*cert|client.*auth",
                ],
                negative_patterns=[
                    r"verify.*=.*False|InsecureSkipVerify",
                    r"skip.*verify|bypass.*verify",
                    r"insecure|allow.*insecure",
                ],
                nist_mapping=["SC-7", "SC-8", "SC-12"],
                owasp_mapping=["LLM05"],
                cwe_mapping=["CWE-295", "CWE-347"],
                tags=["mtls", "encryption", "authentication", "critical"],
            ),
        ]

    def required_scanners(self) -> list[str]:
        """Scanners required for D4 evaluation."""
        return ["auth", "codebase"]

    def required_analyzers(self) -> list[str]:
        """Analyzers that enhance D4 scoring."""
        return ["tls", "semgrep", "bandit"]

    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score D4 controls using auth scanner, codebase, TLS, Semgrep, and Bandit findings.

        Strategy:
          1. Use auth scanner to detect auth modules, JWT validation, OAuth/Keycloak integration
          2. Use TLS analyzer to count verify=False and verify=None occurrences
          3. Use Semgrep/Bandit for auth-related vulnerabilities
          4. Map findings to specific controls
          5. Set T2 floor based on presence of critical patterns + evidence density
        """
        controls = self.define_controls()
        scores: list[ControlScore] = []

        # Extract findings by category for quick lookup
        auth_findings = self._extract_findings_by_category(scan_results.get("auth"))
        codebase_findings = self._extract_findings_by_category(scan_results.get("codebase"))
        tls_findings = self._extract_findings_by_category(analyzer_results.get("tls"))
        semgrep_findings = self._extract_findings_by_category(analyzer_results.get("semgrep"))
        bandit_findings = self._extract_findings_by_category(analyzer_results.get("bandit"))

        # D4.1: Agent Identity Attestation
        score_d41 = self._score_d41(
            controls[0],
            auth_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d41)

        # D4.2: Workload Identity
        score_d42 = self._score_d42(
            controls[1],
            auth_findings,
            codebase_findings,
        )
        scores.append(score_d42)

        # D4.3: JWKS/JWT Federation
        score_d43 = self._score_d43(
            controls[2],
            auth_findings,
            codebase_findings,
            semgrep_findings,
            bandit_findings,
        )
        scores.append(score_d43)

        # D4.4: Delegation Chain Authentication
        score_d44 = self._score_d44(
            controls[3],
            auth_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d44)

        # D4.5: Session Token Validation
        score_d45 = self._score_d45(
            controls[4],
            auth_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d45)

        # D4.6: mTLS Internal Communication
        score_d46 = self._score_d46(
            controls[5],
            auth_findings,
            tls_findings,
            semgrep_findings,
        )
        scores.append(score_d46)

        return scores

    # ------------------------------------------------------------------
    # Per-Control Scoring Logic
    # ------------------------------------------------------------------

    def _score_d41(
        self,
        control_def: ControlDefinition,
        auth_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D4.1: Agent Identity Attestation"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for agent identity patterns in auth scanner
        if auth_findings.get("agent_identity_module"):
            t2_floor = 5.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="Agent identity module detected in codebase",
                confidence=0.8,
            ))

        # Check for cert/key initialization patterns in codebase
        if codebase_findings.get("cert_loading") or codebase_findings.get("key_initialization"):
            t2_floor = max(t2_floor, 6.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Certificate loading or key initialization found in code",
                confidence=0.75,
            ))

        # Check for SPIFFE/SPIRE patterns
        if auth_findings.get("spiffe_spire"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="SPIFFE/SPIRE workload identity patterns detected",
                confidence=0.9,
            ))

        # Check for Semgrep warnings about identity
        if semgrep_findings.get("identity_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified potential identity validation gaps",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No agent identity attestation found"] if t2_floor == 0 else [],
        )

    def _score_d42(
        self,
        control_def: ControlDefinition,
        auth_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D4.2: Workload Identity (SPIFFE/SPIRE)"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for SPIFFE/SPIRE patterns
        if auth_findings.get("spiffe_spire"):
            t2_floor = 8.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="SPIFFE/SPIRE workload identity implementation found",
                confidence=0.9,
            ))

        # Check for automatic provisioning/rotation patterns
        if codebase_findings.get("auto_provision") or codebase_findings.get("auto_rotate"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Automatic identity provisioning or rotation logic found",
                confidence=0.75,
            ))

        # Check for cloud workload identity (AWS IAM, GCP Workload Identity)
        if auth_findings.get("cloud_workload_identity"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="Cloud provider workload identity integration detected",
                confidence=0.85,
            ))

        # Check for static secrets (negative evidence)
        if codebase_findings.get("static_secret"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Static secrets or hardcoded credentials detected (negative evidence)",
                confidence=0.8,
            ))
            # Cap T2 if static secrets present
            t2_floor = min(t2_floor, 2.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No automatic workload identity provisioning found"] if t2_floor < 5 else [],
        )

    def _score_d43(
        self,
        control_def: ControlDefinition,
        auth_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
        bandit_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D4.3: JWKS/JWT Federation"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for JWT validation patterns
        if auth_findings.get("jwt_validation"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="JWT validation logic found in codebase",
                confidence=0.8,
            ))

        # Check for JWKS endpoint fetching
        if codebase_findings.get("jwks_endpoint"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="JWKS endpoint fetch logic detected",
                confidence=0.75,
            ))

        # Check for token signature verification
        if codebase_findings.get("token_signature_verify"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Token signature verification implemented",
                confidence=0.8,
            ))

        # Check for token claims validation
        if codebase_findings.get("token_claims_validation"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Token claims (exp, aud, iss) validation found",
                confidence=0.8,
            ))

        # Check for OAuth/Keycloak/Auth0 integration
        if auth_findings.get("oauth_integration") or auth_findings.get("keycloak"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="OAuth/Keycloak/STS integration detected",
                confidence=0.8,
            ))

        # Check for Semgrep JWT warnings
        if semgrep_findings.get("jwt_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified JWT validation issues",
                confidence=0.7,
            ))

        # Check for Bandit JWT warnings
        if bandit_findings.get("jwt_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:bandit",
                description="Bandit identified JWT security concerns",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=4.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No JWT validation or JWKS integration found"] if t2_floor == 0 else [],
        )

    def _score_d44(
        self,
        control_def: ControlDefinition,
        auth_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D4.4: Delegation Chain Authentication"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for delegation patterns in auth scanner
        if auth_findings.get("delegation"):
            t2_floor = 5.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="Delegation authentication patterns detected",
                confidence=0.75,
            ))

        # Check for scoped credentials/tokens
        if codebase_findings.get("scoped_token") or codebase_findings.get("scoped_cred"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Scoped token or credential passing found",
                confidence=0.75,
            ))

        # Check for chain traceability (audit trail)
        if codebase_findings.get("delegation_traceability"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Delegation chain traceability/audit found",
                confidence=0.7,
            ))

        # Check for Semgrep delegation warnings
        if semgrep_findings.get("delegation_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified potential delegation gaps",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No delegation authentication mechanism found"] if t2_floor == 0 else [],
        )

    def _score_d45(
        self,
        control_def: ControlDefinition,
        auth_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D4.5: Session Token Validation"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for session token validation in auth scanner
        if auth_findings.get("session_validation"):
            t2_floor = 5.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="Session token validation logic found",
                confidence=0.8,
            ))

        # Check for token expiration checks
        if codebase_findings.get("token_expiration"):
            t2_floor = max(t2_floor, 6.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Token expiration validation in code",
                confidence=0.75,
            ))

        # Check for strong typing (NOT Optional[str])
        if codebase_findings.get("required_token"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Session token parameters are required (not Optional)",
                confidence=0.8,
            ))

        # Check for Optional[str] token parameters (negative evidence)
        if codebase_findings.get("optional_token"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Session token marked as Optional[str] (negative evidence)",
                confidence=0.85,
            ))
            # Significantly cap T2
            t2_floor = min(t2_floor, 2.0)

        # Check for token error handling
        if codebase_findings.get("token_error_handling"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Proper error handling for invalid/missing tokens",
                confidence=0.75,
            ))

        # Check for Semgrep session warnings
        if semgrep_findings.get("session_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified session validation gaps",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No session token validation found"] if t2_floor == 0 else [],
        )

    def _score_d46(
        self,
        control_def: ControlDefinition,
        auth_findings: dict[str, list[ScanFinding]],
        tls_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D4.6: mTLS Internal Communication"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for mTLS patterns in auth scanner
        if auth_findings.get("mtls"):
            t2_floor = 7.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="mTLS (mutual TLS) configuration found",
                confidence=0.85,
            ))

        # Count verify=False occurrences (TLS analyzer)
        verify_false_count = len(tls_findings.get("verify_false", []))
        if verify_false_count == 0 and auth_findings.get("tls_verify_true"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:tls",
                description="TLS verification enabled in all client connections",
                confidence=0.9,
            ))
        elif verify_false_count > 0:
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:tls",
                description=f"Found {verify_false_count} instances of verify=False in TLS clients (negative evidence)",
                confidence=0.95,
            ))
            # Significantly cap T2
            t2_floor = min(t2_floor, 1.0)

        # Check for client certificate requirements
        if auth_findings.get("client_cert_required"):
            t2_floor = max(t2_floor, 8.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="Client certificate validation required on server side",
                confidence=0.85,
            ))

        # Check for certificate pinning
        if auth_findings.get("certificate_pinning"):
            t2_floor = max(t2_floor, 9.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:auth",
                description="Certificate pinning or issuer trust constraints found",
                confidence=0.8,
            ))

        # Check for Semgrep TLS warnings
        if semgrep_findings.get("tls_issue"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified TLS/mTLS configuration issues",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=4.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No mTLS configuration found"] if t2_floor == 0 else ["verify=False found in TLS clients"] if verify_false_count > 0 else [],
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
