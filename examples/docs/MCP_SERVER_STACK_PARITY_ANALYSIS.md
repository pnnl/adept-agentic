# MCP Server Stack Parity Analysis

Cross-stack comparison of all ADEPT example MCP server deployments.
Identifies shared "plumbing" that MUST be identical vs. domain-specific deltas.

**Stacks Compared**: slurm_hpc | biofoundation | vfm | emsl_sandbox | academy
**Date**: 2026-03-29 (updated 2026-03-30)
**Author**: Paul Rigor
**Referenced by**: `examples/mcp_server_template/README.md`

### Per-Stack Documentation

| Stack | Lifecycle Audit | Implementation Tracker |
|-------|----------------|----------------------|
| slurm_hpc | [`examples/slurm_hpc/docs/STACK_LIFECYCLE_AUDIT.md`](../slurm_hpc/docs/STACK_LIFECYCLE_AUDIT.md) | [`examples/slurm_hpc/docs/IMPLEMENTATION_TRACKER.md`](../slurm_hpc/docs/IMPLEMENTATION_TRACKER.md) |
| biofoundation | [`examples/biofoundation_mcp_server/docs/STACK_LIFECYCLE_AUDIT.md`](../biofoundation_mcp_server/docs/STACK_LIFECYCLE_AUDIT.md) | — |
| vfm | [`examples/vfm_mcp_server/docs/STACK_LIFECYCLE_AUDIT.md`](../vfm_mcp_server/docs/STACK_LIFECYCLE_AUDIT.md) | — |
| emsl_sandbox | [`examples/emsl_sandbox/docs/STACK_LIFECYCLE_AUDIT.md`](../emsl_sandbox/docs/STACK_LIFECYCLE_AUDIT.md) | — |

---

## 1. Stack Identity Matrix

| Attribute | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|-----------|-----------|---------------|-----|--------------|
| **Domain** | HPC job scheduling | Mass spec / proteomics | Metagenomics foundation model | Secure code execution |
| **Services** | 8 (6 Slurm + MCP + proxy) | 3 (MCP + proxy + Redis) | 3 (MCP + proxy + Redis) | 3 (MCP + proxy + Redis) |
| **MCP Port** | 8002 | 9009 | 9010 | 8082 |
| **Proxy HTTP** | 9820 | 9020 | 9030 | 8080 |
| **Proxy HTTPS** | 9821 | 9021 | 9031 | 8443 |
| **Redis** | N/A (stateless) | 6382 | 6383 | internal only |
| **Tool Count** | 6 | 5 | 4 | 6 |
| **Tool Prefix** | slurm_hpc | biofoundation | vfm | emsl_sandbox |
| **Base Image** | Custom (slurm-mcp) | agentic-framework-deps-base | agentic-framework-deps-base | agentic-framework-deps-base |
| **GPU Support** | No | Yes (CPU/GPU overlays) | Yes (CPU/GPU overlays) | No |

---

## 2. Shared Plumbing (MUST be at parity)

### 2A. Makefile Lifecycle Targets

| Target | slurm_hpc | biofoundation | vfm | emsl_sandbox | Parity? |
|--------|-----------|---------------|-----|--------------|---------|
| `setup` | preflight build start wait-healthy bootstrap-jwt restart-mcp register-tools verify-tools | check-prerequisites init-data build-cpu start-cpu wait-healthy register-tools verify-tools | check-prerequisites init-data build-cpu start-cpu wait-healthy register-tools verify-tools | build start | DELTA |
| `teardown` | down -v --remove-orphans | deregister-tools stop | deregister-tools stop | down -v --remove-orphans | DELTA |
| `rebuild` | (missing) | stop build-no-cache start wait-healthy deregister-tools register-tools verify-tools | stop build-no-cache start wait-healthy deregister-tools register-tools verify-tools | (manual) | GAP |
| `rebuild-quick` | (missing) | stop build start wait-healthy | stop build start wait-healthy | (missing) | GAP |
| `build-no-cache` | Yes | Yes | Yes | Yes (via podman build) | OK |
| `start` | Yes | Yes | Yes | Yes | OK |
| `stop` | Yes | Yes | Yes | Yes | OK |
| `restart` | Yes | Yes | Yes | Yes | OK |
| `status` | Yes | (missing) | (missing) | Yes | DELTA |
| `logs` | Yes | Yes | Yes | Yes | OK |
| `health` | Yes | Yes | Yes | Yes | OK |
| `wait-healthy` | Yes (180s, scontrol) | Yes (60s, curl) | Yes (60s, curl) | (missing) | GAP |
| `register-tools` | Yes (bash) | Yes (python) | Yes (python) | Yes (bash) | OK |
| `deregister-tools` | Yes | Yes | Yes | Yes | OK |
| `verify-tools` | Yes | Yes | Yes | Yes | OK |

**Gaps in slurm_hpc**:
- Missing `rebuild` composite target (bio/vfm have it)
- Missing `rebuild-quick` composite target
- `teardown` does NOT deregister tools first (bio/vfm do)

### 2B. Makefile DRY Test Variables

| Variable | slurm_hpc | biofoundation | vfm | emsl_sandbox | Parity? |
|----------|-----------|---------------|-----|--------------|---------|
| `TEST_IMAGE` | slurm-mcp:latest | biofoundation-mcp:latest | vfm_mcp_server:dev | agentic-framework-deps-base | OK (stack-specific) |
| `TEST_VOLS` | source + tests :ro | source + tests :ro | source + tests + scripts :ro | (inline) | DELTA |
| `TEST_ENV` | PYTHONPATH + HOME=/tmp | PYTHONPATH + HOME=/tmp | PYTHONPATH + HOME=/tmp + TORCHINDUCTOR | OK |
| `TEST_RUN_OFFLINE` | Yes | Yes | Yes | (inline) | GAP in emsl |
| `TEST_RUN_NET` | Yes | Yes | Yes | Yes (DOCKER_RUN_SANDBOX_VALIDATE) | OK |
| `NET_APP` | --network=adept_application_network | same | same | same | OK |
| `TEST_SVC_ENV` | MCP_URL + PROXY_URL | MCP_URL + PROXY_URL | MCP_URL + PROXY_URL | MCP_URL + PROXY_URL | OK |
| `LOG_DIR` | $(pwd)/logs | $(pwd)/logs | $(pwd)/logs | (missing) | GAP in emsl |
| `TIMESTAMP` | date +%Y%m%d_%H%M%S | same | same | (missing) | GAP in emsl |

### 2C. Makefile Test Targets

| Target | slurm_hpc | biofoundation | vfm | emsl_sandbox | Parity? |
|--------|-----------|---------------|-----|--------------|---------|
| `ensure-test-image` | Yes | Yes | Yes | (missing) | GAP |
| `ensure-log-dir` | Yes | Yes | Yes | (missing) | GAP |
| `test-imports` | Yes | Yes | Yes | (missing) | GAP |
| `test-config` | (in test-unit) | Yes | Yes | (missing) | DELTA |
| `test-unit` | Yes | Yes | Yes | (missing) | GAP |
| `test-lint` | Yes | (missing) | (missing) | (missing) | UNIQUE |
| `test-schema` | Yes | (test_schema_discovery.py) | Yes | (missing) | OK |
| `test-certs` | Yes | (missing) | (missing) | (missing) | UNIQUE |
| `test-all` (offline) | Yes | Yes | Yes | (missing) | GAP |
| `test-deployment` | Yes | (in test-integration) | (in test-integration) | validate-deployment | DELTA |
| `test-integration` | Yes | Yes | Yes | (missing, use validate-*) | DELTA |
| `test-e2e` | Yes | (missing) | (missing) | (missing) | UNIQUE |
| `test-tls` | Yes | (missing) | (missing) | (missing) | UNIQUE |
| `nohup-test-all` | Yes | Yes | Yes | (missing) | GAP |
| `nohup-test-unit` | Yes | (missing) | (missing) | (missing) | UNIQUE |
| `nohup-test-integration` | Yes | Yes | Yes | (missing) | GAP |

### 2D. Data Directory Pattern

**Canonical Pattern** (biofoundation/vfm):
```
$(PROJECT_ROOT)/data/<stack_name>/
  checkpoints/    # or models/ — read-only model files
  uploads/        # session-scoped upload staging
  results/        # session-scoped inference outputs
  cache/          # optional caching layer
  reference/      # optional reference data (vfm only)
```

| Aspect | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|--------|-----------|---------------|-----|--------------|
| **Data root** | data/slurm_workspace | data/biofoundation/ | data/vfm/ | data/uploaded_files + data/sandbox_workspace |
| **init-data target** | `init-dirs` (creates workspace only) | `init-data` (4 dirs + chown 1200:1200) | `init-data` (4 dirs + chown 1200:1200) | (missing, entrypoint handles) |
| **Checkpoints dir** | N/A | checkpoints/ (RO mount) | models/ (RO mount) | N/A |
| **Uploads dir** | N/A | uploads/ (RW mount) | (via uploaded_files) | uploaded_files/ (named volume) |
| **Results dir** | N/A | results/ (RW mount) | results/ (RW mount) | uploaded_files/sessions/ |
| **Shared ADEPT files** | N/A | data/uploaded_files (RO) | data/uploaded_files (RO) | data/uploaded_files (bind volume) |
| **UID ownership** | N/A | 1200:1200 (appuser) | 1200:1200 (appuser) | 1200:1200 (appuser) |
| **Fallback perms** | (missing) | chmod a+rwX | chmod a+rwX | entrypoint tolerant chown |

**Gap in slurm_hpc**: `init-dirs` only creates `slurm_workspace/`. Does NOT create a proper
`data/slurm_hpc/` hierarchy. No chown/chmod pattern. No shared uploaded_files mount.

### 2E. Docker Compose Network Topology

| Aspect | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|--------|-----------|---------------|-----|--------------|
| **Internal network** | slurm_backend_network (bridge) | N/A | N/A | N/A (emsl_internal in rc-local overlay) |
| **External network** | adept_application_network | adept_application_network | adept_application_network | adept_application_network |
| **MCP server networks** | Both (dual-homed) | External only | External only | External only |
| **Proxy networks** | External only | External only | External only | External only |

slurm_hpc is unique in needing dual-homing because the MCP server must reach both
slurmrestd (backend) and the ADEPT orchestration service (external).

### 2F. Nginx Proxy Configuration

#### 2F.1 Structural Parity

| Aspect | slurm_hpc | biofoundation | vfm | academy | emsl_sandbox |
|--------|-----------|---------------|-----|---------|--------------|
| **Template file** | slurm_proxy.conf.template | biofoundation_proxy.conf.template | vfm_proxy.conf.template | academy_proxy.conf.template | sandbox_proxy.conf.template |
| **Template method** | entrypoint `envsubst` + `sed` for TLS | nginx `templates/` dir (auto) | nginx `templates/` dir (auto) | nginx `templates/` dir (auto) | entrypoint `envsubst` |
| **Upstream block** | Yes | Yes | Yes | Yes | No (inline) |
| **OIDC template** | Yes (slurm_proxy_oidc.conf.template) | No | No | No | No |
| **TLS mode** | Runtime detection (sed inject) | HTTP-only (no TLS in template) | HTTP-only (no TLS in template) | HTTP-only (no TLS in template) | Static in template (always TLS) |

#### 2F.2 Endpoint Parity

| Endpoint | slurm_hpc | biofoundation | vfm | academy | emsl_sandbox |
|----------|-----------|---------------|-----|---------|--------------|
| **/health response** | `{"status":"ok","proxy":"slurm"}` | `{"status":"ok","proxy":"biofoundation"}` | `{"status":"ok","proxy":"vfm"}` | `{"status":"ok","proxy":"academy"}` | text/plain `sandbox-proxy healthy` |
| **/health access_log** | off | off | off | off | off |
| **/mcp IP restriction** | RFC1918 CIDRs | RFC1918 CIDRs | RFC1918 CIDRs | RFC1918 CIDRs | Explicit IPs + subnet |
| **/files/ endpoint** | No | No | No | No | Yes (IP + X-Sandbox-Token) |
| **/sandbox/health** | No | No | No | No | Yes (IP-restricted) |
| **Catch-all format** | JSON (lists endpoints) | JSON (lists endpoints) | JSON (lists endpoints) | JSON (lists endpoints) | JSON (detailed) |

#### 2F.3 Proxy Directive Parity

| Directive | slurm_hpc | biofoundation | vfm | academy | emsl_sandbox | Canonical? |
|-----------|:---------:|:-------------:|:---:|:-------:|:------------:|:----------:|
| `proxy_http_version 1.1` | Yes | Yes | Yes | Yes | Yes | Required |
| `proxy_set_header Connection ""` | Yes | Yes | Yes | Yes | Yes | Required |
| `proxy_buffering off` | Yes | Yes | Yes | Yes | Yes | Required |
| `proxy_cache off` | Yes | Yes | Yes | Yes | No | Recommended |
| `proxy_read_timeout 600s` | Yes | Yes | Yes | Yes | Yes | Required |
| `proxy_send_timeout 600s` | Yes | Yes | Yes | Yes | Yes | Required |
| `client_max_body_size` | 50M | 50m | 50m | 50m | 50M | Required |
| `proxy_request_buffering off` | Yes | No | No | No | Yes | Optional |
| `proxy_connect_timeout 60s` | Yes | default | default | default | Yes | Optional |
| `set_real_ip_from` | No | No | No | No | Yes (Podman) | Env-specific |

**Gaps**:
- **slurm_hpc**: All P1 gaps RESOLVED (2026-03-30): upstream block, IP restriction, proxy_cache off, health proxy identifier, catch-all endpoints.
- **emsl_sandbox**: Missing `proxy_cache off`. Health response is text/plain instead of JSON. No `upstream` block (inline proxy_pass).

### 2G. TLS Certificate Generation

| Aspect | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|--------|-----------|---------------|-----|--------------|
| **Script** | generate-ca-and-certs.sh | generate-certs.sh | None | generate-ca-and-certs.sh |
| **Makefile target** | `generate-certs` | None (manual) | None | `generate-certs` |
| **Cert type** | Full CA (5yr) + server (1yr) | Self-signed (1yr) | N/A | Full CA (5yr) + server (1yr) |
| **Required env var** | SLURM_HOST_IP | None | N/A | SANDBOX_HOST_IP |
| **Idempotency** | Skip if valid 24h+ | No check | N/A | Skip if valid 24h+ |
| **SAN entries** | proxy hostname, localhost, host IP, Docker IPs | proxy hostname, localhost | N/A | proxy hostname, localhost, host IP, Docker/Podman IPs |
| **In setup chain?** | No (manual) | No (manual) | N/A | No (manual) |
| **Output files** | ca.key, ca.crt, slurm.key, slurm.crt | server.key, server.crt | N/A | ca.key, ca.crt, sandbox.key, sandbox.crt |

**Resolved**: `certs/ca.crt` was an empty directory (root-owned, from Docker bind-mount when
file didn't exist). Fixed by removing the directory and regenerating with `make generate-certs`.
SAN entries include: slurm_nginx_proxy, localhost, host IP, 127.0.0.1, 172.17.0.1, 10.89.0.1.

### 2H. Tool Registration Script

| Aspect | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|--------|-----------|---------------|-----|--------------|
| **Language** | Bash | Python | Python | Bash |
| **Discovery** | Hardcoded schemas | Dynamic (Pydantic introspection) | Dynamic (Pydantic introspection) | Hardcoded schemas |
| **Framework field stripping** | Manual | Automatic (frozenset) | Automatic (frozenset) | Manual |
| **Actions** | register, deregister, verify | register, deregister, verify, show-schemas | register, deregister, verify, show-schemas | register, deregister, verify |
| **Health check before register** | No | Yes (curl /health) | Yes (curl /health) | Yes (docker exec for Docker DNS) |
| **AGENT_GATEWAY_URL export** | No | Yes | TBD | Yes (Session 91) |
| **KEYCLOAK_URL/REALM export** | No | Yes | TBD | Yes (Session 91) |
| **Multi-deployment targets** | No | No | No | Yes (register-tools-rc, -emsl, generic) |

**Gap in slurm_hpc**: Uses bash with hardcoded schemas (fragile, dual-maintenance risk).
biofoundation and vfm use Python with dynamic Pydantic introspection (single source of truth).
**Gap in slurm_hpc + aws_mcp**: Missing `AGENT_GATEWAY_URL`, `KEYCLOAK_URL`, `KEYCLOAK_REALM`
exports. See `docs/bugfixes/SESSION_91_EMSL_SANDBOX_TOOL_ROUTING_AND_GUROBI_AUTH.md` §Backlog.

### 2I. Healthcheck Patterns

| Service | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|---------|-----------|---------------|-----|--------------|
| **MCP server** | urllib /health (15s, 30s start) | curl /health (30s, 60s start) | curl /health (30s, 60s start) | curl /health (15s, 60s start) |
| **Proxy** | wget /health (10s) | wget /health (10s) | wget /health (10s) | wget /health (15s) |
| **Redis** | N/A | redis-cli ping (10s) | redis-cli ping (10s) | redis-cli ping (10s) |
| **Backend** | scontrol ping (10s, 30s start) | N/A | N/A | N/A |

**RESOLVED (2026-03-30)**: slurm_hpc MCP healthcheck now uses `urllib /health` endpoint
(via `@app.custom_route("/health")`). Aligned with biofoundation/vfm/emsl_sandbox pattern.
Note: slurm_hpc uses `urllib` (python stdlib) instead of `curl` because the slurm-mcp image
doesn't include curl — functionally equivalent.

### 2J. Container User / Permissions

| Aspect | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|--------|-----------|---------------|-----|--------------|
| **AppUser UID:GID** | N/A (custom image) | 1200:1200 | 1200:1200 | 1200:1200 |
| **Run user** | root (Slurm needs it) | appuser | appuser | root -> gosu appuser |
| **Data dir ownership** | N/A | chown 1200:1200 | chown 1200:1200 | entrypoint tolerant chown |
| **Fallback** | N/A | chmod a+rwX | chmod a+rwX | chown || true |

---

## 3. Domain-Specific Deltas (Expected Differences)

These differences are legitimate and domain-driven:

### slurm_hpc Only
- 6 Slurm backend services (mysql, slurmdbd, slurmctld, slurmrestd, c1, c2)
- `bootstrap-jwt` target (HMAC key extraction from Slurm cluster)
- `restart-mcp` target (reload JWT credentials without full restart)
- SPIFFE/SPIRE profiles (workload identity for zero-trust)
- OIDC profile (oauth2_proxy for Keycloak integration)
- Federation profiles (cross-trust-domain SPIFFE bundle exchange)
- JWT bridge (RS256 SPIFFE -> HS256 Slurm translation)
- Identity mapper (Globus/ADEPT -> Slurm username mapping)
- Dual network architecture (backend + application)
- `validate-cluster` target (scontrol, munge, test job submission)

### biofoundation Only
- Model checkpoints (633MB PyTorch .pt files)
- GPU/CPU compose overlays
- Model garden YAML (multi-model versioning)
- Preprocessing, inference, tokenization tools
- MZA-to-parquet conversion

### vfm Only
- Model checkpoints (PyTorch Lightning)
- GPU/CPU compose overlays
- Model garden YAML with Track C model variants
- Feature similarity / metagenomics inference
- Scaler path configuration
- `inspect-checkpoints`, `list-models`, `validate-artifacts`, `reload-garden` targets

### emsl_sandbox Only
- Code execution engine (subprocess isolation)
- tmpfs session workspace (noexec, nosuid, 1GB)
- Gurobi license server integration (leghorn DNS, token auth)
- `/files/` endpoint with X-Sandbox-Token auth
- `SANDBOX_RUN_USER` (Linux username for Gurobi license)
- Rootless Podman support (slirp4netns, `set_real_ip_from`)
- `docker-compose.rc-local.yaml` overlay for co-located deployment

---

## 3B. Testing Environment and Dependencies

### Test Client Libraries

| Aspect | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|--------|-----------|---------------|-----|--------------|
| **httpx tests** | Yes (test_slurm_deployment.py) | Yes (test_biofoundation_deployment.py) | Yes (test_vfm_deployment.py) | No |
| **requests tests** | Yes (integration/) | Yes (integration/) | Yes (integration/) | No |
| **Official MCP Client** | Yes (test_mcp_client_protocol.py, FastMCP Client) | No | No | Yes (mcp.client.session.ClientSession) |
| **agentic-cli tests** | No | No (in progress) | No (in progress) | No |

**Key findings**:
- emsl_sandbox is the only stack using the low-level `mcp.client.session.ClientSession` (from the `mcp` package)
- slurm_hpc now has both httpx (transport-level) and FastMCP Client (protocol-level) tests
- biofoundation and vfm have NO official MCP client tests — only httpx/requests
- No stack has agentic-cli based tests (testing tool invocation via the ADEPT CLI)

### Container-Based Test Environment

| Aspect | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|--------|-----------|---------------|-----|--------------|
| **Test image** | slurm-mcp:latest | biofoundation-mcp:latest | vfm_mcp_server:dev | agentic-framework-deps-base |
| **Python version** | 3.12.13 | 3.11.x | 3.11.x | 3.11.x |
| **pytest** | 9.0.2 | 8.x | 8.x | 8.x |
| **pytest-asyncio** | pip install at runtime | pre-installed | pre-installed | pre-installed |
| **pytest.ini** | asyncio_mode = auto | via conftest.py | via conftest.py | via conftest.py |
| **Network** | adept_application_network | adept_application_network | adept_application_network | adept_application_network |
| **Docker CLI in container** | No (E2E tests fail) | No | No | No |
| **Volume mounts** | source + tests :ro | source + tests :ro | source + tests + scripts :ro | inline per-test |
| **PYTHONPATH** | /app/slurm_mcp_server | /app/biofoundation_mcp_server | /app/vfm_mcp_server | /app |
| **HOME** | /tmp | /tmp | /tmp | default |

### Test Dependencies (pip packages in test image)

| Package | slurm_hpc | biofoundation | vfm | emsl_sandbox |
|---------|-----------|---------------|-----|--------------|
| **fastmcp** | 3.1.1 | 3.x | 3.x | 3.x |
| **httpx** | 0.28.1 | 0.27.x | 0.27.x | 0.27.x |
| **requests** | 2.33.0 | 2.32.x | 2.32.x | 2.32.x |
| **pydantic** | 2.x | 2.x | 2.x | 2.x |
| **pytest-asyncio** | runtime install | pre-installed | pre-installed | pre-installed |
| **anyio** | 4.13.0 | 4.x | 4.x | 4.x |

**Gaps**:
- `pytest-asyncio` should be pre-installed in slurm-mcp image (currently pip installed at runtime in test-mcp-client target)
- biofoundation and vfm should add FastMCP Client or mcp.client.session based tests for protocol-level validation
- No stack has E2E tests that work from inside the container (Docker CLI not available) — need Docker socket mount or alternative patterns

---

## 4. Priority Gap Remediation for slurm_hpc

### P0 (Fix Now - Blocking Tests) — ALL RESOLVED

| # | Gap | Fix | Status |
|---|-----|-----|--------|
| 1 | `certs/ca.crt` is empty dir (root-owned) | Removed dir, regenerated as file with `make generate-certs` | DONE |
| 2 | Deployment tests fail (MCP Streamable HTTP) | Rewrote tests with `Accept: application/json, text/event-stream` header + SSE streaming parser | DONE (8/8 pass) |
| 3 | Proxy test fails (406 Not Acceptable) | Fixed by adding proper Accept headers; bare GET returns 406 as expected | DONE |

### P1 (Parity - Should Fix This Session) — MOSTLY RESOLVED

| # | Gap | Fix | Status |
|---|-----|-----|--------|
| 4 | No `rebuild` / `rebuild-quick` targets | Added composite Makefile targets | DONE |
| 5 | `teardown` doesn't deregister tools first | Added `deregister-tools` dependency | DONE |
| 6 | No IP restriction on /mcp in proxy template | Added RFC1918 allow/deny block | DONE |
| 7 | MCP healthcheck uses socket instead of HTTP | Changed to urllib /health (curl not in image) | DONE |
| 8 | `init-dirs` doesn't create full data hierarchy | Expand to create data/slurm_hpc/{workspace,logs} with chown pattern | Backlog |
| 9 | No `show-tool-schemas` target | Add target calling registration script | Backlog |

### P2 (Backlog - Future Session)

| # | Gap | Fix | Effort |
|---|-----|-----|--------|
| 10 | Registration script is bash (hardcoded) | Migrate to Python with Pydantic introspection (bio/vfm pattern) | 2 hr |
| 11 | No `test-config` standalone target | Extract from test-unit into own target | 5 min |
| 12 | No `smoke-test` target | Add curl-based MCP JSON-RPC smoke test | 15 min |
| 13 | Missing nohup targets for some test categories | Add nohup-test-deployment, nohup-test-e2e | 10 min |
| 14 | generate-certs not in setup chain | Consider adding conditional cert gen to setup (like emsl) | 15 min |

---

## 5. Canonical MCP Server Stack Template

Based on cross-stack analysis, the canonical template for any new ADEPT MCP server stack:

```
examples/<stack_name>/
  Makefile                          # 500+ lines, all standard targets
  docker-compose.yaml               # Base services (MCP + proxy + Redis)
  docker-compose.cpu.yaml           # CPU overlay (if GPU support)
  docker-compose.gpu.yaml           # GPU overlay (if GPU support)
  Dockerfile                        # FROM agentic-framework-deps-base
  <stack>_proxy.conf.template       # Nginx reverse proxy config
  .env.example                      # Environment variable reference
  .gitignore                        # certs/, logs/, data/, .env
  README.md                         # Quick start + architecture
  certs/
    .gitkeep                        # Placeholder for TLS certs
  data/ -> ../../data/<stack>/      # Symlink to shared data root
  logs/                             # Test execution logs (gitignored)
  scripts/
    register_<stack>_tools.py       # Python tool registration (Pydantic introspection)
    generate-ca-and-certs.sh        # TLS cert generation (if needed)
  <stack>_mcp/                      # or <stack>_mcp_server/
    __init__.py
    __main__.py
    app.py                          # FastMCP application + /health endpoint
    config.py                       # Pydantic Settings with <STACK>_ prefix
    server.py                       # FastMCP instance + tool registration
    tools/                          # @mcp.tool() decorated functions
  tests/
    conftest.py                     # Shared fixtures
    __init__.py
    test_imports.py                 # Module import validation
    test_lint.py                    # Code quality checks (optional)
    test_schema_discovery.py        # MCP tool schema validation
    unit/
      __init__.py
      test_config.py                # Configuration tests
      test_tools_*.py               # Per-tool unit tests
    integration/
      __init__.py
      test_mcp_server.py            # Health, MCP protocol, tool discovery
      test_tls_proxy.py             # TLS integration tests
  docs/
    TESTING_STRATEGY.md             # 3-tier test architecture
    BOOTSTRAPPING.md                # Setup and operational guide
```

### Required Makefile Targets (all stacks)

```makefile
# Lifecycle
setup setup-cpu setup-gpu teardown rebuild rebuild-quick
start stop restart status

# Build
build build-cpu build-gpu build-no-cache

# Health
health wait-healthy

# Prerequisites
check-prerequisites check-cli check-network init-data init-env init-network

# Registration
register-tools deregister-tools verify-tools show-tool-schemas

# Testing (offline)
ensure-test-image ensure-log-dir
test-imports test-config test-unit test-schema test-all

# Testing (online)
test-deployment test-integration

# Testing (background)
nohup-test-all nohup-test-unit nohup-test-integration

# TLS (optional)
generate-certs test-tls test-certs

# Logging
logs logs-mcp logs-proxy

# Help
help
```

### Required docker-compose.yaml Patterns

```yaml
# All services join adept_application_network (external)
# MCP server healthcheck: curl -f http://localhost:<port>/health
# Proxy healthcheck: wget --spider -q http://127.0.0.1/health
# Redis healthcheck: redis-cli ping
# Data volumes: RO for models/checkpoints, RW for results/uploads
# Cert volume: ./certs:/etc/nginx/ssl:ro
# Proxy template: ./<stack>_proxy.conf.template mounted appropriately
```

### Required Proxy Template Patterns

```nginx
# /health - unrestricted, local JSON response
# /mcp - IP-restricted (RFC1918), proxy to MCP server, SSE streaming enabled
#   proxy_buffering off; proxy_cache off;
#   proxy_read_timeout 600s; proxy_send_timeout 600s;
#   client_max_body_size 50M;
#   proxy_http_version 1.1; proxy_set_header Connection "";
# / - catch-all 404 with endpoint listing
```

---

## 6. Test Results Summary (2026-03-30)

### slurm_hpc Tier 2/3 Test Results

| Suite | Tests | Passed | Skipped | Failed | Notes |
|-------|-------|--------|---------|--------|-------|
| **Imports** (Tier 1) | 18 | 18 | 0 | 0 | Clean after docstring changes |
| **Schema Discovery** (Tier 1) | 14 | 14 | 0 | 0 | Validates all 6 tools + schemas |
| **Deployment** (Tier 2) | 8 | 8 | 0 | 0 | MCP Accept header + SSE streaming fixed |
| **MCP Client** (Tier 2) | 11 | 11 | 0 | 0 | FastMCP Client protocol tests (new) |
| **Integration** (Tier 2) | 22 | 10 | 12 | 0 | TLS tests skip (separate target) |
| **TLS** (Tier 2) | 13 | 11 | 2 | 0 | Docker CLI skip expected in container |
| **E2E** (Tier 3) | 12 | 8 | 0 | 4 | docker exec not in container (expected) |
| **Total** | **98** | **80** | **14** | **4** | 4 failures = infra gap (Docker CLI) |

### Service Log Cross-Reference Evidence

MCP server logs confirm test lifecycle:
- `GET /mcp` → 406 (bare GET, no Accept header — confirms alive)
- `POST /mcp` → 400 (missing session ID — transport alive)
- `POST /mcp` → 200 (initialize — session created)
- `POST /mcp` → 200 (tools/list with session — 6 tools returned)
- `GET /health` → 404 (MCP has no health route — nginx provides it)

nginx proxy logs confirm routing:
- `/health` → 200 (local response)
- `/mcp` → proxied to MCP server (406/400/200 as above)
- `/nonexistent` → 404 (catch-all)

---

## 7. References

- biofoundation Makefile: `examples/biofoundation_mcp_server/Makefile` (512 lines)
- vfm Makefile: `examples/vfm_mcp_server/Makefile` (499 lines)
- emsl_sandbox Makefile: `examples/emsl_sandbox/Makefile` (449 lines)
- slurm_hpc Makefile: `examples/slurm_hpc/Makefile` (708+ lines)
- academy Makefile: `examples/academy_mcp_server/Makefile`
- Nginx proxy configs: `*_proxy.conf.template` per stack
- TESTING_STRATEGY.md: `examples/slurm_hpc/docs/TESTING_STRATEGY.md`
- SPIFFE_IMPLEMENTATION_TRACKER.md: `examples/slurm_hpc/docs/SPIFFE_IMPLEMENTATION_TRACKER.md`
- MCP Server Template: `examples/mcp_server_template/README.md`
