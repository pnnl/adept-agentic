---
name: write-session-report
description: Generate a session implementation report or bugfix document following ADEPT conventions. Use after tests pass, before committing. Pass an optional title hint as argument.
disable-model-invocation: true
allowed-tools: Bash(git *) Read Write Glob Grep
argument-hint: [optional title hint]
---

You are assisting an ADEPT developer with writing a session report.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in document metadata or body text.

## Step 1: Read the documentation conventions

Read `docs/development/CODE_HYGIENE.md` Section 2 (Implementation & Bugfix Tracking) to understand the templates, naming patterns, and cross-referencing conventions.

## Step 2: Detect the next session number

Scan for the highest session number across both directories:

```bash
ls docs/implementation-reports/SESSION_*.md docs/bugfixes/SESSION_*.md 2>/dev/null | grep -oP 'SESSION_\K[0-9]+' | sort -n | tail -1
```

Use N+1 as the session number for this report.

## Step 3: Determine report type

Ask the developer: "Is this session a feature/enhancement or a bugfix?" This determines:
- **Feature/enhancement** -> `docs/implementation-reports/SESSION_<N>_<TITLE>.md` using Section 2.3 template
- **Bugfix** -> `docs/bugfixes/SESSION_<N>_<TITLE>.md` using Section 2.2 template

If the developer provided a title hint via `$ARGUMENTS`, use it to derive the filename. Otherwise, ask for a short descriptive title.

## Step 4: Gather session data

Run these commands to understand what happened in this session:

```bash
git diff --stat
git diff --cached --stat
git log --oneline -10
git branch --show-current
```

Also check `logs/` for test result files from this session (recent timestamps).

## Step 5: Draft the report

**MANDATORY: Validate every test-outcome claim.** If the report states that specific tests pass, specific failures are resolved, or specific code paths are fixed, you MUST have validated those claims BEFORE writing them:

1. **Trace the code path**: From the fix to the test -- identify the exact function (file:line), the call chain, and which test(s) exercise it
2. **Find the Makefile target**: Grep the Makefile for the test file path -- never run ad-hoc `docker run` commands
3. **Run the target**: `mkdir -p logs && nohup make validate-<target> > logs/<name>_$(date +%Y%m%d_%H%M%S).log 2>&1 &`
4. **Check the log**: Confirm the pass/fail counts match the claim you are about to write
5. **Reference the log**: Include the log filename in the Validation section so the claim is auditable

Do NOT write "these failures are resolved" or "N/N tests passing" based on reasoning about the code alone. The test must have actually run and the log must show the result. If you cannot validate a claim, write "pending validation" instead.

**For bugfixes** (Section 2.2 template):
- Summary: 2-3 sentences describing the user-visible failure
- Timeline: if relevant, a table of events
- Root Cause Analysis: technical root cause with code references (file:line notation)
- Changes: list of files changed with specific line references
- Validation: test results with counts (N/N passed) from log files
- Related Documentation: links to related docs using relative paths per Section 5.3

**For features** (Section 2.3 template):
- Problem: what user-visible limitation existed
- Root Cause Analysis: why the problem existed (architecture-level)
- Changes: grouped by tier/component (MCP Server, Pydantic, Wrapper, Makefile, etc.)
- Validation: full test results with counts and Makefile targets
- New Documentation: docs created in this session
- New Test Files: tests created in this session
- Updated Documentation: docs modified in this session

Populate the Changes section from `git diff --stat`. Populate the Validation section from test log files in `logs/`.

## Step 6: Present for approval

Present the full document content and the proposed file path. Do not write the file until the developer approves.

After approval, write the file and confirm the path.
