---
name: validate-tests
description: Check that all required test tiers have been run for the current changes. Use after making code changes and before committing.
disable-model-invocation: true
allowed-tools: Bash(make validate*) Bash(git *) Bash(ls *) Bash(stat *) Read Glob Grep
---

You are assisting an ADEPT developer with test validation before committing.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

## Step 0: Ensure lint-tools image exists

```bash
# Build lint-tools image if missing (fast no-op if already built)
docker images agentic-framework-lint-tools:latest --format "{{.ID}}" | grep -q . || make build-lint-tools
```

If the image does not exist, build it before proceeding. This is required for Docker-based linting targets (`make lint-dead-code`).

## Step 1: Read the testing policy

Read `docs/development/CODE_HYGIENE.md` Section 3 (Testing Strategy Before Commits) to understand the current testing tiers, mandatory execution patterns, and the adept_connectors "all tiers mandatory" policy. Also read `docs/testing/DOCKER_TEST_EXECUTION_REFERENCE.md` for container execution patterns and credential injection (6 validated patterns including Makefile targets, ephemeral venvs, .env injection, and credentials directory mounts).

## Step 2: Identify what changed

Run these commands to understand the scope of changes:

```
git diff --name-only
git diff --cached --name-only
git diff --stat
```

Classify the change type based on file paths:
- Files under `src/` = code change (unit tests mandatory)
- Files across multiple packages under `src/` = cross-component (integration tests required)
- Files in API routes or `agent_gateway/` = API change (E2E tests required)
- Files in `examples/adept_connectors/` = connector change (ALL 4 tiers mandatory per Section 3.6)
- Files in `examples/*_mcp_server/` = external stack (re-registration may be needed)
- Files in `scripts/release/scan_*.py` or `scripts/release/compensating_controls.py` = scanner tools (unit tests in `scripts/release/tests/`)
- MCP tool function signature changes = external stack re-registration required
- Files only in `docs/` = docs-only (no test tiers needed)

## Step 3: Check for test evidence

Look in the `logs/` directory for timestamped test log files. For each required tier, check:
1. Does a log file exist that covers the changed component?
2. Is the log file timestamp newer than the most recent code change? (Use `stat` on both the log and the changed source files to compare.)
3. Does the log file show passing results (look for "passed" and "failed" counts)?

Flag any log files that are older than the code changes as stale evidence.

## Step 4: Report findings

Present a table:

```
| Tier         | Required | Evidence         | Status    |
|--------------|----------|------------------|-----------|
| Unit         | Yes/No   | logs/file or N/A | PASS/MISSING/STALE |
| Integration  | Yes/No   | logs/file or N/A | PASS/MISSING/STALE |
| E2E          | Yes/No   | logs/file or N/A | PASS/MISSING/STALE |
| UAT          | Yes/No   | logs/file or N/A | PASS/MISSING/STALE |
| Contract     | Yes/No   | logs/file or N/A | PASS/MISSING/STALE |
```

## Step 5: Verify service containers are current

MANDATORY for any changes under `src/`. Running unit tests against read-only mounts validates syntax but NOT runtime behavior -- the service containers must be rebuilt so that integration and E2E tests exercise the actual deployed code.

Check whether affected service containers need rebuilding by mapping changed source paths to services:

| Source path prefix | Service | Rebuild command |
|--------------------|---------|-----------------|
| `src/agentic_framework_pkg/orchestration_service/` | orchestration_service | `make rebuild-orchestrator` |
| `src/agentic_framework_pkg/agent_gateway/` | agent_gateway | `make rebuild-gateway` |
| `src/agentic_framework_pkg/gateway_registry/` | gateway_registry | `make rebuild-registry` |
| `src/agentic_framework_pkg/mcp_server/` | mcp_server | `make rebuild-mcp` |
| `src/agentic_framework_pkg/hpc_mcp_server/` | hpc_mcp_server | `make rebuild-hpc-mcp` |
| `src/agentic_framework_pkg/sandbox_mcp_server/` | sandbox_mcp_server | `make rebuild-sandbox-mcp` |
| `src/agentic_framework_pkg/core/` | orchestration_service (+ all MCP servers) | `make rebuild-orchestrator` (minimum) |
| `src/agentic_framework_sdk/` | No container (SDK is client-side) | N/A |

Verify the container image is newer than the source changes:

```bash
# Check container image creation time vs source file modification time
docker inspect --format='{{.Created}}' <container_name>
stat --format='%Y' <changed_source_file>
```

If the container image predates the source changes, flag it:

```
WARNING: <service> container was built BEFORE the latest source changes.
Run: make rebuild-<service>
```

Do NOT report test validation as complete if affected containers are stale.

## Step 6: Provide remediation commands

For any MISSING or STALE tiers, provide the exact `nohup` + `make` commands to run, following the pattern from CODE_HYGIENE.md Section 3.2:

```bash
mkdir -p logs && nohup make validate-<target> \
  > logs/<scope>_<tier>_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

Also check:
- Do external stacks need re-registration? If MCP tool signatures changed, provide the re-registration loop from Section 3.4 step 4.
- Did scanner tools change? If `scripts/release/scan_*.py` or `compensating_controls.py` changed, run their unit tests:
  ```bash
  mkdir -p logs && nohup conda run -n adept-session pytest scripts/release/tests/ -v \
    > logs/scanner_unit_$(date +%Y%m%d_%H%M%S).log 2>&1 &
  ```

For docs-only changes, confirm that no test tiers are needed and the developer can proceed to commit.
