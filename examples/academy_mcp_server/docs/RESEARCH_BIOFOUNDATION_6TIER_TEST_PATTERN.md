# Biofoundation MCP Server: 6-Tier Testing Pattern Analysis

**Date**: 2026-03-31
**Source**: Automated codebase exploration of `examples/biofoundation_mcp_server/`
**Purpose**: Reference for replicating the canonical test architecture in Academy MCP Server

---

## 1. The 6-Tier Testing Pyramid

| Tier | Name | Scope | Prerequisites | Location | Makefile Target |
|------|------|-------|---------------|----------|-----------------|
| **Tier 0** | Module Imports | Can biofoundation_mcp modules be imported? | None (offline) | `test_imports.py` | `make test-imports` |
| **Tier 1** | Configuration | Are settings parsed correctly from env? | None (offline) | `test_config.py` | `make test-config` |
| **Tier 2** | Unit Tests | Do tools, model components, and schemas work? | None (offline) | `test_*.py` (except integration) | `make test-unit` |
| **Tier 3a** | Schema Discovery | Does registration script introspect tools? | None (offline) | `test_schema_discovery.py` | `make test-schema-discovery` |
| **Tier 3b** | MCP Health & Protocol | Does MCP server start and respond? | Biofoundation stack running (`make start`) | `test_biofoundation_deployment.py` | `make test-integration` |
| **Tier 4** | MCP Tool Discovery | Can orchestration discover 5 tools via JSON-RPC? | Biofoundation stack running | `test_tool_registration.py::TestMCPToolDiscovery` | `make test-registration` |
| **Tier 5** | ADEPT Redis Registration | Are tools registered in ADEPT's Redis? | Full stack + `make register-tools` | `test_tool_registration.py::TestADEPTToolRegistration` | `make test-registration-adept` |
| **Tier 6** | CLI Registration Lifecycle | Can agentic CLI register/delete tools? | Full stack + agentic CLI + dual network | `test_tool_registration.py::TestCLIRegistrationLifecycle` | `make test-registration-lifecycle` |

---

## 2. Tier-by-Tier Breakdown

### Tier 0 & 1: Offline Import + Config Tests (No Services Needed)

**Files:**
- `/tests/test_imports.py` (28 tests)
- `/tests/test_config.py` (13 tests)

**Test Structure:**
```python
# test_imports.py -- 3 classes
class TestPackageImports:           # Import root + config + server + app
class TestModelImports:             # Import model.encoder, decoder, tokenizer, dataset, checkpoint, inference
class TestToolImports:              # Import tools.preprocess_spectra, run_inference, get_job_status
class TestDependencies:             # Validate torch, numpy, pandas, fastmcp, redis available

# test_config.py -- 4 classes
class TestSettingsDefaults:         # Validate port=9009, device=cpu, batch_size defaults
class TestSettingsEnvMapping:       # Validate BIOFOUNDATION_* env var mapping
class TestSettingsExtras:           # Validate extra unknown env vars are ignored
class TestConfigNegative:           # Invalid port, negative batch_size, empty redis_url
```

**Execution:**
```bash
make test-imports                   # 28 tests, ~1s
make test-config                    # 13 tests, ~1s
```

**Key Fixtures (from conftest.py):**
```python
@pytest.fixture
def mock_settings(tmp_path, monkeypatch):
    """Mocked Settings with BIOFOUNDATION_* env vars."""
    # Sets: PORT, REDIS_URL, CHECKPOINT_PATH, DEVICE, BATCH_SIZE, etc.
```

### Tier 2: Unit Tests (No Services Needed)

**Files:**
- `test_model_shapes.py` -- Model encoder/decoder shape validation
- `test_model_registry.py` -- Multi-model registry logic
- `test_model_garden.py` -- YAML loading, path resolution, singleton lifecycle (23 tests)
- `test_tools_preprocess.py` -- Preprocessing logic
- `test_tools_inference.py` -- Inference execution
- `test_tools_status.py` -- Status detection (filesystem + Redis state)
- `test_biofoundation_inference.py` -- End-to-end model inference
- `test_conversion_tokenization.py` -- MZA conversion + tokenizer
- `test_tools_convert_mza.py` -- MZA format conversion

**Example: test_model_garden.py (23 tests)**
```python
class TestResolvePath:              # Path resolution logic
class TestLoadModelGarden:          # YAML loading, multiple models, missing file handling
class TestModelCard:                # Model card metadata extraction
class TestModelCardHyperparameters: # Hyperparameter validation
class TestSingletonLifecycle:       # Singleton pattern validation
```

**Fixtures:**
```python
@pytest.fixture
def garden_dir(tmp_path):
    """Create minimal model garden with fake checkpoint."""
    checkpoints_dir = tmp_path / "checkpoints"
    checkpoints_dir.mkdir()
    (checkpoints_dir / "denovo.pt").write_bytes(b"\x00" * 1024)
    return tmp_path

@pytest.fixture
def garden_yaml(garden_dir):
    """Write model_garden.yaml with test config."""

@pytest.fixture
def sample_parquet_path(tmp_path):
    """Create minimal valid parquet with required columns."""
    df = pd.DataFrame({
        "pair_id": ["spec_001", "spec_002"],
        "precursor_mz": [500.25, 750.50],
        "ms2_mz_bins": [np.array([...]), np.array([...])],
    })
```

### Tier 3a: Schema Discovery (No Services Needed)

**File:** `test_schema_discovery.py` (19 tests)

**Purpose:** Validate that `register_biofoundation_tools.py` script can introspect all 5 MCP tool modules and produce correct `ToolDefinition` objects.

**Key Classes:**
```python
class TestDiscoverTools:            # Discovers all 5 tools, validates names
class TestPreprocessSpectraSchema:  # file_id + format params, 2 params total
class TestRunInferenceSchema:       # spectrum_file_id + decode_mode + beam_width, 10 params
class TestConvertMzaSchema:         # file_id + bin_width + include_bin_view + max_pairs, 6 params
class TestZeroParamTools:           # get_status + list_models have empty schemas
```

**Test Example:**
```python
def test_mcp_session_id_excluded(self, tools):
    """Framework-injected mcp_session_id never in args_schema."""
    for t in tools:
        assert "mcp_session_id" not in t.args_schema

def test_has_decode_mode_default(self, schema):
    """run_inference decode_mode defaults to 'greedy'."""
    assert schema.args_schema["decode_mode"]["default"] == "greedy"
```

### Tier 3b: MCP Health & Protocol (Biofoundation Stack Required)

**File:** `test_biofoundation_deployment.py` (8 tests)

**Key Classes:**
```python
class TestHealthEndpoints:
    def test_mcp_server_health(self):       # GET /health -> 200, status=healthy, mcp_tools=5
    def test_proxy_health(self):            # GET /health on nginx proxy
    def test_root_endpoint(self):           # GET / -> name=Bio-Foundation MCP Server

class TestMCPProtocol:
    def test_mcp_endpoint_exists(self):     # POST /mcp with initialize request
    def test_mcp_tools_list(self):          # MCP tools/list returns exactly 5 tools
```

**Test Flow:**
```
1. Initialize MCP session (POST /mcp with initialize method)
2. Extract session ID from response headers
3. Send notifications/initialized
4. Call tools/list with session ID header
5. Parse SSE response format
6. Validate exactly 5 tools returned
```

### Tier 4: MCP Tool Discovery (Biofoundation Stack Required)

**File:** `test_tool_registration.py::TestMCPToolDiscovery` (6 tests)

**Key Tests:**
```python
class TestMCPToolDiscovery:
    def test_mcp_tools_list_returns_5_tools(self):
        """MCP server lists exactly 5 tools."""
        resp = _mcp_rpc(MCP_SERVER_URL, "tools/list")
        tools = data["result"]["tools"]
        assert len(tools) == 5
        for expected in EXPECTED_TOOLS:
            assert expected in tool_names

    def test_each_tool_has_description(self):
    def test_each_tool_has_input_schema(self):
    def test_preprocess_spectra_schema(self):
    def test_run_inference_schema(self):
    def test_tools_list_via_proxy(self):
        """Nginx proxy passes tools/list through correctly."""
```

**JSON-RPC Helper (critical pattern):**
```python
def _mcp_rpc(url, method, params=None):
    """Send JSON-RPC to /mcp endpoint.

    FastMCP Streamable HTTP requires:
    - Accept: text/event-stream
    - Parses SSE response: data: {json}
    """
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    resp = requests.post(f"{url}/mcp", json=payload, headers=headers, timeout=15)
    # Parse SSE to extract JSON
    if resp.status_code == 200 and "text/event-stream" in resp.headers.get("content-type", ""):
        for line in resp.text.splitlines():
            if line.startswith("data: "):
                resp._parsed_json = json.loads(line[6:])
                resp.json = lambda _r=resp: _r._parsed_json
                break
    return resp
```

### Tier 5: ADEPT Redis Registration (Full Stack + registration)

**File:** `test_tool_registration.py::TestADEPTToolRegistration` (7 tests)

**Requires:** Full ADEPT stack + `make register-tools` + dual network (app + data)

**Key Tests:**
```python
class TestADEPTToolRegistration:
    def test_all_tools_registered_in_redis(self, redis_client):
        """All 5 tools exist as external_tool:* keys."""
    def test_tools_have_args_schema(self, redis_client):
    def test_tools_use_mcp_protocol(self, redis_client):
        protocol = data.get("invocation", {}).get("protocol")
        assert protocol == "mcp"
    def test_tools_point_to_mcp_server_url(self, redis_client):
        url = data.get("invocation", {}).get("connection", {}).get("url")
        assert "biofoundation_mcp_server" in url and "/mcp" in url
    def test_preprocess_spectra_args_schema_has_file_id(self, redis_client):
    def test_run_inference_args_schema_has_decode_mode(self, redis_client):
    def test_get_status_args_schema_is_empty(self, redis_client):
        assert len(schema) == 0
```

**Makefile Target with Dual Network:**
```makefile
test-registration-adept:
    $(ENGINE) create --rm \
        --network=adept_application_network \
        $(TEST_VOLS) $(TEST_ENV) \
        -e BIOFOUNDATION_REDIS_URL=redis://redis:6379 \
        --entrypoint python $(TEST_IMAGE) \
        -m pytest tests/test_tool_registration.py::TestADEPTToolRegistration
    # Post-create: connect to adept_data_network for Redis access
```

### Tier 6: CLI Registration Lifecycle (Full Stack + agentic CLI)

**File:** `test_tool_registration.py::TestCLIRegistrationLifecycle` (4 tests)

**Key Tests:**
```python
class TestCLIRegistrationLifecycle:
    def test_register_preprocess_spectra(self, tool_names):
        """Register via CLI, verify protocol + URL in Redis."""
    def test_register_run_inference(self, tool_names):
        """Register run_inference with full schema."""
    def test_register_then_delete_lifecycle(self):
        """Full lifecycle: register -> verify -> delete -> verify gone."""
    def test_args_schema_survives_roundtrip(self, tool_names):
        """Schema survives CLI -> Gateway -> Redis intact."""
```

**Session-Scoped Cleanup Fixture:**
```python
@pytest.fixture(scope="session", autouse=True)
def _sweep_stale_test_tools():
    """Remove test tools from prior runs (pattern: *_test_*)."""
    redis_url = os.environ.get("BIOFOUNDATION_REDIS_URL", "")
    if redis_url:
        stale = _redis_keys("external_tool:biofoundation_*_test_*")
        for key in stale:
            _redis_del(key)
    yield
    stale = _redis_keys("external_tool:biofoundation_*_test_*")
    for key in stale:
        _redis_del(key)
```

**CLI Helper Functions:**
```python
def _find_agentic_cli() -> str:
    """Locate agentic CLI binary in venv or PATH."""
    candidates = [
        os.path.join(PROJECT_ROOT, ".venv311", "bin", "agentic"),
        os.path.join(PROJECT_ROOT, ".venv", "bin", "agentic"),
    ]

def _run_agentic(args: list, *, check: bool = True):
    """Execute agentic CLI command."""
    cli = _find_agentic_cli()
    result = subprocess.run([cli] + args, capture_output=True, text=True, timeout=30)

def _unique_tool_name(base: str) -> str:
    """Append UUID suffix to avoid collision."""
    return f"{base}_test_{uuid.uuid4().hex[:8]}"

def _redis_get(key: str):
    """Read from Redis (redis-py or docker exec fallback)."""

def _redis_del(key: str):
    """Delete from Redis."""

def _redis_keys(pattern: str) -> list:
    """Find keys matching pattern."""
```

**Makefile Target with agentic CLI Installation:**
```makefile
test-registration-lifecycle:
    $(ENGINE) create --rm \
        --network=adept_application_network \
        $(TEST_VOLS) \
        -v "$(PROJECT_ROOT)/src":/project/src:ro \
        -e KEYCLOAK_URL=$(KEYCLOAK_URL) \
        -e AGENT_GATEWAY_URL=http://agent_gateway:8081 \
        -e BIOFOUNDATION_REDIS_URL=redis://redis:6379 \
        -e HOME=/tmp \
        --entrypoint /bin/bash $(TEST_IMAGE) \
        -c "
            cp -r /project/src /tmp/src && \
            python -m venv /tmp/cli_venv && \
            /tmp/cli_venv/bin/pip install -q /tmp/src/ && \
            export PATH=/tmp/cli_venv/bin:\$$PATH && \
            /app/.venv/bin/python -m pytest tests/test_tool_registration.py::TestCLIRegistrationLifecycle
        "
    # Post-create: connect to adept_data_network
```

---

## 3. Key Architectural Patterns

### A. Framework-Injected Fields Stripping

```python
_FRAMEWORK_INJECTED_FIELDS = frozenset({
    "mcp_session_id",
    "session_id",
    "multi_agent_session_id",
    "gateway_session_id",
    "execution_timeout",
    "user_context",
    "session_hierarchy",
    "execution_context",
    "user_id",
    "username",
})
```

**Result:**
- `biofoundation_get_status`: Has `mcp_session_id` parameter but excluded -> empty `args_schema`
- `biofoundation_preprocess_spectra`: Has `mcp_session_id` -> excluded, only `file_id` + `format` remain

### B. Schema Discovery from Pydantic Models

```python
async def biofoundation_preprocess_spectra(
    file_id: Annotated[str, Field(description="File ID from ADEPT uploads")],
    format: Annotated[str, Field(default="auto", description="Input format: auto/csv/parquet")],
    mcp_session_id: Annotated[str, Field(default="", description="...")] = "",
) -> dict:
    ...
```

Result: `args_schema = {"file_id": {"type": "string", ...}, "format": {"type": "string", "default": "auto", ...}}`

### C. Dual Redis Access Pattern

```python
def _redis_get(key: str):
    """Try redis-py first, fall back to docker exec."""
    redis_url = os.environ.get("BIOFOUNDATION_REDIS_URL", "")
    if redis_url:
        try:
            import redis
            r = redis.from_url(redis_url, decode_responses=True)
            return r.get(key)
        except Exception:
            pass
    # Fallback: docker exec redis-cli GET key
    result = subprocess.run(
        ["docker", "exec", "redis", "redis-cli", "GET", key],
        capture_output=True, text=True, timeout=10,
    )
```

### D. SSE Response Parsing

FastMCP HTTP requires special header handling:
```python
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",  # Critical!
}
# Parse SSE format: data: {json}
if "text/event-stream" in resp.headers.get("content-type", ""):
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            resp._parsed_json = json.loads(line[6:])
```

---

## 4. Makefile Test Organization

### Offline Tests (No Services)
```makefile
test-imports              # test_imports.py (28 tests)
test-config               # test_config.py (13 tests)
test-unit                 # All unit tests (no services)
test-model-shapes         # Model shape validation
test-model-registry       # Model registry unit tests
test-model-garden         # Model garden YAML + lifecycle (23 tests)
test-convert-mza          # MZA conversion + tokenization
test-schema-discovery     # Schema discovery from Pydantic (19 tests)
test-all                  # All offline tests combined
```

### Online Tests (Services Required)
```makefile
test-integration          # test_biofoundation_deployment.py (8 tests)
test-registration         # TestMCPToolDiscovery (6 tests)
test-registration-adept   # TestADEPTToolRegistration (7 tests) -- dual network
test-registration-lifecycle # TestCLIRegistrationLifecycle (4 tests) -- dual network + CLI
```

### Background Execution (nohup)
```makefile
nohup-test-all            # All offline -> logs/bio_test_all_TIMESTAMP.log
nohup-test-model-garden   # Model garden -> logs/bio_test_model_garden_TIMESTAMP.log
nohup-test-integration    # Integration -> logs/bio_test_integration_TIMESTAMP.log
nohup-test-registration   # Registration -> logs/bio_test_registration_TIMESTAMP.log
```

---

## 5. Test Execution Flow (Quick Start)

```bash
# Phase 1: Setup (5 min)
cd examples/biofoundation_mcp_server
make setup-cpu              # Build + start containers, register tools

# Phase 2: Offline Tests (30s)
make test-all               # Tier 0-3a: imports, config, unit, schema discovery

# Phase 3: Integration Tests (2 min)
make test-integration       # Tier 3b: Health + MCP protocol
make test-registration      # Tier 4: MCP tool discovery

# Phase 4: ADEPT Registration (1 min)
make test-registration-adept # Tier 5: Redis registration

# Phase 5: CLI Lifecycle (1 min)
make test-registration-lifecycle # Tier 6: agentic CLI register/delete

# Cleanup
make teardown               # Stop + deregister all
```

---

## 6. Expected Test Metrics

| Metric | Value |
|--------|-------|
| Total Test Files | 15 |
| Total Test Count | 150+ |
| Tier 0-1 Tests | 41 (imports + config) |
| Tier 2 Tests | ~80 (unit tests across 9 files) |
| Tier 3a Tests | 19 (schema discovery) |
| Tier 3b Tests | 8 (health + protocol) |
| Tier 4 Tests | 6 (MCP discovery) |
| Tier 5 Tests | 7 (Redis registration) |
| Tier 6 Tests | 4 (CLI lifecycle) |
| Offline Test Time | ~30s |
| Full Stack Time | ~10 min |

---

## 7. Key Takeaways for Academy MCP Server Replication

1. **Tier 0-1:** Import + config tests in separate files (no orchestration)
2. **Tier 2:** Unit tests with fixtures for test data (parquet files, temporary directories)
3. **Tier 3a:** Schema discovery validation (test that registration script introspects tools correctly)
4. **Tier 3b:** Health endpoint tests (simple HTTP GET)
5. **Tier 4:** MCP JSON-RPC tools/list tests (SSE parsing, tool count validation)
6. **Tier 5:** Redis registration tests (dual network for data_network access)
7. **Tier 6:** CLI lifecycle tests (register/delete via agentic CLI, session cleanup fixtures)

**Critical Details:**
- Use `@pytest.fixture(scope="module", autouse=True)` for session-level cleanup
- Implement framework-field filtering (mcp_session_id, session_id, etc.)
- Use Pydantic `Field()` annotations for auto-schema extraction
- Handle SSE parsing for FastMCP HTTP responses
- Dual Redis access pattern (redis-py + docker exec fallback)
- Unique tool names with UUID suffix for test isolation

---

## 8. Critical Files Reference

| File | Purpose | Lines | Key Classes |
|------|---------|-------|------------|
| `Makefile` | Lifecycle + test orchestration | 512 | Dual compose files, env var mapping, dual network setup |
| `conftest.py` | Shared fixtures | 221 | mock_settings, garden_yaml, sample_parquet_path, sample_predictions_file |
| `test_imports.py` | Import validation | 128 | TestPackageImports, TestModelImports, TestToolImports, TestDependencies |
| `test_config.py` | Configuration | 119 | TestSettingsDefaults, TestSettingsEnvMapping, TestSettingsExtras, TestConfigNegative |
| `test_schema_discovery.py` | Schema extraction | 154 | TestDiscoverTools, TestPreprocessSpectraSchema, TestRunInferenceSchema, TestConvertMzaSchema |
| `test_biofoundation_deployment.py` | Health + MCP protocol | 142 | TestHealthEndpoints, TestMCPProtocol |
| `test_tool_registration.py` | All registration tiers | 586 | TestMCPToolDiscovery, TestADEPTToolRegistration, TestCLIRegistrationLifecycle |
| `test_model_garden.py` | Model YAML + lifecycle | 180+ | TestResolvePath, TestLoadModelGarden, TestModelCard, TestSingletonLifecycle |
| `register_biofoundation_tools.py` | Registration script | 400+ | Schema extraction, framework-field filtering, Pydantic validation |
| `docker-compose.yaml` | Service orchestration | 102 | biofoundation_redis, biofoundation_mcp_server, biofoundation_nginx_proxy |
