# Connecting Claude Code to a Local ADEPT Deployment

This tutorial connects Claude Code (running on your development machine) to a local ADEPT stack (running via Docker Compose on the same host). The MCP server bridges the two by running inside a Docker container attached to the ADEPT network, giving it direct access to all services without port-mapping or TLS issues.

## Status

| Client | Connector Status | Test Evidence |
|--------|-----------------|---------------|
| **Claude Desktop** (macOS/Windows) | Fully validated | Sessions 89-104: 306 tests (4 tiers), 7/7 doctor, file uploads, plot embedding, MCP bridge |
| **Claude Code CLI** | Fully validated | Session 108: Docker doctor 7/7, `.mcp.json` generated, live smoke tests passed (list_models, list_tools 27 external, create_session, chat round-trip, sandbox code execution) |

The connector package (`adept_connectors.connectors.claude`) is shared between Claude Desktop and Claude Code — the same MCP server, same tools, different transport configuration (HTTP for Desktop, STDIO for Code CLI).

## Quick Start (Interactive Skill)

If you're already in a Claude Code session, type:

```
/connect-adept
```

This walks through the entire setup interactively — asks local vs remote, collects credentials, generates `.mcp.json`, and runs the doctor check. Works for both local Docker stacks and remote servers.

The rest of this document explains the setup manually for reference or when customization is needed.

## Prerequisites

- ADEPT stack running locally (`make start` from the project root)
- Docker installed and accessible (`docker ps` succeeds)
- Claude Code installed (`claude --version`)
- A valid ADEPT API key (see [Obtaining an API Key](#obtaining-an-api-key))

## Architecture

```
Claude Code (host)
    │ STDIO
    ▼
docker run -i (agentic-framework-deps-base)
    │ adept_connectors MCP server
    │ ADEPT_BASE_URL=http://agent_gateway:8081/v1
    ▼
adept_application_network
    │
    ├── agent_gateway:8081  (Tier 1 — auth proxy)
    ├── keycloak:8180       (IAM — token issuer)
    └── orchestration_service:8084  (Tier 2 — agent logic)
```

Claude Code communicates with the MCP server over STDIO. The MCP server runs inside a container attached to the ADEPT Docker network, so it reaches all services via internal DNS — no port mapping or TLS issues.

## Setup

### Step 1: Verify the ADEPT stack is running

```bash
docker ps --format "{{.Names}}" | grep -E "agent_gateway|orchestration_service|keycloak"
```

You should see all three containers. If not, run `make start` from the project root.

### Step 2: Run the doctor check

Confirm the container can reach ADEPT from inside the Docker network:

```bash
docker run --rm -i \
  --network=adept_application_network \
  -v "$(pwd)/examples/adept_connectors/src":/app/connector_src:ro \
  -e PYTHONPATH=/app/connector_src \
  -e ADEPT_BASE_URL=http://agent_gateway:8081/v1 \
  -e ADEPT_AUTH_METHOD=api_key \
  -e ADEPT_API_KEY=sk-service-openwebui-YOUR_KEY_HERE \
  -e ADEPT_VERIFY_SSL=false \
  agentic-framework-deps-base \
  /app/.venv/bin/python -m adept_connectors.connectors.claude doctor
```

Expected output:

```
Checking configuration...      [PASS]
Checking authentication...     [PASS]
Checking ADEPT connectivity... [PASS]
Checking MCP proxy endpoint... [PASS]
Checking AG-UI endpoint...     [PASS]
Checking Files API endpoint... [PASS]
Checking Claude Desktop config... [SKIP]
Result: 7/7 checks passed
```

If any check fails, see [Troubleshooting](#troubleshooting).

### Step 3: Create `.mcp.json`

Create a `.mcp.json` file in your project root (the directory where you run `claude`):

```json
{
  "mcpServers": {
    "adept": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--network=adept_application_network",
        "-v", "/absolute/path/to/examples/adept_connectors/src:/app/connector_src:ro",
        "-e", "PYTHONPATH=/app/connector_src",
        "-e", "ADEPT_BASE_URL=http://agent_gateway:8081/v1",
        "-e", "ADEPT_AUTH_METHOD=api_key",
        "-e", "ADEPT_API_KEY=sk-service-openwebui-YOUR_KEY_HERE",
        "-e", "ADEPT_VERIFY_SSL=false",
        "agentic-framework-deps-base",
        "/app/.venv/bin/python", "-m", "adept_connectors.connectors.claude"
      ]
    }
  }
}
```

Replace:
- `/absolute/path/to/examples/adept_connectors/src` with the real absolute path
- `sk-service-openwebui-YOUR_KEY_HERE` with your actual API key

### Step 4: Restart Claude Code

Exit and relaunch Claude Code in the project directory. The `adept` MCP server appears in the tool list automatically.

### Step 5: Verify in Claude Code

Ask Claude Code:

> "Use adept_list_models to check connectivity to the ADEPT server"

Claude Code will invoke the MCP tool and return available models.

## Available Tools

Once connected, these tools are available to Claude Code:

| Tool | Purpose |
|------|---------|
| `adept_create_session` | Start a persistent conversation session |
| `adept_chat` | Send messages to the ADEPT scientific agent |
| `adept_agui_run` | Send messages via the AG-UI protocol (richer events) |
| `adept_list_tools` | Discover all MCP tools on the ADEPT server |
| `adept_call_tool` | Call any ADEPT tool by name with arguments |
| `adept_list_models` | List available LLM models |
| `adept_upload_file` | Upload a file for agent processing |
| `adept_list_files` | List uploaded and generated files |
| `adept_get_image` | Fetch and display an image inline |
| `adept_download_artifact` | Download a file to the container filesystem |
| `adept_list_sessions` | List active conversation sessions |
| `adept_list_mcp_resources` | List MCP resources from the host |

## Example Workflows

### Scientific Query

```
You: "Use adept_create_session, then use adept_chat to ask ADEPT:
      What BLAST databases are available for nucleotide sequences?"
```

### Tool Discovery and Direct Invocation

```
You: "Use adept_list_tools to see what's on the ADEPT server,
      then use adept_call_tool to run websearch with query 'AlphaFold3 2026'"
```

### File Analysis

```
You: "Use adept_create_session, upload /tmp/experiment_results.csv
      via adept_upload_file, then use adept_chat to ask ADEPT to
      summarize the data and generate a plot"
```

### Multi-Agent Team

```
You: "Use adept_create_session, then use adept_chat to ask ADEPT:
      Create a multi-agent team with a biologist and data scientist
      to analyze this protein sequence: MVLSPADKTNVKAAWGKVGAHAGEYGAEALERMFLSFPTTKTYFPHFDLSH"
```

## Authentication Options

### API Key (recommended for local development)

Simplest method. Bypasses Keycloak entirely — the gateway validates against Redis/file lookup.

```json
"-e", "ADEPT_AUTH_METHOD=api_key",
"-e", "ADEPT_API_KEY=sk-service-openwebui-YOUR_KEY_HERE",
```

### Password (ROPC)

Uses Keycloak for JWT issuance. Works from inside the container because Docker DNS resolves `keycloak:8180`:

```json
"-e", "ADEPT_AUTH_METHOD=password",
"-e", "ADEPT_USERNAME=admin",
"-e", "ADEPT_PASSWORD=your-password",
"-e", "ADEPT_KEYCLOAK_URL=http://keycloak:8180",
```

### JWT (pre-obtained token)

Pass a valid JWT directly:

```json
"-e", "ADEPT_AUTH_METHOD=jwt",
"-e", "ADEPT_JWT_TOKEN=eyJhbGciOiJSUzI1NiIs...",
```

The token must have issuer `http://keycloak:8180/realms/master` to be accepted by the orchestration service.

## Obtaining an API Key

API keys are generated during stack bootstrap. To retrieve one:

```bash
# From the credentials directory
cat deployment/local/docker-compose/.env-keycloak-credentials-dir/OPENWEBUI_SERVICE_API_KEY

# Or from the consolidated env file
grep SERVICE_API_KEY deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials
```

Keys follow the format `sk-service-<client>-<random>`.

## Alternative: Password Auth with Internal Keycloak

If you need per-user identity (audit trail, ACL enforcement), use password auth. Inside the container, `keycloak:8180` resolves correctly, so the JWT issuer matches what the orchestration service expects:

```json
{
  "mcpServers": {
    "adept": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--network=adept_application_network",
        "-v", "/absolute/path/to/examples/adept_connectors/src:/app/connector_src:ro",
        "-e", "PYTHONPATH=/app/connector_src",
        "-e", "ADEPT_BASE_URL=http://agent_gateway:8081/v1",
        "-e", "ADEPT_AUTH_METHOD=password",
        "-e", "ADEPT_USERNAME=admin",
        "-e", "ADEPT_PASSWORD=admin",
        "-e", "ADEPT_KEYCLOAK_URL=http://keycloak:8180",
        "-e", "ADEPT_VERIFY_SSL=false",
        "agentic-framework-deps-base",
        "/app/.venv/bin/python", "-m", "adept_connectors.connectors.claude"
      ]
    }
  }
}
```

## Remote ADEPT Instance (e.g., AWS EC2 VM)

When ADEPT runs on a remote server (not the same machine as Claude Code), the connector runs directly on your local machine — no Docker network tricks needed. The connector reaches ADEPT over the network via its external HTTPS URL (through nginx).

### Architecture (Remote)

```
Your workstation                          Remote EC2 VM
─────────────────                         ──────────────────────
Claude Code                               nginx (443/TLS)
    │ STDIO                                  │
    ▼                                        ▼
uv run (adept_connectors)  ───HTTPS───▶  agent_gateway:8081
    │                                        │
    │                                        ▼
    │                                    orchestration_service
    │                                        │
    │                                    keycloak:8180
    └─ tokens issued by external URL ───────┘
       (matches Keycloak's FRONTEND_URL)
```

The issuer mismatch problem does not exist in this scenario because:
- Keycloak's `KEYCLOAK_FRONTEND_URL` is set to the external hostname (e.g., `https://your-adept-host.example.com`)
- Tokens obtained via that URL have issuer `https://your-adept-host.example.com/realms/master`
- The orchestration service trusts that issuer (it's in its `valid_issuers` list)

### Step 1: Install adept_connectors locally

```bash
# Clone the repo (or just the examples/adept_connectors directory)
git clone https://github.com/pnnl/adept-agentic.git
cd adept-agentic/examples/adept_connectors

# Install with uv
uv sync --extra claude
```

### Step 2: Verify connectivity from your machine

```bash
cd examples/adept_connectors

# API key auth (simplest)
ADEPT_BASE_URL="https://your-adept-host.example.com/v1" \
ADEPT_AUTH_METHOD=api_key \
ADEPT_API_KEY="sk-service-openwebui-YOUR_KEY_HERE" \
ADEPT_VERIFY_SSL=false \
uv run python -m adept_connectors.connectors.claude doctor

# Password auth (per-user identity)
ADEPT_BASE_URL="https://your-adept-host.example.com/v1" \
ADEPT_AUTH_METHOD=password \
ADEPT_USERNAME="your.username@example.org" \
ADEPT_PASSWORD='your-password' \
ADEPT_KEYCLOAK_URL="https://your-adept-host.example.com" \
ADEPT_VERIFY_SSL=false \
uv run python -m adept_connectors.connectors.claude doctor
```

### Step 3: Create `.mcp.json` (API key — simplest)

```json
{
  "mcpServers": {
    "adept": {
      "command": "uv",
      "args": [
        "run", "--extra", "claude",
        "--directory", "/absolute/path/to/examples/adept_connectors",
        "python", "-m", "adept_connectors.connectors.claude"
      ],
      "env": {
        "ADEPT_BASE_URL": "https://your-adept-host.example.com/v1",
        "ADEPT_AUTH_METHOD": "api_key",
        "ADEPT_API_KEY": "sk-service-openwebui-YOUR_KEY_HERE",
        "ADEPT_VERIFY_SSL": "false"
      }
    }
  }
}
```

### Step 3 (alt): Create `.mcp.json` (password auth)

```json
{
  "mcpServers": {
    "adept": {
      "command": "uv",
      "args": [
        "run", "--extra", "claude",
        "--directory", "/absolute/path/to/examples/adept_connectors",
        "python", "-m", "adept_connectors.connectors.claude"
      ],
      "env": {
        "ADEPT_BASE_URL": "https://your-adept-host.example.com/v1",
        "ADEPT_AUTH_METHOD": "password",
        "ADEPT_USERNAME": "your.username@example.org",
        "ADEPT_PASSWORD": "your-password",
        "ADEPT_KEYCLOAK_URL": "https://your-adept-host.example.com",
        "ADEPT_VERIFY_SSL": "false"
      }
    }
  }
}
```

### Step 4: Restart Claude Code and verify

Same as the local setup — restart Claude Code and ask it to call `adept_list_models`.

### Network Requirements

Your workstation must be able to reach the ADEPT host on port 443 (HTTPS). Common scenarios:

| Environment | Access method |
|-------------|--------------|
| On-campus (PNNL) | Direct network access |
| Off-campus | VPN required (PulseSecure, GlobalProtect, etc.) |
| SSH tunnel | `ssh -L 8443:localhost:443 user@adept-host` then use `https://localhost:8443/v1` |
| AWS Session Manager | `aws ssm start-session --target i-xxx --document-name AWS-StartPortForwardingSession --parameters portNumber=443,localPortNumber=8443` |

For SSH tunnel or port-forward scenarios, set `ADEPT_VERIFY_SSL=false` (the certificate won't match `localhost`).

### Obtaining an API Key from a Remote Instance

Ask your ADEPT administrator for a service API key, or if you have SSH access:

```bash
ssh user@adept-host "cat /path/to/deployment/local/docker-compose/.env-keycloak-credentials-dir/OPENWEBUI_SERVICE_API_KEY"
```

### TLS Certificate Verification

Most ADEPT deployments use self-signed TLS certificates (generated during bootstrap, not signed by a public CA). With `ADEPT_VERIFY_SSL=true` (the default), the connector rejects the connection because the certificate isn't in the system's trusted CA bundle.

Setting `ADEPT_VERIFY_SSL=false` disables both certificate chain validation and hostname matching. The security implications depend on your network path:

| Scenario | Risk of disabling | Recommendation |
|----------|-------------------|----------------|
| Local (same host, Docker network) | None — traffic stays on loopback | `false` is fine |
| Internal network (campus, VPN) | Low — attacker needs LAN position | `false` is acceptable |
| Public internet (no VPN) | Real MITM risk — credentials in transit | Install the CA cert instead |

To keep verification enabled, install the ADEPT deployment's CA certificate into your system trust store:

```bash
# Linux (RHEL/Rocky)
sudo cp /path/to/adept-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust

# Linux (Ubuntu/Debian)
sudo cp /path/to/adept-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates

# macOS
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain /path/to/adept-ca.crt
```

Then omit `ADEPT_VERIFY_SSL` entirely (defaults to `true`).

If your deployment uses a proper CA-signed certificate (e.g., Let's Encrypt, internal PKI trusted by your OS), no action is needed — leave verification enabled.

## Why Docker? (Keycloak Issuer Mismatch)

Running the connector directly on the host with password auth causes a JWT issuer mismatch:

1. Host obtains token from `http://localhost:8180` → issuer = `http://localhost:8180/realms/master`
2. Gateway accepts it (has `localhost:8180` in its `valid_issuers` list)
3. Orchestration service rejects it (only trusts `http://keycloak:8180/realms/master`)

Inside the Docker network, the connector reaches Keycloak at `http://keycloak:8180`, producing tokens with the correct issuer that all services trust.

API key auth avoids this entirely — it's validated at the gateway without any JWT involvement. The Docker approach is still preferred because:
- Consistent environment (same Python, same deps as CI)
- No host Python installation required
- Network isolation matches production behavior
- Works identically on Linux, macOS (Docker Desktop), and Windows (WSL2)

## Configuration Reference

All `ADEPT_*` environment variables are read by `AdeptConnectorConfig` (pydantic-settings):

| Variable | Default | Description |
|----------|---------|-------------|
| `ADEPT_BASE_URL` | (required) | ADEPT API base URL |
| `ADEPT_AUTH_METHOD` | `password` | `api_key`, `password`, or `jwt` |
| `ADEPT_API_KEY` | — | Service API key (`sk-service-*`) |
| `ADEPT_USERNAME` | — | Keycloak username (for password auth) |
| `ADEPT_PASSWORD` | — | Keycloak password (for password auth) |
| `ADEPT_KEYCLOAK_URL` | derived from base_url | Keycloak base URL |
| `ADEPT_VERIFY_SSL` | `true` | Set `false` for self-signed certs |
| `ADEPT_DEFAULT_MODEL` | `agentic-framework:scientific-agent-v1` | Default chat model |
| `ADEPT_SESSION_PERSISTENCE` | `true` | Persist sessions across restarts |
| `ADEPT_WORKSPACE_DIR` | — | Directory for downloaded artifacts |

## Troubleshooting

### Doctor check fails

| Check | Likely cause | Fix |
|-------|-------------|-----|
| Configuration | Missing env vars | Verify `-e` flags in docker command |
| Authentication | Bad API key or credentials | Get fresh key from credentials dir |
| ADEPT connectivity | Stack not running | `make start` from project root |
| MCP proxy | Gateway misconfigured | `make rebuild-gateway` |
| AG-UI | Orchestration service down | `docker logs orchestration_service --tail 20` |

### "network adept_application_network not found"

The ADEPT stack isn't running. Start it:

```bash
make start
```

### "ModuleNotFoundError: No module named 'adept_connectors'"

The source mount path is wrong. Verify:

```bash
ls /absolute/path/to/examples/adept_connectors/src/adept_connectors/__init__.py
```

### Container exits immediately

MCP servers using STDIO transport need the `-i` flag (interactive/keep stdin open). Verify your args include `"-i"` not just `"--rm"`.

### "Connection refused" to agent_gateway

The container isn't on the right network. Verify:

```bash
docker network inspect adept_application_network --format '{{range .Containers}}{{.Name}} {{end}}'
```

Should list `agent_gateway`, `orchestration_service`, `keycloak`, etc.

### Permission denied on source mount

Use read-only mount (`:ro`) and ensure the host path is readable:

```bash
ls -la examples/adept_connectors/src/
```

### Slow startup

First run pulls the `agentic-framework-deps-base` image. Subsequent launches are fast (~2s) since the image is cached locally.

## Choosing Your Setup

| Scenario | Method | Password auth | API key auth | Python on host |
|----------|--------|---------------|--------------|----------------|
| ADEPT on same machine | Docker container (local network) | Works | Works | No |
| ADEPT on same machine | `uv run` (localhost ports) | Fails (issuer mismatch) | Works | Yes (3.10+) |
| ADEPT on remote server | `uv run` (HTTPS to remote) | Works | Works | Yes (3.10+) |
| ADEPT on remote server | Docker container (HTTPS to remote) | Works | Works | No |

**Recommended:**
- **Local ADEPT** → Docker container method (no host deps, all auth methods work)
- **Remote ADEPT** → `uv run` method (simpler, no Docker needed, all auth methods work over HTTPS)

For the host-based `uv run` setup with a local stack, see [ONBOARDING_LINUX.md](../ONBOARDING_LINUX.md) (API key auth only due to issuer mismatch).

To configure any of these interactively within Claude Code, use the `/connect-adept` skill — it handles all scenarios and generates the correct `.mcp.json` automatically.
