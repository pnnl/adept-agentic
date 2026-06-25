---
name: pre-push-review
description: Semantic self-review of staged/committed changes before push. Runs 5 targeted audits to catch pattern inconsistency, dead code, doc-code divergence, Helm template logic gaps, and unreachable code paths. Reduces Copilot review from 4+ rounds to 0-1.
disable-model-invocation: true
allowed-tools: Bash(git * | grep * | find * | ruff * | vulture * | helm *) Read Glob Grep
---

You are performing a semantic pre-push review of ADEPT code changes. Your goal is to catch issues that static linters miss but Copilot reviewers would flag.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

## Input

Optional focus area argument: `/pre-push-review [focus]`
- No argument: run all 5 audits
- `pydantic`: focus on pattern consistency for Pydantic models
- `helm`: focus on Helm template logic
- `docs`: focus on doc-code divergence
- `dead-code`: focus on dead code and stale references
- `surface`: focus on interaction surface analysis

## Step 0: Ensure lint-tools image exists

```bash
# Build lint-tools image if missing (fast no-op if already built)
docker images agentic-framework-lint-tools:latest --format "{{.ID}}" | grep -q . || make build-lint-tools
```

If the image does not exist, build it before proceeding. This is required for `make lint-dead-code` (Docker-based vulture).

## Step 1: Identify the change set

```bash
# Determine what to review
git diff --cached --name-only 2>/dev/null || git diff --name-only HEAD~1..HEAD
```

If no staged changes and no recent commit, tell the developer:
**"No changes detected. Stage your changes or specify a commit range."**

Store the list of changed files for use in subsequent audits.

## Step 2: Run static analysis first (Layer 1 gate)

```bash
# Quick mechanical checks — these should already pass before this skill runs
# Use Docker-based lint for reproducibility (pinned versions)
make lint-dead-code 2>&1 | tail -30

# Ruff check on changed files only (host or Docker)
ruff check --target-version py311 $(git diff --cached --name-only 2>/dev/null | grep '\.py$' | tr '\n' ' ')
```

If ruff finds violations, report them and ask whether to continue with semantic review or fix first.
Note: `make lint-dead-code` is advisory (exit code != 0 is expected when findings exist). Only new dead code introduced by the current changeset is actionable.

## Audit 1: Pattern Consistency

For each changed Python file:

1. Identify structural patterns shared across the file or module:
   - Pydantic BaseModel subclasses: do ALL have `model_config = ConfigDict(extra="forbid")`?
   - FastAPI router functions: do ALL use consistent response models?
   - MCP tool registrations: do ALL follow `@mcp.tool()` + Pydantic input schema?

2. Grep for the pattern across ALL instances in the file (not just changed lines):
   ```bash
   grep -n "class.*BaseModel" <file>
   grep -n "model_config" <file>
   ```

3. Report any instance that LACKS the pattern applied to its siblings.

**Output format:**
```
AUDIT 1 - Pattern Consistency
  [PASS] All 4 BaseModel classes in llm_config.py have extra="forbid"
  [FAIL] RetryConfig (line 43) missing model_config = ConfigDict(extra="forbid")
         Other classes in file have it: LLMYamlConfig (L12), ProviderConfig (L28), PurposeConfig (L35)
```

## Audit 2: Dead Code / Stale References

For each NEW constant, function, or class in the diff:

1. Grep for usage across the entire codebase:
   ```bash
   grep -rn "<identifier>" src/ --include="*.py" | grep -v "def <identifier>\|class <identifier>"
   ```

2. Flag module-level definitions with zero callers outside their own file.

3. Cross-reference: if a doc or comment says "default: X" or "calls Y", verify X is read or Y is called:
   ```bash
   grep -rn "<claimed_default>" src/ --include="*.py"
   ```

**Output format:**
```
AUDIT 2 - Dead Code / Stale References
  [PASS] resolve_credentials() called from 3 locations
  [FAIL] DEFAULT_CONFIG_PATH defined at line 31 but never referenced in load() or any caller
         Grep result: 0 hits outside definition
```

## Audit 3: Doc-Code Divergence

For each changed `.py` file:

1. Find related documentation:
   ```bash
   grep -rln "<module_name>\|<class_name>" docs/ config/ examples/ --include="*.md" --include="*.yaml" --include="*.example"
   ```

2. For each related doc, verify claims match code:
   - "default: X" claims match actual default values
   - "calls Y" claims match actual call graph
   - "returns Z" claims match actual return type

For each changed doc/example file:

1. Verify code references are accurate:
   ```bash
   grep -n "line [0-9]" <doc_file>  # Check line number references still valid
   ```

**Output format:**
```
AUDIT 3 - Doc-Code Divergence
  [PASS] llm.yaml.example accurately describes LLM_CONFIG_PATH as opt-in
  [FAIL] config/llm.yaml.example line 24 claims "default: config/llm.yaml"
         but load() has no default path — it's strictly opt-in via env var
```

## Audit 4: Helm Template Logic (if applicable)

Skip if no Helm chart files changed. Otherwise:

1. Run template validation:
   ```bash
   helm lint infra/helm/agentic-framework --set llmConfig.enabled=true --set llmConfig.configMapName=test-config 2>&1
   helm lint infra/helm/adept-local --set llmConfig.enabled=true --set llmConfig.configMapName=test-config 2>&1
   ```

2. For each `{{- if }}` block in changed templates:
   - Verify the matching `{{- end }}` covers all conditional resources
   - Check that arrays/volumeMounts dependent on a flag are inside the conditional

3. Template with flags disabled — verify no null/empty arrays render:
   ```bash
   helm template infra/helm/agentic-framework --set llmConfig.enabled=false | grep -A2 "volumeMounts\|volumes"
   ```

**Output format:**
```
AUDIT 4 - Helm Template Logic
  [PASS] volumeMounts conditional on llmConfig.enabled
  [FAIL] orchestration_service volumeMounts renders unconditionally even when llmConfig.enabled=false
```

## Audit 5: Interaction Surface

For each new function, parameter, or env var in the diff:

1. Trace callers to identify behavior change propagation:
   ```bash
   grep -rn "<new_function>" src/ --include="*.py"
   ```

2. Flag env var precedence issues:
   - If a new env var overrides YAML config, is precedence documented?
   - If config mode changes meaning of an env var, is that called out?

3. Check for unreachable code paths:
   - New code path A that is never called from existing callers
   - Feature flag required but not set in any deployment config

**Output format:**
```
AUDIT 5 - Interaction Surface
  [PASS] get_credentials_for_purpose() called from both _call_litellm and get_langchain_chat_model
  [FAIL] _resolve_provider() introduced but never called from any production path
         Only callers: test files (51 references)
```

## Step 3: Summary

After all audits, produce a summary:

```
PRE-PUSH REVIEW SUMMARY
========================
Audit 1 (Pattern Consistency):  X findings
Audit 2 (Dead Code):            X findings
Audit 3 (Doc-Code Divergence):  X findings
Audit 4 (Helm Templates):       X findings (or SKIPPED)
Audit 5 (Interaction Surface):  X findings

TOTAL FINDINGS: X
RECOMMENDATION: [PUSH / FIX FIRST / DISCUSS]
```

- 0 findings: PUSH
- 1-3 minor findings: PUSH (note findings for PR description)
- Any FAIL on Audit 2 or 5: FIX FIRST (dead code or unreachable paths are high-confidence bugs)
- Audit 1 or 3 findings: Developer judgment (may be intentional)

## Relationship to Other Skills

- Run AFTER: `/audit-hygiene` (code hygiene checklist)
- Run BEFORE: `git push` and `/prepare-pr`
- Invoked BY: `/close-task` Phase 5.5 (Semantic Self-Review)
- Complements: `make lint-host` (Layer 1 mechanical checks)
