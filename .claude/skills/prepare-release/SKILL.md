---
name: prepare-release
description: Before publish — ASOPB scan, staging, dry-run, publish gate (NEVER executes publish)
disable-model-invocation: true
allowed-tools: Bash(make stage*) Bash(make docker-scan*) Bash(make docker-push-ghcr) Bash(make publish-dry*) Bash(python3 scripts/release/*) Bash(docker logs*) Bash(docker ps*) Bash(docker images*) Bash(git *) Bash(ls *) Bash(cat logs/*) Read Write Edit Glob Grep
---

You are assisting an ADEPT developer with the pre-release verification workflow. This skill walks through the full ASOPB release gate process.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

CRITICAL: This skill NEVER executes the actual publish step. Only the developer can trigger `make publish` or `twine upload`. The skill stops at dry-run verification.

## Pre-Requisites

Before starting, verify:
- Working tree is clean (`git status` shows no uncommitted changes)
- You are on the correct release branch (see Branch Strategy below)
- Docker is running and the `adept-release-scanner` image is built

## Branch Strategy for Releases

ADEPT uses a **phase-based branching model** with squash-merge to main:

```
main ─────────────────●───────────────────●──────────────
                      ↑ squash-merge       ↑ squash-merge
FY26Q4 ──────────────┘                    │
FY26Q4-phase1 ────────────────────────────┘
FY26Q4-phase2 ─── ... (future)
```

**Release sequence (execute in order)**:

1. **Version bump** on the parent feature branch (e.g., `FY26Q4`):
   - Update 3 touchpoints to CalVer `v1.0.YYYYMMDD`:
     - `pyproject.toml` (main package)
     - `examples/adept_asopb/pyproject.toml` (ASOPB package)
     - `src/agentic_framework_sdk/__init__.py` (`__version__` string)
   - Regenerate lock file: `uv lock`
   - Commit: `chore(release): bump version to v1.0.YYYYMMDD`

2. **Create the next phase branch** off the parent tip BEFORE merging:
   ```bash
   git checkout feature-platform-optimizations-FY26Q4
   git checkout -b feature-platform-optimizations-FY26Q4-phase1
   git push -u origin feature-platform-optimizations-FY26Q4-phase1
   ```
   This preserves full commit lineage for the team.

3. **Squash-merge to main** via PR (developer approves and merges):
   - PR title: `release(v1.0.YYYYMMDD): <summary of quarter's work>`
   - PR body: covers all work since last squash-merge to main
   - NEVER execute `gh pr merge` yourself — developer approves

4. **Forward-merge main into phase branch** (updates merge-base):
   ```bash
   git checkout feature-platform-optimizations-FY26Q4-phase1
   git merge main -m "chore: sync with main after v1.0.YYYYMMDD release"
   git push origin feature-platform-optimizations-FY26Q4-phase1
   ```
   This ensures future PRs from phase1 to main show ONLY the delta (new work), not previously-merged content.

5. **Team develops on phase branch** — when ready, repeat from step 1.

**Key rules**:
- NEVER rebase feature branches onto main (destroys history)
- ALWAYS forward-merge (preserves all original SHAs)
- Squash-merge is ONLY for feature-branch → main (public release flattening)
- Child → parent PRs use fast-forward merge (preserves individual commits)

## Phase 1: Pre-Flight Checks

1. Verify branch and clean state:
```bash
git branch --show-current
git status --short
```

2. Verify version parity across all 3 touchpoints:
```bash
echo "=== Version Parity Check ==="
grep '^version' pyproject.toml
grep '^version' examples/adept_asopb/pyproject.toml
grep '__version__' src/agentic_framework_sdk/__init__.py
```
All 3 MUST show the same YYYYMMDD date. If any differ, bump them before proceeding:
- `pyproject.toml` — main package (agentic_framework_pkg)
- `examples/adept_asopb/pyproject.toml` — ASOPB package
- `src/agentic_framework_sdk/__init__.py` — SDK `__version__` string

After bumping, regenerate the lock file: `uv lock`

3. Verify scanner image exists:
```bash
docker images adept-release-scanner --format "{{.Tag}} {{.CreatedAt}}"
```

4. Regenerate OpenAPI specs from live services:
```bash
python3 docs/api/generate_openapi.py
```
This fetches the current API surface from the running agent_gateway and orchestration_service, merges with hand-authored metadata, scans for prohibited patterns, and writes `docs/api/openapi.json` and `docs/api/openapi-admin.json`. If the stack is not running, start it first (`make start`). If specs changed, commit them before staging.

GATE CHECK: All four checks must pass before proceeding.

## Phase 2: Stage Release Tree

Stage the release artifacts using the `.publish-exclude` filter:

```bash
make -C scripts/release stage
```

For staging from working tree (includes uncommitted changes, useful for pre-commit validation):
```bash
make -C scripts/release stage-worktree
```

This runs rsync with 270+ exclusion rules, outputting to `/tmp/adept-release-stage-YYYYMMDD`.

Verify staging results:
```bash
STAGE_DIR=$(ls -td /tmp/adept-release-stage-* | head -1)
ls "$STAGE_DIR/" | head -20
find "$STAGE_DIR" -type f | wc -l
```

Expected: 1000-1500 files (varies by release).

**Important**: All release Makefile targets live in `scripts/release/Makefile`, not the root Makefile. Always use `make -C scripts/release <target>` or `cd scripts/release && make <target>`.

## Phase 2b: Validate GitHub Pages Content

Verify the Pages documentation site builds cleanly from the staged tree:

```bash
# 1. Confirm docs/public-site/ is present in staged tree
ls /tmp/adept-release-stage/docs/public-site/mkdocs.yml

# 2. Run prohibited-pattern scan on Pages content
if grep -rniE -f scripts/release/prohibited_patterns.txt /tmp/adept-release-stage/docs/public-site/docs/; then
  echo "FAIL: Prohibited patterns in Pages content"
else
  echo "PASS: No prohibited patterns"
fi

# 3. Verify nav completeness (all referenced .md files exist)
grep -oP '(?<=: ).*\.md' /tmp/adept-release-stage/docs/public-site/mkdocs.yml | while read f; do
  if [ ! -f "/tmp/adept-release-stage/docs/public-site/docs/$f" ]; then
    echo "MISSING: docs/public-site/docs/$f"
  fi
done

# 4. Test MkDocs build in isolated venv (matches CI runner conditions)
#    CRITICAL: Must use a fresh venv to catch dependency incompatibilities
#    that host-cached packages would mask. The CI runner installs fresh.
rm -rf /tmp/pages-venv
python3 -m venv /tmp/pages-venv
/tmp/pages-venv/bin/pip install -q -r /tmp/adept-release-stage/docs/public-site/requirements.txt
cd /tmp/adept-release-stage/docs/public-site && /tmp/pages-venv/bin/mkdocs build --strict --site-dir /tmp/pages-build-test 2>&1
rm -rf /tmp/pages-venv
```

GATE CHECK: All four checks must pass. If the MkDocs build fails (broken links, missing nav files, or dependency incompatibilities), fix in the source repo and re-stage.

**Why this matters**: After publishing, `deploy-docs.yml` triggers on the public repo. If Pages content has prohibited patterns or broken links, the workflow will either deploy sensitive content or fail the strict build — both unacceptable. The fresh venv ensures dependency resolution matches the CI runner (which installs from scratch), preventing cases where a host-cached compatible Pygments masks an incompatibility that only surfaces in CI.

---

## Phase 3: Run ASOPB 7-Pass Scan

Run the full security scan pipeline inside the Docker scanner:

```bash
make -C scripts/release docker-scan-staged
```

This runs:
- Pass 0: Regex pattern scan (credentials, internal infra)
- Pass 1: detect-secrets (Secret Keyword, API keys)
- Pass 1.5: TruffleHog deep secrets (API-verified)
- Pass 2: NER + PII (DeBERTa person names, passwords, emails)
- Pass 3: Toxicity (Detoxify content safety)
- Pass 4: Grype CVE scan (supply-chain vulnerabilities)
- Pass 5 (optional): Promptfoo red-team (requires `--promptfoo-target`)

**Promptfoo distinction — CI vs pre-release**:
- In CI (`.github/workflows/asopb-pre-release-scan.yml`): advisory only (`continue-on-error: true`), expensive due to backend LLM calls, non-blocking
- In pre-release (this skill): REQUIRED gate step — invoke `/promptfoo-check` before publish approval
- Reason: Promptfoo probes a live LLM endpoint (Azure, Bedrock, or ADEPT), so it cannot run in air-gapped CI without significant cost/latency

Monitor progress:
```bash
docker ps --filter name=release-scanner
docker logs adept-release-scanner --tail 20 --follow
```

Wait for completion. Output lands in `logs/scan-staged-YYYYMMDD-HHMM/`.

## Phase 4: Analyze Findings

Run the codified analysis suite on the scan output. These scripts (in `scripts/release/`) are the proper tooling for release analysis — not ad-hoc one-liners:

```bash
# Find the latest scan directory
SCAN_DIR=$(ls -td logs/scan-staged-* | head -1)
echo "Scan directory: $SCAN_DIR"

# 1. Full analysis with FP classification simulation
#    Shows: per-domain breakdown, FP suppression rates, simulated ASPI
python3 scripts/release/analyze_findings.py "$SCAN_DIR" --simulate

# 2. Actionable findings only (everything that survives FP filtering)
#    Use this to identify what ACTUALLY needs fixing before publish
python3 scripts/release/analyze_findings.py "$SCAN_DIR" --actionable-only

# 3. JSON output for downstream tooling / CI integration
python3 scripts/release/analyze_findings.py "$SCAN_DIR" --format json
```

Or equivalently via Makefile targets (from `scripts/release/`):
```bash
make -C scripts/release scan-analyze SCAN_DIR="$SCAN_DIR"
make -C scripts/release scan-actionable SCAN_DIR="$SCAN_DIR"
```

Review the output:
- Total findings vs. actionable findings (FP suppression rate)
- Per-domain score simulation (D5, D8, D7)
- Classification of NER/PII findings into buckets (real_pii, unverified_credentials, informational)
- Secrets FP rate (docs, placeholders, Helm charts)
- Toxicity FP rate (DevOps vocabulary, IaC commands)

## Phase 4b: T2 Token Budget Gate (Full ASOPB Evaluation Only)

If running the full 8-domain ASOPB evaluation with LLM scoring (not required for Pipeline ASPI release gate), estimate the T2 LLM token cost before proceeding:

```bash
# Estimate token budget (dry-run, no LLM calls)
python3 -c "
from asopb.config import EvalConfig
from asopb.evaluator import Evaluator
config = EvalConfig(skip_llm=False)
evaluator = Evaluator(config=config)
estimate = evaluator.estimate_t2_token_budget()
print(f'Estimated LLM calls:   {estimate[\"estimated_calls\"]}')
print(f'Estimated input tokens: {estimate[\"estimated_input_tokens\"]:,}')
print(f'Estimated output tokens: {estimate[\"estimated_output_tokens\"]:,}')
print(f'Estimated total:        {estimate[\"estimated_total_tokens\"]:,}')
for d, info in estimate['per_domain'].items():
    print(f'  {d}: {info[\"controls_t2_eligible\"]} eligible controls, ~{info[\"input_tokens\"]:,} input tokens')
"
```

Present the estimate to the developer with three options:
1. **Proceed with full analysis** — run all T2 LLM calls (use `--token-budget-confirm`)
2. **Enforce cap** — set `--token-budget <N>` to skip LLM if estimated exceeds budget
3. **Skip LLM** — run deterministic-only with `--skip-llm` (fastest, no cost)

GATE CHECK: Developer must explicitly choose an option before proceeding with LLM-enabled evaluation. This prevents unexpected cost from large codebases.

For the release gate (Pipeline ASPI), LLM scoring is NOT needed — skip this phase.

## Phase 5: Gate Decision

**Release Gate Policy** (see `docs/development/VERSIONING_AND_RELEASE_CONVENTIONS.md` Section 8):

| Gate | Metric | Threshold | Blocking? |
|------|--------|-----------|-----------|
| Release | Pipeline ASPI (staged, D5/D7/D8) | >= 95 | YES |
| Advisory | Full 8-domain ASPI (evaluator) | Report only | NO |

The Pipeline ASPI is the release gate. The full evaluator score is informational — it reports codebase health for future investment but does NOT block publishing.

Run the gate check:

```bash
python3 scripts/release/gate_check.py "$SCAN_DIR" --no-report --verbose
```

Or equivalently:
```bash
python3 scripts/release/compute_aspi.py "$SCAN_DIR" --no-report --gate 95
```

### If PASS (Pipeline ASPI >= 95, S4 Hardened):

Proceed to dry-run:
```bash
make -C scripts/release dry-run VERSION=v1.0.YYYYMMDD
```

Report results to developer. The developer decides whether to execute `make -C scripts/release publish VERSION=v1.0.YYYYMMDD`.

### If FAIL (Pipeline ASPI < 95):

1. Show the domain breakdown and gap to gate
2. Run `python3 scripts/release/analyze_findings.py "$SCAN_DIR" --actionable-only` to identify what needs fixing
3. Common remediation paths:
   - D5 low: Check for real credentials in staged files, expand `.publish-exclude`
   - D8 low: Check TruffleHog verified secrets (catastrophic), remove or rotate
   - D7 low: Check toxicity content for genuine harmful material
4. After fixes, re-stage and re-scan: go back to Phase 2

## Phase 5b: Push Scanner Image to GHCR (if Dockerfile changed)

If the scanner Dockerfile or ML model dependencies changed since last push, update GHCR so CI Phase 2 jobs (ml-fast, grype-scan) run instead of skipping:

```bash
make -C scripts/release docker-push-ghcr
```

This pushes two tags: `ghcr.io/<org>/adept-release-scanner:latest` (mutable, CI pulls this) and `:YYYYMMDD` (immutable audit reference). Authenticates via `gh auth token`. Requires `write:packages` scope on the GitHub PAT.

After push, verify the package is linked to the repo (required for CI pull via GITHUB_TOKEN):

```bash
gh api orgs/<org>/packages/container/adept-release-scanner --jq '.repository.full_name // "NOT LINKED"'
```

If output is "NOT LINKED" or errors with 404, this is the first push and you must link it:
1. Go to https://github.com/orgs/<org>/packages/container/package/adept-release-scanner/settings
2. Manage Actions access > Add Repository > `adept-agentic-framework-extended` (Read)
3. Re-run the check above to confirm linkage.

GATE CHECK: Verify the next push triggers Phase 2 CI jobs (not skipped).

NOTE — Repo-Agnostic Abstraction (#79): When ASOPB is extracted into a standalone
MCP tool/server, this Phase 5b must be parameterized for arbitrary target repositories:
- GHCR_REGISTRY, GHCR_IMAGE, and repo linkage are currently hard-coded to <org>/adept-*
- The MCP tool version should accept: org, repo, image_name, and PAT scope as inputs
- Package-to-repo linkage verification must work for any org/repo pair
- The /prepare-release skill will ship as a repo-agnostic template with the MCP server
- See: GitHub issue #79, internal task #156

## Phase 5c: Update Tracking Documentation

Before proceeding to dry-run, ensure the three tracking documents reflect the release state. These are user-facing docs that ship in the published tree.

### Required Updates

1. **`docs/CHANGELOG.md`** — Add a new top-level entry for this release:
   - Date, branch, GitHub issues, PR number, type
   - Summary (1-2 sentences)
   - Key Changes (bullet list of what shipped)
   - Test Evidence (table of suite results)
   - Key Files (paths to primary implementation files)

2. **`docs/ROADMAP.md`** — Update three sections:
   - **FY26Q\* Active Work**: Move completed items to "Closed This Quarter" table
   - **Closed This Quarter**: Add rows for issues closed in this release
   - **Recently Completed**: Add a summary block at the top (status, branch, issues, key deliverables)

3. **`docs/KNOWN_ISSUES.md`** — Update as applicable:
   - **Working Features**: Add newly shipped capabilities
   - **Partial/In-Progress**: Update status of items that progressed (mark DONE if resolved)
   - **Known Issues**: Remove resolved issues, add new ones discovered during release prep
   - **ASPI score**: Update the "Current ASPI" reference to match the gate check result

### Checklist

```bash
# Verify all three docs are updated
grep "Last Updated" docs/CHANGELOG.md docs/ROADMAP.md docs/KNOWN_ISSUES.md
# All should show today's date or the release date

# Verify CHANGELOG has the new release entry at the top
head -20 docs/CHANGELOG.md

# Verify KNOWN_ISSUES ASPI score matches gate result
grep -i "ASPI" docs/KNOWN_ISSUES.md | grep -i "current"
```

GATE CHECK: All three documents updated with current release state. Commit these changes before proceeding to dry-run.

---

## Phase 6: Dry-Run Verification (PASS only)

```bash
make -C scripts/release dry-run VERSION=v1.0.YYYYMMDD
```

This validates:
- Package builds successfully
- No missing dependencies
- Metadata is correct
- rsync to public repo would succeed (without actually pushing)

STOP HERE. Report results to developer. NEVER execute `make -C scripts/release publish`.

## Release Candidate (RC) Process

Release candidates allow iterative validation of the published tree before the final GA release. Each RC publishes to the public repo with a version tag suffix (e.g., `v1.0.20260601-rc7`).

### When to use RCs

- After adding new content categories (skills, docs, examples) to the publish set
- After modifying `.publish-exclude` rules
- After creating or updating public variants (`.public.md` files)
- Before final squash-merge to main (validates the staged tree matches expectations)

### RC Workflow

```bash
# 1. Stage from working tree (includes uncommitted changes for pre-commit testing)
make -C scripts/release stage-worktree

# 2. Verify staged content (spot-check new additions)
STAGE_DIR=$(ls -td /tmp/adept-release-stage-* | head -1)
ls "$STAGE_DIR/.claude/skills/"         # Skills present?
find "$STAGE_DIR" -name "*.public.md"   # Public variants waiting for swap?

# 3. Dry-run publish (simulates full pipeline including public-variant swap)
scripts/release/publish-to-public.sh --version v1.0.YYYYMMDD-rcN --dry-run \
  --public-repo https://github.com/<org>/<public-repo>.git

# 4. Inspect dry-run output
cd /tmp/publish-public-*/public
ls .claude/skills/                     # All SKILL.md (no .public.md after swap)

# 5. Execute publish (developer decision)
scripts/release/publish-to-public.sh --version v1.0.YYYYMMDD-rcN \
  --public-repo https://github.com/<org>/<public-repo>.git
```

**IMPORTANT**: Always use `--public-repo https://...` (HTTPS) not the SSH default (`git@github.com:...`). HTTPS uses the `gh` CLI token for authentication which is universally available; SSH requires key setup that may not be present on all development hosts.

### RC vs GA Distinction

| Aspect | Release Candidate | General Availability |
|--------|-------------------|---------------------|
| Version tag | `v1.0.YYYYMMDD-rcN` | `v1.0.YYYYMMDD` |
| ASOPB scan | Optional (gate already passed) | Required (full 7-pass) |
| Purpose | Validate staged tree content | Production release |
| Publish frequency | Multiple per session as needed | Once per release cycle |
| Rollback | Just re-publish from prior RC | Requires coordination |

### Common RC Validation Checks

After each RC publish, verify on the public repo:
1. New files appear (e.g., `.claude/skills/` directory)
2. Public variants were swapped (only `SKILL.md`, no `.public.md`)
3. Internal-only content is absent (Category C skills, settings, session reports)
4. No prohibited patterns in newly added files
5. GitHub Pages build still succeeds (if `docs/public-site/` changed)

---

## Public Release Notes Guidelines

When creating GitHub Release notes on the **public** repo (pnnl/adept-agentic), the following information MUST NOT appear:

- File counts (published or excluded) — reveals internal codebase size
- ASPI scores or security scan statistics — internal security posture details
- Exclusion rule counts or .publish-exclude details
- References to internal GitHub org (<org>)
- Any mention of "sanitization", "content filter", or "public-variant swap"
- Scanner findings counts (HIGH/LOW/etc.)
- Internal commit hashes or branch names
- References to internal documentation or session reports

**Allowed in public release notes**:
- Feature highlights and capabilities
- Links to public documentation (docs/, examples/)
- Known limitations relevant to external users
- Pre-release/GA status indicators
- Public repo URLs (pnnl/adept-agentic)

**Internal release notes** (on <org>/<repo> issues and team emails) may contain all details.

## Reference: Scoring Model

See **`docs/security/ASPI_SCORING_REFERENCE.md`** for the complete ASPI scoring reference, including Pipeline ASPI vs Full ASPI distinctions, all gate thresholds, and the FP suppression stack.

Key points for release:
- **Pipeline ASPI >= 95** is the release gate (blocking)
- **Full ASPI** (8-domain evaluator) is advisory only
- Grype-only scans (CI Phase 2) produce lower scores because they lack allowlist suppression
- Formula: `ASPI = D5 * 0.4 + D8 * 0.4 + D7 * 0.2`
- Stages: S4>=90, S3>=70, S2>=50, S1<50

## Reference: Key Files

- **Makefile**: `scripts/release/Makefile` — All release targets (stage, scan, dry-run, publish, test, GHCR push). Invoke with `make -C scripts/release <target>`.
- Pipeline: `scripts/release/scan_pipeline.py`
- Scoring: `scripts/release/scan_pipeline.py` (ASPOBScore class)
- FP patterns: `scripts/release/fp_patterns.py`
- Analysis: `scripts/release/analyze_findings.py`
- Gate check: `scripts/release/gate_check.py`
- ASPI compute: `scripts/release/compute_aspi.py`
- Grype CVE: `scripts/release/scan_grype.py`
- Dead imports: `scripts/release/scan_dead_imports.py`
- Compensating controls: `scripts/release/compensating_controls.py`
- Publisher: `scripts/release/publish-to-public.sh`
- Exclusions: `.publish-exclude`

## Reference: Supplemental Scanner Tools

### Dead Import Cross-Reference Scanner

Detects imports referencing symbols that no longer exist in the source tree (beyond what ruff F401 catches). Use during pre-release to identify stale test imports that may mask broken code paths.

```bash
# Run on tests/ directory (most common)
cd scripts/release && python3 scan_dead_imports.py --target ../../tests/ --src ../../src/ --format json

# Gate mode (exit 1 if DEAD imports found)
cd scripts/release && python3 scan_dead_imports.py --target ../../tests/ --src ../../src/ --gate

# Actionable only (hides FIXTURE and UNUSED_VALID)
cd scripts/release && python3 scan_dead_imports.py --target ../../tests/ --src ../../src/ --actionable-only
```

Classifications: DEAD (symbol gone), MOVED (exists elsewhere), FIXTURE (pytest), UNUSED_VALID (exists but unused).

### Allowlist Validator (Layer 2)

Validates that `.asopb-allowlist.yaml` has no structural errors. The allowlist provides category-level FP suppression via declarative YAML rules (type, file_patterns, pattern, min_score, max_entity_length).

```bash
cd scripts/release

# Validate allowlist structure
python3 -c "
import sys; sys.path.insert(0, '../../examples/adept_asopb/src')
from asopb.quality.allowlist import load_allowlist, validate_allowlist
from pathlib import Path
al = load_allowlist(Path('.asopb-allowlist.yaml'))
print(f'Allowlist: {al.total_rules} rules, hash={al.content_hash[:16]}..., version={al.schema_version}')
issues = validate_allowlist(al)
errors = [i for i in issues if i.severity == 'ERROR']
if errors:
    for e in errors: print(f'  ERROR [{e.category}:{e.rule_index}]: {e.message}')
    sys.exit(1)
print('Validation: PASS')
"

# Run scan with allowlist suppression
python3 scan_pipeline.py /tmp/adept-release-stage --passes all --allowlist .asopb-allowlist.yaml
```

Guide: `docs/guides/ALLOWLIST_SUPPRESSION_GUIDE.md`

### Compensating Controls Fingerprint Validator (Layer 4)

Validates integrity of false-positive suppressions. Detects stale suppressions where the underlying file changed (SHA-256 mismatch), entity moved, or file deleted.

```bash
cd scripts/release

# Validate all compensating controls against current codebase
python3 compensating_controls.py validate

# CI gate mode (exit 1 on stale/invalidated/expired)
python3 compensating_controls.py gate --fail-on stale,invalidated,expired

# List controls with current status
python3 compensating_controls.py list --format table

# Add new control (auto-computes file hash + fingerprint)
python3 compensating_controls.py add --domain D5 --file <path> --line 10-20 --entity <pattern> --justification "..."
```

Statuses: active, stale (file hash changed), invalidated (file/entity gone), expired (past expiration date).

### Badge Generation (Optional, post-gate)

After a successful gate pass, generate SVG badges for repository README or CI artifacts:

```bash
# Auto-discover latest scan output and generate badges
python3 scripts/release/generate_badges.py

# Explicit scan directory
python3 scripts/release/generate_badges.py logs/scan-staged-20260511-1418

# Manual score values
python3 scripts/release/generate_badges.py --pipeline-aspi 92.1 --full-aspi 87.3 --dast 84.6

# JSON format (for shields.io dynamic badges)
python3 scripts/release/generate_badges.py --format json --output-dir ./badges
```

Produces: `pipeline-aspi.svg`, `full-aspi.svg`, `dast.svg` in `/tmp/asopb-badges/`.
