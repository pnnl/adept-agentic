---
name: mcp-register
description: Register (or re-register) an MCP server's tools with the ADEPT gateway. Includes pre-flight validation, schema checking, registration, and verification. Use during Phase 9 (Close) of the feature development lifecycle.
disable-model-invocation: true
allowed-tools: Bash(make *) Bash(curl *) Bash(docker *) Bash(grep *) Bash(find *) Bash(ls *) Bash(git *) Read Glob Grep
argument-hint: [optional: server-directory]
---

You are assisting an ADEPT developer with registering an MCP server's tools with the ADEPT gateway. This skill corresponds to Phase 9 (Close) in the feature development lifecycle.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

---

## Step 1: Identify Target Server

If `$ARGUMENTS` provides the server directory, use it. Otherwise ask:

**"Which MCP server are you registering?"**

```bash
ls -d examples/*_mcp_server/ examples/*_mcp/ 2>/dev/null
```

Read the server's Makefile to confirm registration targets exist:
```bash
grep -n 'register-tools\|deregister-tools\|verify-tools\|show-tool-schemas' <server_dir>/Makefile
```

If any of these targets are missing, stop and tell the developer to add them before proceeding.

---

## Step 2: Pre-Flight Checks

Run the pre-registration checklist. All checks must pass before attempting registration.

**2a. MCP server is running and healthy**:
```bash
cd <server_dir> && make health 2>&1 || echo "Server not running -- start with: make start"
```

**2b. ADEPT stack is running**:
```bash
curl -sf http://localhost:8083/v1/health && echo "ADEPT gateway OK" || echo "ADEPT gateway NOT reachable"
```

**2c. Credentials are synced**:
```bash
ls -la .env-keycloak-credentials-dir/.env-keycloak-credentials 2>/dev/null && echo "Credentials exist" || echo "Credentials missing -- run: make sync-credentials"
```

**2d. Network connectivity** (container can reach ADEPT services):
```bash
docker inspect --format='{{range $net,$v := .NetworkSettings.Networks}}{{$net}} {{end}}' $(docker ps -q --filter "name=<server_name>") 2>/dev/null | grep -q "adept_application_network" && echo "Network OK" || echo "Container NOT on adept_application_network"
```

**2e. DNS resolution** (no Redis shadow bug -- Sessions 98-99):
```bash
docker exec <server_container> nslookup redis 2>/dev/null | head -5 || echo "DNS check skipped (nslookup not available)"
```

**2f. Port and container collision check** (catch drift since scaffold time):

This is a lightweight runtime check. The full collision gate runs during `/mcp-scaffold`; this catches conflicts introduced after scaffolding (e.g., another server started on the same port).

```bash
# Check if this server's host ports are bound by another container
docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null | grep -v '<server_name>' | grep '<MCP_PORT>\|<HTTP_PORT>\|<HTTPS_PORT>\|<REDIS_PORT>'
```

If a port conflict is detected, tell the developer which container owns the conflicting port and suggest stopping it or reassigning ports.

If any of these checks fail with a Docker-based server, present the specific remediation. If running in Docker-free mode (host tools), adapt the checks to use the `.env.remote` connection settings instead.

Present the pre-flight results and ask the developer to confirm before proceeding.

---

## Step 3: Schema Validation

Verify tool schemas are clean before registration. Framework-internal fields must NOT appear in published schemas.

```bash
cd <server_dir> && make show-tool-schemas 2>&1
```

If `make show-tool-schemas` is not available, attempt direct introspection:
```bash
curl -sf http://localhost:<MCP_PORT>/mcp -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' -H "Content-Type: application/json" 2>/dev/null | python3 -m json.tool
```

Check for framework fields that should be stripped from published schemas:
```bash
cd <server_dir> && make show-tool-schemas 2>&1 | grep -i 'mcp_session_id\|user_context\|session_id' && echo "WARNING: Framework fields found in published schemas" || echo "Schema check OK -- no framework fields exposed"
```

If framework fields are found in published schemas, stop and explain:
- `mcp_session_id` is injected by the framework at invocation time
- It must NOT appear in the tool's published parameter list
- The registration script should strip it before publishing

Present the schema summary (tool count, tool names) and ask the developer to confirm.

---

## Step 4: Registration

Run the server's registration target:
```bash
cd <server_dir> && make register-tools 2>&1
```

If registration fails with a 401 error, check credentials:
```bash
make sync-credentials 2>&1
# Then retry:
cd <server_dir> && make register-tools 2>&1
```

If the developer is re-registering (replacing existing tools), deregister first:
```bash
cd <server_dir> && make deregister-tools 2>&1
cd <server_dir> && make register-tools 2>&1
```

Note: Deregistration scripts must use the `-y` flag on `agentic tools delete` to bypass the click.confirm() prompt (Session 99 bug).

---

## Step 5: Verification

**5a. CLI verification** -- confirm tools appear in the ADEPT tool catalog:
```bash
cd <server_dir> && make verify-tools 2>&1
```

**5b. Redis integration check** -- confirm tool metadata is stored:
```bash
docker exec redis redis-cli keys "tool:*" 2>/dev/null | grep -i "<server_name>" || echo "No Redis keys found for this server"
```

**5c. Orchestration service discovery** -- confirm tools are available to agents:
```bash
curl -sf http://localhost:8083/v1/health 2>/dev/null | python3 -m json.tool 2>/dev/null | grep -A2 'tools\|external' || echo "Cannot parse gateway health for tool count"
```

If any verification step fails, present the failure details and suggest remediation.

---

## Step 6: Report

Present a summary:

```
Server: <server_dir>
Registration: SUCCESS / FAILED
Tools registered: <count>
Tool names:
  - <tool_1>
  - <tool_2>
  - ...
MCP endpoint: http://<container>:<port>
Redis keys: <count> keys matching tool:<server>_*
Pre-flight: <pass_count>/<total_count> checks passed
```

If registration succeeded, remind the developer of next steps in the lifecycle:
- Run full tests: `/mcp-test`
- Complete task closure: `/close-task` (Phases 5-9)
- Create or update PR: `/prepare-pr`

If registration failed, provide the specific error and remediation steps. Do not proceed to closure until registration succeeds.
