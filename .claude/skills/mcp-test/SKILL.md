---
name: mcp-test
description: Run the 4-tier test strategy for an MCP server (unit, integration, registration, E2E). Use during Phase 5 (Test) of the feature development lifecycle.
disable-model-invocation: true
allowed-tools: Bash(make *) Bash(nohup *) Bash(docker *) Bash(grep *) Bash(find *) Bash(ls *) Bash(stat *) Bash(git *) Read Glob Grep
argument-hint: [optional: server-directory]
---

You are assisting an ADEPT developer with running the 4-tier MCP server test strategy. This skill corresponds to Phase 5 (Test) in the feature development lifecycle.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

---

## Step 1: Identify Target Server

If `$ARGUMENTS` provides the server directory, use it. Otherwise ask:

**"Which MCP server are you testing?"**

```bash
ls -d examples/*_mcp_server/ examples/*_mcp/ 2>/dev/null
```

Then read the server's test documentation:
```bash
cat <server_dir>/tests/TESTING.md 2>/dev/null || echo "No TESTING.md found"
ls <server_dir>/tests/
```

---

## Step 2: Determine Required Tiers

Check what changed to determine which tiers are mandatory:

```bash
git diff --name-only $(git merge-base HEAD main)..HEAD -- <server_dir>/
```

Apply the tier selection matrix:

| Change Type | Tiers Required |
|-------------|---------------|
| New tool added | Tier 1 (schema discovery) + Tier 3 (registration) |
| Config/settings change | Tier 1 (config validation) |
| Docker/compose change | Tier 2 (deployment health) |
| Full release / new server | All 4 tiers |
| Pre-registration check | Tier 1 + 2 + 3 |

Present the required tiers and ask the developer to confirm.

---

## Step 3: Run Tier 1 -- Unit Tests

Unit tests validate imports, configuration, and schema discovery. No Docker required.

```bash
mkdir -p logs && nohup make -C <server_dir> test-unit \
  > logs/<name>_unit_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

If `make test-unit` is not available:
```bash
mkdir -p logs && nohup bash -c "cd <server_dir> && python3 -m pytest tests/ -k 'unit or schema or config or import' -v" \
  > logs/<name>_unit_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

Wait for completion, then check results:
```bash
tail -20 logs/<name>_unit_*.log | grep -E "passed|failed|error"
```

If unit tests fail, stop here. Do not proceed to integration tests until unit tests pass.

---

## Step 4: Run Tier 2 -- Integration Tests

Integration tests verify the server starts, responds to health checks, and connects to MCP protocol. Requires Docker.

First verify the server containers are running:
```bash
cd <server_dir> && make health 2>&1 || echo "Server not running -- start with: make start"
```

If not running, ask the developer whether to start:
```bash
cd <server_dir> && make build && make start
```

Then run integration tests:
```bash
mkdir -p logs && nohup make -C <server_dir> test-integration \
  > logs/<name>_integration_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

Check results:
```bash
tail -20 logs/<name>_integration_*.log | grep -E "passed|failed|error"
```

---

## Step 5: Run Tier 3 -- Registration Tests

Registration tests validate the tool registration lifecycle with the ADEPT gateway: tools/list JSON-RPC, Redis key creation, CLI register/deregister.

Prerequisites:
- MCP server running (Tier 2 passed)
- ADEPT stack running (`curl -sf http://localhost:8083/v1/health`)
- Credentials synced (`make sync-credentials` from project root)
- For credential details, see root `Makefile` target `sync-credentials` and `DOCKER_RUN_VALIDATE_BASE` (line 7). The credentials directory `.env-keycloak-credentials-dir/` is auto-mounted in all validation containers via `--env-file` and `-v` flags.

```bash
mkdir -p logs && nohup make -C <server_dir> test-registration \
  > logs/<name>_registration_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

Check results:
```bash
tail -20 logs/<name>_registration_*.log | grep -E "passed|failed|error"
```

---

## Step 6: Run Tier 4 -- E2E Tests

End-to-end tests validate full domain-specific workflows through the ADEPT orchestrator.

Prerequisites:
- All previous tiers passed
- Tools registered with ADEPT gateway (Tier 3 or `/mcp-register`)

```bash
mkdir -p logs && nohup make -C <server_dir> test-e2e \
  > logs/<name>_e2e_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

Check results:
```bash
tail -20 logs/<name>_e2e_*.log | grep -E "passed|failed|error"
```

---

## Step 7: Report

Present a summary table:

```
| Tier          | Required | Log File                    | Result       |
|---------------|----------|-----------------------------|--------------|
| 1. Unit       | Yes      | logs/<name>_unit_*.log      | PASS/FAIL/SKIP |
| 2. Integration| Yes/No   | logs/<name>_integration_*.log | PASS/FAIL/SKIP |
| 3. Registration| Yes/No  | logs/<name>_registration_*.log | PASS/FAIL/SKIP |
| 4. E2E        | Yes/No   | logs/<name>_e2e_*.log       | PASS/FAIL/SKIP |
```

Verify log timestamps are newer than code changes:
```bash
stat --format='%Y %n' logs/<name>_*_*.log 2>/dev/null | sort -rn | head -4
stat --format='%Y %n' <server_dir>/<package>/tools/*.py | sort -rn | head -1
```

If any required tier failed or is missing, provide remediation guidance. Do not proceed to Phase 6 (Document) until all required tiers pass.

Remind the developer of next steps in the lifecycle:
- Register tools: `/mcp-register`
- Document: `/write-session-report`
- Close the task: `/close-task` (Phases 5-9)
