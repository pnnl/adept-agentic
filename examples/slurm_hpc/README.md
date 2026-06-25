# Slurm HPC Example Stack for ADEPT

Demonstration of HPC integration via Slurm. Includes a full Slurm cluster (mysql, slurmdbd, slurmctld, slurmrestd, 2 compute nodes) and a FastMCP server that registers as an external tool with the ADEPT stack.

## Architecture

```
adept_application_network (external)          slurm_backend_network (internal)
┌──────────────────────────────┐     ┌──────────────────────────────────────┐
│  ADEPT orchestration_service │     │  mysql → slurmdbd → slurmctld       │
│  agent_gateway               │     │                  → slurmrestd:6820  │
│                              │     │                  → c1, c2           │
│  slurm_nginx_proxy ──────────┼─────┼── slurm_mcp_server ────────────────│
│  (host:9820 HTTP, 9821 HTTPS)│     │  (dual-homed: both networks)        │
└──────────────────────────────┘     └──────────────────────────────────────┘
```

## Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| mysql | mariadb:11 | Internal | Job accounting DB |
| slurmdbd | slurm-hpc:25.11.2 | Internal | Database daemon |
| slurmctld | slurm-hpc:25.11.2 | Internal | Cluster controller |
| slurmrestd | slurm-hpc:25.11.2 | Internal | REST API (6820) |
| c1, c2 | slurm-hpc:25.11.2 | Internal | Compute nodes |
| slurm_mcp_server | slurm-mcp:latest | 8002 | FastMCP server |
| slurm_nginx_proxy | nginx:alpine | 9820 (HTTP), 9821 (HTTPS) | Reverse proxy |

## MCP Tools (6)

| Tool | Description |
|------|-------------|
| `submit_slurm_job` | Submit a batch job with script + resource spec |
| `get_job_details` | Get status/details for a specific job |
| `cancel_slurm_job` | Cancel a running or pending job |
| `ping` | Test cluster connectivity |
| `list_cluster_jobs` | List jobs with optional filters |
| `get_cluster_summary` | Full cluster overview with recommendations |

## Quick Start

```bash
# Full setup (preflight + build + start + bootstrap JWT + register tools)
# Automatically creates .env from .env.example, required directories, and Docker network
make setup

# Verify everything works
make validate-all
```

### Manual Flow

```bash
# Run pre-flight checks (prerequisites, .env, directories, network)
make preflight

# Build images (Slurm RPM build takes ~10 minutes first time)
make build

# Start all 8 services
make start

# Wait for cluster health, then bootstrap JWT credentials
make wait-healthy
make bootstrap-jwt

# Restart MCP server to pick up JWT credentials
make restart-mcp

# Register tools with ADEPT (requires core stack running)
make register-tools
make verify-tools
```

## Bootstrap Flow

The Slurm cluster generates a random HMAC key at first startup. The bootstrap process extracts this key and configures the MCP server to generate JWT tokens on-the-fly:

1. `slurmdbd` creates `/etc/slurm/jwt_hs256.key` on first boot
2. `bootstrap-jwt.sh` extracts the base64-encoded key
3. Key is written to `.env` as `SLURM_JWT_KEY`
4. MCP server's `JWTTokenManager` uses the key to generate short-lived tokens per-request

## Decoupled Architecture

The MCP server is decoupled from the backend. It connects to any Slurm REST API via `SLURM_API_URL`:

```bash
# Point to a different cluster (edit .env):
SLURM_API_URL=https://production-slurm.example.com:6820
SLURM_JWT_KEY=<base64-encoded-hmac-key-from-production>

# Restart MCP server
make restart-mcp
```

## Makefile Targets

### Setup & Lifecycle

| Target | Description |
|--------|-------------|
| `setup` | Full end-to-end setup (preflight + build + start + bootstrap + register) |
| `preflight` | Run all pre-flight checks (prerequisites + dirs + env + network) |
| `start` / `stop` / `restart` | Lifecycle management |
| `teardown` | Remove everything (containers, volumes, networks) |
| `status` / `logs` / `health` | Observe running services |

### Build

| Target | Description |
|--------|-------------|
| `build` | Build all custom images (backend + MCP server) |
| `build-all` | Build all custom images + pull external images |
| `build-backend` | Build Slurm backend image only |
| `build-mcp` | Build MCP server image only |
| `pull` | Pull external images (mariadb:11, nginx:alpine) |
| `build-no-cache` | Rebuild all images without cache |
| `build-backend-no-cache` | Rebuild backend image without cache |
| `build-mcp-no-cache` | Rebuild MCP server image without cache |

### Per-Service

| Target | Description |
|--------|-------------|
| `restart-mcp` | Restart MCP server (after bootstrap) |
| `rebuild-mcp` | Rebuild + restart MCP server |
| `rebuild-backend` | Rebuild + restart backend services |

### TLS / HTTPS

| Target | Description |
|--------|-------------|
| `generate-certs` | Generate CA + server certs (requires `SLURM_HOST_IP`) |
| `health-proxy` | Check proxy health (HTTP + HTTPS if certs present) |

### Bootstrap & Registration

| Target | Description |
|--------|-------------|
| `bootstrap-jwt` | Extract HMAC key + generate JWT |
| `register-tools` | Register 27 tools with ADEPT |
| `deregister-tools` | Remove tools from ADEPT |
| `verify-tools` | Check Redis for tool registration |

#### Tool Registration Requirements

The `register-tools` target calls `scripts/register-slurm-tools.sh` which uses
the `agentic` CLI to register 27 tools with the ADEPT core tool registry via Redis.

**Prerequisites**:
- ADEPT core stack running (keycloak, agent_gateway, orchestration_service)
- Slurm stack running and healthy (`make wait-healthy`)
- `agentic` CLI installed (`pip install -e src/` from project root)
- `/etc/hosts` contains: `127.0.0.1 keycloak agent_gateway orchestration_service redis`

**Token Issuer Requirement**: The `agentic` CLI authenticates via Keycloak.
The token issuer must match what `orchestration_service` expects
(`http://keycloak:8180/realms/master`). Set `KEYCLOAK_URL=http://keycloak:8180`
and ensure `/etc/hosts` aliases `keycloak` to `127.0.0.1`.

```bash
# Register (MCP URL defaults to http://slurm_mcp_server:8002/mcp)
KEYCLOAK_URL=http://keycloak:8180 make register-tools
make verify-tools

# Verify on core (from project root)
make list-registered-tools
```

**Registered tool names** (prefix `slurm_hpc_`):
`slurm_hpc_submit_job`, `slurm_hpc_get_job_details`, `slurm_hpc_cancel_job`,
`slurm_hpc_ping`, `slurm_hpc_list_jobs`, `slurm_hpc_cluster_summary`

### Tests

All test targets auto-build the `slurm-mcp:latest` image if it doesn't exist.

| Target | Description | Services Required |
|--------|-------------|-------------------|
| `test-all` | Run all offline tests (lint + imports + unit) | None |
| `test-lint` | Linting and code quality | None |
| `test-imports` | Module import validation | None |
| `test-unit` | Unit tests | None |
| `test-integration` | Integration tests | MCP server running |
| `test-e2e` | End-to-end tests | Full stack running |
| `test-infrastructure-health` | Tool visibility in ADEPT core Redis (dual-network) | ADEPT core stack |

### Validation

| Target | Description |
|--------|-------------|
| `validate-cluster` | Test Slurm backend health |
| `validate-mcp` | Test MCP server health |
| `validate-all` | Run all validations |

## Dependency Chains

The Makefile enforces proper dependency ordering:

```
make setup
  └─ preflight (prerequisites + dirs + env + network)
     └─ build (build-backend + build-mcp)
        └─ start (init-dirs + init-network + compose up)
           └─ wait-healthy → bootstrap-jwt → restart-mcp → register-tools → verify-tools

make test-all  (= test-lint + test-imports + test-unit)
  └─ each target depends on ensure-test-image
     └─ if slurm-mcp:latest missing → auto-builds via build-mcp

make test-integration / test-e2e
  └─ ensure-test-image + init-network
```

Running `make test-all` on a fresh clone will automatically build the required `slurm-mcp:latest` image before running any tests.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SLURM_VERSION` | 25.11.2 | Slurm version to build |
| `SLURM_API_URL` | http://slurmrestd:6820 | REST API URL |
| `SLURM_JWT_KEY` | (set by bootstrap) | Base64 HMAC key |
| `SLURM_SERVICE_USER` | root | JWT username claim |
| `SLURM_MCP_PORT` | 8002 | MCP server host port |
| `SLURM_PROXY_PORT` | 9820 | Nginx proxy HTTP host port |
| `SLURM_PROXY_HTTPS_PORT` | 9821 | Nginx proxy HTTPS host port |
| `SLURM_PROTO` | http | Protocol for tool registration (`http` or `https`) |
| `SLURM_HOST_IP` | (unset) | Host IP for cert SAN (required for `generate-certs`) |
| `SLURM_CA_CERT` | ./certs/ca.crt | CA cert path for HTTPS verification |
| `MYSQL_PASSWORD` | password | MariaDB password |

## TLS / HTTPS (Cross-Host Deployments)

When the Slurm HPC stack runs on a different host from ADEPT, the orchestration_service uses HTTPS to call external MCP tools. Without TLS, tool calls will fail with SSL verification errors.

### When TLS is Needed

- **Same host** (Slurm + ADEPT on same VM): Not needed. HTTP via Docker network works fine.
- **Cross-host** (Slurm on HPC node, ADEPT on EC2): Required. ADEPT defaults to HTTPS verification for external tool calls.

### Generate Certificates

On the **Slurm host**:

```bash
cd examples/slurm_hpc

# Generate CA + server cert (auto-detect host IP)
SLURM_HOST_IP=$(hostname -I | awk '{print $1}') make generate-certs

# Or specify IP explicitly
SLURM_HOST_IP=10.0.1.50 make generate-certs

# With extra SAN entries
SLURM_HOST_IP=10.0.1.50 SLURM_EXTRA_DNS=slurm.lab.org SLURM_EXTRA_IPS=192.168.1.100 make generate-certs
```

Output in `certs/`:
- `ca.crt` — CA certificate (distribute to ADEPT host)
- `ca.key` — CA private key (keep secure, never distribute)
- `slurm.crt` — Server certificate (used by nginx)
- `slurm.key` — Server private key (used by nginx)

### Enable TLS on Slurm Proxy

Restart the proxy after generating certs — nginx auto-detects them:

```bash
make restart-proxy
# Logs should show: "[slurm-proxy] TLS enabled (certs found)"

# Verify both HTTP and HTTPS
make health-proxy
```

### Install CA on ADEPT Host

On the **ADEPT host** (EC2):

```bash
# 1. Copy ca.crt from the Slurm host
scp slurm-host:examples/slurm_hpc/certs/ca.crt examples/slurm_hpc/certs/ca.crt

# 2. Rebuild orchestration_service to pick up the new CA cert
make rebuild-orchestrator
# install-external-ca-certs.sh auto-discovers and injects all CA certs in
# /usr/local/share/ca-certificates/ into the Python certifi bundle
```

### Request Path (How Traffic Reaches the MCP Server)

The MCP server itself **never speaks HTTPS** — only the nginx proxy handles TLS termination. All three registration use cases ultimately deliver plain HTTP to the MCP server:

```
Use Case 1: HTTP (same host, default)
  orchestration_service → http://slurm_mcp_server:8002/mcp
  (Direct Docker DNS, no proxy involved)

Use Case 2: HTTPS same-host (via nginx proxy on Docker network)
  orchestration_service → https://slurm_nginx_proxy:443/mcp
                          ↓ TLS termination
                          → http://slurm_mcp_server:8002/mcp

Use Case 3: HTTPS cross-host (via host port mapping)
  orchestration_service → https://10.0.1.50:9821/mcp
                          ↓ host:9821 → container:443
                          ↓ TLS termination (nginx)
                          → http://slurm_mcp_server:8002/mcp
```

### Tool Registration Routing

The registration script uses **protocol-aware defaults** — the endpoint changes based on `SLURM_PROTO` to ensure traffic is routed through the correct service:

| Use Case | `SLURM_PROTO` | Default Host | Default Port | Registered URL |
|----------|---------------|--------------|--------------|----------------|
| HTTP direct | `http` (default) | `slurm_mcp_server` | `8002` | `http://slurm_mcp_server:8002/mcp` |
| HTTPS same-host | `https` | `slurm_nginx_proxy` | `443` | `https://slurm_nginx_proxy:443/mcp` |
| HTTPS cross-host | `https` | (override required) | (override required) | `https://10.0.1.50:9821/mcp` |

All defaults can be overridden via `SLURM_MCP_HOST` and `SLURM_MCP_PORT` environment variables.

### Register Tools via HTTPS

```bash
# Same-host HTTPS (through nginx proxy on Docker network)
# Defaults to slurm_nginx_proxy:443 when SLURM_PROTO=https
SLURM_PROTO=https ./scripts/register-slurm-tools.sh register

# Cross-host HTTPS (remote Slurm host, external IP + port)
SLURM_PROTO=https \
  SLURM_MCP_HOST=10.0.1.50 \
  SLURM_MCP_PORT=9821 \
  ./scripts/register-slurm-tools.sh register
```

### Port Mapping Reference

No host ports 80 or 443 are exposed — the Slurm HPC stack uses high-numbered configurable ports to avoid clashes with the main ADEPT stack running on the same VM.

| Host Port | Container Port | Service | Configurable Via |
|-----------|----------------|---------|------------------|
| 9820 | 80 | nginx HTTP | `SLURM_PROXY_PORT` |
| 9821 | 443 | nginx HTTPS | `SLURM_PROXY_HTTPS_PORT` |
| 8002 | 8002 | MCP server | `SLURM_MCP_PORT` |

Without certs in `certs/`, nginx only listens on container port 80. The host:9821 → container:443 mapping is harmless when nginx isn't listening on 443.

### Verification

```bash
# HTTP still works (backward compatible)
curl -sf http://localhost:9820/health

# HTTPS with CA cert
curl -sf --cacert certs/ca.crt https://localhost:9821/health

# HTTPS without CA cert (should fail — proves TLS is enforced)
curl -sf https://localhost:9821/health  # Expected: SSL error

# Dual health check
make health-proxy
```

### Backward Compatibility

Without certs in `certs/`, the proxy starts in HTTP-only mode. The HTTPS port (9821) is mapped but nginx does not listen on 443. All existing workflows are unchanged.

## Data Workspace

Job scripts, inputs, and outputs live in `data/slurm_workspace/` (bind-mounted as `/data` in compute nodes). This is the default `current_working_directory` for submitted jobs.

---

*Created: Session 75 (2026-03-05)*
*Updated: Session 76 (2026-03-05) — Added TLS/HTTPS support*
*Sources: temp/slurm-docker-cluster + temp/slurmmcp*
