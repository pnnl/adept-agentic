---
name: review-pr
description: Assess and address PR review findings from Copilot, CodeRabbit, or human reviewers — classify, fix, reply, resolve
disable-model-invocation: true
allowed-tools: Bash(gh *) Bash(git *) Bash(grep *) Bash(find *) Bash(cat *) Bash(ls *) Read Write Edit Glob Grep
---

You are assisting an ADEPT developer with assessing and addressing pull request review findings from automated reviewers (GitHub Copilot, CodeRabbit, SonarCloud) or human reviewers.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

CRITICAL: Always use `--paginate` with `gh api` list endpoints to avoid missing results beyond page 1.

## Input

The skill accepts one argument: a PR number (e.g., `/review-pr 108`). If no number is provided, detect the PR for the current branch:

```bash
PR_NUMBER=$(gh pr list --head "$(git branch --show-current)" --json number --jq '.[0].number')
echo "PR #$PR_NUMBER"
```

If no PR exists for the current branch, stop and inform the developer.

---

## Phase 1: Collect Review Findings

Retrieve all review comments (inline findings) and PR reviews:

```bash
# Get all review comments with pagination
gh api repos/{owner}/{repo}/pulls/$PR_NUMBER/comments --paginate \
  --jq '.[] | select(.in_reply_to_id == null) | {id: .id, user: .user.login, path: .path, line: .line, body: .body[:300]}'

# Get review summaries
gh api repos/{owner}/{repo}/pulls/$PR_NUMBER/reviews --paginate \
  --jq '.[] | {id: .id, user: .user.login, state: .state, submitted_at: .submitted_at, body: .body[:200]}'
```

Determine the repository owner/repo from:
```bash
gh repo view --json nameWithOwner --jq '.nameWithOwner'
```

Present findings in a numbered table:

| # | Reviewer | File | Finding (summary) | Classification |
|---|----------|------|-------------------|----------------|
| 1 | copilot | path/to/file.py | Description... | SECURITY |

---

## Phase 2: Classify Findings

Classify each finding into one of these categories:

| Category | Description | Action Required |
|----------|-------------|-----------------|
| **SECURITY** | Permission model, credential exposure, injection risks, unsafe defaults | Must fix before merge |
| **CORRECTNESS** | Logic errors, exit code masking, escaping bugs, race conditions | Must fix before merge |
| **CONSISTENCY** | Acronym drift, threshold mismatches, version discrepancies across docs | Should fix in this PR |
| **STYLE** | Naming, comments, formatting, code organization | Fix if trivial, defer if not |
| **OPTIMIZATION** | Performance suggestions, redundant operations, resource waste | Acknowledge, defer to backlog |
| **INFORMATIONAL** | Observations, suggestions for future work, non-blocking notes | Acknowledge only |

Priority order: SECURITY > CORRECTNESS > CONSISTENCY > STYLE > OPTIMIZATION > INFORMATIONAL

Present the classified findings to the developer. Ask which to address.

---

## Phase 3: Analyze Findings

For each finding the developer wants to address, perform targeted analysis:

### 3a. Read the affected file

```bash
# Read the file at the path and line referenced
```

### 3b. Determine if the finding is valid

Check whether:
- The code/doc actually has the issue described
- The suggestion is applicable in ADEPT's architecture context
- The finding conflicts with other project conventions (check CLAUDE.md, CODE_HYGIENE.md)
- The finding is a false positive (reviewer misunderstood the pattern)

### 3c. Determine resolution type

| Resolution | When to Use |
|-----------|-------------|
| **FIX** | Finding is valid and fixable in this PR |
| **ACKNOWLEDGE** | Finding is valid but intentional design choice — explain why |
| **DEFER** | Finding is valid but out of scope for this PR — create issue/backlog |
| **FALSE_POSITIVE** | Finding is incorrect given ADEPT's architecture — explain why |

Report the analysis to the developer before making changes.

---

## Phase 4: Apply Fixes

For each finding classified as FIX:

1. Read the affected file
2. Apply the minimal edit to resolve the finding
3. Verify the fix doesn't break anything else in the same file
4. Stage the file

Group related fixes into a single commit:

```bash
git add <fixed-files>
git commit -m "$(cat <<'EOF'
fix(<scope>): address PR #<N> review findings

<what was fixed and why>

Findings addressed:
- <path:line> — <finding summary> (<category>)
- <path:line> — <finding summary> (<category>)

Related documentation (this commit):
- <paths>

Related documentation (past 5 commits):
- <paths from git log -5 -- docs/>
EOF
)"
```

---

## Phase 5: Reply to Review Comments

After fixing, reply to each comment on GitHub to close the feedback loop:

### Reply templates by resolution type

**FIX** (code change made):
```
Addressed in `<commit_hash>`: <brief explanation of what was changed>.
```

**ACKNOWLEDGE** (intentional, no change):
```
Acknowledged — <why this is intentional>. <reference to convention or architecture doc if applicable>.
```

**DEFER** (out of scope):
```
Tracked as backlog item <issue_ref or doc_ref>. Out of scope for this PR — <brief reason>.
```

**FALSE_POSITIVE** (reviewer incorrect):
```
Not applicable in ADEPT context: <brief explanation>. <evidence, e.g., "No Jinja2 template rendering exists in the output pipeline">.
```

### Post replies using the GitHub API

```bash
# Reply to a specific review comment
gh api repos/{owner}/{repo}/pulls/$PR_NUMBER/comments/<comment_id>/replies \
  -f body="<resolution message>"
```

### Batch resolution summary (post after all individual replies)

```bash
gh pr comment $PR_NUMBER --body "$(cat <<'EOF'
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

---

## Phase 6: Push and Verify

Push the fix commit to trigger re-review:

```bash
git branch --show-current  # Safety check
git push origin <branch>
```

After push, check for re-review:
```bash
gh api repos/{owner}/{repo}/pulls/$PR_NUMBER/reviews --paginate \
  --jq '.[] | select(.submitted_at > "<push_timestamp>") | {user: .user.login, state: .state, submitted_at: .submitted_at}'
```

If new findings appear, return to Phase 1.

---

## Phase 7: Report

Present the developer with:

1. **Total findings**: N found across M files
2. **Disposition**: N fixed, N acknowledged, N deferred, N false positives
3. **Commits**: List of fix commits with hashes
4. **Remaining**: Any unresolved items or items needing developer decision
5. **Re-review status**: Whether automated reviewer has re-reviewed after push

---

## Common Patterns (ADEPT-Specific)

### Acronym Consistency

ADEPT projects have canonical expansions that reviewers frequently flag:
- **ADEPT**: Agentic Discovery and Exploration Platform for Tools
- **ASOPB**: Agentic Security & Operations Performance Benchmark
- **ASPI**: Agentic Security Posture Index

When a reviewer flags acronym inconsistency, search broadly:
```bash
grep -rniE "Agentic (Safety|Software|System|Stack|Automated).*(Operations|Security|Operational)" \
  docs/ examples/ src/ CLAUDE*.md --include="*.md" --include="*.py" --include="*.yaml" | head -30
```

### Threshold Consistency

Release gate thresholds must match `docs/development/VERSIONING_AND_RELEASE_CONVENTIONS.md` Section 8:
- Pipeline ASPI >= 95 (publish gate, blocking)
- Full ASPI (advisory only, not blocking)
- CI merge gate (ASPI >= 90)

### Pass Count Consistency

Scanner pass count references:
- Current implementation: 7 passes (P0, P1, P1.5, P2, P3, P4, P5)
- Whitepaper/research: may reference aspirational 10-pass (includes planned passes)
- Public documentation should match current implementation

### Internal Path References

Files excluded by `.publish-exclude` must not be referenced from public-site docs:
```bash
# Check if a referenced path survives staging
grep "<path>" .publish-exclude
```

### Workflow Permissions

GitHub Actions permissions should follow least-privilege:
- `peaceiris/actions-gh-pages@v4`: only needs `contents: write`
- `actions/deploy-pages`: needs `pages: write` + `id-token: write`
- Never grant permissions beyond what the specific action requires

---

## Multi-Reviewer Handling

When multiple reviewers have commented (e.g., Copilot + human reviewer):

1. **Prioritize human reviewer findings** — they have project context
2. **Cross-reference automated findings** — if both flag the same issue, it's likely real
3. **Automated reviewer false positive rate** — Copilot flags ~30-40% false positives on doc-heavy PRs
4. **Reply to each reviewer separately** — don't batch different reviewers' threads

---

## Quick Reference: gh api Patterns

```bash
# Owner/repo detection
REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner')

# All review comments (top-level only, excludes replies)
gh api repos/$REPO/pulls/$PR_NUMBER/comments --paginate \
  --jq '.[] | select(.in_reply_to_id == null) | {id, path, body: .body[:200]}'

# Check which comments already have replies
REPLIED=$(gh api repos/$REPO/pulls/$PR_NUMBER/comments --paginate \
  --jq '[.[] | select(.in_reply_to_id != null)] | .[].in_reply_to_id' | sort -u)

# Post reply to a comment
gh api repos/$REPO/pulls/$PR_NUMBER/comments/<ID>/replies -f body="..."

# Post PR-level comment (summary)
gh pr comment $PR_NUMBER --body "..."

# Check CI status
gh pr view $PR_NUMBER --json statusCheckRollup \
  --jq '.statusCheckRollup[] | {name: .name, conclusion: .conclusion}'

# Get latest commit hash for references
COMMIT=$(git rev-parse --short HEAD)
```
