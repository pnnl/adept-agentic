# Slurm HPC MCP Server - Stack Lifecycle Audit

**Stack**: examples/slurm_hpc
**Date**: 2026-03-29
**Author**: Paul Rigor

---

## 1. Stack Overview

| Attribute | Value |
|-----------|-------|
| Domain | HPC job scheduling (Slurm) |
| Services | 8 (mysql, slurmdbd, slurmctld, slurmrestd, c1, c2, slurm_mcp_server, slurm_nginx_proxy) |
| MCP Port | 8002 |
| Proxy HTTP/HTTPS | 9820 / 9821 |
| Redis | N/A (stateless MCP server) |
| Tool Count | 6 (submit_job, get_job_details, cancel_job, ping, list_jobs, cluster_summary) |
| Tool Prefix | slurm_hpc |
| Base Image | slurm-mcp:latest (custom, not deps-base) |
| GPU | No |
| Networks | slurm_backend_network (internal) + adept_application_network (external) |

---

## 2. Makefile Targets (708 lines)

### 2A. Configuration (Lines 10-35)

| Variable | Default | Purpose |
|----------|---------|---------|
| CONTAINER_ENGINE | docker | Overridable (podman) |
| SLURM_VERSION | 25.11.2 | Slurm backend version |
| ADMIN_USER / ADMIN_PASS | admin / admin | Keycloak creds for tool registration |
| AGENTIC_CLI | Auto-detect | .venv311, .venv, or PATH |

### 2B. Lifecycle Targets

| Target | Dependencies | Lines |
|--------|--------------|-------|
| setup | preflight build start wait-healthy bootstrap-jwt restart-mcp register-tools verify-tools | 63-64 |
| preflight | check-prerequisites init-dirs init-env init-network | 94-95 |
| check-prerequisites | (validates engine + compose) | 70-75 |
| init-network | create adept_application_network | 77-79 |
| init-env | copy .env.example to .env if missing | 82-87 |
| init-dirs | create data/slurm_workspace | 90-91 |

### 2C. Build Targets

| Target | Dependencies | Lines |
|--------|--------------|-------|
| build-backend | init-network | 102-105 |
| build-mcp | init-network | 108-111 |
| pull | (mariadb:11 + nginx:alpine) | 114-118 |
| build | build-backend build-mcp | 121-122 |
| build-all | pull build | 125-126 |
| build-no-cache | init-network (all images --no-cache) | 129-131 |

### 2D. Container Control

| Target | Lines |
|--------|-------|
| start | 146-149 |
| stop | 152-153 |
| restart | 156 |
| teardown | 159-161 (down -v --remove-orphans) |
| status | 165 |
| logs | 168-169 |
| health | 172-176 (inspect 4 services) |
| wait-healthy | 179-191 (180s max, scontrol ping) |

### 2E. Per-Service Targets

**Backend**: start-backend, stop-backend, restart-backend, rebuild-backend
**MCP**: start-mcp, stop-mcp, restart-mcp, rebuild-mcp, logs-mcp, health-mcp
**Proxy**: start-proxy, stop-proxy, restart-proxy, logs-proxy, health-proxy

### 2F. TLS / Security

| Target | Lines |
|--------|-------|
| generate-certs | 264-268 (requires SLURM_HOST_IP) |
| start-spire | 523-525 (--profile spire) |
| stop-spire | 528-529 |
| start-oidc | 532-534 (--profile oidc) |
| stop-oidc | 537-538 |
| start-secure | 541-542 (start + spire + oidc) |
| bootstrap-spire | 545-546 |
| start-federation | 549-551 (--profile federation) |
| stop-federation | 554-555 |
| bootstrap-federation | 558-559 |

### 2G. Bootstrap & Registration

| Target | Lines |
|--------|-------|
| bootstrap-jwt | 275-277 (extract HMAC, generate JWT, detect API version) |
| register-tools | 280-282 (27 tools via bash script) |
| deregister-tools | 285-286 |
| verify-tools | 289-290 |

### 2H. Validation

| Target | Lines |
|--------|-------|
| validate-cluster | 297-314 (containers, munge, scontrol, nodes, test job) |
| validate-mcp | 317-325 (health checks) |
| validate-all | 328-329 (cluster + mcp + tools) |

### 2I. Test Infrastructure (DRY Variables, Lines 335-350)

```
TEST_IMAGE = slurm-mcp:latest
TEST_VOLS = source + tests :ro
TEST_ENV = PYTHONPATH + HOME=/tmp
TEST_RUN_OFFLINE = docker run --rm (no network)
TEST_RUN_NET = docker run --rm --network=adept_application_network
```

### 2J. Test Targets

**Offline (no services)**:

| Target | Files | Lines |
|--------|-------|-------|
| test-lint | test_lint.py | 366-375 |
| test-imports | test_imports.py | 378-387 |
| test-unit | tests/unit/ | 390-400 |
| test-certs | test_generate_certs.py | 435-445 |
| test-schema | test_schema_discovery.py | 448-453 |
| test-spiffe | test_spiffe_auth.py | 482-487 |
| test-identity-mapper | test_identity_mapper.py | 490-495 |
| test-globus | test_globus_token_exchange.py | 498-507 |
| test-security | spiffe + identity + globus | 510-511 |
| test-federation | federation_config + jwt_bridge | 563-573 |
| test-all | all offline | 514-515 |

**Online (services required)**:

| Target | Files | Lines |
|--------|-------|-------|
| test-deployment | test_slurm_deployment.py | 456-462 |
| test-integration | tests/integration/ | 403-416 |
| test-e2e | test_slurm_mcp_e2e.py | 419-432 |
| test-tls | test_tls_proxy.py (+ certs) | 465-479 |

**Nohup (background)**:

| Target | Log File | Lines |
|--------|----------|-------|
| nohup-test-all | logs/test_all_TIMESTAMP.log | 591-594 |
| nohup-test-unit | logs/test_unit_TIMESTAMP.log | 596-598 |
| nohup-test-security | logs/test_security_TIMESTAMP.log | 600-602 |
| nohup-test-integration | logs/test_integration_TIMESTAMP.log | 604-606 |
| nohup-test-deployment | logs/test_deployment_TIMESTAMP.log | 608-610 |

---

## 3. Docker Compose Architecture (379 lines)

### Networks

| Network | Type | Services |
|---------|------|----------|
| slurm_backend_network | bridge (internal) | mysql, slurmdbd, slurmctld, slurmrestd, c1, c2, slurm_mcp_server |
| adept_application_network | external | slurm_mcp_server, slurm_nginx_proxy |

### Volumes

| Volume | Type | Mount Target |
|--------|------|-------------|
| etc_munge | docker | Munge auth secrets |
| etc_slurm | docker | Slurm configuration |
| var_lib_mysql | docker | MySQL data |
| var_log_slurm | docker | Slurm logs |
| slurm_jobdir | bind (data/slurm_workspace) | Job working directory |
| slurm_spire_*_data | docker | SPIRE server state |
| slurm_spire_*_socket | docker | SPIRE Workload API |

### Services

| Service | Image | Port | Health | Network |
|---------|-------|------|--------|---------|
| mysql | mariadb:11 | (internal) | healthcheck.sh --connect | backend |
| slurmdbd | slurm-hpc:25.11.2 | (internal) | N/A | backend |
| slurmctld | slurm-hpc:25.11.2 | (internal) | scontrol ping | backend |
| slurmrestd | slurm-hpc:25.11.2 | (internal) | N/A | backend |
| c1 | slurm-hpc:25.11.2 | (internal) | N/A | backend |
| c2 | slurm-hpc:25.11.2 | (internal) | N/A | backend |
| slurm_mcp_server | slurm-mcp:latest | 8002 | socket connect | both |
| slurm_nginx_proxy | nginx:alpine | 9820/9821 | wget /health | external |

### Optional Profiles

| Profile | Services | Purpose |
|---------|----------|---------|
| spire | slurm_spire_server, slurm_spire_agent | SPIFFE workload identity |
| oidc | slurm_oauth2_proxy | Keycloak OIDC auth |
| federation | adept_spire_server, adept_spire_agent | Cross-domain trust |

---

## 4. Data Directory Structure

### Current
```
data/slurm_workspace/     # Job output files (bind-mounted as slurm_jobdir)
```

### Expected (per parity analysis)
```
data/slurm_hpc/
  workspace/              # Job output files
  logs/                   # Slurm log archive
```

**Gap**: `init-dirs` only creates `slurm_workspace/`. No `data/slurm_hpc/` hierarchy.

---

## 5. Certs Directory

### Expected
```
certs/
  .gitkeep
  ca.key     (600, CA private key)
  ca.crt     (644, CA certificate)
  slurm.key  (600, server private key)
  slurm.crt  (644, server certificate)
```

### Current (broken)
```
certs/
  .gitkeep
  ca.key     (600, 3272 bytes - valid)
  ca.crt/    (DIRECTORY - should be a file, root-owned empty dir from Docker mount)
```

**Root cause**: Docker created `ca.crt` as a directory when the compose file mounted
`./certs:/etc/nginx/ssl:ro` and the file didn't exist yet. Docker bind-mount creates
missing source paths as directories (not files).

---

## 6. Scripts Directory

| Script | Lines | Purpose |
|--------|-------|---------|
| bootstrap-jwt.sh | 116 | Extract HMAC key, generate JWT, detect API version |
| register-slurm-tools.sh | 319 | Register/deregister/verify 27 tools (bash, hardcoded schemas) |
| generate-ca-and-certs.sh | 129 | CA + server cert generation (requires SLURM_HOST_IP) |
| bootstrap-spire.sh | 69 | SPIRE server+agent bootstrap, workload registration |
| bootstrap-federation.sh | 168 | Bidirectional trust bundle exchange |

---

## 7. Source Modules

```
slurm_mcp_server/slurm_mcp/
  __init__.py        app.py          client.py
  config.py          models.py       prompts.py
  resources.py       tools.py        utils.py
  __main__.py        spiffe_auth.py  identity_mapper.py
  jwt_bridge.py
```

13 modules total. Domain-specific: spiffe_auth, identity_mapper, jwt_bridge.

---

## 8. Test Files

```
tests/
  conftest.py                    test_imports.py
  test_lint.py                   test_schema_discovery.py
  test_slurm_deployment.py       test_slurm_mcp_e2e.py
  test_slurm_cluster.sh
  unit/
    test_app.py                  test_client.py
    test_config.py               test_models.py
    test_utils.py                test_generate_certs.py
    test_spiffe_auth.py          test_identity_mapper.py
    test_globus_token_exchange.py test_jwt_bridge.py
    test_federation_config.py
  integration/
    test_mcp_server.py           test_tls_proxy.py
```

22 test files total. Tier 1: 387 passed, 31 skipped. Tier 2/3: pending.

---

## 9. Proxy Configuration

### slurm_proxy.conf.template (39 lines)
- /health: local 200 JSON (unrestricted)
- /mcp: proxy to MCP server (NO IP restriction - gap)
- /: catch-all 404
- SSE streaming: buffering off, 600s timeouts, 50M body

### slurm_proxy_oidc.conf.template (73 lines)
- Extends standard with oauth2_proxy auth_request
- /oauth2/auth: internal auth handler
- /mcp: auth_request + proxy with X-Auth-User/Groups/Email headers

### TLS Injection (docker-compose.yaml lines 212-217)
- Runtime detection: `if [ -f /etc/nginx/ssl/slurm.crt ]`
- Injects TLS block via `sed` into default.conf
- Falls back to HTTP-only if certs missing

---

## 10. Environment Configuration

### .env.example Sections
- Slurm version (25.11.2)
- MySQL/MariaDB credentials
- Slurm REST API (URL, version, SSL, timeout)
- JWT authentication (key, token, user)
- Port mappings (8002, 9820, 9821)
- TLS/HTTPS (proto, host IP, CA cert path)
- ADEPT integration (admin creds)
- OIDC (issuer, client, cookie secret)
- SPIFFE (enabled flag)
- Globus (identity map path)

### config.py (SlurmConfig)
- env_prefix: SLURM_
- Fields: api_url, api_version, verify_ssl, timeout, jwt_key, service_jwt, service_user
- SPIFFE: spiffe_enabled, spiffe_endpoint_socket, spiffe_audience
- State emojis: 18 job states, 24 node states

---

## 11. Parity Gaps (vs. biofoundation/vfm)

| # | Gap | Severity | Fix |
|---|-----|----------|-----|
| 1 | No `rebuild` / `rebuild-quick` targets | P1 | Add composite targets |
| 2 | `teardown` doesn't deregister first | P1 | Add dependency |
| 3 | No IP restriction on /mcp | P1 | Add RFC1918 allow/deny |
| 4 | MCP healthcheck uses socket, not HTTP | P1 | Change to curl |
| 5 | `init-dirs` doesn't create full hierarchy | P1 | Expand to data/slurm_hpc/ pattern |
| 6 | No `show-tool-schemas` target | P2 | Add target |
| 7 | Registration in bash (hardcoded) | P2 | Migrate to Python |
| 8 | certs/ca.crt is a directory | P0 | Remove, regenerate |
| 9 | No `smoke-test` target | P2 | Add curl JSON-RPC test |
| 10 | No separate `test-config` target | P2 | Extract from test-unit |
