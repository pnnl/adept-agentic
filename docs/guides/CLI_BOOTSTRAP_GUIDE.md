# CLI Bootstrap Guide

## Quick Start

```bash
# One command to configure the CLI from the host machine
agentic config bootstrap
```

This auto-detects your environment, discovers the correct gateway and Keycloak URLs, authenticates, and saves a working configuration.

## Prerequisites

1. **Docker services running** — `make start` (or `./scripts/quick-start-adept-and-subsystems.sh`)
2. **Python virtualenv active** — the `agentic` CLI must be on your `PATH`
3. **Ports available** — Gateway on `localhost:8083`, Keycloak on `localhost:8180`

## What Bootstrap Does

The command executes five steps:

| Step | Action | Details |
|------|--------|---------|
| 1/5 | Detect environment | Checks for `/.dockerenv` to distinguish host vs container |
| 2/5 | Discover gateway | Probes candidate URLs in priority order until one responds |
| 3/5 | Discover Keycloak | Probes OIDC discovery endpoint on candidate URLs |
| 4/5 | Authenticate | Obtains a JWT via Keycloak ROPC (Resource Owner Password Credentials) |
| 5/5 | Save config | Writes `gateway_url` and `api_key` to `~/.adept-agentic/config.json` |

### Gateway URL Discovery Order

**Host machine** (no `/.dockerenv`):

1. `--gateway-url` flag (if provided)
2. `AGENT_GATEWAY_URL` environment variable
3. `http://localhost:8083` (default host port)
4. `https://api.agentic.local` (Docker DNS, usually unreachable from host)

**Inside Docker container**:

1. `--gateway-url` flag (if provided)
2. `AGENT_GATEWAY_URL` environment variable
3. `https://api.agentic.local` (nginx proxy)
4. `http://agent_gateway:8081/v1` (direct container DNS)

### Keycloak URL Discovery Order

**Host machine**: `http://localhost:8180` → `http://keycloak:8180`

**Docker container**: `http://keycloak:8180` → `http://localhost:8180`

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_GATEWAY_URL` | (none) | Overrides saved `gateway_url` in config at load time |
| `KEYCLOAK_URL` | `http://localhost:8180` | Keycloak base URL for authentication |
| `KEYCLOAK_REALM` | `master` | Keycloak realm name |
| `AGENTIC_USERNAME` | `notebook-user` | Default username for non-interactive auth |
| `AGENTIC_PASSWORD` | `notebook-password` | Default password for non-interactive auth |

### Environment Variable Override Behavior

As of the bootstrap fix, `AGENT_GATEWAY_URL` **overrides** any saved value in `config.json`. This means:

```bash
# This works even if config.json has gateway_url: "https://api.agentic.local"
AGENT_GATEWAY_URL=http://localhost:8083 agentic chat
```

Previously, the saved config took precedence and the env var was only used for missing keys.

## Host vs Docker URLs

The framework runs inside Docker Compose. Services communicate using Docker DNS names (e.g. `api.agentic.local`, `keycloak:8180`). These names are **not resolvable from the host machine**.

| Context | Gateway URL | Keycloak URL |
|---------|-------------|--------------|
| Host machine (CLI) | `http://localhost:8083` | `http://localhost:8180` |
| Docker container | `https://api.agentic.local` | `http://keycloak:8180` |
| Test containers | `http://agent_gateway:8081/v1` | `http://keycloak:8180` |

The `config bootstrap` command detects which context you're in and picks the right URL automatically.

## Manual Setup

If you prefer manual configuration:

```bash
# 1. Set gateway URL
agentic config set gateway_url http://localhost:8083

# 2. Authenticate
agentic config auth
# Enter: notebook-user / notebook-password

# 3. Verify
agentic config doctor
```

Or use environment variables directly:

```bash
export AGENT_GATEWAY_URL=http://localhost:8083
agentic config auth
agentic tools list
```

## Non-Interactive Mode

For CI/CD pipelines and automation:

```bash
# Uses defaults: localhost:8083, localhost:8180, notebook-user/notebook-password
agentic config bootstrap --non-interactive

# With explicit values
agentic config bootstrap \
  --gateway-url http://localhost:8083 \
  --keycloak-url http://localhost:8180 \
  --username notebook-user \
  --password notebook-password \
  --non-interactive
```

Non-interactive mode:
- Never prompts for input
- Uses defaults and environment variables
- Exits with code 1 if gateway is unreachable
- Skips authentication if Keycloak is unreachable

## Troubleshooting

### DNS Resolution Errors

**Symptom**: `[Errno -3] Temporary failure in name resolution` when running `agentic chat`

**Cause**: Config file has `gateway_url: "https://api.agentic.local"` which is only resolvable inside Docker.

**Fix**:
```bash
agentic config bootstrap
# or
agentic config set gateway_url http://localhost:8083
```

### Stale Token

**Symptom**: `401 Unauthorized` when running `agentic tools list`

**Cause**: JWT token has expired (default TTL is 5 minutes).

**Fix**:
```bash
agentic config auth
# or
agentic config bootstrap
```

### Admin Role Required for Tools

**Symptom**: `403: User does not have the required 'admin' role` when running `agentic tools list`

**Cause**: Tool management endpoints require the `admin` Keycloak group. The default `notebook-user` only has `notebook-users`.

**Fix**: `agentic tools list` now defaults to `admin`/`admin` credentials automatically. To use explicit credentials:
```bash
agentic tools list --username admin --password admin
# or
ADMIN_USERNAME=admin ADMIN_PASSWORD=admin agentic tools list
```

### Config File Precedence

**Symptom**: Setting `AGENT_GATEWAY_URL` has no effect.

**Cause** (before bootstrap fix): The saved config value took precedence over env vars.

**Fix**: Update to latest CLI version. The env var now overrides saved config.

### Port Mapping Confusion

| Service | Container Port | Host Port |
|---------|----------------|-----------|
| Agent Gateway | 8081 | **8083** |
| HPC MCP Server | 8081 | **8081** |
| Keycloak | 8180 | 8180 |

The Agent Gateway is on host port **8083**, not 8081. Using 8081 from the host hits the HPC MCP Server instead.

### Services Not Running

**Symptom**: Bootstrap reports gateway and Keycloak as unreachable.

**Fix**:
```bash
make start
# Wait for services to initialize, then:
agentic config bootstrap
```

## Verification

After bootstrap, verify everything works:

```bash
# Health check
agentic config doctor

# List available tools
agentic tools list

# Interactive chat
agentic chat

# Quick non-interactive test
echo "exit" | agentic chat --no-stream
```
