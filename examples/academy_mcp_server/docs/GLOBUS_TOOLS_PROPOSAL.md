# Proposal: Globus Tools for Academy MCP Server

**Date**: 2026-03-29
**Branch**: `feature-platform-optimizations-FY26Q2-update-academy-mcp-with-globus`
**Status**: Proposal

---

## 1. Overview

Add a full complement of Globus tools to `examples/academy_mcp_server`, covering 7 Globus service surfaces (Transfer, Search, Compute, Flows, Groups, Timers, Auth). The tools follow the same plumbing patterns as the existing 4 agent lifecycle tools — `register()` function, Pydantic input models, `_FRAMEWORK_INJECTED_FIELDS` stripping, session-scoped state, and two-step registration.

### Globus SDK Services (from `temp/globus-sdk-python`)

| Service | SDK Client | Methods | Use Case |
|---------|-----------|---------|----------|
| **Transfer** | `TransferClient` | 40+ | File transfer between endpoints, directory listing, task management |
| **Search** | `SearchClient` | 21 | Scientific metadata indexing, full-text + faceted search |
| **Compute** | `ComputeClientV2/V3` | 12 | Remote function execution on Globus Compute endpoints |
| **Flows** | `FlowsClient` + `SpecificFlowClient` | 18 | Multi-step workflow orchestration (transfer → compute → notify) |
| **Groups** | `GroupsClient` | 15 | Collaboration group management, membership, policies |
| **Timers** | `TimersClient` | 10 | Scheduled/recurring job execution |
| **Auth** | `AuthLoginClient` / `ConfidentialClient` | 20+ | OAuth2 token management, identity resolution |

---

## 2. Authentication Architecture

### Globus Auth Model

Globus uses OAuth2 with **scoped consent**. Each service has its own scope:

| Service | Scope |
|---------|-------|
| Transfer | `urn:globus:auth:scope:transfer.api.globus.org:all` |
| Search | `urn:globus:auth:scope:search.api.globus.org:all` |
| Compute | `https://auth.globus.org/scopes/facd7ccc-c5f4-42aa-916b-a0e270e2c2a9/all` |
| Flows | `https://auth.globus.org/scopes/eec9b274-0c81-4334-bdc2-54e90e689b9e/flow_owner` |
| Groups | `urn:globus:auth:scope:groups.api.globus.org:all` |

### Integration with Academy MCP Server

**Two auth modes** (matching ADEPT's pattern):

#### Mode A: Confidential Client (Service-Level, Default)

For server-side operations where the academy MCP server acts on behalf of the ADEPT platform:

```
GLOBUS_CLIENT_ID=<uuid>           # Globus App registration
GLOBUS_CLIENT_SECRET=<secret>     # Confidential client secret
```

Uses `ClientCredentialsAuthorizer` → auto-refreshing access tokens. Stored in `config.py` alongside existing `Settings`.

#### Mode B: User Token Delegation (Per-User)

For operations requiring user-specific Globus identity (e.g., transfer from a user's personal collection). The ADEPT orchestration service passes the user's Globus access token via `user_context`:

```python
# Injected by framework:
user_context = {
    "globus_access_token": "<user's Globus token>",
    "globus_identity": "user@institution.edu"
}
```

Uses `AccessTokenAuthorizer` with the delegated token. Falls back to Mode A if no user token.

### New Config Fields (`config.py`)

```python
class Settings(BaseSettings):
    # Existing
    port: int = 9004
    redis_url: str = "redis://academy_redis:6379/0"
    log_level: str = "INFO"

    # Globus Auth
    globus_client_id: str = ""
    globus_client_secret: str = ""
    globus_scopes: str = ""  # Space-separated, auto-derived if empty

    # Globus Defaults
    globus_default_transfer_endpoint: str = ""  # Pre-configured collection UUID
    globus_default_compute_endpoint: str = ""   # Pre-configured compute endpoint UUID
    globus_default_search_index: str = ""       # Pre-configured search index UUID

    model_config = {"env_prefix": "ACADEMY_", "env_file": ".env", "extra": "ignore"}
```

---

## 3. Client Architecture

### New File: `clients/globus_client.py`

Singleton client manager (matching `manager_registry.py` pattern — session-scoped where needed):

```python
class GlobusClientManager:
    """Manages Globus SDK clients with automatic auth and token refresh."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._confidential_client: Optional[ConfidentialAppAuthClient] = None
        self._authorizers: Dict[str, GlobusAuthorizer] = {}  # scope → authorizer
        self._clients: Dict[str, BaseClient] = {}            # service → client

    def get_transfer_client(self, user_token: Optional[str] = None) -> TransferClient:
        """Get TransferClient with appropriate authorizer."""

    def get_search_client(self, user_token: Optional[str] = None) -> SearchClient:
        """Get SearchClient with appropriate authorizer."""

    def get_compute_client(self, user_token: Optional[str] = None) -> ComputeClientV3:
        """Get ComputeClientV3 with appropriate authorizer."""

    def get_flows_client(self, user_token: Optional[str] = None) -> FlowsClient:
        """Get FlowsClient with appropriate authorizer."""

    def get_groups_client(self, user_token: Optional[str] = None) -> GroupsClient:
        """Get GroupsClient with appropriate authorizer."""

    def get_timers_client(self, user_token: Optional[str] = None) -> TimersClient:
        """Get TimersClient with appropriate authorizer."""
```

**Auth Resolution Order** (per-call):
1. `user_token` parameter → `AccessTokenAuthorizer(user_token)`
2. `user_context["globus_access_token"]` from framework injection → same
3. `ACADEMY_GLOBUS_CLIENT_ID` + `ACADEMY_GLOBUS_CLIENT_SECRET` → `ClientCredentialsAuthorizer`
4. None configured → raise descriptive error

---

## 4. Tool Inventory (28 Tools)

### 4a. Transfer Tools (`tools/globus_transfer.py`)

| # | Tool Name | SDK Method | Description |
|---|-----------|-----------|-------------|
| 1 | `globus_list_directory` | `operation_ls` | List files/dirs at a path on a Globus collection |
| 2 | `globus_mkdir` | `operation_mkdir` | Create directory on a collection |
| 3 | `globus_rename` | `operation_rename` | Rename file/dir on a collection |
| 4 | `globus_stat` | `operation_stat` | Get file/dir metadata (size, modified, type) |
| 5 | `globus_submit_transfer` | `submit_transfer` | Initiate async file transfer between two collections |
| 6 | `globus_submit_delete` | `submit_delete` | Initiate async recursive delete on a collection |
| 7 | `globus_get_task` | `get_task` | Get status of a transfer/delete task |
| 8 | `globus_list_tasks` | `task_list` | List recent transfer tasks (with filters) |
| 9 | `globus_cancel_task` | `cancel_task` | Cancel an in-progress transfer task |
| 10 | `globus_wait_for_task` | `task_wait` | Poll until task completes (with timeout) |
| 11 | `globus_search_endpoints` | `endpoint_search` | Search for collections by name/keyword |

**Pydantic Input Models:**

```python
class SubmitTransferInput(BaseModel):
    source_endpoint: str = Field(..., description="Source collection UUID")
    destination_endpoint: str = Field(..., description="Destination collection UUID")
    transfer_items: List[Dict[str, str]] = Field(
        ..., description="List of {source_path, destination_path, recursive?} items"
    )
    label: str = Field(default="", description="Human-readable label for the transfer")
    sync_level: Optional[int] = Field(default=None, description="Sync level: 0=exists, 1=size, 2=mtime, 3=checksum")
    mcp_session_id: Optional[str] = None
```

### 4b. Search Tools (`tools/globus_search.py`)

| # | Tool Name | SDK Method | Description |
|---|-----------|-----------|-------------|
| 12 | `globus_search_query` | `post_search` | Full-text + faceted search on a Globus Search index |
| 13 | `globus_search_scroll` | `scroll` | Paginated scroll through large result sets |
| 14 | `globus_ingest_entries` | `ingest` | Ingest metadata entries into a search index |
| 15 | `globus_get_search_subject` | `get_subject` | Get all entries for a specific subject URI |
| 16 | `globus_delete_search_subject` | `delete_subject` | Delete a subject from the index |
| 17 | `globus_list_search_indices` | `index_list` | List accessible search indices |

### 4c. Compute Tools (`tools/globus_compute.py`)

| # | Tool Name | SDK Method | Description |
|---|-----------|-----------|-------------|
| 18 | `globus_compute_submit` | `submit` | Submit a function execution to a compute endpoint |
| 19 | `globus_compute_get_task` | `get_task` | Get result/status of a compute task |
| 20 | `globus_compute_get_endpoint` | `get_endpoint` | Get compute endpoint details and status |
| 21 | `globus_compute_list_endpoints` | `get_endpoints` | List compute endpoints the user can access |
| 22 | `globus_compute_register_function` | `register_function` | Register a Python function for remote execution |

### 4d. Flows Tools (`tools/globus_flows.py`)

| # | Tool Name | SDK Method | Description |
|---|-----------|-----------|-------------|
| 23 | `globus_list_flows` | `list_flows` | List available Globus Flows |
| 24 | `globus_run_flow` | `run_flow` | Start a flow run with input parameters |
| 25 | `globus_get_flow_run` | `get_run` | Get status/logs of a flow run |
| 26 | `globus_cancel_flow_run` | `cancel_run` | Cancel an in-progress flow run |

### 4e. Groups & Identity Tools (`tools/globus_groups.py`)

| # | Tool Name | SDK Method | Description |
|---|-----------|-----------|-------------|
| 27 | `globus_list_groups` | `get_my_groups` | List groups the user belongs to |
| 28 | `globus_get_group` | `get_group` | Get group details and membership |

### Tool Count Summary

| Module | Tools | Priority |
|--------|-------|----------|
| `globus_transfer.py` | 11 | P0 — Core data movement |
| `globus_search.py` | 6 | P0 — Scientific metadata discovery |
| `globus_compute.py` | 5 | P1 — Remote execution |
| `globus_flows.py` | 4 | P1 — Workflow orchestration |
| `globus_groups.py` | 2 | P2 — Collaboration |
| **Total** | **28** | |

---

## 5. Plumbing Parity Checklist

Every aspect of the existing agent lifecycle tools must be replicated for Globus tools:

| Plumbing Layer | Existing (Agent Lifecycle) | Globus (Proposed) | Status |
|----------------|---------------------------|-------------------|--------|
| **Tool file** | `tools/agent_lifecycle.py` | `tools/globus_transfer.py`, `tools/globus_search.py`, `tools/globus_compute.py`, `tools/globus_flows.py`, `tools/globus_groups.py` | New |
| **register() function** | `register(mcp: FastMCP)` in each tool file | Same pattern — `register(mcp)` called from `server.py` | Match |
| **Pydantic input models** | `schemas.py` (4 models) | `schemas.py` extended (12+ new models) | Extend |
| **Schema export** | `export_registration_schema()` | Same function, new models | Reuse |
| **Config env vars** | `ACADEMY_PORT`, `ACADEMY_REDIS_URL` | Add `ACADEMY_GLOBUS_CLIENT_ID`, etc. | Extend |
| **Client layer** | `manager_registry.py` (AcademyManagerRegistry) | `clients/globus_client.py` (GlobusClientManager) | New |
| **Session isolation** | Per-`mcp_session_id` Manager | Per-`mcp_session_id` client cache (transfer tasks scoped to session) | Match |
| **Framework field stripping** | `_FRAMEWORK_INJECTED_FIELDS` in register script | Same frozenset, reused | Reuse |
| **Two-step registration** | `register_academy_tools.py` + `register_from_schemas.py` | Same scripts discover new tools automatically (MockMCP pattern) | Auto |
| **Health endpoint** | Lists 4 tool names | Lists 4 + 28 = 32 tool names | Extend |
| **Error handling** | Returns `{"status": "error", "error": "..."}` | Same pattern | Match |
| **Logging** | `logger.info(f"[ACADEMY] ...")` | `logger.info(f"[GLOBUS] ...")` prefix | Match |
| **Unit tests** | `test_agent_lifecycle.py`, `test_schemas.py` | `test_globus_transfer.py`, `test_globus_search.py`, etc. + `test_globus_client.py` | New |
| **Integration tests** | `test_manager_registry.py` | Mock Globus SDK responses via `responses` or `respx` | New |
| **E2E registration tests** | `test_tool_registration_e2e.py` | Same test discovers new tools automatically | Auto |
| **Docker deps** | `requirements.txt` (academy-py) | Add `globus-sdk>=3.43.0` | Extend |
| **Makefile targets** | `register-tools`, `verify-tools` | Same targets — auto-discovers new tools | Auto |

---

## 6. File Changes

### New Files

| File | Purpose | Lines (est.) |
|------|---------|-------------|
| `clients/__init__.py` | Package init | 1 |
| `clients/globus_client.py` | GlobusClientManager (auth + client factory) | ~200 |
| `tools/globus_transfer.py` | 11 transfer tools + `register(mcp)` | ~400 |
| `tools/globus_search.py` | 6 search tools + `register(mcp)` | ~250 |
| `tools/globus_compute.py` | 5 compute tools + `register(mcp)` | ~200 |
| `tools/globus_flows.py` | 4 flows tools + `register(mcp)` | ~180 |
| `tools/globus_groups.py` | 2 groups tools + `register(mcp)` | ~100 |
| `tests/test_globus_client.py` | Auth + client factory tests | ~150 |
| `tests/test_globus_transfer.py` | Transfer tool unit tests (mocked SDK) | ~300 |
| `tests/test_globus_search.py` | Search tool unit tests | ~200 |
| `tests/test_globus_compute.py` | Compute tool unit tests | ~150 |
| `tests/test_globus_flows.py` | Flows tool unit tests | ~120 |
| `tests/test_globus_groups.py` | Groups tool unit tests | ~80 |

### Modified Files

| File | Change |
|------|--------|
| `config.py` | Add 6 `globus_*` fields to `Settings` |
| `server.py` | Import and call `register()` from each new tool module |
| `schemas.py` | Add 12+ new Pydantic input models + extend `ALL_MODELS` dict |
| `requirements.txt` | Add `globus-sdk>=3.43.0` |
| `Dockerfile` | No change (pip installs from requirements.txt) |
| `docker-compose.yaml` | Add `ACADEMY_GLOBUS_*` env vars |
| `scripts/register_academy_tools.py` | No change (auto-discovers via MockMCP) |
| `scripts/register_from_schemas.py` | No change (reads JSON schemas) |
| `main.py` | No change (health endpoint auto-lists tools from FastMCP) |
| `README.md` | Add Globus tool documentation section |

---

## 7. Implementation Phases

### Phase 1: Foundation (Transfer + Search)

**Scope:** Core data movement and scientific discovery — the two most-used Globus services.

1. `clients/globus_client.py` — GlobusClientManager with dual auth modes
2. `config.py` — Globus settings
3. `tools/globus_transfer.py` — 11 tools
4. `tools/globus_search.py` — 6 tools
5. `schemas.py` — Transfer + Search input models
6. `server.py` — Register new tools
7. Unit tests for all 17 tools (mocked SDK responses)
8. Docker compose env vars
9. Registration verification

**Deliverable:** 17 new Globus tools registered in ADEPT, discoverable via `adept_list_tools`, callable via `adept_call_tool` or natural language.

### Phase 2: Compute + Flows

**Scope:** Remote function execution and multi-step workflow orchestration.

1. `tools/globus_compute.py` — 5 tools
2. `tools/globus_flows.py` — 4 tools
3. `schemas.py` — Compute + Flows input models
4. Unit tests for 9 tools

**Deliverable:** 26 total Globus tools. Enables: "Submit this analysis function to the HPC compute endpoint, then transfer results to my collection."

### Phase 3: Groups + E2E

**Scope:** Collaboration identity and full E2E validation.

1. `tools/globus_groups.py` — 2 tools
2. E2E tests: real Globus API calls (requires Globus credentials)
3. Documentation updates (README, onboarding, testing strategy)
4. Makefile targets for Globus-specific validation

**Deliverable:** 28 total tools. Full E2E validation with live Globus endpoints.

---

## 8. Example Workflows

### Scientific Data Transfer
```
User: "Transfer the CRISPR dataset from the EMSL collection to the PNNL archive"

Agent calls:
  1. globus_search_endpoints(filter="EMSL") → finds source collection UUID
  2. globus_search_endpoints(filter="PNNL archive") → finds dest collection UUID
  3. globus_list_directory(endpoint=source, path="/datasets/crispr/") → lists files
  4. globus_submit_transfer(source, dest, items=[...]) → returns task_id
  5. globus_wait_for_task(task_id, timeout=300) → waits for completion
```

### Scientific Metadata Search
```
User: "Find all proteomics datasets with mass spec data from 2025"

Agent calls:
  1. globus_list_search_indices() → finds relevant index
  2. globus_search_query(index_id, q="proteomics mass spectrometry", filters=[{field: "year", values: ["2025"]}])
  3. Returns: matching entries with metadata, subjects, and access URLs
```

### Remote Compute + Results Transfer
```
User: "Run the protein folding prediction on the HPC endpoint and save results"

Agent calls:
  1. globus_compute_register_function(function_code=...) → function_id
  2. globus_compute_submit(endpoint_id, function_id, args={...}) → task_id
  3. globus_compute_get_task(task_id) → poll until complete
  4. globus_submit_transfer(hpc_collection, user_collection, items=[results]) → transfer results
```

### Automated Workflow via Flows
```
User: "Set up a weekly transfer of new sequencing data from the instrument"

Agent calls:
  1. globus_list_flows() → find or create a transfer flow
  2. globus_run_flow(flow_id, input={source, dest, path, schedule}) → run_id
  3. globus_get_flow_run(run_id) → monitor status
```

---

## 9. Dependencies

### Python Packages

```
# Add to requirements.txt
globus-sdk>=3.43.0
```

The Globus SDK is pure Python with minimal transitive dependencies (PyJWT, cryptography, requests). It's compatible with the existing academy-py and FastMCP stack.

### Environment Variables (docker-compose.yaml)

```yaml
academy_mcp_server:
  environment:
    # Existing
    ACADEMY_REDIS_URL: redis://academy_redis:6379/0
    ACADEMY_LOG_LEVEL: INFO
    # Globus (new)
    ACADEMY_GLOBUS_CLIENT_ID: "${GLOBUS_CLIENT_ID:-}"
    ACADEMY_GLOBUS_CLIENT_SECRET: "${GLOBUS_CLIENT_SECRET:-}"
    ACADEMY_GLOBUS_DEFAULT_TRANSFER_ENDPOINT: "${GLOBUS_DEFAULT_TRANSFER_ENDPOINT:-}"
    ACADEMY_GLOBUS_DEFAULT_COMPUTE_ENDPOINT: "${GLOBUS_DEFAULT_COMPUTE_ENDPOINT:-}"
    ACADEMY_GLOBUS_DEFAULT_SEARCH_INDEX: "${GLOBUS_DEFAULT_SEARCH_INDEX:-}"
```

### Globus App Registration

A Globus application must be registered at [developers.globus.org](https://developers.globus.org):
- **Type:** Confidential Client (server-side operations)
- **Scopes:** Transfer, Search, Compute, Flows, Groups
- **Redirect URI:** Not needed (client credentials flow)

---

## 10. Testing Strategy

### Unit Tests (Mocked SDK)

Every tool gets unit tests with mocked Globus SDK responses:

```python
@pytest.fixture
def mock_transfer_client(monkeypatch):
    """Mock GlobusClientManager.get_transfer_client()."""
    mock_client = MagicMock(spec=TransferClient)
    mock_client.operation_ls.return_value = GlobusHTTPResponse(...)
    monkeypatch.setattr(
        "academy_mcp_server.clients.globus_client.globus_manager.get_transfer_client",
        lambda **kw: mock_client,
    )
    return mock_client
```

### Integration Tests (Live Globus, Optional)

Gated by `GLOBUS_CLIENT_ID` env var:

```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ACADEMY_GLOBUS_CLIENT_ID"),
        reason="No Globus credentials configured",
    ),
]
```

### Registration Tests (Auto-Discovered)

Existing `test_tool_registration_e2e.py` auto-discovers all `@mcp.tool()` functions via the MockMCP pattern. No changes needed — new Globus tools will be discovered automatically when `register()` is called in `server.py`.

---

## 11. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Globus token expiration during long transfers | Transfer fails mid-stream | `ClientCredentialsAuthorizer` auto-refreshes; `globus_wait_for_task` retries |
| Large directory listings (>10K items) | Memory/timeout | Paginate via `has_next_page` + `marker` params |
| Compute function serialization | Functions must be picklable | Document constraints, validate before submission |
| Scope consent not granted | 403 on first API call | `globus_check_auth` diagnostic tool + clear error messages |
| Network latency to Globus APIs | Slow tool calls | Async httpx in GlobusClientManager; timeout config |

---

## Cross-References

- **Globus SDK source**: `temp/globus-sdk-python/src/globus_sdk/services/`
- **Academy MCP server**: `examples/academy_mcp_server/`
- **Existing tools pattern**: `examples/academy_mcp_server/tools/agent_lifecycle.py`
- **Registration scripts**: `examples/academy_mcp_server/scripts/register_academy_tools.py`
- **Academy architecture**: `examples/academy_mcp_server/docs/ACADEMY_MCP_SERVER_LIFECYCLE_ARCHITECTURE.md`
