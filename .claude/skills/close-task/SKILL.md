---
name: close-task
description: Full task closure workflow -- runs test validation, session report, tracking doc updates, commit preparation, and hygiene audit in sequence. Use at the end of a development session. Pass an optional title hint as argument.
disable-model-invocation: true
allowed-tools: Bash(git *) Bash(make validate*) Bash(ls *) Bash(stat *) Read Write Edit Glob Grep
argument-hint: [optional session title hint]
---

You are assisting an ADEPT developer with closing out a development task. This runs the full task closure workflow from the ADEPT Code Hygiene Guide.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in commit messages, trailers, or document metadata.

You will work through 6 phases. Pause for developer confirmation between each phase before proceeding to the next. If any phase reveals a blocking issue, stop and explain what needs to be fixed before continuing.

---

## Phase 1: Situational Awareness

Read `docs/development/CODE_HYGIENE.md` to understand the full code hygiene checklist.

Then gather the current state:

```bash
git branch --show-current
git status
git diff --stat
git diff --cached --stat
git log --oneline -5
```

Summarize:
- Current branch name
- Total files changed (staged vs unstaged)
- Whether the working tree is clean or dirty
- Recent commit history for context

Present the summary and ask the developer to confirm before proceeding.

---

## Phase 2: Test Validation

Identify all changed files from `git diff --name-only` and `git diff --cached --name-only`.

Classify the change type and determine required test tiers (per CODE_HYGIENE.md Section 3):
- `src/` changes -> unit tests mandatory
- Cross-package changes -> integration tests required
- API routes or gateway -> E2E tests required
- `examples/adept_connectors/` -> ALL 4 tiers mandatory
- MCP tool signature changes -> external stack re-registration required
- Docs-only -> no tests needed

**MANDATORY: Verify service containers are current.** If any files under `src/` changed, check whether the affected service containers have been rebuilt. Map source paths to services:

| Source path prefix | Service | Rebuild command |
|--------------------|---------|-----------------|
| `src/agentic_framework_pkg/orchestration_service/` | orchestration_service | `make rebuild-orchestrator` |
| `src/agentic_framework_pkg/agent_gateway/` | agent_gateway | `make rebuild-gateway` |
| `src/agentic_framework_pkg/gateway_registry/` | gateway_registry | `make rebuild-registry` |
| `src/agentic_framework_pkg/mcp_server/` | mcp_server | `make rebuild-mcp` |
| `src/agentic_framework_pkg/hpc_mcp_server/` | hpc_mcp_server | `make rebuild-hpc-mcp` |
| `src/agentic_framework_pkg/sandbox_mcp_server/` | sandbox_mcp_server | `make rebuild-sandbox-mcp` |
| `src/agentic_framework_pkg/core/` | orchestration_service (minimum; may affect MCP servers) | `make rebuild-orchestrator` |
| `src/agentic_framework_sdk/` | No container (SDK is client-side) | N/A |

Compare container creation time against source file modification time:
```bash
docker inspect --format='{{.Created}}' <container_name>
stat --format='%Y' <changed_source_file>
```

If the container predates the source changes, report it as a blocking issue and provide the rebuild command. Unit tests via read-only mounts validate syntax but NOT runtime behavior -- integration and E2E tests require rebuilt containers.

Check `logs/` for timestamped test evidence. Compare log timestamps against code change timestamps.

Report which tiers have valid evidence and which are missing. For missing tiers, provide the exact `nohup make ...` commands.

If test evidence is incomplete or containers are stale, stop here and tell the developer what to run. Do not proceed to Phase 3 until the developer confirms test coverage is adequate and containers are current.

---

## Phase 3: Session Report

Detect the next session number by scanning `docs/implementation-reports/SESSION_*.md` and `docs/bugfixes/SESSION_*.md` for the highest N, then use N+1.

Ask the developer: "Is this a feature/enhancement or a bugfix?"

If `$ARGUMENTS` was provided, use it as a title hint. Otherwise ask for a short descriptive title.

Draft the session report following CODE_HYGIENE.md Section 2 templates:
- **Bugfixes** (Section 2.2): Summary, Timeline, Root Cause Analysis, Changes, Validation, Related Documentation
- **Features** (Section 2.3): Problem, Root Cause Analysis, Changes (grouped by tier), Validation (test counts), New Documentation, New Test Files, Updated Documentation

Populate from `git diff --stat` and `logs/` files. Use `file:line` notation for code references. Include cross-references per Section 5.3.

**MANDATORY: Validate every test-outcome claim.** If the report states that specific tests pass, failures are resolved, or code paths are fixed, you MUST validate those claims BEFORE writing them:

1. **Trace the code path**: From the fix to the test -- identify the exact function (file:line), the call chain, and which test(s) exercise it
2. **Find the Makefile target**: Grep the Makefile for the test file path -- never run ad-hoc `docker run` commands
3. **Run the target**: `mkdir -p logs && nohup make validate-<target> > logs/<name>_$(date +%Y%m%d_%H%M%S).log 2>&1 &`
4. **Check the log**: Confirm the pass/fail counts match the claim you are about to write
5. **Reference the log**: Include the log filename in the Validation section

Do NOT write "these failures are resolved" or "N/N tests passing" based on reasoning about the code alone. The test must have actually run and the log must show the result. If you cannot validate a claim, write "pending validation" instead.

Present the full document content and proposed file path. Do not write until approved.

---

## Phase 4: Tracking Documentation Updates

Read the current state of these files:
- `docs/CHANGELOG.md` (top 100 lines for format reference)
- `docs/ROADMAP.md` (find the Recently Completed / progress tracking section)
- `docs/KNOWN_ISSUES.md`

Draft updates for each:

**CHANGELOG.md**: New entry at the top following Section 2.4 format (Session N, Date, Branch, Type, Problem, Changes, Validation, New Documentation, Related Documentation from past 5 commits). Include `GitHub Issues:` line with issue numbers and their current state (OPEN/CLOSED).

**ROADMAP.md**: New entry in the progress tracking section following the pattern of surrounding entries. Include `GitHub Issues:` line.

**KNOWN_ISSUES.md**: Check if new issues were discovered (pre-existing test failures) or existing issues were resolved. Draft updates per Section 2.5 format, or report "no updates needed." If claiming an issue is "resolved," apply the same validation mandate from Phase 3: trace the code path, find the Makefile target, run it, and confirm the log shows the fix. Do not mark an issue resolved based on code reasoning alone.

**Per-issue parity + Sprint tracker**: For every GitHub issue whose state changed during this session, run `grep -rn '#N' docs/ --include='*.md'` and verify every local reference has the correct status (OPEN/CLOSED/IN PROGRESS). Then find the active sprint status tracker (`ls -t docs/implementation-sprints/SPRINT_*_STATUS.md | head -1`) and update its issue table, categorized view, summary line, and Key Metrics. Run `gh issue view <N> --json state` to verify local/remote parity. Follow the sync checklist at the bottom of the sprint tracker if one exists. If no issue states changed, report "no updates needed."

**CLAUDE.md**: Only if the diff shows architectural pattern changes (new API endpoints, port mappings, testing conventions, tool registration patterns). Otherwise report "no updates needed."

Present all proposed changes. Do not edit until approved.

---

## Phase 5: Commit Preparation

Check `git diff --cached --stat`. If nothing staged, ask what to stage.

Classify commit type and scope per CODE_HYGIENE.md Section 4.1.

Draft the full commit message:
- Subject: `<type>(<scope>): <imperative, max 72 chars>`
- Body: what changed + why + test evidence with counts
- `Related documentation (this commit):` from staged doc files
- `Related documentation (past 5 commits):` from `git log --oneline -5` cross-referenced with modified docs

Validate:
- NO AI agent references anywhere in the message (Section 4.5)
- No `.env`, credential files, `logs/`, `__pycache__/`, or large binaries staged (Section 4.6)

Present the complete `git commit` command with heredoc format. Do not execute it.

---

## Phase 5.5: Semantic Self-Review

Run `/pre-push-review` on the staged changes.

This catches semantic issues that mechanical linters miss: pattern inconsistency across similar constructs, dead code with zero callers, doc-code divergence, and unreachable code paths.

If findings are reported:
- FAIL on Audit 2 (dead code) or Audit 5 (unreachable paths): Fix before proceeding
- Findings on Audit 1 or 3: Developer judgment -- may be intentional, note in PR description
- Re-stage fixed files after remediation

If clean (0 findings): proceed to Phase 6.

---

## Phase 6: Final Hygiene Audit

Walk the full Quick Reference Card from CODE_HYGIENE.md. For each checkbox, report PASS, FAIL, or N-A:

**BRANCH**: naming convention, correct parent, pushed to both remotes
**IMPLEMENTATION**: session doc exists, root cause analysis (if bugfix), file:line notation
**TESTING**: timestamped logs, all tiers executed, counts recorded, pre-existing failures documented, services rebuilt, stacks re-registered
**COMMIT**: Conventional Commits format, body with what+why+evidence, both Related Documentation sections, no AI references
**DOCUMENTATION**: CHANGELOG updated, ROADMAP updated, KNOWN_ISSUES updated (if applicable), CLAUDE.md updated (if applicable)

Present the checklist with status for each item.

For any FAIL items, provide the specific remediation action.

If all items pass, confirm: "All hygiene checks pass. Ready to push." Then remind about pushing and PR review:
```bash
git push origin <branch>
# Optional: push to personal fork (e.g., git push paul-origin <branch>)
```

If the developer wants to create or update a PR, suggest: **"Run `/prepare-pr` to create the PR and check review status."**
