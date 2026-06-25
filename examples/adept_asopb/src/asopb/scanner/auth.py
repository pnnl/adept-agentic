"""
Authentication Scanner

Detects authentication patterns, session management, API key handling,
and RBAC/ABAC mechanisms.
"""

from __future__ import annotations

import re

from asopb.models import ScanResult, Severity
from asopb.scanner.base import ScannerBase


class AuthScanner(ScannerBase):
    """Detects authentication and authorization patterns.

    Identifies:
    - JWT/token-based authentication modules
    - OAuth/OIDC providers and integrations
    - Identity providers (Keycloak, Auth0, Okta)
    - RBAC/ABAC implementation patterns
    - Session validation and management
    - Dangerous patterns: Optional[str] = None session params without validation
    - API key management and rotation
    - Middleware chains and decorator patterns
    - AUTH_ENABLED/feature flags
    """

    name = "auth"
    description = "Authentication and authorization pattern detection"

    # JWT/Token module patterns
    JWT_PATTERNS = [
        r"import jwt",
        r"from jwt import",
        r"import PyJWT",
        r"from cryptography.jwt",
        r'import\s+\{.*jwt.*\}',  # JS/TS
        r"jose\.jwt",
        r"jsonwebtoken",
        r'"jwt"',
        r'"PyJWT"',
    ]

    # OAuth/OIDC patterns
    OAUTH_PATTERNS = [
        r"oauth\d",
        r"OAuth2Session",
        r"OAuthlib",
        r"authlib",
        r"from authlib",
        r"import authlib",
        r"openid.*connect",
        r"OIDC",
        r"client_id.*client_secret",
        r"authorization.*endpoint",
        r"token.*endpoint",
    ]

    # Identity provider patterns
    IDPROVIDER_PATTERNS = {
        "keycloak": [
            r"keycloak",
            r"Keycloak",
            r"http.*keycloak",
            r"KEYCLOAK_.*",
        ],
        "auth0": [
            r"auth0",
            r"Auth0",
            r"AUTH0_",
            r"auth0\.com",
        ],
        "okta": [
            r"okta",
            r"Okta",
            r"OKTA_",
            r"okta\.com",
        ],
        "cognito": [
            r"cognito",
            r"Cognito",
            r"COGNITO_",
            r"aws.*cognito",
        ],
    }

    # RBAC/ABAC patterns
    RBAC_PATTERNS = [
        r"@.*permission",
        r"@.*role",
        r"check_permission",
        r"has_permission",
        r"check_role",
        r"verify_role",
        r"permission_required",
        r"role_required",
        r"can_access",
        r"is_authorized",
        r"authorize\(",
        r"Authorize\(",
        r"\bRBAC\b",
        r"\bABAC\b",
        r"policy.*decision",
        r"access_control",
        r"acl\.",
        r"ACL\[",
    ]

    # Session validation patterns
    SESSION_PATTERNS = [
        r"session.*validate",
        r"validate.*session",
        r"check_session",
        r"session.*expired",
        r"Session\(",
        r"session_timeout",
        r"verify_session",
        r"@login_required",
        r"LoginRequired",
        r"requires_login",
    ]

    # Dangerous: Optional[str] = None session/auth params without validation
    UNSAFE_SESSION_PATTERNS = [
        r"(?:session|auth|token|credential|secret)\s*:\s*Optional\[str\]\s*=\s*None",
        r"Optional\[str\]\s*=\s*None.*(?:session|auth|token|credential)",
        r"def\s+\w+\([^)]*\s*(?:session|user|auth|token)\s*:\s*Optional\[str\]\s*=\s*None",
    ]

    # API Key patterns
    APIKEY_PATTERNS = [
        r"api_key",
        r"apiKey",
        r"API_KEY",
        r"api\.key",
        r"secret.*key",
        r"private.*key",
        r"access_key",
        r"secret_access_key",
        r"token.*secret",
        r"X-API-Key",
        r"Authorization.*Bearer",
    ]

    # Middleware/decorator patterns
    MIDDLEWARE_PATTERNS = [
        r"@middleware",
        r"@app\.middleware",
        r"@router\.middleware",
        r"middleware\(",
        r"Middleware\(",
        r"class.*Middleware",
        r"@auth.*decorator",
        r"@require_auth",
        r"@protected",
        r"@verify",
    ]

    # Auth enable/disable flags
    AUTH_FLAG_PATTERNS = [
        r"AUTH_ENABLED",
        r"ENABLE_AUTH",
        r"AUTHENTICATION_REQUIRED",
        r"SKIP_AUTH",
        r"disable_auth",
        r"disable_authentication",
        r"auth_enabled\s*=\s*(?:True|False)",
    ]

    async def scan(self) -> ScanResult:
        """Execute authentication scan."""
        result = ScanResult(
            tool_name=self.name,
            tool_version="1.0.0",
        )

        findings = []
        stats = {
            "jwt_detected": False,
            "oauth_detected": False,
            "idproviders": {},
            "rbac_detected": False,
            "session_validation_detected": False,
            "unsafe_session_params": 0,
            "api_key_patterns": 0,
            "middleware_detected": False,
            "auth_flags": 0,
        }

        try:
            # JWT detection
            jwt_matches = self.grep(
                "|".join(self.JWT_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            if jwt_matches:
                stats["jwt_detected"] = True
                findings.append(
                    self._make_finding(
                        "jwt_module_detected",
                        f"JWT module imported: {jwt_matches[0].match_text}",
                        file_path=jwt_matches[0].file_path,
                        line_number=jwt_matches[0].line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # OAuth detection
            oauth_matches = self.grep(
                "|".join(self.OAUTH_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            if oauth_matches:
                stats["oauth_detected"] = True
                findings.append(
                    self._make_finding(
                        "oauth_oidc_detected",
                        f"OAuth/OIDC pattern found: {oauth_matches[0].match_text}",
                        file_path=oauth_matches[0].file_path,
                        line_number=oauth_matches[0].line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Identity provider detection
            for provider, patterns in self.IDPROVIDER_PATTERNS.items():
                matches = self.grep(
                    "|".join(patterns),
                    glob="**/*",
                    ignore_case=True,
                    max_results=1,
                )
                if matches:
                    stats["idproviders"][provider] = True
                    findings.append(
                        self._make_finding(
                            f"idprovider_{provider}",
                            f"Identity provider {provider} detected: {matches[0].match_text}",
                            file_path=matches[0].file_path,
                            line_number=matches[0].line_number,
                            severity=Severity.INFORMATIONAL,
                        )
                    )

            # RBAC/ABAC detection
            rbac_matches = self.grep(
                "|".join(self.RBAC_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            if rbac_matches:
                stats["rbac_detected"] = True
                for match in rbac_matches[:3]:  # Limit to 3 findings
                    findings.append(
                        self._make_finding(
                            "rbac_abac_pattern",
                            f"RBAC/ABAC pattern: {match.match_text}",
                            file_path=match.file_path,
                            line_number=match.line_number,
                            severity=Severity.INFORMATIONAL,
                        )
                    )

            # Session validation detection
            session_matches = self.grep(
                "|".join(self.SESSION_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            if session_matches:
                stats["session_validation_detected"] = True
                findings.append(
                    self._make_finding(
                        "session_validation",
                        f"Session validation pattern: {session_matches[0].match_text}",
                        file_path=session_matches[0].file_path,
                        line_number=session_matches[0].line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Dangerous pattern: Optional[str] = None without validation
            unsafe_matches = self.grep(
                "|".join(self.UNSAFE_SESSION_PATTERNS),
                glob="**/*.py",
                ignore_case=False,
            )
            if unsafe_matches:
                stats["unsafe_session_params"] = len(unsafe_matches)
                for match in unsafe_matches[:5]:  # Limit to 5 findings
                    findings.append(
                        self._make_finding(
                            "unsafe_optional_session_param",
                            f"Optional session/auth parameter without validation: {match.match_text}",
                            file_path=match.file_path,
                            line_number=match.line_number,
                            severity=Severity.HIGH,
                            confidence=0.75,
                        )
                    )

            # API key patterns
            apikey_matches = self.grep(
                "|".join(self.APIKEY_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            if apikey_matches:
                stats["api_key_patterns"] = len(apikey_matches)
                for match in apikey_matches[:3]:
                    findings.append(
                        self._make_finding(
                            "api_key_pattern",
                            f"API key pattern detected: {match.match_text}",
                            file_path=match.file_path,
                            line_number=match.line_number,
                            severity=Severity.MEDIUM,
                            confidence=0.7,
                        )
                    )

            # Middleware detection
            middleware_matches = self.grep(
                "|".join(self.MIDDLEWARE_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            if middleware_matches:
                stats["middleware_detected"] = True
                for match in middleware_matches[:3]:
                    findings.append(
                        self._make_finding(
                            "middleware_chain",
                            f"Middleware pattern: {match.match_text}",
                            file_path=match.file_path,
                            line_number=match.line_number,
                            severity=Severity.INFORMATIONAL,
                        )
                    )

            # Auth flag detection
            auth_flag_matches = self.grep(
                "|".join(self.AUTH_FLAG_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            if auth_flag_matches:
                stats["auth_flags"] = len(auth_flag_matches)
                for match in auth_flag_matches[:3]:
                    findings.append(
                        self._make_finding(
                            "auth_feature_flag",
                            f"Auth flag detected: {match.match_text}",
                            file_path=match.file_path,
                            line_number=match.line_number,
                            severity=Severity.MEDIUM,
                        )
                    )

            result.findings = findings
            result.summary_stats = stats
            result.success = True

        except Exception as e:
            result.success = False
            result.error_message = str(e)

        return result
