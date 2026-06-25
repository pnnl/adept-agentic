"""
Shared pytest fixtures for ASOPB test suite.

Provides:
- Temporary repository fixtures with minimal structure
- Sample evaluation report fixtures
- Configuration fixtures with LLM disabled
- Evidence store fixtures
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line(
        "markers", "llm: marks tests that depend on LLM (deselect with '-m \"not llm\"')"
    )


from asopb.config import EvalConfig, LLMConfig
from asopb.evidence_store import EvidenceStore
from asopb.models import (
    Applicability,
    ControlEvidence,
    ControlScore,
    ControlStatus,
    DomainResult,
    EvaluationReport,
    EvidenceSource,
    EvidenceTier,
    FrameworkVersion,
    ScanFinding,
    ScanResult,
    Severity,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repository structure with pyproject.toml and src/ directory."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Create pyproject.toml
    pyproject = repo / "pyproject.toml"
    pyproject.write_text("""\
[project]
name = "test-agent"
version = "0.1.0"
dependencies = [
    "pydantic>=2.0",
    "requests",
]
""")

    # Create src directory with some Python files
    src = repo / "src"
    src.mkdir()

    agent_py = src / "agent.py"
    agent_py.write_text("""\
from typing import Optional

class Agent:
    def __init__(self):
        self.session: Optional[str] = None

    async def run(self):
        return "running"
""")

    tools_py = src / "tools.py"
    tools_py.write_text("""\
def register_tools(agent):
    agent.tools = ["tool1", "tool2"]

def execute_tool(name, args):
    return f"Executed {name}"
""")

    return repo


@pytest.fixture
def tmp_repo_with_auth(tmp_repo: Path) -> Path:
    """Extend tmp_repo with authentication patterns."""
    auth_py = tmp_repo / "src" / "auth.py"
    auth_py.write_text("""\
import jwt
from typing import Optional

class KeycloakAuth:
    def __init__(self, url: str):
        self.url = url

    def validate_token(self, token: str) -> dict:
        return jwt.decode(token, options={"verify_signature": False})

    def get_jwks(self):
        return {"keys": []}
""")

    docker_compose = tmp_repo / "docker-compose.yaml"
    docker_compose.write_text("""\
version: "3.8"
services:
  keycloak:
    image: quay.io/keycloak/keycloak:latest
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: change_me
""")

    return tmp_repo


@pytest.fixture
def tmp_repo_with_tools(tmp_repo: Path) -> Path:
    """Extend tmp_repo with tool registration patterns."""
    tools_py = tmp_repo / "src" / "tools.py"
    tools_py.write_text("""\
from typing import Callable, Optional

def register_tools(agent, allowed_permissions: Optional[list[str]] = None):
    '''Register available tools with optional ACL filtering.'''
    all_tools = {
        "search": {"name": "search", "description": "Search the web"},
        "exec": {"name": "exec", "description": "Execute shell commands"},
        "read_file": {"name": "read_file", "description": "Read file"},
    }

    if allowed_permissions:
        agent.tools = {k: v for k, v in all_tools.items() if k in allowed_permissions}
    else:
        agent.tools = all_tools

def apply_acl(tool_name: str, user_permissions: list[str]) -> bool:
    return tool_name in user_permissions
""")

    return tmp_repo


@pytest.fixture
def sample_config() -> EvalConfig:
    """Return an EvalConfig with LLM disabled for deterministic testing."""
    return EvalConfig(
        skip_llm=True,
        verbose=False,
        llm=LLMConfig(model="claude-sonnet-4-20250514"),
    )


@pytest.fixture
def evidence_store() -> EvidenceStore:
    """Return an in-memory EvidenceStore."""
    return EvidenceStore(db_path=None)


@pytest.fixture
def sample_scan_result() -> ScanResult:
    """Return a pre-built ScanResult with realistic findings."""
    findings = [
        ScanFinding(
            finding_id="auth:jwt_module:src/auth.py:1",
            category="jwt_module_detected",
            severity=Severity.INFORMATIONAL,
            file_path="src/auth.py",
            line_number=1,
            message="JWT module imported",
            snippet='import jwt',
            confidence=0.9,
        ),
        ScanFinding(
            finding_id="auth:keycloak:src/auth.py:5",
            category="idprovider_keycloak",
            severity=Severity.INFORMATIONAL,
            file_path="src/auth.py",
            line_number=5,
            message="Keycloak integration detected",
            snippet='keycloak_url = os.getenv("KEYCLOAK_URL")',
            confidence=0.85,
        ),
    ]

    return ScanResult(
        tool_name="auth",
        tool_version="1.0.0",
        success=True,
        findings=findings,
        summary_stats={
            "jwt_detected": True,
            "oauth_detected": False,
            "idproviders": {"keycloak": True},
            "rbac_detected": False,
        },
    )


@pytest.fixture
def sample_domain_result() -> DomainResult:
    """Return a pre-built DomainResult with sample controls."""
    controls = [
        ControlScore(
            control_id="D4.1",
            control_name="Agent Identity Attestation",
            status=ControlStatus.PARTIALLY_IMPLEMENTED,
            t1_score=5.0,
            t2_score=3.0,
            t3_score=0.0,
            t1_floor=3.0,
            t2_floor=3.0,
            evidence=[
                ControlEvidence(
                    tier=EvidenceTier.T2_IMPLEMENTATION,
                    source=EvidenceSource.SCANNER,
                    source_tool="scanner:auth",
                    description="JWT module detected",
                    confidence=0.9,
                )
            ],
        ),
        ControlScore(
            control_id="D4.3",
            control_name="JWKS/JWT Federation",
            status=ControlStatus.PARTIALLY_IMPLEMENTED,
            t1_score=6.0,
            t2_score=5.0,
            t3_score=2.0,
            t1_floor=0.0,
            t2_floor=5.0,
            evidence=[
                ControlEvidence(
                    tier=EvidenceTier.T2_IMPLEMENTATION,
                    source=EvidenceSource.SCANNER,
                    source_tool="scanner:auth",
                    description="JWT validation found",
                    confidence=0.85,
                )
            ],
        ),
    ]

    return DomainResult(
        domain_id="D4",
        domain_name="Identity and Authentication",
        applicability=Applicability.APPLICABLE,
        weight=1.0,
        controls=controls,
        summary="Domain controls are partially implemented with JWT support detected.",
    )


@pytest.fixture
def sample_evaluation_report(sample_domain_result: DomainResult) -> EvaluationReport:
    """Return a complete EvaluationReport with all domains."""
    framework = FrameworkVersion(
        name="test-agentic-framework",
        version="1.0.0",
        git_commit="abc123def456",
        snapshot_date=datetime.now(timezone.utc),
    )

    domains = {
        "D4": sample_domain_result,
        "D1": DomainResult(
            domain_id="D1",
            domain_name="Foundation Model Integrity",
            applicability=Applicability.APPLICABLE,
            weight=1.5,
            controls=[
                ControlScore(
                    control_id="D1.1",
                    control_name="Model Provenance",
                    status=ControlStatus.PARTIALLY_IMPLEMENTED,
                    t1_score=5.0,
                    t2_score=4.0,
                    t3_score=0.0,
                )
            ],
        ),
        "D5": DomainResult(
            domain_id="D5",
            domain_name="Federation and Trust",
            applicability=Applicability.NOT_APPLICABLE,
        ),
    }

    return EvaluationReport(
        report_id="asopb-test-20250329-120000",
        framework=framework,
        timestamp=datetime.now(timezone.utc),
        asopb_version="1.0.0",
        config_snapshot={"skip_llm": True},
        domains=domains,
        scan_results={},
        analyzer_results={},
        evaluation_duration_seconds=15.5,
        llm_calls_made=0,
    )


@pytest.fixture
def minimal_agent_fixture_dir(tmp_path: Path) -> Path:
    """Create /sessions/stoic-clever-ptolemy/asopb/tests/fixtures/minimal_agent/."""
    fixtures_base = Path("/sessions/stoic-clever-ptolemy/asopb/tests/fixtures")
    fixtures_base.mkdir(parents=True, exist_ok=True)

    minimal = fixtures_base / "minimal_agent"
    minimal.mkdir(exist_ok=True)

    # pyproject.toml
    (minimal / "pyproject.toml").write_text("""\
[project]
name = "minimal-agent"
version = "0.1.0"
dependencies = [
    "pydantic>=2.0",
    "langchain>=0.1.0",
]
""")

    # src/agent.py
    src = minimal / "src"
    src.mkdir(exist_ok=True)

    (src / "agent.py").write_text("""\
import asyncio
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.tools import tool

class SimpleAgent:
    def __init__(self):
        self.tools = []

    async def run(self, query: str):
        return f"Response to: {query}"

    def register_tools(self):
        self.tools = ["search", "calculator"]

agent = SimpleAgent()
agent.register_tools()
""")

    (src / "tools.py").write_text("""\
def search(query: str) -> str:
    return f"Search results for {query}"

def calculator(expr: str) -> float:
    return eval(expr)

def register_tools(agent):
    agent.tools = [search, calculator]
""")

    return minimal


@pytest.fixture
def agent_with_auth_fixture_dir(tmp_path: Path) -> Path:
    """Create /sessions/stoic-clever-ptolemy/asopb/tests/fixtures/agent_with_auth/."""
    fixtures_base = Path("/sessions/stoic-clever-ptolemy/asopb/tests/fixtures")
    fixtures_base.mkdir(parents=True, exist_ok=True)

    with_auth = fixtures_base / "agent_with_auth"
    with_auth.mkdir(exist_ok=True)

    # pyproject.toml
    (with_auth / "pyproject.toml").write_text("""\
[project]
name = "agent-with-auth"
version = "0.1.0"
dependencies = [
    "pydantic>=2.0",
    "langchain>=0.1.0",
    "PyJWT>=2.8.0",
    "requests>=2.31.0",
]
""")

    # src/agent.py
    src = with_auth / "src"
    src.mkdir(exist_ok=True)

    (src / "agent.py").write_text("""\
import asyncio
from typing import Optional
from auth import KeycloakAuth

class SecureAgent:
    def __init__(self, auth: KeycloakAuth):
        self.auth = auth
        self.user_token: Optional[str] = None
        self.tools = []

    async def run(self, query: str, token: str):
        await self.validate_token(token)
        return f"Authorized response to: {query}"

    async def validate_token(self, token: str):
        claims = self.auth.validate_token(token)
        if not claims:
            raise ValueError("Invalid token")
        self.user_token = token

    def register_tools(self, allowed: Optional[list[str]] = None):
        all_tools = ["search", "calculator", "exec"]
        self.tools = [t for t in all_tools if allowed is None or t in allowed]
""")

    (src / "auth.py").write_text("""\
import jwt
import requests
from typing import Optional, Dict, Any

class KeycloakAuth:
    def __init__(self, realm_url: str):
        self.realm_url = realm_url
        self.jwks_cache: Optional[Dict[str, Any]] = None

    def validate_token(self, token: str) -> Dict[str, Any]:
        '''Validate JWT token against Keycloak JWKS.'''
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")

            jwks = self.get_jwks()
            key_data = self._find_key(jwks, kid)

            if not key_data:
                raise ValueError(f"Key {kid} not found in JWKS")

            claims = jwt.decode(
                token,
                key_data,
                algorithms=["RS256"],
                options={"verify_signature": True},
            )
            return claims
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")

    def get_jwks(self) -> Dict[str, Any]:
        '''Fetch JWKS from Keycloak realm.'''
        if self.jwks_cache:
            return self.jwks_cache

        url = f"{self.realm_url}/protocol/openid-connect/certs"
        response = requests.get(url)
        response.raise_for_status()
        self.jwks_cache = response.json()
        return self.jwks_cache

    def _find_key(self, jwks: Dict[str, Any], kid: str) -> Optional[str]:
        '''Find a key in JWKS by kid.'''
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return key_data
        return None
""")

    (src / "tools.py").write_text("""\
from typing import Optional
from auth import KeycloakAuth

class ToolManager:
    def __init__(self, auth: KeycloakAuth):
        self.auth = auth
        self.user_token: Optional[str] = None

    def register_tools(self, agent, token: str, allowed_permissions: Optional[list[str]] = None):
        '''Register tools with ACL filtering based on user permissions.'''
        claims = self.auth.validate_token(token)
        user_perms = claims.get("permissions", [])

        all_tools = {
            "search": "web_access",
            "read_file": "file_read",
            "exec": "system_execution",
        }

        if allowed_permissions:
            agent.tools = {
                k: v for k, v in all_tools.items()
                if k in allowed_permissions and v in user_perms
            }
        else:
            agent.tools = {k: v for k, v in all_tools.items() if v in user_perms}

    def apply_acl(self, tool_name: str, token: str) -> bool:
        '''Check if user has permission to execute tool.'''
        try:
            claims = self.auth.validate_token(token)
            user_perms = claims.get("permissions", [])
            return tool_name in user_perms
        except:
            return False
""")

    # docker-compose.yaml
    (with_auth / "docker-compose.yaml").write_text("""\
version: "3.8"
services:
  keycloak:
    image: quay.io/keycloak/keycloak:latest
    ports:
      - "8080:8080"
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: password
    volumes:
      - ./keycloak_data:/opt/keycloak/data
""")

    return with_auth
