---
name: prepare-commit
description: Build a Conventional Commit message with Related Documentation footer chains. Use after all docs are updated, when ready to commit.
disable-model-invocation: true
allowed-tools: Bash(git *) Read Glob Grep
---

You are assisting an ADEPT developer with preparing a commit message.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

## Step 1: Read the commit conventions

Read `docs/development/CODE_HYGIENE.md` Section 4 (Commit Strategy) to understand Conventional Commits format, scope conventions, the Related Documentation footer chain, AI attribution policy, and what not to commit.

## Step 2: Verify test evidence exists for affected code paths

**MANDATORY GATE — do not proceed to Step 3 without passing this check.**

Identify changed source files:
```bash
git diff --cached --name-only -- 'src/' 'examples/'
# If nothing staged yet, check unstaged:
git diff --name-only -- 'src/' 'examples/'
```

If ANY files under `src/` or `examples/` are present, verify timestamped test logs exist that are NEWER than the source changes:

```bash
# Get most recent source file modification time
NEWEST_SRC=$(stat --format='%Y' $(git diff --cached --name-only -- 'src/' 'examples/' | head -1))

# Find test logs from today
ls -t logs/*_$(date +%Y%m%d)*.log 2>/dev/null | head -10

# Compare timestamps
for log in $(ls -t logs/*_$(date +%Y%m%d)*.log 2>/dev/null | head -5); do
  LOG_TIME=$(stat --format='%Y' "$log")
  if [ "$LOG_TIME" -gt "$NEWEST_SRC" ]; then
    echo "VALID: $log (newer than source changes)"
  else
    echo "STALE: $log (older than source changes)"
  fi
done
```

Map changed source paths to required test tiers using the table from `/validate-tests`:

| Source path prefix | Required validation |
|--------------------|---------------------|
| `src/.../orchestration_service/` | `make validate-response-api-tool-calls` or `make validate-test-suite` |
| `src/.../agent_gateway/` | `make validate-service-health` |
| `src/.../mcp_server/` | `make validate-mcp-direct-health` |
| `src/.../scientific_workflow/` | `make validate-unit-contract-tests` + integration |
| `examples/adept_connectors/` | ALL 4 tiers (unit, integration, e2e, uat) |
| `examples/*_mcp_server/` | `make -C <server> test-unit test-integration` |
| `scripts/release/` | `make -C scripts/release redteam-quick` (if red-team changes) |

If test logs are MISSING or STALE for any affected path, tell the developer:

**"BLOCKED: No valid test evidence for changed code paths. Run the required validation targets before committing."**

Provide the exact commands needed. Do NOT proceed to Step 3 until valid evidence exists.

If ONLY `docs/`, `.claude/skills/`, or non-code files changed, skip this gate.

## Step 3: Check staged changes

Run:
```bash
git diff --cached --stat
git diff --cached --name-only
```

If nothing is staged, run `git diff --stat` and `git diff --name-only` instead, then ask the developer what files to stage.

## Step 3: Classify commit type and scope

**Type** (from Section 4.1): Determine the primary type based on the nature of the change:
- `feat` -- new feature or capability
- `fix` -- bug fix
- `docs` -- documentation-only change
- `build` -- build system or dependency change
- `test` -- test-only change
- `refactor` -- code restructuring without behavior change
- `ci` -- CI/CD pipeline change
- `chore` -- maintenance (lock files, etc.)

**Scope** (from Section 4.1 scope table): Derive from the primary file paths changed. Examples: `connectors`, `bio-tools`, `vfm`, `session-NNN`, `release`, `CLAUDE.md`, `onboarding`. For cross-component changes, use `+` separator (e.g., `biofoundation+framework`).

## Step 4: Draft the commit message

Structure per Section 4.2:

```
<type>(<scope>): <one-line summary, imperative mood, max 72 chars>

<2-5 line paragraph: WHAT changed and WHY>

<Optional: bulleted list of key changes grouped by component>

<Test evidence: N/N tests passed, tier breakdown if applicable>

Related documentation (this commit):
- <path/to/doc1.md>
- <path/to/doc2.md>

Related documentation (past 5 commits):
- <path/to/doc3.md> (<short-hash>)
- <path/to/doc4.md> (<short-hash>)
```

Generate "Related documentation (this commit)" from documentation files in the staged changes.

Generate "Related documentation (past 5 commits)" by running:
```bash
git log --oneline -5
```
Then for each commit, check which docs were modified:
```bash
git diff-tree --no-commit-id --name-only -r <hash> -- docs/
```

## Step 5: Validate against policies

**Section 4.5 -- AI Attribution Policy**: Verify the draft commit message contains NONE of the following:
- `Co-Authored-By:` trailers referencing any AI agent
- `AI-assisted:` or similar phrases
- References to Claude, Gemini, ChatGPT, Copilot, Cursor, or any other AI assistant

If any are found, remove them and note the removal.

**Section 4.6 -- Excluded files**: Check the staged files for:
- `.env` files with real secrets
- Credential files from `.env-keycloak-credentials-dir/`
- `logs/` files
- `__pycache__/` directories
- Large binary files

Warn the developer if any are staged.

## Step 6: Present the commit command

Present the complete `git commit` command using heredoc format:

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <summary>

<body>

Related documentation (this commit):
- <paths>

Related documentation (past 5 commits):
- <paths>
EOF
)"
```

Remind the developer to push to origin after committing (Section 1.5):
```bash
git push origin <branch>
# Optional: push to personal fork (e.g., git push paul-origin <branch>)
```

Do not execute the commit command. Present it for the developer to review and run.
