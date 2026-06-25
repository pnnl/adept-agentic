---
name: mcp-scaffold
description: Create a new external MCP server from the canonical template. Replaces placeholders, assigns ports, validates the result. Use during Phase 4 (Implement) of the feature development lifecycle.
disable-model-invocation: true
allowed-tools: Bash(find *) Bash(sed *) Bash(cp *) Bash(mv *) Bash(grep *) Bash(make *) Bash(ls *) Bash(mkdir *) Bash(git *) Read Write Edit Glob Grep
argument-hint: [optional: server-name]
---

You are assisting an ADEPT developer with scaffolding a new external MCP server from the canonical template. This skill corresponds to Phase 4 (Implement) in the feature development lifecycle.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in commit messages, trailers, or document metadata.
Pause for developer confirmation at each numbered step before proceeding.

---

## Prerequisites

Before running this skill, the developer should have completed:
- Phase 0 (Orient): Read `CLAUDE.md`, `docs/development/CODE_HYGIENE.md`
- Phase 1 (Plan): GitHub issue exists, implementation plan written
- Phase 2 (Discover): 3+ analogous MCP servers reviewed
- Phase 3 (Branch): Working branch created

If any of these are incomplete, recommend the developer run `/start-feature` first.

---

## Step 1: Read Reference Material

Read these files to understand the template structure and patterns:

1. `examples/mcp_server_template/QUICKSTART.md` -- placeholder tokens, port registry, step-by-step guide
2. `docs/MCP_SERVER_BLUEPRINT.md` -- 11-section reference distilled from exemplar servers
3. `docs/implementation-plans/MCP_SERVER_DEVELOPMENT_SKILLS_PLAN.md` -- critical patterns from 8 server implementations

Then ask the developer (or use `$ARGUMENTS` if provided):

**"What is the name for your new MCP server?"**

Collect these values:
- `NAME`: lowercase, no spaces, no hyphens (e.g., `proteinfolding`)
- `NAME_UPPER`: uppercase version (e.g., `PROTEINFOLDING`)
- `DISPLAY_NAME`: human-readable (e.g., `Protein Folding`)
- `DESCRIPTION`: one-line description for docstrings
- `INITIAL_TOOL_COUNT`: number of tools to start with (default: 2 -- example + get_job_status)

---

## Step 2: Collision Detection Gate

This is a mandatory gate. Do NOT proceed to Step 3 until all checks pass.

The template produces these resources from `{NAME}`:
- Directory: `examples/{NAME}_mcp_server/`
- Container names: `{NAME}_redis`, `{NAME}_mcp_server`, `{NAME}_nginx_proxy`
- Docker image: `{NAME}-mcp:latest`
- Host ports: MCP port, proxy HTTP, proxy HTTPS, Redis host port

Run ALL collision checks and present results as a single pass/fail table.

**2a. Directory collision**:
```bash
ls -d examples/{NAME}_mcp_server/ 2>/dev/null && echo "FAIL: directory already exists" || echo "PASS"
```

**2b. Container name collision** (against ALL compose files -- core stack + examples):
```bash
grep -rn 'container_name:' deployment/local/docker-compose/docker-compose*.yaml examples/*/docker-compose*.yaml 2>/dev/null | grep -i '{NAME}' && echo "FAIL: container name collision" || echo "PASS"
```

Also check running containers:
```bash
docker ps -a --format '{{{{.Names}}}}' 2>/dev/null | grep -i '{NAME}' && echo "FAIL: running/stopped container with this name" || echo "PASS"
```

**2c. Docker image name collision**:
```bash
docker images --format '{{{{.Repository}}}}:{{{{.Tag}}}}' 2>/dev/null | grep -i '{NAME}' && echo "FAIL: image name collision" || echo "PASS"
```

**2d. Port collision** -- scan ALL host port mappings across the entire stack:
```bash
# Collect every host port from core stack + all examples
grep -rn 'ports:' -A3 deployment/local/docker-compose/docker-compose*.yaml examples/*/docker-compose*.yaml 2>/dev/null \
  | grep -oP '(\d{4,5})(?=:)' | sort -n | uniq -c | sort -rn
```

Cross-reference with the port allocation registry in `examples/mcp_server_template/QUICKSTART.md`.

Also check ports currently bound on the host:
```bash
docker ps --format '{{{{.Ports}}}}' 2>/dev/null | grep -oP '\d+(?=->)' | sort -un
```

Assign the next available ports (use the QUICKSTART.md "next available" line as starting point):
- MCP server port (9000-series, avoid core stack range 8080-8902)
- Proxy HTTP port (paired, e.g., 9040/9041)
- Proxy HTTPS port (paired with HTTP)
- Redis host port (6380-series)

Verify each proposed port does NOT appear in any of the above scans.

**2e. Docker network alias collision** (service names on adept_application_network):
```bash
# Service names become DNS aliases on the Docker network
grep -rn '^\s\{2\}[a-z][a-z0-9_]*:$' deployment/local/docker-compose/docker-compose*.yaml examples/*/docker-compose*.yaml 2>/dev/null \
  | sed 's/.*:  //' | sed 's/:$//' | sort -u | grep -i '{NAME}' && echo "FAIL: service name collision" || echo "PASS"
```

**Present the collision report**:

```
| Check                | Result | Detail                          |
|----------------------|--------|---------------------------------|
| Directory            | PASS   |                                 |
| Container names (3)  | PASS   |                                 |
| Docker image         | PASS   |                                 |
| MCP port (XXXX)      | PASS   |                                 |
| HTTP port (XXXX)     | PASS   |                                 |
| HTTPS port (XXXX)    | PASS   |                                 |
| Redis port (XXXX)    | PASS   |                                 |
| Network aliases      | PASS   |                                 |
```

If ANY check fails, explain the conflict and propose an alternative. Do NOT proceed until all checks pass and the developer confirms the assignments.

---

## Step 3: Copy Template

```bash
cp -r examples/mcp_server_template examples/{NAME}_mcp_server
```

Verify the copy:
```bash
ls examples/{NAME}_mcp_server/
find examples/{NAME}_mcp_server/ -name "*.py" -o -name "*.md" -o -name "*.yaml" | wc -l
```

---

## Step 4: Replace Placeholder Tokens

Replace all `{{PLACEHOLDER}}` tokens across the new server directory:

```bash
find examples/{NAME}_mcp_server/ -type f \( -name "*.py" -o -name "*.md" -o -name "*.yaml" -o -name "*.yml" \
  -o -name "*.toml" -o -name "*.txt" -o -name "*.sh" -o -name "*.tpl" \
  -o -name ".env.example" -o -name "Makefile" -o -name "*.template" \) \
  -exec sed -i \
    -e "s/{{NAME_UPPER}}/{NAME_UPPER}/g" \
    -e "s/{{NAME}}/{NAME}/g" \
    -e "s/{{DISPLAY_NAME}}/{DISPLAY_NAME}/g" \
    -e "s/{{DESCRIPTION}}/{DESCRIPTION}/g" \
    -e "s/{{MCP_PORT}}/{MCP_PORT}/g" \
    -e "s/{{PROXY_HTTP_PORT}}/{PROXY_HTTP_PORT}/g" \
    -e "s/{{PROXY_HTTPS_PORT}}/{PROXY_HTTPS_PORT}/g" \
    -e "s/{{REDIS_HOST_PORT}}/{REDIS_HOST_PORT}/g" \
    -e "s/{{TOOL_COUNT}}/{TOOL_COUNT}/g" \
    {} +
```

---

## Step 5: Rename Package Directory

The template uses `{{NAME}}_mcp/` as the Python package directory. Rename it:

```bash
mv examples/{NAME}_mcp_server/{{NAME}}_mcp examples/{NAME}_mcp_server/{NAME}_mcp 2>/dev/null || true
```

If the directory was already named correctly by the sed replacements, verify:
```bash
ls examples/{NAME}_mcp_server/{NAME}_mcp/
```

---

## Step 6: Validate

Run these validation checks:

**6a. No remaining placeholders**:
```bash
grep -rn '{{' examples/{NAME}_mcp_server/ --include="*.py" --include="*.md" --include="*.yaml" --include="*.toml" --include="Makefile"
```
Expected: 0 matches. If any remain, fix them.

**6b. Directory structure matches template**:
```bash
find examples/{NAME}_mcp_server/ -type f | wc -l
```
Compare with the template file count.

**6c. Python imports resolve**:
```bash
cd examples/{NAME}_mcp_server && python3 -c "import {NAME}_mcp" 2>&1 || echo "Import check failed (may need deps installed)"
```

**6d. Critical patterns present** (from plan's "Critical Patterns to Encode"):
```bash
# FastMCP mount at "/" not "/mcp"
grep -n 'mount("/"' examples/{NAME}_mcp_server/{NAME}_mcp/server.py

# register(mcp) pattern
grep -rn 'def register(mcp)' examples/{NAME}_mcp_server/{NAME}_mcp/tools/

# mcp_session_id on tool functions
grep -rn 'mcp_session_id' examples/{NAME}_mcp_server/{NAME}_mcp/tools/

# Redis hostname explicit (prevents DNS shadow bug)
grep -n 'hostname:' examples/{NAME}_mcp_server/docker-compose*.yaml
```

---

## Step 7: Model Catalog Integration

Ask the developer: **"Do any of this server's tools use LLM calls internally (like csv_rag_tool uses llm_purpose='coding_agent')?"**

If **no**, skip to Step 8.

If **yes**:

**7a. Check if a matching purpose already exists**:
```bash
grep -A2 'purposes:' config/model_catalog.yaml | head -30
```

If a suitable purpose exists (e.g., `biology_agent` for a biology MCP server), tell the developer to use it.

**7b. If no matching purpose exists**, add one to `config/model_catalog.yaml`:

```yaml
  {NAME}_agent:
    description: "<domain description>"
    env_var: "{NAME_UPPER}_AGENT_DEFAULT_MODEL"
    providers:
      - name: bedrock-claude-sonnet
        model: "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        provider: aws_bedrock
        cost_tier: medium
```

**7c. Add role aliases** if the server's domain has well-known role names:
```yaml
role_aliases:
  {domain_expert}: {NAME}_agent
  {NAME}_agent: {NAME}_agent
```

**7d. Add the env var** to `.env.example`:
```
{NAME_UPPER}_AGENT_DEFAULT_MODEL=  # e.g., bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

Present the proposed additions and wait for developer confirmation before editing.

---

## Step 8: Report

Present a summary:

```
Server: examples/{NAME}_mcp_server/
Package: {NAME}_mcp
Files: <count>
Ports: MCP={MCP_PORT}, HTTP={PROXY_HTTP_PORT}/{PROXY_HTTPS_PORT}, Redis={REDIS_HOST_PORT}
Tools: {TOOL_COUNT} (example + get_job_status)
Placeholders remaining: <count>
Model catalog: <updated / not needed>

Next steps:
1. Add domain-specific tools: /mcp-add-tool
2. Run tests: /mcp-test
3. Build and start: cd examples/{NAME}_mcp_server && make build && make start
4. Register with ADEPT: /mcp-register
5. Continue the feature lifecycle: /close-task (Phases 5-9)
```

Ask if the developer wants to add tools now (`/mcp-add-tool`) or proceed with the lifecycle.
