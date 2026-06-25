---
name: update-tracking-docs
description: Update CHANGELOG.md, ROADMAP.md, and KNOWN_ISSUES.md with entries for the current session. Use after the session report is written, before committing.
disable-model-invocation: true
allowed-tools: Bash(git log*) Bash(git branch*) Bash(git diff*) Read Edit Glob Grep
---

You are assisting an ADEPT developer with updating tracking documentation.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in document metadata or body text.

## Step 1: Read the tracking conventions

Read `docs/development/CODE_HYGIENE.md` Sections 2.4 (Tracking Across Sessions) and 5 (Documentation Strategy) to understand the format and update expectations for each tracking document.

## Step 2: Gather context

Run:
```bash
git branch --show-current
git log --oneline -5
git diff --stat
```

Identify the current session number by checking for the session report just written (the most recent `SESSION_*.md` file in `docs/implementation-reports/` or `docs/bugfixes/`).

## Step 3: Draft CHANGELOG.md entry

Read the top 100 lines of `docs/CHANGELOG.md` to understand the current format.

Draft a new entry at the top following the format from CODE_HYGIENE.md Section 2.4:

```markdown
## Session <N>: <Title> (<Month Year>)

**Date**: <YYYY-MM-DD>
**Branch**: `<branch-name>`
**Type**: <Feature-add | Bug fix | Enhancement | Documentation>

### Problem
<Concise problem statement>

### Changes
<Grouped by component>

### Validation
<Test counts, rebuild evidence, re-registration evidence>

### New Documentation
<Links to docs created in this session>

### Related Documentation (from past 5 commits)
<Links to docs from recent commits with short commit hashes>
```

Generate the "Related Documentation (from past 5 commits)" section by running `git log --oneline -5` and cross-referencing with docs modified in those commits.

## Step 4: Draft ROADMAP.md entry

Read the "Recently Completed" progress tracking section of `docs/ROADMAP.md` (search for the last few entries to find the right location).

Draft a new entry following the existing pattern. Use plain text status markers consistent with the surrounding entries.

## Step 5: Check KNOWN_ISSUES.md

Read `docs/KNOWN_ISSUES.md`. Determine:
- Were any new issues discovered during this session? (Check test logs for pre-existing failures that should be documented.)
- Were any existing issues resolved by this session's work?

If yes to either, draft the addition or update using the format from CODE_HYGIENE.md Section 2.5.

**MANDATORY: Validate before claiming resolution.** If marking an issue as "resolved" or claiming a test now passes, you MUST validate the claim first:

1. **Trace the code path**: Identify the exact function (file:line) and call chain from the fix to the test
2. **Find the Makefile target**: Grep the Makefile for the test file path -- never run ad-hoc `docker run` commands
3. **Run the target**: `mkdir -p logs && nohup make validate-<target> > logs/<name>_$(date +%Y%m%d_%H%M%S).log 2>&1 &`
4. **Check the log**: Confirm the result matches the claim

Do not mark an issue resolved based on code reasoning alone. If you cannot run the test, write "fix applied, pending validation" instead of "resolved."

If no changes needed, report "KNOWN_ISSUES.md: no updates needed."

## Step 6: Per-issue parity check across all trackers

When a GitHub issue's state changes (opened, closed, progress updated), **every local document that references that issue must reflect the same state**. This is per-issue parity, not just per-session.

### 6a: Discover the current sprint tracker

Find the active sprint status file:
```bash
ls -t docs/implementation-sprints/SPRINT_*_STATUS.md | head -1
```

Read the file header to identify the overarching GitHub issue it mirrors (look for the `GitHub Issue:` line near the top). This is the sprint's tracking issue.

### 6b: Identify changed issues

From the session's work, list every GitHub issue whose state changed (opened, closed, progress updated).

### 6c: Find all local references to each changed issue

For each changed issue number N, run:
```bash
grep -rn '#N' docs/ --include='*.md' | grep -v node_modules
```

Every file returned must be checked. The issue's status annotation (OPEN/CLOSED/IN PROGRESS) must be consistent across all of them. Common locations:

- The sprint status tracker — issue table + categorized view
- `docs/ROADMAP.md` — `GitHub Issues:` lines in session entries
- `docs/CHANGELOG.md` — `GitHub Issues:` lines in session entries
- `docs/KNOWN_ISSUES.md` — if the issue relates to a known issue or gap
- `docs/implementation-plans/SESSION_*` — session tracker Related Issues headers, outcome tables, issue structure sections
- `docs/implementation-reports/SESSION_*` — GitHub Issue/PR header lines

Flag any file where the issue status is stale or missing.

### 6d: Update sprint tracker

If any issue states changed during this session:

1. Update the issue status table in the sprint status tracker
2. Update the categorized view (move issues between Completed / In Progress / Ready / Open sections)
3. Update the summary count line
4. Update the "Key Metrics" table if scores or test counts changed

### 6e: Verify parity with GitHub

Run `gh issue view <N> --json state` for each changed issue. If any local tracker says CLOSED but GitHub says OPEN (or vice versa), flag the mismatch.

Check for a sync checklist at the bottom of the sprint status tracker and follow it.

If no issue states changed, report "No issue state changes — sprint tracker and per-issue parity: no updates needed."

## Step 7: Check CLAUDE.md (conditional)

Only if the `git diff --stat` shows changes to architectural patterns (new API endpoints, new port mappings, new testing conventions, new tool registration patterns), propose updates to `CLAUDE.md`.

If no architectural changes detected, report "CLAUDE.md: no updates needed (no architectural changes detected)."

## Step 8: Present for approval

Present all proposed changes as diffs or full text blocks, grouped by file:
1. CHANGELOG.md entry
2. ROADMAP.md entry
3. KNOWN_ISSUES.md updates (if any)
4. Sprint status tracker updates (if any)
5. CLAUDE.md updates (if any)
6. GitHub issue updates needed (if any mismatches detected)

Do not write or edit any files until the developer approves each change.
