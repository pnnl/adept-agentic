# ADEPT Core E2E Test Patterns: Comprehensive Analysis

**Date**: 2026-03-31
**Source**: Automated codebase exploration of `tests/e2e/`, `examples/biofoundation_mcp_server/tests/`, and ADEPT core infrastructure
**Purpose**: Catalog reusable E2E patterns from the ADEPT platform for Academy MCP Server lifecycle tests

---

## 1. Authentication Patterns

### 1.1 ROPC (Resource Owner Password Credentials) Flow

The primary authentication pattern for user-initiated operations. Defined in `tests/e2e/conftest.py:16-36`.

```python
async def get_user_token(username, password) -> str:
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
    realm = os.getenv("KEYCLOAK_REALM", "master")
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"
    payload = {
        "client_id": "login-client",
        "username": username,
        "password": password,
        "grant_type": "password",
        "scope": "openid profile email",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=payload)
        response.raise_for_status()
        return response.json()["access_token"]
```

**Key details**:
- Uses `login-client` (public OAuth2 client) — no client_secret needed
- Returns raw JWT access_token string
- `scope: "openid profile email"` gives standard claims
- Error handling via `pytest.fail()` for clear test failure messages

**Pre-defined user accounts** (from `conftest.py`):

| User | Password | Groups | Purpose |
|------|----------|--------|---------|
| `admin` | `admin` | admin, gateway-service | Full admin operations |
| `notebook-user` | `notebook-password` | notebook-users | Standard user operations |
| `streamlit-user` | `streamlit-password` | streamlit-users | Streamlit UI testing |

### 1.2 Service-to-Service (Client Credentials) Flow

For service accounts and automated operations. Defined in `tests/e2e/conftest.py:46-62`.

```python
async def get_s2s_token(client_id, client_secret) -> str:
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
    realm = os.getenv("KEYCLOAK_REALM", "master")
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=payload)
        response.raise_for_status()
        return response.json()["access_token"]
```

**Key service clients**:

| Client ID | Secret Source | Purpose |
|-----------|-------------|---------|
| `admin-cli` | `KC_ADMIN_CLI_SECRET` env/file | Keycloak admin operations |
| `validation-runner-client` | `VALIDATION_RUNNER_CLIENT_SECRET` | Gateway Registry access |
| `login-client` | Public (no secret) | ROPC user authentication |

### 1.3 Token Factory Fixtures

ADEPT uses a **factory fixture pattern** for flexible token acquisition (`conftest.py:149-162`):

```python
@pytest_asyncio.fixture
async def admin_s2s_token_factory() -> Callable[[], str]:
    """Factory fixture: tries client_credentials first, falls back to ROPC."""
    async def _get_token() -> str:
        secret = _get_admin_cli_secret()
        if secret:
            return await get_s2s_token("admin-cli", secret)
        # Fallback: ROPC with admin user (always works, same permissions)
        return await get_user_token("admin", "admin")
    return _get_token
```

**Credential resolution chain** (`_get_admin_cli_secret()` at `conftest.py:132-147`):
1. `KC_ADMIN_CLI_SECRET` environment variable
2. `/app/credentials/KC_ADMIN_CLI_SECRET` file
3. `/run/secrets/KC_ADMIN_CLI_SECRET` file
4. Returns `None` (triggers ROPC fallback)

### 1.4 Token Claims Inspection

Used in `test_authentication_flows.py:41-61` for JWT validation without signature verification:

```python
def inspect_token_claims(token: str, context: str, expected_claims: Dict = None):
    payload = jwt.decode(token, options={"verify_signature": False})
    assert 'sub' in payload, f"Token for {context} must contain 'sub' claim."
    assert 'azp' in payload, f"Token for {context} must contain 'azp' claim."
    if expected_claims:
        for claim, expected_value in expected_claims.items():
            assert claim in payload
            # Supports both exact match and list-contains checks
```

### 1.5 Fixture Scoping Strategy

| Fixture | Scope | Rationale |
|---------|-------|-----------|
| `admin_token` | `module` | One token per test file (reduces Keycloak load) |
| `admin_token_function` | `function` | Fresh token per test (isolation) |
| `http_client` | `module` | Shared httpx client with auth headers |
| `http_client_function` | `function` | Per-test isolated client |
| `admin_s2s_token_factory` | `function` | Factory returns fresh tokens on demand |

---

## 2. MCP Tool Registration via ADEPT SDK

### 2.1 CLI Tool Registration Pattern

The canonical pattern from `biofoundation_mcp_server/tests/test_tool_registration.py:424-586`.

**Step 1: Locate the CLI binary** (`_find_agentic_cli()` at line 303):

```python
def _find_agentic_cli() -> str:
    candidates = [
        os.path.join(PROJECT_ROOT, ".venv311", "bin", "agentic"),
        os.path.join(PROJECT_ROOT, ".venv", "bin", "agentic"),
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    found = shutil.which("agentic")
    if found:
        return found
    pytest.skip("agentic CLI not found — install with: pip install -e src/")
```

**Step 2: Run CLI commands** (`_run_agentic()` at line 318):

```python
def _run_agentic(args: list, *, check: bool = True):
    cli = _find_agentic_cli()
    cmd = [cli] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if check and result.returncode != 0:
        detail = result.stderr or result.stdout
        pytest.fail(f"agentic {' '.join(args[:3])}... failed (rc={result.returncode}): {detail}")
    return result
```

**Step 3: Register a tool** (complete invocation at line 460):

```python
_run_agentic([
    "tools", "register", name,
    "-d", "Description of the tool",
    "-p", "mcp",                           # Protocol
    "-u", "http://server:9009/mcp",         # MCP endpoint URL
    "--tool-name", "original_tool_name",    # Tool name on MCP server
    "--args-schema", json.dumps(schema),    # JSON schema for parameters
    "--username", ADMIN_USER,               # Keycloak username
    "--password", ADMIN_PASS,               # Keycloak password
])
```

**Step 4: Verify in Redis** (Redis read at line 470):

```python
raw = _redis_get(f"external_tool:{name}")
assert raw is not None, f"Tool {name} not found in Redis after registration"
config = json.loads(raw)
assert config["invocation"]["protocol"] == "mcp"
assert config["invocation"]["connection"]["url"] == TOOL_URL
assert "file_id" in config.get("args_schema", {})
```

### 2.2 UUID-Suffixed Tool Names

Prevent collision with production tools (`_unique_tool_name()` at line 419):

```python
def _unique_tool_name(base: str) -> str:
    return f"{base}_test_{uuid.uuid4().hex[:8]}"
```

Example: `biofoundation_preprocess_spectra_test_a1b2c3d4`

Production pattern: `external_tool:biofoundation_preprocess_spectra`
Test pattern: `external_tool:biofoundation_preprocess_spectra_test_*`

### 2.3 Fixture-Based Cleanup

Test tools are cleaned up via fixture teardown (`tool_names` fixture at line 431):

```python
@pytest.fixture
def tool_names(self):
    names = []
    yield names
    for name in names:
        # Try CLI delete first
        _run_agentic([
            "tools", "delete", name, "-y",
            "--username", ADMIN_USER, "--password", ADMIN_PASS,
        ], check=False)
        # Belt-and-suspenders: also delete directly from Redis
        _redis_del(f"external_tool:{name}")
```

### 2.4 Session-Scoped Stale Tool Sweep

Prevents test pollution across runs (`_sweep_stale_test_tools` at line 392):

```python
@pytest.fixture(scope="session", autouse=True)
def _sweep_stale_test_tools():
    """Remove stale test tool registrations from prior runs."""
    redis_url = os.environ.get("BIOFOUNDATION_REDIS_URL", "")
    if not redis_url:
        yield
        return
    stale = _redis_keys("external_tool:biofoundation_*_test_*")
    for key in stale:
        _redis_del(key)
    yield
    # Post-session sweep (belt-and-suspenders)
    stale = _redis_keys("external_tool:biofoundation_*_test_*")
    for key in stale:
        _redis_del(key)
```

### 2.5 Full Register/Delete Lifecycle Test

Complete lifecycle validation (`test_register_then_delete_lifecycle` at line 508):

```python
def test_register_then_delete_lifecycle(self):
    name = _unique_tool_name("biofoundation_lifecycle")
    schema = json.dumps({"mcp_session_id": {"type": "string", "description": "Session ID"}})

    # Register
    _run_agentic(["tools", "register", name, "-d", "Lifecycle test",
                   "-p", TOOL_PROTOCOL, "-u", TOOL_URL,
                   "--tool-name", "biofoundation_get_status",
                   "--args-schema", schema,
                   "--username", ADMIN_USER, "--password", ADMIN_PASS])

    # Verify registered
    assert _redis_get(f"external_tool:{name}") is not None

    # Delete
    _run_agentic(["tools", "delete", name, "-y",
                   "--username", ADMIN_USER, "--password", ADMIN_PASS])

    # Verify gone
    assert _redis_get(f"external_tool:{name}") is None
```

### 2.6 Schema Round-Trip Fidelity Test

Validates schema survives CLI → Gateway → Redis intact (`test_args_schema_survives_roundtrip` at line 538):

```python
def test_args_schema_survives_roundtrip(self, tool_names):
    original_schema = {
        "spectrum_file_id": {"type": "string", "description": "..."},
        "decode_mode": {"type": "string", "description": "...", "default": "greedy"},
        "beam_width": {"type": "integer", "description": "...", "default": 5},
    }
    _run_agentic([...])
    raw = _redis_get(f"external_tool:{name}")
    config = json.loads(raw)
    stored_schema = config.get("args_schema", {})
    assert set(stored_schema.keys()) == set(original_schema.keys())
    assert stored_schema["decode_mode"]["default"] == "greedy"
```

---

## 3. Dual Redis Access Pattern

For maximum test flexibility — works both inside containers (with redis-py) and from host (via docker exec).

### 3.1 Redis GET (`_redis_get()` at line 329)

```python
def _redis_get(key: str):
    redis_url = os.environ.get("BIOFOUNDATION_REDIS_URL", "")
    if redis_url:
        try:
            import redis as redis_mod
            r = redis_mod.from_url(redis_url, decode_responses=True)
            value = r.get(key)
            return value if value else None
        except Exception:
            pass
    # Fallback to docker exec
    result = subprocess.run(
        ["docker", "exec", "redis", "redis-cli", "GET", key],
        capture_output=True, text=True, timeout=10,
    )
    value = result.stdout.strip()
    if value in ("", "(nil)"):
        return None
    return value
```

### 3.2 Redis DEL (`_redis_del()` at line 351)

Same dual-access pattern: redis-py first, `docker exec redis redis-cli DEL` fallback.

### 3.3 Redis KEYS (`_redis_keys()` at line 371)

Pattern matching for cleanup sweeps. Handles `(empty array)` output from redis-cli.

---

## 4. MCP JSON-RPC Protocol Discovery

### 4.1 The `_mcp_rpc()` Helper

The core pattern for MCP protocol testing, from `biofoundation_mcp_server/tests/test_tool_registration.py:64-90`:

```python
def _mcp_rpc(url, method, params=None):
    """Send a JSON-RPC request to an MCP endpoint.

    FastMCP Streamable HTTP requires Accept: text/event-stream.
    The response is SSE; we parse the first data: line for JSON-RPC result.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    resp = requests.post(f"{url}/mcp", json=payload, headers=headers, timeout=TIMEOUT)
    # Parse SSE to extract JSON body
    if resp.status_code == 200 and "text/event-stream" in resp.headers.get("content-type", ""):
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                resp._parsed_json = json.loads(line[6:])
                resp.json = lambda _r=resp: _r._parsed_json
                break
    return resp
```

**Critical details**:
- **Accept header**: Must include `text/event-stream` for FastMCP Streamable HTTP
- **Endpoint**: Always `{base_url}/mcp` (not `/mcp/` or `/tools/list`)
- **SSE parsing**: Response is `text/event-stream`, not raw JSON — must parse `data: ` lines
- **Monkey-patch**: `resp.json()` is overridden to return parsed SSE data for caller convenience

### 4.2 MCP Tool Discovery Tests (Tier 1)

From `TestMCPToolDiscovery` class (line 98):

| Test | Purpose | Key Assertion |
|------|---------|---------------|
| `test_mcp_tools_list_returns_N_tools` | Tool count validation | `len(tools) == N` |
| `test_each_tool_has_description` | Non-empty descriptions | `tool.get("description")` truthy |
| `test_each_tool_has_input_schema` | Schema structure | `schema.get("type") == "object"` |
| `test_preprocess_spectra_schema` | Parameter presence | `"file_id" in props` |
| `test_tools_list_via_proxy` | Nginx proxy passthrough | Same count through proxy URL |

### 4.3 JSON-RPC Response Structure

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "tool_name",
                "description": "Tool description",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "param1": {"type": "string", "description": "..."},
                        "mcp_session_id": {"type": "string", "description": "..."}
                    },
                    "required": ["param1"]
                }
            }
        ]
    }
}
```

---

## 5. Nginx Proxy Routing Patterns

### 5.1 Three Access Paths

Validated in `test_authentication_flows.py` and `test_nginx_sse_streaming_fix.py`:

| Path | URL Pattern | TLS | Auth | Use Case |
|------|-------------|-----|------|----------|
| External (nginx) | `https://api.agentic.local/v1/...` | Yes | JWT via nginx | Production, external clients |
| Internal (gateway) | `http://agent_gateway:8081/v1/...` | No | JWT direct | Container-to-container |
| Host (localhost) | `http://localhost:8083/v1/...` | No | JWT direct | Developer debugging |

### 5.2 SSE Streaming Through Nginx

From `test_nginx_sse_streaming_fix.py` — validates 3 critical fixes:

**Fix 1: Content-Type** (`test_orchestration_service_returns_event_stream_content_type`):
```python
content_type = response.headers.get("content-type", "")
assert "text/event-stream" in content_type
```

**Fix 2: X-Accel-Buffering** (`test_gateway_returns_x_accel_buffering_no`):
```python
x_accel = response.headers.get("x-accel-buffering", "")
assert x_accel == "no"
```

**Fix 3: Chunk Streaming** (`test_nginx_proxy_streams_sse_chunks`):
```python
async with client.stream("POST", f"{NGINX_PROXY_URL}/chat/completions", ...):
    async for chunk in response.aiter_text():
        chunk_timestamps.append(time.monotonic())
assert len(chunk_timestamps) >= 2  # Multiple chunks, not batched
```

### 5.3 SSE Format Compliance Test

Validates OpenAI-compatible SSE format through nginx (`test_nginx_proxy_sse_format_compliance`):

```python
def _parse_sse_chunks(raw_text: str) -> list:
    chunks = []
    for line in raw_text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                chunks.append({"_done": True})
            else:
                chunks.append(json.loads(data))
    return chunks

# Assertions:
assert len(parsed) >= 3       # role + content + stop + [DONE]
assert any(c.get("_done") for c in parsed)  # [DONE] marker present
assert "choices" in content_chunks[0]        # OpenAI structure
```

### 5.4 Domain Resolution Test

Docker DNS resolution for `api.agentic.local` (`test_authentication_flows.py:115-124`):

```python
async def test_domain_resolution_in_containers(self):
    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
        try:
            response = await client.get("https://api.agentic.local/health")
            assert response.status_code in [200, 404, 401, 403, 405]
        except httpx.ConnectError:
            pytest.fail("api.agentic.local should resolve within Docker network")
```

---

## 6. A2A (Agent-to-Agent) Gateway Registration

### 6.1 Full A2A Workflow Test

From `test_a2a_cli_commands.py:106-201` — 6-step lifecycle:

```
Step 1: register-peer → exit_code == 0
Step 2: list-peers --format json → exit_code == 0
Step 3: GET /v1/gateways/{alias} → 200, verify fields
Step 4: test-connection → exit_code == 1 (expected: peer not real)
Step 5: remove-peer --yes → exit_code == 0
Step 6: GET /v1/gateways/{alias} → 404 (verified removal)
```

### 6.2 A2A Auth Headers Fixture

Service-to-service authentication for Gateway Registry (`test_a2a_cli_commands.py:39-75`):

```python
@pytest.fixture
async def auth_headers():
    client_id = os.getenv("VALIDATION_RUNNER_CLIENT_ID") or os.getenv("GATEWAY_REGISTRY_CLIENT_ID")
    client_secret = os.getenv("VALIDATION_RUNNER_CLIENT_SECRET") or os.getenv("GATEWAY_REGISTRY_CLIENT_SECRET")
    # ... client_credentials flow → {"Authorization": f"Bearer {access_token}"}
```

### 6.3 A2A Cleanup Fixture

Prevents test pollution (`cleanup_test_gateway` at line 78):

```python
@pytest.fixture
async def cleanup_test_gateway(registry_url, test_gateway_alias, auth_headers):
    yield
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.delete(
                f"{registry_url}/v1/gateways/{test_gateway_alias}",
                headers=auth_headers
            )
            # Accept 200, 204, 404 (idempotent)
    except Exception as e:
        print(f"WARNING: Exception during cleanup: {e}")
```

### 6.4 A2A Nginx Routing Tests

From `test_a2a_nginx_routing.py`:

| Test | Purpose | Key Assertion |
|------|---------|---------------|
| `test_a2a_agentcard_via_nginx` | AgentCard discovery (public) | 200, has `name`, `url`, `capabilities`, `securitySchemes` |
| `test_a2a_endpoint_requires_auth` | Auth enforcement | 401/403 for unauthenticated |
| `test_a2a_endpoint_accessible_via_nginx` | Routing correctness | status != 404 (endpoint exists) |
| `test_gateway_registry_accessible` | Registry reachability | 200 with auth token |

### 6.5 A2A AgentCard Validation

OAuth2 security scheme validation (`test_a2a_nginx_routing.py:32-56`):

```python
agentcard = response.json()
assert "name" in agentcard
assert "url" in agentcard
assert "capabilities" in agentcard
assert "securitySchemes" in agentcard
assert "keycloak_oauth" in agentcard["securitySchemes"]
oauth_scheme = agentcard["securitySchemes"]["keycloak_oauth"]
assert oauth_scheme["type"] == "oauth2"
assert "clientCredentials" in oauth_scheme["flows"]
```

---

## 7. CLI Mock Patterns for Non-Interactive Testing

### 7.1 Click CLI Test Runner

From `test_a2a_cli_commands.py:19-22`:

```python
from click.testing import CliRunner
from agentic_framework_sdk.cli.a2a_commands import a2a_group

@pytest.fixture
def cli_runner():
    return CliRunner()

# Usage:
result = cli_runner.invoke(a2a_group, [
    "register-peer", alias, url, "--registry-url", registry_url,
])
assert result.exit_code == 0, f"Register failed: {result.output}"
```

### 7.2 Comprehensive Mock CLI Prompts

From `conftest.py:312-417` — intercepts ALL input methods:

```python
@pytest.fixture
def mock_cli_prompts(monkeypatch):
    """Mock CLI prompts for non-interactive testing.
    Intercepts: builtins.input(), questionary.*, rich.prompt.*, sys.stdin.readline()
    """
    responses = {
        "Enter thread ID": "test-thread-123",
        "Enter message": "Hello, agent!",
        "Continue chatting": "n",
        "Enter your choice": "1",
    }
    # ... monkeypatch.setattr("builtins.input", mock_input)
    # ... patch('rich.prompt.Prompt.ask', ...)
    # ... patch('questionary.text', ...)
```

### 7.3 Subprocess-Based CLI Execution

From `_run_agentic()` pattern (biofoundation):

```python
def _run_agentic(args: list, *, check: bool = True):
    cli = _find_agentic_cli()
    cmd = [cli] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if check and result.returncode != 0:
        pytest.fail(f"agentic {' '.join(args[:3])}... failed (rc={result.returncode}): {detail}")
    return result
```

Key flags for non-interactive execution:
- `--yes` / `-y` for confirmations
- `--username` / `--password` for auth (avoids interactive login)
- `--format json` for machine-parseable output

---

## 8. Negative Test Cases and Security Validation

### 8.1 Auth Rejection Tests

From `test_authentication_flows.py:94-104`:

```python
async def test_agent_gateway_direct_access_requires_auth(self):
    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
        # Health endpoint — public
        response = await client.get("http://agent_gateway:8081/health")
        assert response.status_code == 200

        # Models endpoint — requires auth
        response = await client.get("http://agent_gateway:8081/v1/models")
        assert response.status_code == 401
```

### 8.2 Invalid Credentials Test

From `test_authentication_flows.py:161-177`:

```python
async def test_authentication_error_handling(self):
    auth = KeycloakAuth(keycloak_url="http://keycloak:8180", realm="master", client_id="agentic-cli")
    with pytest.raises(AuthenticationError):
        await auth.authenticate_password(username="invalid_user", password="invalid_password")
```

### 8.3 Connection Error Test

From `test_authentication_flows.py:180-191`:

```python
async def test_connection_error_handling(self):
    auth = KeycloakAuth(keycloak_url="http://invalid-server:8180", ...)
    can_connect = await auth.test_connection(use_external_proxy=False)
    assert not can_connect
```

### 8.4 A2A Security Tests

From `test_a2a_security.py` — comprehensive boundary validation:

- Request size limits (oversized payloads → 413/422)
- Concurrent requests (parallel POST → valid status codes)
- Invalid auth tokens (malformed Bearer → 401/403)
- Cross-origin validation (CORS headers)
- Rate limiting (rapid sequential requests)

Common assertion pattern:
```python
assert response.status_code in [200, 400, 401, 403, 422], \
    f"Unexpected status code: {response.status_code}"
```

### 8.5 Directory Traversal Prevention

From `test_agent_gateway_file_serving.py:253-257`:

```python
for malicious_path in ["../../etc/passwd", "../../../.env", "..%2F..%2F.env"]:
    response = await client.get(f"{gateway_url}/v1/files/{malicious_path}")
    assert response.status_code in [403, 404], f"Directory traversal not blocked for: {malicious_path}"
```

---

## 9. Container-Based MCP Server Lifecycle

### 9.1 Docker Compose Test Execution Pattern

Standard Makefile target pattern (from biofoundation and academy):

```makefile
# Application network only (MCP protocol tests)
test-registration:
    docker run --rm \
        --network=adept_application_network \
        -v "$$(pwd)/tests":/app/tests:ro \
        $(IMAGE) pytest tests/test_tool_registration.py::TestMCPToolDiscovery -v

# Dual network (Redis + MCP)
test-registration-adept:
    docker run --rm \
        --network=adept_application_network \
        --network=adept_data_network \
        -v "$$(pwd)/tests":/app/tests:ro \
        -e BIOFOUNDATION_REDIS_URL=redis://redis:6379/0 \
        $(IMAGE) pytest tests/test_tool_registration.py::TestADEPTToolRegistration -v
```

### 9.2 Network Requirements by Test Tier

| Tier | Networks Required | Reason |
|------|-------------------|--------|
| MCP Discovery | `adept_application_network` | Access MCP server container |
| Redis Verification | + `adept_data_network` | Access Redis for tool metadata |
| CLI Lifecycle | + host Docker socket | CLI runs via `subprocess` |
| Auth Flows | + `adept_frontend_network` | Access nginx_proxy for external path |
| A2A Routing | + `adept_frontend_network` | Access `api.agentic.local` via nginx |

### 9.3 Health Check Patterns

```python
# FastAPI health
response = await client.get("http://academy_mcp_server:9004/health")
assert response.status_code == 200

# Redis health
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)
r.ping()  # Raises if unreachable

# Nginx health
response = await client.get("http://academy_nginx_proxy:80/health")
assert response.status_code == 200
```

### 9.4 Framework-Injected Field Stripping

Fields that the ADEPT framework injects at runtime but must NOT appear in user-facing `args_schema`:

```python
_FRAMEWORK_INJECTED_FIELDS = {
    "mcp_session_id",
    "session_id",
    "user_id",
    "username",
    "groups",
    "gateway_session_id",
    "multi_agent_session_id",
}
```

Validated in registration tests:
```python
def test_get_status_args_schema_is_empty(self, redis_client):
    """get_status args_schema has no user-visible params (session is framework-injected)."""
    val = redis_client.get("external_tool:biofoundation_get_status")
    data = json.loads(val)
    schema = data.get("args_schema", {})
    assert len(schema) == 0  # All params are framework-injected
```

---

## 10. Test Configuration Constants

### 10.1 Environment-Driven Configuration

From `conftest.py:172-176`:

```python
AGENT_GATEWAY_URL = os.getenv("AGENT_GATEWAY_URL", "http://localhost:8081/v1")
ORCHESTRATION_SERVICE_URL = os.getenv("ORCHESTRATION_SERVICE_URL", "http://localhost:8084")
GATEWAY_REGISTRY_URL = os.getenv("GATEWAY_REGISTRY_URL", "http://localhost:8086")
NGINX_PROXY_URL = os.getenv("NGINX_PROXY_URL", "https://nginx_proxy")
MODEL_NAME = "agentic-framework:scientific-agent-v1"
```

### 10.2 Service URL Defaults (Container vs Host)

| Service | Container Default | Host Default |
|---------|-------------------|--------------|
| Agent Gateway | `http://agent_gateway:8081/v1` | `http://localhost:8083/v1` |
| Orchestration | `http://orchestration_service:8084` | `http://localhost:8084` |
| Gateway Registry | `http://gateway_registry:8086` | `http://localhost:8086` |
| Keycloak | `http://keycloak:8180` | `http://localhost:8180` |
| Nginx Proxy | `https://api.agentic.local` | `https://api.agentic.local` (requires /etc/hosts) |

### 10.3 Test Data Factory

From `conftest.py:276-300`:

```python
@pytest.fixture
def test_data_factory() -> Dict[str, Any]:
    return {
        "create_gateway": lambda alias: {
            "alias": alias,
            "gateway_url": f"http://{alias}:8081/v1",
            "description": f"Test gateway {alias}",
            "capabilities": ["assistant_api", "response_api", "a2a_delegation"],
        },
        "create_assistant": lambda name: {
            "name": name,
            "instructions": f"Test assistant {name} for validation",
            "model": MODEL_NAME,
        },
    }
```

---

## 11. Key Design Patterns Summary

| Pattern | Where Used | Purpose |
|---------|-----------|---------|
| **ROPC + fallback** | `conftest.py` | User tokens with S2S fallback |
| **Token factory fixtures** | `conftest.py` | On-demand fresh tokens |
| **`_mcp_rpc()` SSE parser** | biofoundation, academy | MCP JSON-RPC over Streamable HTTP |
| **Dual Redis access** | biofoundation | redis-py preferred, docker exec fallback |
| **UUID-suffixed tool names** | biofoundation | Test isolation from production |
| **Session-scoped sweep** | biofoundation | Stale test tool cleanup |
| **Fixture-based cleanup** | biofoundation, A2A | Yield-then-cleanup pattern |
| **Click CliRunner** | A2A CLI tests | Non-interactive CLI testing |
| **Environment-driven URLs** | all E2E tests | Container/host portability |
| **`verify=False`** | nginx tests | Self-signed cert handling |

---

## 12. Applicability to Academy MCP Server

### Direct Reuse (Copy and Adapt)

1. **`_mcp_rpc()` helper** → Academy's 32 tools via `POST /mcp`
2. **`_find_agentic_cli()` + `_run_agentic()`** → Tool registration/deletion
3. **`_redis_get()` / `_redis_del()` / `_redis_keys()`** → Redis verification
4. **`_unique_tool_name()`** → Test isolation for academy tools
5. **`_sweep_stale_test_tools()`** → Pre/post-session cleanup
6. **Token factory fixtures** → Auth for all test tiers
7. **`_parse_sse_chunks()`** → SSE streaming validation

### Academy-Specific Adaptations Needed

1. **Tool count**: 32 tools (4 agent + 28 Globus) vs biofoundation's 5
2. **Two-step registration**: Schema discovery inside container + host CLI registration
3. **Academy-specific Redis**: `academy_redis:6379` (separate from ADEPT Redis)
4. **Echo Agent round-trip**: Launch → invoke → validate response → shutdown
5. **Nginx proxy**: Academy has its own `academy_nginx_proxy` at ports 9020/9021
6. **Config validation**: `ACADEMY_*` env prefix for Pydantic Settings

### File References

| File | Line Range | Pattern |
|------|-----------|---------|
| `tests/e2e/conftest.py` | 16-36 | ROPC token acquisition |
| `tests/e2e/conftest.py` | 46-62 | S2S client credentials |
| `tests/e2e/conftest.py` | 132-162 | Token factory + credential resolution |
| `tests/e2e/conftest.py` | 312-417 | CLI mock prompts |
| `biofoundation/.../test_tool_registration.py` | 64-90 | `_mcp_rpc()` helper |
| `biofoundation/.../test_tool_registration.py` | 98-184 | MCP discovery tests |
| `biofoundation/.../test_tool_registration.py` | 192-290 | Redis verification tests |
| `biofoundation/.../test_tool_registration.py` | 296-586 | CLI lifecycle tests |
| `tests/e2e/test_authentication_flows.py` | 64-191 | Auth flow tests |
| `tests/e2e/test_nginx_sse_streaming_fix.py` | 56-280 | SSE streaming tests |
| `tests/e2e/test_a2a_cli_commands.py` | 19-258 | A2A CLI lifecycle |
| `tests/e2e/test_a2a_nginx_routing.py` | 28-150 | A2A nginx routing |
| `tests/e2e/test_a2a_security.py` | 1-609 | Security boundary tests |
