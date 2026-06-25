---
name: connect-adept
description: Configure Claude Code to connect to an ADEPT instance (local Docker stack or remote server). Generates .mcp.json, runs doctor check, verifies connectivity. Use when setting up or switching between ADEPT instances.
disable-model-invocation: true
allowed-tools: Bash(docker *) Bash(cat *) Bash(grep *) Bash(ls *) Bash(find *) Bash(ssh *) Bash(curl *) Bash(uv *) Bash(python3 *) Read Write Edit Glob Grep AskUserQuestion
argument-hint: [optional: local | remote]
---

You are helping a developer connect Claude Code to an ADEPT instance via the adept_connectors MCP server. This creates or updates the `.mcp.json` file that Claude Code reads on startup.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

---

## Step 1: Determine Deployment Type

If `$ARGUMENTS` specifies `local` or `remote`, use that. Otherwise ask:

**"Is the ADEPT instance running locally (same machine, Docker Compose) or on a remote server (e.g., AWS EC2)?"**

Options:
- **local** -- ADEPT running via Docker Compose on this machine
- **remote** -- ADEPT running on a different server, accessible over HTTPS

---

## Step 2: Gather Connection Details

### If LOCAL:

**2a. Verify the ADEPT stack is running**:
```bash
docker ps --format "{{.Names}}" | grep -E "agent_gateway|orchestration_service|keycloak" | sort
```

If containers are not running, tell the developer to start the stack first (`make start` from project root) and stop.

**2b. Verify the Docker network exists**:
```bash
docker network ls --format "{{.Name}}" | grep adept_application_network
```

**2c. Locate the connector source**:
```bash
find . -path "*/adept_connectors/src/adept_connectors/__init__.py" -type f 2>/dev/null | head -1
```

Store the parent `src/` directory as `CONNECTOR_SRC_PATH` (resolve to absolute path).

If not found, check common locations:
```bash
ls -d examples/adept_connectors/src/adept_connectors/ 2>/dev/null
ls -d ../adept-agentic/examples/adept_connectors/src/adept_connectors/ 2>/dev/null
```

If the connector source cannot be found, tell the developer where to clone it from and stop.

**2d. Verify the deps-base image exists**:
```bash
docker images --format "{{.Repository}}:{{.Tag}}" | grep "agentic-framework-deps-base"
```

If missing, tell the developer to build it (`make build-deps-base` or equivalent) and stop.

### If REMOTE:

**2a. Ask for the ADEPT instance URL**:

**"What is the ADEPT instance URL? (e.g., https://your-adept-host.example.com/v1 or https://your-host.example.com/v1)"**

Validate the URL includes `/v1` suffix. If not, append it and confirm with the developer.

**2b. Ask about network access**:

**"Can your machine reach that URL directly, or do you need a VPN/SSH tunnel?"**

If a tunnel is needed, note it in the report but do not configure it (developer's responsibility).

**2c. Locate the connector source (same as local 2c)**:
```bash
find . -path "*/adept_connectors/src/adept_connectors/__init__.py" -type f 2>/dev/null | head -1
```

If not found, check if `uv` is available and the package can be run from the examples directory:
```bash
which uv 2>/dev/null && echo "uv available" || echo "uv NOT found"
ls examples/adept_connectors/pyproject.toml 2>/dev/null && echo "pyproject.toml found" || echo "pyproject.toml NOT found"
```

---

## Step 3: Choose Authentication Method

Ask: **"Which authentication method? (api_key or password)"**

- **api_key** (recommended for local development): Bypasses Keycloak entirely, simplest setup.
- **password** (recommended for remote with per-user identity): Uses Keycloak ROPC flow for JWT.

### If API_KEY:

Ask: **"What is your API key? (format: sk-service-...)"**

Or offer to auto-discover from the local credentials directory:
```bash
cat deployment/local/docker-compose/.env-keycloak-credentials-dir/OPENWEBUI_SERVICE_API_KEY 2>/dev/null
```

If the file exists and contains a key, present it and ask the developer to confirm.

### If PASSWORD:

Ask for:
- **Username**: Keycloak username (e.g., `admin`, `alice.test@example.org`)
- **Password**: Keycloak password

For remote, also confirm the Keycloak URL (usually same hostname as ADEPT, without `/v1`):
```
ADEPT_KEYCLOAK_URL = <base_url without /v1>
```

For local (Docker), the Keycloak URL is always `http://keycloak:8180` (internal DNS).

---

## Step 4: TLS Verification

Ask: **"Does the ADEPT instance use a CA-signed TLS certificate (trusted by your system), or self-signed?"**

- **CA-signed** (e.g., Let's Encrypt, internal PKI in trust store): Set `ADEPT_VERIFY_SSL=true`
- **Self-signed** (most deployments): Set `ADEPT_VERIFY_SSL=false`
- **Local Docker** (no TLS on internal network): Set `ADEPT_VERIFY_SSL=false`

Explain: Disabling TLS verification means the connection is not protected against man-in-the-middle attacks on the network path. For same-host Docker traffic this is a non-issue. For remote access over trusted internal networks (VPN, campus) the risk is low. For public internet without VPN, recommend installing the CA certificate instead.

---

## Step 5: Generate .mcp.json

Check if `.mcp.json` already exists:
```bash
cat .mcp.json 2>/dev/null
```

If it exists and already has an `adept` entry, ask: **"An existing ADEPT MCP configuration was found. Replace it, or add a new entry with a different name (e.g., adept-staging)?"**

### LOCAL configuration:

Generate `.mcp.json` with the Docker container approach:

```json
{
  "mcpServers": {
    "<server_name>": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--network=adept_application_network",
        "-v", "<CONNECTOR_SRC_PATH>:/app/connector_src:ro",
        "-e", "PYTHONPATH=/app/connector_src",
        "-e", "ADEPT_BASE_URL=http://agent_gateway:8081/v1",
        "-e", "ADEPT_AUTH_METHOD=<method>",
        <auth_env_vars>,
        "-e", "ADEPT_VERIFY_SSL=false",
        "agentic-framework-deps-base",
        "/app/.venv/bin/python", "-m", "adept_connectors.connectors.claude"
      ]
    }
  }
}
```

For password auth on local, add:
```json
"-e", "ADEPT_KEYCLOAK_URL=http://keycloak:8180",
```

### REMOTE configuration:

Generate `.mcp.json` with the `uv run` approach:

```json
{
  "mcpServers": {
    "<server_name>": {
      "command": "uv",
      "args": [
        "run", "--extra", "claude",
        "--directory", "<CONNECTOR_DIR>",
        "python", "-m", "adept_connectors.connectors.claude"
      ],
      "env": {
        "ADEPT_BASE_URL": "<remote_url>",
        "ADEPT_AUTH_METHOD": "<method>",
        <auth_env_vars>,
        "ADEPT_VERIFY_SSL": "<true|false>"
      }
    }
  }
}
```

For password auth on remote, add:
```json
"ADEPT_KEYCLOAK_URL": "<keycloak_url>"
```

If `.mcp.json` already exists with other servers, merge the new entry rather than overwriting.

Write the file and present the full content to the developer for confirmation.

---

## Step 6: Run Doctor Check

Run the diagnostic to verify end-to-end connectivity using the same command pattern that `.mcp.json` will use.

### LOCAL:

```bash
docker run --rm -i \
  --network=adept_application_network \
  -v "<CONNECTOR_SRC_PATH>":/app/connector_src:ro \
  -e PYTHONPATH=/app/connector_src \
  -e ADEPT_BASE_URL=http://agent_gateway:8081/v1 \
  -e ADEPT_AUTH_METHOD=<method> \
  <auth_flags> \
  -e ADEPT_VERIFY_SSL=false \
  agentic-framework-deps-base \
  /app/.venv/bin/python -m adept_connectors.connectors.claude doctor
```

### REMOTE:

```bash
cd <connector_dir> && \
ADEPT_BASE_URL="<remote_url>" \
ADEPT_AUTH_METHOD=<method> \
<auth_vars> \
ADEPT_VERIFY_SSL=<true|false> \
uv run python -m adept_connectors.connectors.claude doctor
```

Present the doctor output. If any checks fail, explain the likely cause and remediation:

| Check | Likely cause | Fix |
|-------|-------------|-----|
| Configuration | Missing or malformed env var | Review .mcp.json env values |
| Authentication | Bad key or credentials | Regenerate key or check password |
| ADEPT connectivity | Stack not running / unreachable | Start stack or check network |
| MCP proxy | Gateway not running | `make rebuild-gateway` |
| AG-UI | Orchestration service down | Check `docker logs orchestration_service` |
| Files API | Service error | Check orchestration logs |

If doctor passes (6/7 or 7/7), proceed. Otherwise help the developer fix issues before continuing.

---

## Step 7: Verify .mcp.json is Excluded from Git

Check that `.mcp.json` will not be committed:

```bash
grep -n "\.mcp\.json" .gitignore 2>/dev/null
```

If not in `.gitignore`, warn the developer:

**"WARNING: .mcp.json contains credentials and is NOT in .gitignore. Add it now?"**

If confirmed, append `.mcp.json*` to `.gitignore`.

---

## Step 8: Report

Present the final summary:

```
ADEPT MCP Connection Configured
================================
Type:           <local | remote>
Instance:       <url>
Auth:           <api_key | password>
TLS verify:     <true | false>
Server name:    <server_name> (in .mcp.json)
Doctor result:  <N>/7 checks passed
Config file:    .mcp.json

Next steps:
1. Restart Claude Code in this directory (exit and re-run `claude`)
2. Ask Claude Code: "Use adept_list_models to verify connectivity"
3. Start working: "Use adept_create_session, then adept_chat to ask ADEPT..."

Available tools after restart:
  adept_create_session    - Start a persistent conversation
  adept_chat              - Chat with the scientific agent
  adept_agui_run          - AG-UI protocol (richer tool visibility)
  adept_list_tools        - Discover MCP tools on the server
  adept_call_tool         - Call any ADEPT tool by name
  adept_list_models       - List available LLM models
  adept_upload_file       - Upload files for processing
  adept_list_files        - List uploaded/generated files
  adept_get_image         - View images inline
  adept_download_artifact - Save files to disk
  adept_list_sessions     - List conversation sessions

Tutorial: examples/adept_connectors/docs/claude_code/CLAUDE_CODE_MCP_TUTORIAL.md
```

If the developer had issues or wants to switch instances later, remind them they can re-run `/connect-adept` at any time.
