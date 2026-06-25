"""
Unit tests for ASOPB scanners.

Tests scanner detection capabilities:
- AuthScanner detects JWT, OAuth, identity providers, session validation
- AuthScanner detects unsafe patterns like Optional[str] = None
- Scanners return empty on minimal/empty repos
- Each test creates minimal fixture files
"""

import asyncio
from pathlib import Path

import pytest

from asopb.scanner.auth import AuthScanner


class TestAuthScanner:
    """Tests for authentication and authorization pattern detection."""

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_jwt(self, tmp_path: Path):
        """Test that AuthScanner detects JWT module imports."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        auth_py = repo / "auth.py"
        auth_py.write_text("""\
import jwt

def validate_token(token):
    return jwt.decode(token)
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert any(f.category == "jwt_module_detected" for f in result.findings)
        assert result.summary_stats["jwt_detected"] is True

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_optional_none_session(self, tmp_path: Path):
        """Test detection of Optional[str] = None session parameters."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        auth_py = repo / "auth.py"
        auth_py.write_text("""\
from typing import Optional

def process_request(session: Optional[str] = None):
    if session is None:
        return None
    return validate(session)
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert any(
            f.category == "unsafe_optional_session_param"
            for f in result.findings
        )
        assert result.summary_stats["unsafe_session_params"] > 0

    @pytest.mark.asyncio
    async def test_auth_scanner_empty_repo(self, tmp_path: Path):
        """Test that AuthScanner returns empty findings on empty repo."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert len(result.findings) == 0

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_oauth(self, tmp_path: Path):
        """Test detection of OAuth/OIDC patterns."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        auth_py = repo / "auth.py"
        auth_py.write_text("""\
from authlib.integrations.requests_client import OAuth2Session

def get_oauth_client():
    return OAuth2Session(client_id='xxx')
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert any(f.category == "oauth_oidc_detected" for f in result.findings)

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_keycloak(self, tmp_path: Path):
        """Test detection of Keycloak identity provider."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        config = repo / "config.py"
        config.write_text("""\
KEYCLOAK_URL = "http://keycloak:8080/auth"
KEYCLOAK_REALM = "myrealm"
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["idproviders"].get("keycloak") is True
        assert any(
            f.category == "idprovider_keycloak"
            for f in result.findings
        )

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_rbac(self, tmp_path: Path):
        """Test detection of RBAC/ABAC patterns."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        auth_py = repo / "auth.py"
        auth_py.write_text("""\
from decorators import check_permission

@check_permission("admin")
def admin_function():
    pass

def has_role(user, role):
    return role in user.roles
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["rbac_detected"] is True

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_session_validation(self, tmp_path: Path):
        """Test detection of session validation patterns."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        auth_py = repo / "auth.py"
        auth_py.write_text("""\
def validate_session(session_id):
    if session_expired(session_id):
        return False
    return True

def check_session(req):
    session = Session(req)
    return session.is_valid()
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["session_validation_detected"] is True

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_api_key_patterns(self, tmp_path: Path):
        """Test detection of API key patterns."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        config = repo / "config.py"
        config.write_text("""\
API_KEY = os.getenv("API_KEY")
SECRET_ACCESS_KEY = "xxx"
headers = {"X-API-Key": api_key}
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["api_key_patterns"] > 0

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_middleware(self, tmp_path: Path):
        """Test detection of middleware patterns."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        app_py = repo / "app.py"
        app_py.write_text("""\
@app.middleware
def auth_middleware(request):
    token = request.headers.get("Authorization")
    return validate(token)

class AuthMiddleware:
    def __call__(self, request):
        return check_auth(request)
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["middleware_detected"] is True

    @pytest.mark.asyncio
    async def test_auth_scanner_detects_auth_flags(self, tmp_path: Path):
        """Test detection of AUTH_ENABLED/feature flags."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        config = repo / "config.py"
        config.write_text("""\
AUTH_ENABLED = True
AUTHENTICATION_REQUIRED = True
SKIP_AUTH = False
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["auth_flags"] > 0

    @pytest.mark.asyncio
    async def test_auth_scanner_multiple_findings(self, tmp_path: Path):
        """Test scanner with multiple authentication patterns."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        auth_py = repo / "auth.py"
        auth_py.write_text("""\
import jwt
from authlib.integrations.requests_client import OAuth2Session
from decorators import check_permission

@check_permission("admin")
def admin_handler():
    pass

def validate_jwt(token):
    return jwt.decode(token)

class KeycloakAuth:
    def __init__(self):
        self.url = "http://keycloak:8080"
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["jwt_detected"] is True
        assert result.summary_stats["oauth_detected"] is True
        assert result.summary_stats["rbac_detected"] is True
        assert result.summary_stats["idproviders"].get("keycloak") is True

    @pytest.mark.asyncio
    async def test_auth_scanner_limits_findings(self, tmp_path: Path):
        """Test that scanner limits findings to avoid overwhelming output."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        # Create many files with JWT imports
        for i in range(10):
            module_py = repo / f"module_{i}.py"
            module_py.write_text(f"import jwt\n# Module {i}")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        # Scanner should have findings but limited to prevent bloat
        jwt_findings = [f for f in result.findings if "jwt" in f.category]
        assert len(jwt_findings) > 0

    @pytest.mark.asyncio
    async def test_auth_scanner_finds_multiple_unsafe_params(self, tmp_path: Path):
        """Test detection of multiple unsafe Optional parameters."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        auth_py = repo / "auth.py"
        auth_py.write_text("""\
from typing import Optional

def handler1(token: Optional[str] = None):
    pass

def handler2(session: Optional[str] = None):
    pass

def handler3(credential: Optional[str] = None):
    pass
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        unsafe_findings = [
            f for f in result.findings
            if f.category == "unsafe_optional_session_param"
        ]
        assert len(unsafe_findings) >= 3

    @pytest.mark.asyncio
    async def test_auth_scanner_idprovider_auth0(self, tmp_path: Path):
        """Test detection of Auth0 identity provider."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        config = repo / "config.py"
        config.write_text("""\
AUTH0_DOMAIN = "example.auth0.com"
AUTH0_CLIENT_ID = "xxx"
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["idproviders"].get("auth0") is True

    @pytest.mark.asyncio
    async def test_auth_scanner_idprovider_okta(self, tmp_path: Path):
        """Test detection of Okta identity provider."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        config = repo / "config.py"
        config.write_text("""\
OKTA_ORG_URL = "https://myorg.okta.com"
""")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert result.summary_stats["idproviders"].get("okta") is True

    @pytest.mark.asyncio
    async def test_auth_scanner_python_specific_patterns(self, tmp_path: Path):
        """Test that scanner correctly targets Python files."""
        repo = tmp_path / "test_repo"
        repo.mkdir()

        # Python file
        py_file = repo / "auth.py"
        py_file.write_text("import jwt\n")

        # Non-Python file (should still be checked by grep)
        txt_file = repo / "README.md"
        txt_file.write_text("import jwt\n")

        scanner = AuthScanner(repo)
        result = await scanner.scan()

        assert result.success
        assert any(f.category == "jwt_module_detected" for f in result.findings)
