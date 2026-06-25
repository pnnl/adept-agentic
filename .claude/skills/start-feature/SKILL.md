---
name: start-feature
description: Walk through the full ADEPT feature development lifecycle (Phase 0-9). Invokes sub-skills at each gate. Use at the START of any new feature, bugfix, enhancement, or refactoring work. Pass optional work type as argument (feature, bugfix, refactor, chore).
disable-model-invocation: true
allowed-tools: Bash(git *) Bash(gh *) Bash(grep *) Bash(find *) Bash(ls *) Bash(stat *) Bash(make validate*) Read Write Edit Glob Grep
argument-hint: [optional: feature | bugfix | refactor | chore]
---

You are guiding an ADEPT developer through the canonical feature development lifecycle. This is the master conductor skill that orchestrates Phases 0-9 from the ADEPT Feature Development Workflow.

Do not use emojis in any output.
Do not include any AI agent references in commit messages, trailers, or document metadata.
Do not implement code changes yourself during this skill -- guide the developer through the process.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

Pause for developer confirmation at each phase gate before proceeding. If a gate check fails, explain what must be fixed and do not advance.

---

## Phase 0: Orient

Read these files to understand the project conventions:

1. `CLAUDE.md` (project root) -- architecture, port mappings, API strategy
2. `docs/development/CODE_HYGIENE.md` -- branch naming, commit format, testing tiers
3. `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md` -- this lifecycle (the authoritative reference)
4. `docs/development/AGENT_CODING_RULES.md` -- universal AI agent operational rules

Then ask the developer:

**"What type of work is this?"**
- If `$ARGUMENTS` was provided, use that. Otherwise ask.
- Options: `feature` | `bugfix` | `refactor` | `chore`

Based on the answer, determine which phases to follow:

| Type | Phases |
|------|--------|
| feature | 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 |
| bugfix | 0, (skip 1 -- use existing issue), 2, 3, 4, 5, 6, 7, 8, 9 |
| refactor | 0, 1 (lightweight), 3, 4, 5, 6, 7, 8, 9 |
| chore | 3, 4, 5 (if testable), 7, 9 |

Report the determined phase sequence to the developer before proceeding.

---

## Phase 1: Plan

Ask: **"What GitHub issue does this relate to? (number, or 'new' to create one)"**

If existing issue:
```bash
gh issue view <N> --json title,body,state
```
Read the issue and confirm scope with the developer.

If new issue:
- Ask for title and 2-3 sentence description
- Propose creating the issue:
  ```bash
  gh issue create --title "<type>: <title>" --body "<body>"
  ```

Then check if an implementation plan exists:
```bash
find docs/implementation-plans/ -name "*.md" | xargs grep -l "<relevant keywords>" 2>/dev/null
```

If no plan exists, tell the developer:
**"No implementation plan found. Before any code changes, create one at `docs/implementation-plans/<DESCRIPTIVE_NAME>.md` with: Problem, Approach, Tasks (T#.# format), Files to Create/Modify, Acceptance Criteria."**

Offer to help draft the plan structure.

**GATE CHECK**: Verify the plan doc exists:
```bash
ls docs/implementation-plans/<plan-name>.md
```
If it does not exist, do not proceed to Phase 2.

---

## Phase 2: Discover

Tell the developer:
**"Before implementing, find 3+ analogous implementations in the codebase."**

Help search:
```bash
# Find SKILLS.md files for the target area
find . -name "SKILLS.md" -type f

# Find similar MCP tools
find examples/ src/ -name "*.py" | xargs grep -l "<pattern>" 2>/dev/null

# Find similar patterns
grep -rn "<similar_function_or_class>" src/ examples/ --include="*.py" | head -20
```

Ask: **"Which existing implementations did you review? List at least 3 file paths."**

If fewer than 3, help find more. The developer should add these to the "Reusable Patterns" section of their implementation plan doc.

**GATE CHECK**: Implementation plan doc has a "Reusable Patterns" or "Existing Analogues" section. If not, do not proceed.

---

## Phase 3: Branch

Check current branch:
```bash
git branch --show-current
git status
```

If the working tree is not clean, warn the developer.

If a new branch is needed:
```bash
# Verify parent branch
git log --oneline -1

# Create child branch
git checkout -b <category>-<workstream>-<FY-quarter>-<scope>

# Push to origin (developers with a personal fork can also push there)
git push -u origin <branch-name>
```

**GATE CHECK**: Branch exists on origin:
```bash
git branch -r | grep <branch-name>
```

---

## Phase 4: Implement

Tell the developer:
**"Implementation phase. Work through the tasks in your plan doc. I'll help when you need it."**

Remind them of the rules:
- All operations use Makefile targets, never ad-hoc shell commands
- Rebuild affected services after server-side changes
- Re-register external tool stacks if MCP tool signatures changed
- If you discover something unexpected, investigate (read logs) before guessing
- Persist all findings to docs, not just conversation
- No scope drift -- new discoveries go to backlog, not current scope

The developer does the work. This skill resumes when they signal they are ready to test.

Ask: **"Are all planned tasks complete? Ready to move to testing?"**

---

## Phase 5: Test

If the target module has a `TESTING_STRATEGY.md` (in `docs/` or `tests/`), read it first to understand the credential acquisition, networking requirements, and available Makefile targets. For canonical Docker test patterns and credential injection, see `docs/testing/DOCKER_TEST_EXECUTION_REFERENCE.md`.

Determine required test tiers by checking what changed:
```bash
git diff --name-only $(git merge-base HEAD main)..HEAD
```

Classify changes using the test tier matrix from `FEATURE_DEVELOPMENT_WORKFLOW.md`:
- `src/` changes → unit tests mandatory
- Cross-package → integration required
- API routes / gateway → E2E required
- Connectors / UI → all 4 tiers
- `examples/adept_connectors/` → ALL 4 tiers mandatory
- Docs only → no tests needed
- IaC → dry-run validation

**MANDATORY: Verify service containers are current.** If any files under `src/` changed, check whether affected service containers have been rebuilt. Map changed source paths to services using the table in `/validate-tests`. If the container image predates the source changes, tell the developer to run the appropriate `make rebuild-*` target BEFORE running integration or E2E tests.

Tell the developer which tiers are required. Then invoke the validation:

**"Run `/validate-tests` to check test coverage and evidence."**

Or provide the commands directly:
```bash
mkdir -p logs && nohup make validate-<target> \
  > logs/<scope>_<tier>_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

**GATE CHECK**: Timestamped logs exist and are newer than code changes:
```bash
ls -lt logs/*_$(date +%Y%m%d)*.log | head -5
```

---

## Phase 6: Document

Tell the developer:
**"Run `/write-session-report` to draft the session documentation, then `/update-tracking-docs` to sync CHANGELOG, ROADMAP, and KNOWN_ISSUES."**

Or guide manually:

### 6a. Session Report
```bash
# Find next session number
ls docs/implementation-reports/SESSION_*.md docs/bugfixes/SESSION_*.md 2>/dev/null | sort -t_ -k2 -n | tail -1
```

Create report at:
- Feature: `docs/implementation-reports/SESSION_<N>_<TITLE>.md`
- Bugfix: `docs/bugfixes/SESSION_<N>_<TITLE>.md`

### 6b. Tracking Docs
Update (if applicable):
- `docs/CHANGELOG.md` -- session entry
- `docs/ROADMAP.md` -- Recently Completed section
- `docs/KNOWN_ISSUES.md` -- new issues or resolved issues
- `CLAUDE.md` -- only if architectural patterns changed
- Active sprint tracker in `docs/implementation-sprints/`

**GATE CHECK**: Session report exists. CHANGELOG has this session's entry.

---

## Phase 7: Commit

**PRE-GATE: Verify test evidence before allowing commit.**

Before drafting the commit message, verify that timestamped test logs exist for ALL changed `src/` and `examples/` paths. This is NOT optional -- it was separated from Phase 5 to catch cases where code changes happen AFTER initial testing.

```bash
# Check for source changes that require test evidence
git diff --cached --name-only -- 'src/' 'examples/' 2>/dev/null
git diff --name-only -- 'src/' 'examples/' 2>/dev/null

# If source files changed, verify logs are newer than source
ls -lt logs/*_$(date +%Y%m%d)*.log 2>/dev/null | head -5
```

If test logs are MISSING or STALE (older than the source changes), do NOT proceed. Tell the developer:

**"BLOCKED: Test evidence is missing or stale for changed code paths. Run the required validation targets (see `/validate-tests`) before committing."**

If only docs/skills/non-code files changed, skip this pre-gate.

---

Tell the developer:
**"Run `/prepare-commit` to build the commit message with documentation references."**

Or guide manually:

1. Stage specific files (never `git add -A`):
   ```bash
   git add <files>
   ```
2. Build commit message with:
   - `type(scope): subject`
   - Body: what + why + test evidence
   - `Related documentation (this commit):` section
   - `Related documentation (past 5 commits):` section
   - NO AI agent references

Check past 5 commits for doc references:
```bash
git log --oneline -5
git log -5 --format="%h %s" -- docs/
```

**GATE CHECK**: Commit message has both Related Documentation sections. No AI agent attribution. Test evidence verified in pre-gate.

---

## Phase 8: Validate

Tell the developer:
**"Run `/audit-hygiene` for the final pre-push checklist."**

Or walk the Quick Reference Card from `CODE_HYGIENE.md` manually -- all items in BRANCH, IMPLEMENTATION, TESTING, COMMIT, and DOCUMENTATION categories.

**GATE CHECK**: All applicable items pass. Any FAIL must be resolved.

---

## Phase 9: Close

Push to origin:
```bash
git push origin <branch>
```

Create or update the pull request:
```bash
gh pr list --head "$(git branch --show-current)" --json number,url
```

If no PR exists, ask the developer if they want to create one. If yes:

**"Run `/prepare-pr` to create the PR, check Copilot/peer review status, and address any findings."**

If a PR already exists, check review status:
```bash
gh pr view <N> --json reviews --jq '.reviews[] | {author: .author.login, state: .state}'
gh api repos/{owner}/{repo}/pulls/<N>/comments --jq '.[] | {user: .user.login, path: .path, body: .body[:200]}'
```

If there are unresolved findings, tell the developer:
**"PR has unresolved review findings. Run `/prepare-pr <N>` to address them."**

Update GitHub issues:
```bash
gh issue comment <N> --body "Completed in commit $(git rev-parse --short HEAD). See docs/implementation-reports/SESSION_<N>_<TITLE>.md"
```

If all acceptance criteria met, close the issue:
```bash
gh issue close <N>
```

Update sprint tracker if active.

Report to the developer:
**"Feature lifecycle complete. Pushed to origin. PR created/updated. GitHub issue updated."**
