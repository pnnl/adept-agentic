---
name: prepare-pr
description: Create a pull request, check Copilot/peer review status, address findings, resolve review conversations on GitHub, and verify review clearance. Use after committing and pushing, as part of Phase 9 (Close). Pass optional PR number as argument to check an existing PR.
disable-model-invocation: true
allowed-tools: Bash(git *) Bash(gh *) Bash(grep *) Bash(find *) Bash(ls *) Read Write Edit Glob Grep
argument-hint: [optional: existing PR number to check]
---

You are assisting an ADEPT developer with the pull request lifecycle. This covers creating a PR, monitoring review status, addressing findings, and confirming clearance.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in PR descriptions or comments.

---

## Phase 1: Situational Awareness

Gather the current state:

```bash
git branch --show-current
git status
git log --oneline -5
```

Identify the parent branch:
```bash
git log --oneline --graph --all | head -20
```

Check if a PR already exists for this branch:
```bash
gh pr list --head "$(git branch --show-current)" --json number,title,state,url
```

If `$ARGUMENTS` was provided as a PR number, use that PR directly:
```bash
gh pr view $ARGUMENTS --json number,title,state,url,reviews,statusCheckRollup
```

Report:
- Current branch and parent branch
- Whether a PR already exists (number + URL) or needs to be created
- Number of commits ahead of parent

Ask the developer to confirm before proceeding.

---

## Phase 2: Create PR (skip if PR exists)

If no PR exists for this branch, draft one.

### Determine PR Type

Identify the PR type based on branches:

| Source → Target | Type | Merge Strategy | Title Format |
|-----------------|------|----------------|--------------|
| child → parent feature branch | Regular | Fast-forward | `<type>(<scope>): <summary>` |
| parent feature branch → main | Release | Squash-merge | `release(v1.0.YYYYMMDD): <summary>` |

### Regular PRs (child → parent)

Analyze changes relative to parent:
```bash
git log $(git merge-base HEAD <parent>)..HEAD --oneline
git diff $(git merge-base HEAD <parent>)..HEAD --stat
```

Draft the PR:
- **Title**: `<type>(<scope>): <summary>` — under 70 characters
- **Body**: Summary (3-5 bullets), Test plan (checklist), key references

Present the `gh pr create` command:
```bash
gh pr create --title "<title>" --body "$(cat <<'EOF'
## Summary
- <bullet 1>
- <bullet 2>

## Test plan
- [ ] <test item>

## Key references
- <doc paths>
EOF
)"
```

### Release PRs (feature branch → main, squash-merge)

For squash-merge PRs to main, follow the release branch strategy:

**Pre-requisites** (must be done BEFORE creating the PR):

1. **Version bump** on the feature branch (3 touchpoints + `uv lock`):
   ```bash
   # Verify current version
   grep '^version' pyproject.toml
   grep '^version' examples/adept_asopb/pyproject.toml
   grep '__version__' src/agentic_framework_sdk/__init__.py
   ```
   All 3 must match CalVer format `v1.0.YYYYMMDD`.

2. **Create next phase branch** off the feature branch tip:
   ```bash
   git checkout <feature-branch>
   git checkout -b <feature-branch>-phase<N>
   git push -u origin <feature-branch>-phase<N>
   ```
   This preserves full commit lineage for the team to continue work.

3. **Run `/prepare-release`** to verify ASOPB gate passes (Pipeline ASPI >= 95).

**Create the release PR**:
```bash
gh pr create --base main --head <feature-branch> \
  --title "release(v1.0.YYYYMMDD): <quarter summary>" \
  --body "$(cat <<'EOF'
## Summary

Squash-merge of <feature-branch> into main for public release v1.0.YYYYMMDD.

### Highlights
- <major feature 1>
- <major feature 2>
- <major feature 3>

### ASOPB Gate
- Pipeline ASPI: <score> (threshold: 95)
- Scan directory: logs/scan-staged-YYYYMMDD-HHMM/

## Post-merge steps (developer must complete)
- [ ] Forward-merge main into <phase-branch>: `git checkout <phase-branch> && git merge main`
- [ ] Push phase branch: `git push origin <phase-branch>`
- [ ] Tag release: `git tag v1.0.YYYYMMDD main && git push origin v1.0.YYYYMMDD`

## Key references
- CHANGELOG: docs/CHANGELOG.md
- ROADMAP: docs/ROADMAP.md
EOF
)"
```

**Post-merge steps** (after developer approves and squash-merges):

The developer (not this skill) must:
1. Forward-merge main into the phase branch to update merge-base:
   ```bash
   git checkout <feature-branch>-phase<N>
   git merge main -m "chore: sync with main after v1.0.YYYYMMDD release"
   git push origin <feature-branch>-phase<N>
   ```
2. This ensures future phase → main PRs show ONLY new delta work.

**Key rules**:
- NEVER execute `gh pr merge` for release PRs — developer approves
- NEVER rebase phase branches onto main (destroys history)
- ALWAYS forward-merge main into phase branch (preserves all SHAs)
- Squash-merge is ONLY for feature → main (public release flattening)

Do not execute until the developer approves. After creation, record the PR number.

---

## Phase 3: Check Review Status

Check the PR for reviews and inline comments:

```bash
# Review summary
gh pr view <N> --json reviews --jq '.reviews[] | {author: .author.login, state: .state, body: .body[:200]}'

# Inline comments (Copilot and human)
gh api repos/{owner}/{repo}/pulls/<N>/comments --jq '.[] | {user: .user.login, path: .path, body: .body[:300]}'

# Check status (CI checks)
gh pr view <N> --json statusCheckRollup --jq '.statusCheckRollup[] | {name: .name, conclusion: .conclusion}'
```

Classify each finding:
- **SECURITY**: Permission model, credential exposure, injection risks
- **CORRECTNESS**: Logic errors, exit code masking, escaping bugs
- **STYLE**: Naming, comments, formatting

Present a numbered list of findings with classification and recommended action for each. Ask the developer which findings to address.

---

## Phase 4: Address Findings

For each finding the developer wants to address:

1. Read the file at the path mentioned in the review comment
2. Propose the specific edit (show old vs new)
3. Apply edits after developer approval
4. Track what was addressed vs. acknowledged-but-deferred

**MANDATORY: Validate before claiming.** If any edit (code fix, doc update, or review reply) claims that a test passes, a failure is resolved, or a code path behaves a certain way, you MUST validate that claim before writing it:

1. **Trace the code path**: Identify the exact function, file:line, and call chain affected by the fix
2. **Identify the test**: Find the specific test(s) that exercise that code path (search `tests/unit/`, `tests/integration/`, `tests/e2e/`)
3. **Find the Makefile target**: Grep the Makefile for the test file path -- never run ad-hoc `docker run` commands
4. **Run the target**: `mkdir -p logs && nohup make validate-<target> > logs/<name>_$(date +%Y%m%d_%H%M%S).log 2>&1 &`
5. **Check the log**: Confirm pass/fail counts match your claim

If you cannot validate a claim (no test exists, target unavailable), state that explicitly rather than asserting the claim is true.

After all edits:
```bash
git add <modified-files>
git status
```

Draft a commit message:
```bash
git commit -m "$(cat <<'EOF'
fix(<scope>): address PR review findings

<what was fixed and why>

Findings addressed:
- <finding 1 summary>
- <finding 2 summary>

Related documentation (this commit):
- <paths>

Related documentation (past 5 commits):
- <paths from git log>
EOF
)"
```

Push to trigger re-review:
```bash
git push origin <branch>
# Optional: push to personal fork (e.g., git push paul-origin <branch>)
```

---

## Phase 4b: Resolve Review Conversations (optional, highly recommended)

After addressing findings in code and pushing, resolve the review conversations on GitHub by replying to each comment with the resolution. This closes the feedback loop for reviewers and creates an audit trail.

**Prerequisites**: This phase requires a GitHub Personal Access Token (PAT) with `repo` scope (specifically `pull_requests:write`). The default `GITHUB_TOKEN` in CI may not have sufficient permissions. If using Claude Code, the `gh` CLI must be authenticated with a PAT that can post PR review comments.

If the token lacks permissions, skip this phase — it is not a blocking gate. The code fixes in Phase 4 are sufficient for re-review.

**List unresolved review comments**:
```bash
# Get all review comments with their IDs
gh api repos/{owner}/{repo}/pulls/<N>/comments \
  --jq '.[] | {id: .id, user: .user.login, path: .path, line: .line, body: .body[:200]}'
```

**Reply to each addressed comment** with a resolution explanation:
```bash
# Reply to a specific review comment (uses comment ID from above)
gh api repos/{owner}/{repo}/pulls/<N>/comments/<comment_id>/replies \
  -f body="Addressed in <commit_hash>: <brief explanation of what was changed and why>"
```

**Resolution reply templates** (adapt to context):

| Finding Type | Reply Template |
|---|---|
| SECURITY | "Addressed in `<hash>`: Added `<mitigation>`. See `<file:line>` for the gating mechanism." |
| CORRECTNESS | "Addressed in `<hash>`: Fixed `<what>` — `<why the original was wrong>`." |
| STYLE | "Addressed in `<hash>`: Added `<comment/declaration/etc>` as suggested." |
| ACKNOWLEDGED | "Acknowledged — intentional design choice: `<justification>`. No code change needed." |
| DEFERRED | "Tracked as backlog item `<issue_or_doc_ref>`. Out of scope for this PR." |

**Batch resolution** (when many comments were addressed in a single commit):
```bash
# Post a summary comment on the PR itself
gh pr comment <N> --body "$(cat <<'EOF'
## Review Findings Addressed

Commit `<hash>` resolves the following review findings:

| # | Finding | Resolution |
|---|---------|------------|
| 1 | <path:line> — <summary> | <what was done> |
| 2 | <path:line> — <summary> | <what was done> |

Remaining items (acknowledged, no code change):
- <item>: <justification>
EOF
)"
```

Report to the developer:
- How many conversations were resolved
- Any that could not be resolved (permission errors, ambiguous findings)
- Whether to proceed to Phase 5 (verify clearance)

---

## Phase 5: Verify Review Clearance

After pushing fixes, re-check review status:

```bash
gh pr view <N> --json reviews --jq '.reviews[] | {author: .author.login, state: .state, submittedAt: .submittedAt}'
```

Report:
- Whether Copilot has re-reviewed (new review timestamp after the fix push)
- Whether new findings were raised
- Whether all CI checks pass

If new findings exist, return to Phase 4.

If review is clear, report:
**"PR review complete. Ready to merge or continue with issue closure."**

For **release PRs** (squash-merge to main), additionally remind the developer:
1. After merge: forward-merge main into phase branch (`git merge main`)
2. Push phase branch to update remote merge-base
3. Tag the release on main (`git tag v1.0.YYYYMMDD main`)

Remind the developer to update GitHub issues and sprint tracker (Phase 9 steps 4-6 in the workflow guide), or suggest using `/close-task` to complete the remaining closure steps.
