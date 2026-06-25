"""
Federation Scanner

Detects A2A (agent-to-agent) federation, cross-facility delegation,
and SSRF prevention patterns.
"""

from __future__ import annotations

import re

from asopb.models import ScanResult, Severity
from asopb.scanner.base import ScannerBase


class FederationScanner(ScannerBase):
    """Detects federation and delegation patterns.

    Identifies:
    - Gateway/registry infrastructure for A2A communication
    - JWKS (JSON Web Key Set) endpoints for key distribution
    - Cross-facility delegation patterns
    - Trust delegation chains
    - CIDR allowlisting
    - SSRF (Server-Side Request Forgery) prevention
    - URL validation and allowlisting
    - Mutual TLS (mTLS) patterns
    - Service mesh integration
    - Policy enforcement
    """

    name = "federation"
    description = "Federation and delegation pattern detection"

    # Gateway/registry patterns
    GATEWAY_PATTERNS = [
        r"gateway",
        r"registry",
        r"service.*registry",
        r"service.*discovery",
        r"endpoint.*registry",
        r"peer.*registry",
        r"agent.*registry",
        r"federation.*gateway",
        r"federation.*coordinator",
    ]

    # JWKS endpoint patterns
    JWKS_PATTERNS = [
        r"\.well-known/jwks",
        r"jwks_uri",
        r"JWKS",
        r"jwks\.json",
        r"get_jwks",
        r"fetch_keys",
        r"key.*endpoint",
        r"public.*key.*endpoint",
    ]

    # Cross-facility delegation patterns
    DELEGATION_PATTERNS = [
        r"delegation",
        r"delegate.*to",
        r"delegated.*call",
        r"delegation.*chain",
        r"transitive.*delegation",
        r"delegation.*policy",
        r"trust.*delegation",
        r"on.*behalf.*of",
        r"impersonation",
    ]

    # CIDR allowlisting patterns
    CIDR_PATTERNS = [
        r"\d+\.\d+\.\d+\.\d+/\d+",  # CIDR notation
        r"allowed.*cidr",
        r"allowed.*ip",
        r"ip.*whitelist",
        r"ip.*allowlist",
        r"cidr.*filter",
        r"cidr.*check",
        r"network.*acl",
    ]

    # SSRF prevention patterns
    SSRF_PATTERNS = [
        r"url.*validate",
        r"validate.*url",
        r"url.*check",
        r"allowed.*domain",
        r"allowed.*url",
        r"url.*allowlist",
        r"url.*whitelist",
        r"domain.*allowlist",
        r"domain.*filter",
        r"is_safe_url",
        r"safe_redirect",
        r"ssrf.*prevent",
    ]

    # URL validation patterns
    URL_VALIDATION_PATTERNS = [
        r"urllib\.parse",
        r"urlparse\(",
        r"validate_url",
        r"is_valid_url",
        r"url_validator",
        r"scheme.*http",
        r"allowed.*scheme",
        r"forbidden.*scheme",
    ]

    # Mutual TLS patterns
    MTLS_PATTERNS = [
        r"mtls",
        r"mTLS",
        r"mutual.*tls",
        r"client.*cert",
        r"certificate.*verify",
        r"verify_peer",
        r"ca.*cert",
        r"tls\.verify",
        r"ssl\.verify",
        r"certificate.*path",
    ]

    # Service mesh patterns
    SERVICE_MESH_PATTERNS = [
        r"istio",
        r"Istio",
        r"linkerd",
        r"Linkerd",
        r"consul",
        r"service.*mesh",
        r"envoy",
        r"Envoy",
        r"sidecar.*proxy",
    ]

    # Policy enforcement patterns
    POLICY_PATTERNS = [
        r"policy.*engine",
        r"policy.*check",
        r"enforce.*policy",
        r"opa",
        r"OPA",
        r"rego",
        r"policy.*as.*code",
        r"kyverno",
        r"policy.*rules",
    ]

    # Trust establishment patterns
    TRUST_PATTERNS = [
        r"verify.*identity",
        r"verify.*agent",
        r"verify.*caller",
        r"trust.*store",
        r"certificate.*chain",
        r"chain.*validation",
        r"trust.*anchor",
        r"root.*ca",
    ]

    async def scan(self) -> ScanResult:
        """Execute federation scanner."""
        result = ScanResult(
            tool_name=self.name,
            tool_version="1.0.0",
        )

        findings = []
        stats = {
            "gateway_patterns": 0,
            "jwks_endpoints": 0,
            "delegation_patterns": 0,
            "cidr_allowlisting": 0,
            "ssrf_prevention": 0,
            "url_validation": 0,
            "mtls_patterns": 0,
            "service_mesh": 0,
            "policy_enforcement": 0,
            "trust_patterns": 0,
        }

        try:
            # Gateway/registry detection
            gateway_matches = self.grep(
                "|".join(self.GATEWAY_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["gateway_patterns"] = len(gateway_matches)
            for match in gateway_matches[:3]:
                findings.append(
                    self._make_finding(
                        "gateway_registry",
                        f"Gateway/registry pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # JWKS endpoint detection
            jwks_matches = self.grep(
                "|".join(self.JWKS_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["jwks_endpoints"] = len(jwks_matches)
            for match in jwks_matches[:3]:
                findings.append(
                    self._make_finding(
                        "jwks_endpoint",
                        f"JWKS endpoint detected: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Delegation patterns
            delegation_matches = self.grep(
                "|".join(self.DELEGATION_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["delegation_patterns"] = len(delegation_matches)
            for match in delegation_matches[:3]:
                findings.append(
                    self._make_finding(
                        "delegation_pattern",
                        f"Delegation pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # CIDR allowlisting
            cidr_matches = self.grep(
                "|".join(self.CIDR_PATTERNS),
                glob="**/*",
                ignore_case=False,
            )
            stats["cidr_allowlisting"] = len(cidr_matches)
            for match in cidr_matches[:3]:
                findings.append(
                    self._make_finding(
                        "cidr_allowlist",
                        f"CIDR allowlisting pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # SSRF prevention
            ssrf_matches = self.grep(
                "|".join(self.SSRF_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["ssrf_prevention"] = len(ssrf_matches)
            for match in ssrf_matches[:3]:
                findings.append(
                    self._make_finding(
                        "ssrf_prevention",
                        f"SSRF prevention pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # URL validation
            url_val_matches = self.grep(
                "|".join(self.URL_VALIDATION_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["url_validation"] = len(url_val_matches)
            for match in url_val_matches[:3]:
                findings.append(
                    self._make_finding(
                        "url_validation",
                        f"URL validation pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # mTLS patterns
            mtls_matches = self.grep(
                "|".join(self.MTLS_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["mtls_patterns"] = len(mtls_matches)
            for match in mtls_matches[:3]:
                findings.append(
                    self._make_finding(
                        "mtls_pattern",
                        f"Mutual TLS pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Service mesh detection
            mesh_matches = self.grep(
                "|".join(self.SERVICE_MESH_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["service_mesh"] = len(mesh_matches)
            for match in mesh_matches[:3]:
                findings.append(
                    self._make_finding(
                        "service_mesh",
                        f"Service mesh integration: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Policy enforcement
            policy_matches = self.grep(
                "|".join(self.POLICY_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["policy_enforcement"] = len(policy_matches)
            for match in policy_matches[:3]:
                findings.append(
                    self._make_finding(
                        "policy_enforcement",
                        f"Policy enforcement: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Trust establishment
            trust_matches = self.grep(
                "|".join(self.TRUST_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["trust_patterns"] = len(trust_matches)
            for match in trust_matches[:3]:
                findings.append(
                    self._make_finding(
                        "trust_establishment",
                        f"Trust establishment pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            result.findings = findings
            result.summary_stats = stats
            result.success = True

        except Exception as e:
            result.success = False
            result.error_message = str(e)

        return result
