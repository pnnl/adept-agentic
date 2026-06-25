# Slurm HPC Stack -- Credentials and Authentication Reference

**Stack**: `examples/slurm_hpc`
**Last updated**: 2026-06-12

---

## 1. Credential Categories

The stack uses two distinct credential categories for different purposes:

| Category | Location | Gitignored | Purpose |
|----------|----------|-----------|---------|
| **SSH keys** | `ssh_keys/` | Yes | Transport-layer auth to remote Slurm clusters |
| **E2E credentials** | `config/e2e_credentials.json` | Yes | ADEPT gateway auth for cross-service E2E tests |
| **Identity map** | `config/identity_map.json` | No (static) | Identity-to-Slurm username mappings |

---

## 2. E2E Credentials (`config/e2e_credentials.json`)

### Purpose

The E2E credentials file provides Keycloak authentication parameters for tests that communicate with the full ADEPT stack (agent gateway, orchestration service, etc.) via the Response API. These tests validate the full agentic workflow: authenticate, prompt the agent, observe tool calls, verify results.

### Setup

```bash
# Copy the example file and fill in your credentials
cp config/e2e_credentials.json.example config/e2e_credentials.json
```

Edit `config/e2e_credentials.json` with your actual values:

```json
{
    "username": "your-keycloak-username",
    "password": "your-keycloak-password",
    "client_id": "agent-gateway-client",
    "model": "agentic-framework:scientific-agent-v1",
    "gateway_url": "http://agent_gateway:8081/v1",
    "keycloak_url": "http://keycloak:8180"
}
```

### Field Reference

| Field | Description | Default | Env Var Override |
|-------|-------------|---------|-----------------|
| `username` | Keycloak user with `notebook-users` group | (none) | `ADEPT_TEST_USER` |
| `password` | Keycloak user password | (none) | `ADEPT_TEST_PASSWORD` |
| `client_id` | OAuth2 client ID | `agent-gateway-client` | `ADEPT_TEST_CLIENT_ID` |
| `model` | LLM model identifier for agent requests | `agentic-framework:scientific-agent-v1` | `ADEPT_TEST_MODEL` |
| `gateway_url` | Agent gateway base URL | `http://agent_gateway:8081/v1` | `AGENT_GATEWAY_URL` |
| `keycloak_url` | Keycloak base URL | `http://keycloak:8180` | `KEYCLOAK_URL` |

### Resolution Order

The E2E test configuration resolves credentials in this priority:

1. **Environment variables** (highest priority, overrides file values)
2. **`config/e2e_credentials.json`** file (relative to project root)
3. **`/app/config/e2e_credentials.json`** (inside test container)
4. **Empty string** (test skips if credentials unavailable)

### Client Secret

The OAuth2 client secret is NOT stored in the JSON file. It is resolved separately from:

1. `/app/credentials/AGENT_GATEWAY_CLIENT_SECRET` (Docker secrets mount)
2. `/run/secrets/AGENT_GATEWAY_CLIENT_SECRET` (Kubernetes secrets)
3. `AGENT_GATEWAY_CLIENT_SECRET` environment variable

### Security Rules

- NEVER commit `config/e2e_credentials.json` (it is in `.gitignore`)
- NEVER store passwords in docker-compose.yaml (use env var substitution)
- The example file (`e2e_credentials.json.example`) contains placeholder values only
- Passwords stored here are Keycloak user passwords, not service account secrets

### Which Tests Use This

| Test File | Guard | Consumes |
|-----------|-------|----------|
| `tests/e2e/test_agentic_sandbox_to_cluster.py` | `AGENTIC_SANDBOX_E2E=true` | Full config (auth + gateway + model) |

---

## 3. SSH Key Lifecycle

SSH keys provide transport-layer authentication to remote HPC clusters. Full documentation is in [OPERATOR_ONBOARDING.md](OPERATOR_ONBOARDING.md) Section 2.

### Quick Reference

```
ssh_keys/
  slurm.id_ed25519.<cluster-a-fqdn>       # Private key (mode 600)
  slurm.id_ed25519.<cluster-a-fqdn>.pub   # Public key
  slurm.id_ed25519.<cluster-b-fqdn>       # Private key (mode 600)
  slurm.id_ed25519.<cluster-b-fqdn>.pub   # Public key
```

### Permission Model

| File | Required Mode | Why |
|------|--------------|-----|
| Private key (`.id_ed25519.*`) | `0600` (`-rw-------`) | SSH refuses keys with group/other read |
| Public key (`.pub`) | `0644` (`-rw-r--r--`) | Read by any, written by owner |
| `ssh_keys/` directory | `0755` (`drwxr-xr-x`) | Traversable by container UID |

### Volume Mount Architecture

| Container | Mount Point | Mode | Access |
|-----------|-------------|------|--------|
| `slurm_mcp_server` | `./ssh_keys:/app/.ssh` | `rw` | Read keys + generate new keys |
| Integration test runner | `./ssh_keys:/app/.ssh` | `ro` | Read keys for connectivity tests |

### Key Discovery Flow

1. `clusters.yaml` defines `ssh_key.private_key_path` per cluster
2. Cluster config (`<cluster>/config.py`) provides `resolved_ssh_key_path`
3. `FabricSSHTransport._get_connection()` reads the key from the resolved path
4. If key does not exist: logs warning, SSH auth will fail
5. If key permissions are wrong: SSH auth may fail (paramiko enforces 600)

### Generating Keys

```bash
# Via ssh-keygen (recommended for operators)
ssh-keygen -t ed25519 -f ssh_keys/slurm.id_ed25519.<cluster-fqdn> -N "" -C "adept-mcp@<cluster>"
chmod 600 ssh_keys/slurm.id_ed25519.<cluster-fqdn>

# Via MCP tool (agent-assisted workflow)
# The agent calls hpc_generate_ssh_key("<cluster>") which uses ssh_keys.py:generate_key_pair()
```

### Rotation and Revocation

| Operation | Steps |
|-----------|-------|
| **Rotate** | 1. Generate new key pair 2. Append new pubkey to remote `authorized_keys` 3. Verify connectivity 4. Remove old pubkey from remote 5. Delete old local key files |
| **Revoke** | 1. Remove pubkey from remote `authorized_keys` 2. Delete local key files |
| **Check status** | Use `hpc_check_ssh_key` MCP tool or `ssh_keys.py:check_key_status()` |

### Rotation Policy

Defined in `clusters.yaml` under `key_policy`:
- `rotation_reminder_days`: 365 (warns if key older than this)
- `preferred_algorithm`: ed25519 (only algorithm supported)
- `strict_host_key_checking`: false (accept-new policy for known_hosts)

---

## 4. Identity Mapping (`config/identity_map.json`)

Maps external identities (Globus UUID, email, Keycloak subject) to Slurm usernames:

```json
{
    "mappings": {
        "alice@example.org": "alice",
        "bob@example.org": "bob",
        "admin": "root"
    }
}
```

This file is git-tracked (contains no secrets). It enables multi-tenant job submission where the ADEPT gateway authenticates users via Keycloak, and the Slurm MCP server maps the authenticated identity to the correct Slurm username for job submission.

---

## 5. Environment Variables

All credential-adjacent configuration can be overridden via environment variables:

### SSH Transport

| Variable | Purpose | Default |
|----------|---------|---------|
| `<CLUSTER>_HOST` | Cluster login node FQDN | (from clusters.yaml) |
| `<CLUSTER>_USERNAME` | SSH username | (from config.py) |
| `<CLUSTER>_SSH_KEY_PATH` | Path to private key | `/app/.ssh/slurm.id_ed25519.<fqdn>` |
| `<CLUSTER>_PASSWORD` | 2FA password (if cluster requires it) | (none) |

### E2E Test Authentication

| Variable | Purpose | Default |
|----------|---------|---------|
| `ADEPT_TEST_USER` | Keycloak username | (from JSON) |
| `ADEPT_TEST_PASSWORD` | Keycloak password | (from JSON) |
| `ADEPT_TEST_CLIENT_ID` | OAuth2 client ID | `agent-gateway-client` |
| `ADEPT_TEST_MODEL` | LLM model for agent | `agentic-framework:scientific-agent-v1` |
| `AGENT_GATEWAY_URL` | Gateway base URL | `http://agent_gateway:8081/v1` |
| `KEYCLOAK_URL` | Keycloak base URL | `http://keycloak:8180` |
| `AGENT_GATEWAY_CLIENT_SECRET` | OAuth2 client secret | (from file) |

### Test Guards

| Variable | Purpose | Default |
|----------|---------|---------|
| `AGENTIC_SANDBOX_E2E` | Enable full agentic E2E test | `false` |
| `AGENTIC_E2E_TIMEOUT` | Response wait timeout (seconds) | `300` |
| `AGENTIC_E2E_JOB_POLL_TIMEOUT` | Job polling timeout (seconds) | `180` |

---

## 6. Gitignore Coverage

The following paths are excluded from version control:

```gitignore
.env                          # Environment variable overrides
ssh_keys/                     # All SSH key material
config/e2e_credentials.json   # Filled-in credentials
```

The following ARE tracked (safe, no secrets):

```
config/e2e_credentials.json.example   # Placeholder template
config/identity_map.json              # Static identity mappings
ssh_keys/.gitkeep                     # Ensures directory exists in repo
```
