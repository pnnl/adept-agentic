---
name: audit-hygiene
description: Walk the full ADEPT Code Hygiene Quick Reference Card checklist and report PASS/FAIL/N-A for each item. Use as a final check before pushing.
disable-model-invocation: true
allowed-tools: Bash(git *) Read Glob Grep
---

You are assisting an ADEPT developer with a final code hygiene audit.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

## Step 1: Read the full code hygiene guide

Read `docs/development/CODE_HYGIENE.md` in full, paying special attention to the Quick Reference Card (the checklist near the end of the file).

## Step 2: Gather state

Run:
```bash
git branch --show-current
git status
git log -1 --format="%H %s"
git log -1 --format="%B"
git remote -v
git log --oneline origin/$(git branch --show-current)..HEAD 2>/dev/null | wc -l
```

## Step 3: Walk the checklist

Evaluate every item in the Quick Reference Card. Report each as PASS, FAIL, or N-A with a brief justification.

### BRANCH

- [ ] **Branch naming**: Does the current branch name follow `<type>-<workstream>-<FY-quarter>-<scope>` convention?
- [ ] **Correct parent**: Was the branch created from the correct parent? (Check `git log --oneline --graph -10` for merge base.)
- [ ] **Pushed to origin**: Are there unpushed commits to `origin`? (Check `git log --oneline origin/<branch>..HEAD`. Developers with personal forks should also check their fork remote.)

### IMPLEMENTATION

- [ ] **Session doc created**: Does a `SESSION_<N>_*.md` file exist in `docs/implementation-reports/` or `docs/bugfixes/` for the current session?
- [ ] **Root cause analysis**: For bugfixes, does the session doc contain a "Root Cause Analysis" section?
- [ ] **Code references**: Does the session doc use `file:line` notation for code references?

### TESTING

- [ ] **Timestamped logs**: Do test log files exist in `logs/` with timestamps from this session?
- [ ] **All relevant tiers executed**: Based on what files changed, were all required tiers run? (Use the same logic as `/validate-tests`.)
- [ ] **Test counts recorded**: Do the session doc and/or commit message include specific test counts (N passed, M failed)?
- [ ] **Test claims validated**: For every test-outcome claim in docs (session report, validation report, KNOWN_ISSUES, CHANGELOG), verify the claim against an actual timestamped log in `logs/`. If a doc says "N/N passed" or "failure resolved," the log must exist and show that result. Flag any unvalidated claims.
- [ ] **Pre-existing failures documented**: If any test failures exist, are they explicitly documented as pre-existing?
- [ ] **Services rebuilt**: If files under `src/` changed, verify that affected service containers have been rebuilt (image newer than source changes). Use the source-to-service mapping from `/validate-tests` to identify which containers need checking. Compare `docker inspect --format='{{.Created}}' <container>` against source file timestamps.
- [ ] **External stacks re-registered**: If MCP tool signatures changed, is there evidence of re-registration?

### COMMIT

- [ ] **Conventional Commit format**: Does the most recent commit message follow `<type>(<scope>): <description>`?
- [ ] **Body has what+why+test evidence**: Does the commit body explain what changed, why, and include test counts?
- [ ] **Related documentation (this commit)**: Is this footer section present in the commit message?
- [ ] **Related documentation (past 5 commits)**: Is this footer section present with commit hashes?
- [ ] **No AI agent references**: Does the commit message contain zero references to Claude, Gemini, ChatGPT, Copilot, or any AI agent in Author, Co-Authored-By, Signed-off-by, or body text?

### DOCUMENTATION

- [ ] **CHANGELOG.md updated**: Does `docs/CHANGELOG.md` contain an entry for the current session with `GitHub Issues:` line?
- [ ] **ROADMAP.md updated**: Does the Recently Completed section of `docs/ROADMAP.md` have an entry for this session's work with `GitHub Issues:` line?
- [ ] **KNOWN_ISSUES.md updated**: If issues were discovered or resolved, is `docs/KNOWN_ISSUES.md` updated?
- [ ] **Sprint tracker updated**: If any GitHub issue states changed, is the active sprint status tracker (`ls -t docs/implementation-sprints/SPRINT_*_STATUS.md | head -1`) updated and in parity with GitHub? (Run `gh issue view <N> --json state` to verify.)
- [ ] **Per-issue parity**: For each issue that changed state, run `grep -rn '#N' docs/ --include='*.md'`. Does every local reference (sprint tracker, session tracker, ROADMAP, CHANGELOG, KNOWN_ISSUES, implementation plans/reports) show the correct status? Flag any stale references.
- [ ] **CLAUDE.md updated**: If architectural patterns changed, is `CLAUDE.md` updated?

## Step 4: Present the report

Output a formatted checklist:

```
ADEPT Code Hygiene Audit
========================

BRANCH
  [PASS] Branch naming: feature-platform-optimizations-FY26Q2-...
  [PASS] Correct parent: branched from feature-platform-optimizations-FY26Q2
  [FAIL] Pushed to origin: 3 commits unpushed to origin

IMPLEMENTATION
  [PASS] Session doc: docs/implementation-reports/SESSION_NNN_...
  [N-A]  Root cause analysis: not a bugfix
  [PASS] Code references: file:line notation used

TESTING
  ...

COMMIT
  ...

DOCUMENTATION
  ...

Summary: 18/20 PASS, 1 FAIL, 1 N-A
```

## Step 5: Remediation

For each FAIL item, provide the specific action needed to fix it. Example:

```
REMEDIATION:
1. [Pushed to origin] Run: git push origin <branch>
```

If all items PASS, confirm: "All hygiene checks pass. Ready to push."
