---
name: asopb-evaluate
description: Run ASOPB evaluation with credential routing, build context sync, and baseline comparison
disable-model-invocation: true
allowed-tools: Bash(docker run*) Bash(docker build*) Bash(docker images*) Bash(docker ps*) Bash(rsync*) Bash(make *) Bash(source *) Bash(diff *) Bash(find *) Bash(ls *) Bash(cat logs/*) Bash(tail *) Bash(grep *) Bash(python3 *) Bash(git log*) Bash(git diff*) Bash(mkdir *) Bash(wc *) Read Write Edit Glob Grep
---

You are assisting an ADEPT developer with running ASOPB (Agentic Security and Operations
Performance Benchmark) evaluations. This skill handles credential routing, build context
synchronization, execution, analysis, and baseline comparison.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

## Overview

ASOPB evaluates repositories across 8 security domains (D1-D8) using three tiers:
- T1: Design/Scanner (deterministic pattern matching)
- T2: Implementation/LLM (LLM-graded evidence assessment)
- T3: Adversarial/Red-team (promptfoo results)

The composite score is ASPI (Agentic Security Posture Index, 0-100).

## Relationship to CI Pipeline

This full 8-domain evaluation (`/asopb-evaluate`) is distinct from the CI pipeline scans:

| Scan Mode | Scope | DevSecOps Categories | Score Type | Where |
|-----------|-------|---------------------|------------|-------|
| CI Phase 1 | SAST (regex only) | SAST | Pipeline ASPI (3 domains) | `.github/workflows/asopb-pre-release-scan.yml` |
| CI Phase 2 | SAST+SCA+DLP+DAST | SAST, SCA, DLP, DAST | Pipeline ASPI (3 domains) | Same workflow, advisory jobs |
| `/scan-release` | All 10 passes | SAST, SCA, DLP | Pipeline ASPI (3 domains) | Local, 30-75 min |
| `/asopb-evaluate` | 8 domains, 44 controls | Full DevSecOps | Full ASPI (8 domains) | Local, air-gapped container |

The full evaluation (this skill) includes LLM-as-judge scoring (T2) and integrates promptfoo red-team results (T3) to produce a comprehensive 8-domain score. The CI pipeline only produces a Pipeline ASPI (D5+D8+D7) since T2/T3 require live LLM calls.

---

## Phase 1: Pre-Flight Checks

### 1a. Verify scanner image exists

```bash
docker images adept-release-scanner --format "{{.Tag}} {{.CreatedAt}}" | head -5
```

If no image exists, ask the developer if they want to build one:
```bash
cd scripts/release && make docker-build
```

### 1b. Check build context freshness

```bash
diff <(find examples/adept_asopb/src/asopb -name "*.py" -exec md5sum {} \; | sort) \
     <(find scripts/release/asopb/src/asopb -name "*.py" -exec md5sum {} \; | sort) \
     2>/dev/null | head -20
```

If there are differences, the build context is stale:
```bash
rsync -av --delete examples/adept_asopb/src/asopb/ scripts/release/asopb/src/asopb/
find scripts/release/asopb/ -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
```

Then rebuild the image:
```bash
cd scripts/release && make docker-build
```

### 1c. Self-test (optional, recommended after rebuild)

```bash
docker run --rm --network=none --entrypoint python3 \
  adept-release-scanner:latest -m scanner_selftest
```

Expected: 33/33 PASS.

GATE CHECK: Image exists and self-test passes (if run).

---

## Phase 2: Configure Evaluation

### Evaluation Cube (3 Dimensions)

ASOPB evaluation has three independent dimensions. Ask the developer which combination they need:

1. **Target stage**: Pre-stage (source repo) vs Staged (release tree)
2. **Scoring mode**: Pipeline (D5/D7/D8, penalty) vs Full (8 domains, T1+T2+T3)
3. **Codebase**: ADEPT (`--profile adept`) vs Arbitrary (generic profile)

**The 2x2 matrix (most common — ADEPT codebase):**

| | Pipeline ASPI (D5/D7/D8, penalty) | Full ASPI (8 domains, T1+T2+T3) |
|--|------------------------------------|---------------------------------|
| **Pre-stage** (source repo) | Fast CI check (~5 min, no LLM) | Deep dev analysis (~15 min, LLM) |
| **Staged** (release tree) | Release gate (ASPI >= 95, blocking) | Advisory quality (non-blocking) |

Decision guide:
- Preparing a release? **Pipeline + Staged** (the release gate)
- Quick regression check? **Pipeline + Pre-stage** (no LLM cost)
- Deep security audit? **Full + Pre-stage** (T1+T2 per-domain breakdown)
- Post-gate confidence? **Full + Staged** (advisory, after pipeline passes)
- Scanning third-party code? Add `ASOPB_PROFILE=generic` or custom YAML path

### Parameters

Ask the developer for evaluation parameters. Use these defaults if not specified:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Target | Project root (pre-stage) | Path to scan |
| Model | `azure/o4-mini` | LLM model for T2 scoring |
| Domains | All (D1-D8) | Domain subset |
| Red-team | `scripts/release/tests/promptfoo_results/` | Promptfoo results dir |
| Skip LLM | No | Deterministic only |
| Skip analyzers | Yes (recommended) | Avoids TLS OOM on large repos |
| Disable analyzers | `tls` | TLS analyzer produces 15.4M noise findings |
| Baseline | Latest `logs/asopb-eval-*/report.json` | For comparison |

### Credential Routing

CRITICAL: The LLM model prefix determines which credentials to use:

| Model Prefix | Credential Source | Injection Method |
|-------------|------------------|------------------|
| `azure/*` | `.env` file | `--env-file .env` |
| `bedrock/*` | `setup-claude-bedrock.sh` | `-e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID"` etc. |
| (skip-llm) | None | `--network=none` is safe |

The `.env` file contains AWS credentials (AKIAW72...) that do NOT have Bedrock access.
Bedrock models MUST use credentials from `setup-claude-bedrock.sh` (AKIAXQXZ52...).

NEVER mix these — Azure models get `.env`, Bedrock models get shell-sourced credentials.

---

## Phase 3: Execute Evaluation

### Azure model (default):

```bash
mkdir -p logs/asopb-eval-$(date +%Y%m%d-%H%M) && \
nohup docker run --rm \
  -v $(pwd):/scan:ro \
  -v "$(pwd)/logs/asopb-eval-$(date +%Y%m%d-%H%M)":/output \
  -v "$(pwd)/scripts/release/tests/promptfoo_results:/redteam:ro" \
  --env-file .env \
  --entrypoint python3 \
  adept-release-scanner:latest \
  -m asopb.cli evaluate /scan --format json --output /output \
    --model "azure/o4-mini" \
    --skip-analyzers \
    --redteam-dir /redteam \
  > logs/asopb_eval_$(date +%Y%m%d_%H%M%S).log 2>&1 & echo "PID: $!"
```

### Bedrock model:

```bash
source setup-claude-bedrock.sh && \
mkdir -p logs/asopb-eval-bedrock-$(date +%Y%m%d-%H%M) && \
nohup docker run --rm \
  -v $(pwd):/scan:ro \
  -v "$(pwd)/logs/asopb-eval-bedrock-$(date +%Y%m%d-%H%M)":/output \
  -v "$(pwd)/scripts/release/tests/promptfoo_results:/redteam:ro" \
  -e AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  -e AWS_REGION_NAME="${AWS_REGION_NAME:-us-west-2}" \
  -e AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}" \
  --entrypoint python3 \
  adept-release-scanner:latest \
  -m asopb.cli evaluate /scan --format json --output /output \
    --model "bedrock/us.anthropic.claude-opus-4-20250514-v1:0" \
    --skip-analyzers \
    --redteam-dir /redteam \
  > logs/asopb_eval_bedrock_$(date +%Y%m%d_%H%M%S).log 2>&1 & echo "PID: $!"
```

### Domain subset:

Add `--domains D5,D7,D8` to either command above.

### Deterministic only (no LLM, no network):

```bash
docker run --rm --network=none \
  -v $(pwd):/scan:ro \
  -v "$(pwd)/logs/asopb-eval-deterministic":/output \
  --entrypoint python3 \
  adept-release-scanner:latest \
  -m asopb.cli evaluate /scan --format json --output /output --skip-llm --skip-analyzers
```

### New granular flags (after image rebuild with cli.py changes):

```bash
--disable-analyzers tls,bandit     # Skip specific analyzers
--only-analyzers semgrep,pip_audit # Whitelist analyzers
--disable-scanners codebase        # Skip specific scanners
--only-scanners federation,itot,supply_chain  # Whitelist scanners
```

---

## Phase 4: Monitor Progress

```bash
tail -f logs/asopb_eval_*.log
```

Key progress indicators:
- `[START] Evaluator.evaluate` — evaluation started
- `[DONE]  Evaluator.quick_scan` — all scanners complete
- `[DONE]  Evaluator._run_analyzers` — analyzers complete (skipped if --skip-analyzers)
- `Evaluating domains...` — LLM phase starting
- `[D5] T2 grading` — per-domain LLM calls
- ASPI score printed at end

Typical durations (pre-stage, 8 domains):
- Scanners: 7 min
- Analyzers: 56 min (47 min is TLS alone — skip it)
- LLM (azure/o4-mini): 10-15 min
- LLM (Bedrock Opus): 60-90 min
- Total (with --skip-analyzers): 17-22 min (o4-mini) or 67-97 min (Opus)

---

## Phase 5: Analyze Results

### 5a. Parse report

```bash
OUTPUT_DIR=$(ls -td logs/asopb-eval-* | head -1)
python3 -c "
import json, sys
r = json.load(open('$OUTPUT_DIR/report.json'))
print(f'ASPI: {r.get(\"aspi\", \"N/A\")}')
print(f'Duration: {r.get(\"duration_seconds\", 0):.0f}s')
print(f'LLM calls: {r.get(\"llm_calls\", 0)}')
print(f'Tokens: {r.get(\"total_tokens\", 0):,}')
print()
for k, v in r.get('domains', {}).items():
    score = v.get('domain_score', 0)
    t1 = v.get('t1_score', 0)
    t2 = v.get('t2_score', 0)
    t3 = v.get('t3_score', 0)
    print(f'  {k}: {score:5.1f}  [T1={t1:.1f}, T2={t2:.1f}, T3={t3:.1f}]')
"
```

### 5b. Compare against baseline

Find the most recent prior report:
```bash
BASELINE=$(ls -t logs/asopb-eval-*/report.json 2>/dev/null | sed -n '2p')
```

If a baseline exists, compare:
```bash
python3 -c "
import json
current = json.load(open('$OUTPUT_DIR/report.json'))
baseline = json.load(open('$BASELINE'))
print('Domain     Current  Baseline  Delta')
print('------     -------  --------  -----')
for k in sorted(current.get('domains', {}).keys()):
    c = current['domains'][k].get('domain_score', 0)
    b = baseline.get('domains', {}).get(k, {}).get('domain_score', 0)
    delta = c - b
    flag = ' ***' if abs(delta) > 2 else ''
    print(f'  {k}:    {c:5.1f}    {b:5.1f}    {delta:+.1f}{flag}')
c_aspi = current.get('aspi', 0)
b_aspi = baseline.get('aspi', 0)
print(f'  ASPI:  {c_aspi:5.1f}    {b_aspi:5.1f}    {c_aspi - b_aspi:+.1f}')
"
```

### 5c. Append to history (optional)

```bash
python3 -c "
import json, datetime
r = json.load(open('$OUTPUT_DIR/report.json'))
entry = {
    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
    'aspi': r.get('aspi'),
    'model': r.get('model', 'unknown'),
    'domains': {k: v.get('domain_score') for k, v in r.get('domains', {}).items()},
    'llm_calls': r.get('llm_calls', 0),
    'tokens': r.get('total_tokens', 0),
    'duration_seconds': r.get('duration_seconds', 0),
    'report_path': '$OUTPUT_DIR/report.json'
}
with open('logs/asopb-eval-history.jsonl', 'a') as f:
    f.write(json.dumps(entry) + '\n')
print('Appended to logs/asopb-eval-history.jsonl')
"
```

---

## Scan Profiles

Profiles bundle framework-specific configuration: domain mappings, penalty weights, scanner
maps, and category classification patterns. Use `--profile` to select one.

### Built-in Profiles

| Profile | Use Case | Framework Patterns | Scoring Weights |
|---------|----------|-------------------|-----------------|
| `generic` | Codebase-agnostic | OWASP LLM Top 10 only (8 regex) | D5=0.4, D8=0.4, D7=0.2 |
| `adept` | ADEPT platform | OWASP + ADEPT categories A-H (16 regex) | Same as generic + disabled TLS |

### Using Profiles

```bash
# Use built-in ADEPT profile (adds A-H attack categories for red-team classification)
make -C scripts/release asopb-evaluate SCAN_TARGET=... ASOPB_PROFILE=adept

# Use generic profile (any codebase, OWASP-only classification)
make -C scripts/release asopb-evaluate SCAN_TARGET=... ASOPB_PROFILE=generic

# Use custom profile from YAML file
make -C scripts/release asopb-evaluate SCAN_TARGET=... ASOPB_PROFILE=/path/to/my-profile.yaml
```

### What Profiles Control

A profile overrides these evaluation parameters:
- **Domain mapping**: How red-team findings map to ASOPB domains (e.g., "LLM01" -> D2)
- **Pipeline weights**: ASPI domain weighting formula (D5/D7/D8 ratios)
- **Penalty weights**: Per-domain severity-to-penalty scaling for pipeline scoring
- **Scanner map**: Which scanners contribute findings to which domains
- **Category patterns**: Regex patterns for auto-classifying promptfoo results

### Custom Profile YAML

```yaml
name: my-framework
description: Custom profile for framework X
pipeline_weights:
  D5: 0.3
  D7: 0.3
  D8: 0.4
penalty_weights:
  D5:
    critical: 50.0
    high: 20.0
    medium: 10.0
    low: 2.0
framework_domain_map:
  CUSTOM_01:
    target_domain: D3
    target_controls: [D3.1, D3.2]
    base_t3_score: 7.5
category_patterns:
  - ["CUSTOM_01", "custom.*pattern|specific.*keyword"]
```

### Profile-Aware Testing

```bash
# Run profile unit tests (container)
make -C examples/adept_asopb test-profiles-container

# Run scoring + profiles tests together (container)
make -C examples/adept_asopb test-scoring-container
```

---

## Common Developer Workflows

Most developers do not need a full 8-domain LLM-graded evaluation. Here are quick presets:

### Workflow A: "Are there linting issues, bugs, or CVEs?" (fastest, 2-3 min)

Run D8 (Supply Chain) with only the `supply_chain` scanner and `semgrep` + `pip_audit`
analyzers. This catches CVEs, dependency issues, and code quality patterns:

```bash
make -C scripts/release asopb-lint SCAN_TARGET=$(pwd)
```

This gives a deterministic T1 score for D8 (supply chain health). No LLM needed, no network
needed, completes in 2-3 minutes.

### Workflow B: "Quick security posture check" (5-7 min)

Run the pipeline domains (D5/D7/D8) deterministic-only:

```bash
make -C scripts/release asopb-posture SCAN_TARGET=$(pwd)
```

Or with pipeline-equivalent scoring (targets 90+ baseline, matching historical ASPI 90.4):

```bash
make -C scripts/release asopb-pipeline SCAN_TARGET=$(pwd)
```

The `--scoring-mode pipeline` flag uses `max(0, 100 - SUM(weight * ln(1 + count)))` per
domain with `ASPI = D5 * 0.4 + D8 * 0.4 + D7 * 0.2`. This matches the scan_pipeline.py
formula exactly. A score above 90 means no verified secrets or critical findings.

### Workflow C: "Full maturity assessment with LLM" (20-30 min)

All 8 domains, T1+T2+T3, with LLM grading. Requires network for API access:

```bash
# Azure (default)
make -C scripts/release asopb-evaluate SCAN_TARGET=$(pwd)

# Bedrock Opus (requires: source setup-claude-bedrock.sh)
make -C scripts/release asopb-evaluate-bedrock SCAN_TARGET=$(pwd)
```

### Workflow D: "Red-team my dev stack" (live promptfoo, 10-15 min)

Run promptfoo against a live ADEPT instance (dev, staging, or RC). This probes the LLM
endpoint with adversarial inputs and generates T3 (red-team) evidence that ASOPB can ingest.

Prerequisites:
- ADEPT stack running (e.g., `make start` or RC VM)
- Access to the agent gateway endpoint
- Azure OpenAI or Bedrock credentials for the grader

```bash
# Step 1: Run promptfoo against live ADEPT stack
make -C scripts/release asopb-redteam-live

# Step 2: Feed results into ASOPB evaluation (auto-picks up latest red-team results)
make -C scripts/release asopb-release-gate SCAN_TARGET=$(pwd)
```

The promptfoo config at `scripts/release/tests/promptfoo_redteam_config.yaml` defines:
- 13 adversarial test cases across 11 OWASP LLM Top 10 categories
- Target: configurable via ADEPT_TARGET env var
- Grader: Claude or GPT-4o for response evaluation

The `--redteam-dir` auto-detects promptfoo output format (via `evalId` or `results` keys)
and routes findings into T3 scoring for relevant domains (D2, D3, D4 primarily).

### Workflow E: "D5/D7/D8 + live red-team" (release-gate equivalent, 15-20 min)

This is the standard pre-release workflow: run the pipeline domains with LLM grading, plus
live promptfoo probing against a running ADEPT stack. Matches the release gate but with full
T1+T2+T3 scoring instead of deterministic-only.

```bash
# Step 1: Run promptfoo against live ADEPT stack (dev or RC)
make -C scripts/release asopb-redteam-live ADEPT_TARGET="http://agent_gateway:8081/v1/responses/chat/completions"

# Step 2: Run D5/D7/D8 ASOPB evaluation with live red-team results
make -C scripts/release asopb-release-gate SCAN_TARGET=$(pwd)
```

This gives the most accurate pre-release picture:
- D5 (Federation): T1 patterns + T2 LLM assessment + T3 from promptfoo probing
- D7 (IT/OT): T1 patterns + T2 LLM assessment
- D8 (Supply Chain): T1 patterns + T2 LLM assessment + CVE findings

**Scoring modes** (both produce results — see `docs/security/ASPI_SCORING_REFERENCE.md` for full details):
- Default (composite): ASPI ~21.6 — conservative T1+T2+T3 average per control
- Pipeline mode: ASPI ~90.4 — penalty-based, matches historical release gate

To force pipeline scoring on the release gate:
```bash
make -C scripts/release asopb-release-gate SCAN_TARGET=$(pwd) ASOPB_SCORING_MODE=pipeline
```

### Workflow F: "Only show me what changed" (tier-specific)

The tier system maps to developer concerns:

| Tier | What It Measures | When to Use |
|------|-----------------|-------------|
| T1 (Design) | Architecture patterns exist in code | "Do we have auth/federation/etc. at all?" |
| T2 (Implementation) | Patterns are correctly implemented | "Are our security controls actually working?" |
| T3 (Adversarial) | System resists attacks | "Can an attacker bypass our controls?" |

To get only T1 (fastest, no LLM): use `--skip-llm` (T2 and T3 require LLM or red-team data).

To get T1+T2 without T3: omit `--redteam-dir` (no red-team data = no T3 scores).

To get T1+T2+T3: provide both LLM credentials and `--redteam-dir`.

### Targeting Specific Domains

| Developer Concern | Domains | Scanners Used |
|------------------|---------|---------------|
| Authentication/SSO | D4 | auth, codebase |
| Agent-to-agent security | D5 | federation, codebase |
| Tool/MCP safety | D3 | tools, codebase |
| Supply chain / CVEs | D8 | supply_chain, codebase |
| Code execution safety | D2 | sandbox, codebase |
| Observability / logging | D6 | observability, codebase |
| IT/OT convergence | D7 | itot, codebase |
| Model provenance | D1 | supply_chain, codebase |

Example — "I only care about auth and supply chain":
```bash
--domains D4,D8 --only-scanners auth,supply_chain,codebase
```

---

## Phase 6: Report to Developer

Provide:
1. ASPI score and gate status (PASS >= 90, FAIL < 90)
2. Per-domain breakdown with tier scores
3. Baseline comparison (if available) with flagged regressions (> 2 point drop)
4. Duration, LLM calls, token usage
5. Recommended next steps:
   - If ASPI < 20: T2 criteria need authoring (content gap, not code gap)
   - If ASPI 20-50: Scanner findings present but LLM grading is conservative
   - If ASPI 50-90: Focus on T3 red-team expansion and specific domain gaps
   - If ASPI >= 90: Ready for release gate

---

## Token Budget Gate (T2 LLM Cost Control)

When running full 8-domain evaluations with LLM scoring (Workflow C), the T2 phase makes
one LLM call per eligible control (~44 calls across 8 domains, ~196k tokens). Use the
token budget gate to control cost before execution begins.

### Estimate Token Budget (dry-run, no LLM calls)

```bash
docker run --rm --network=none \
  -v $(pwd):/scan:ro \
  --entrypoint python3 \
  adept-release-scanner:latest \
  -c "
from asopb.config import EvalConfig
from asopb.evaluator import Evaluator
config = EvalConfig(skip_llm=False)
evaluator = Evaluator(config=config)
estimate = evaluator.estimate_t2_token_budget()
print(f'Estimated LLM calls:    {estimate[\"estimated_calls\"]}')
print(f'Estimated input tokens:  {estimate[\"estimated_input_tokens\"]:,}')
print(f'Estimated output tokens: {estimate[\"estimated_output_tokens\"]:,}')
print(f'Estimated total:         {estimate[\"estimated_total_tokens\"]:,}')
for d, info in estimate['per_domain'].items():
    print(f'  {d}: {info[\"controls_t2_eligible\"]} eligible controls, ~{info[\"input_tokens\"]:,} input tokens')
"
```

### Enforce Token Budget

```bash
# Set a ceiling — if estimated tokens exceed budget, CLI prompts for confirmation
asopb evaluate /scan --token-budget 200000

# Auto-confirm (CI mode) — proceeds even if budget exceeded
asopb evaluate /scan --token-budget 200000 --token-budget-confirm

# Environment variable alternative (same effect as --token-budget)
ASOPB_TOKEN_BUDGET=200000 asopb evaluate /scan
```

### Human Gate Behavior

When `--token-budget` is set and the estimate exceeds it, the CLI presents three choices:
1. **f (full)**: Proceed with all T2 LLM calls regardless of budget
2. **c (cap)**: Skip LLM entirely (equivalent to `--skip-llm`)
3. **a (abort)**: Exit immediately (default)

In CI or non-interactive environments, use `--token-budget-confirm` to auto-proceed
(equivalent to choosing "f").

### Typical Token Budgets

| Scenario | Estimated Tokens | Budget Suggestion |
|----------|-----------------|-------------------|
| Full 8-domain (all t2_criteria) | ~196,000 | 200,000 |
| D5/D7/D8 only | ~60,000 | 75,000 |
| Single domain | ~15,000-30,000 | 35,000 |

---

## Reference: Available CLI Flags

```
asopb evaluate <repo_path>
  --config, -c PATH         YAML configuration file
  --model, -m TEXT          LLM model override
  --output, -o PATH         Output directory
  --format, -f [json|md|html]  Output format
  --domains, -d TEXT        Comma-separated domain IDs (D1,D3,D5)
  --skip-llm               Deterministic scoring only
  --skip-analyzers         Skip all external analyzers
  --disable-analyzers TEXT Comma-separated analyzers to skip (tls,bandit)
  --only-analyzers TEXT    Whitelist analyzers (semgrep,pip_audit)
  --disable-scanners TEXT  Comma-separated scanners to skip (codebase)
  --only-scanners TEXT     Whitelist scanners (federation,itot)
  --scoring-mode [composite|pipeline]  Scoring formula (default: composite)
  --profile TEXT           Scan profile name or path to YAML (generic, adept, or custom)
  --token-budget INT       Max token budget for T2 LLM grading (0=unlimited)
  --token-budget-confirm   Auto-confirm token budget (skip interactive prompt)
  --verbose, -v            Verbose logging
  --stage-hint [S1-S4]    Stage applicability hint
  --custom-controls PATH   Custom controls YAML
  --redteam-dir PATH       Red-team results directory
```

## Reference: Makefile Targets

All targets live in `scripts/release/Makefile`. Run with `make -C scripts/release <target>`.

| Target | Workflow | Duration | Network | Description |
|--------|----------|----------|---------|-------------|
| `asopb-lint` | A | 2-3 min | air-gapped | D8 CVE/lint check (semgrep + pip_audit) |
| `asopb-posture` | B | 5-7 min | air-gapped | D5/D7/D8 deterministic posture |
| `asopb-pipeline` | B+ | 5-7 min | air-gapped | D5/D7/D8 pipeline scoring (targets 90+) |
| `asopb-evaluate` | C | 20-30 min | egress proxy | Full 8-domain with LLM (azure/o4-mini) |
| `asopb-evaluate-bedrock` | C | 60-90 min | egress proxy | Full 8-domain with Bedrock Opus |
| `asopb-redteam-live` | D | 10-15 min | app network | Promptfoo against live ADEPT stack |
| `asopb-release-gate` | E | 15-20 min | egress proxy | D5/D7/D8 + red-team (pre-release) |
| `asopb-custom` | - | varies | egress proxy | Fully parameterized evaluation |

**Key variables** (override with `make ... VAR=value`):

| Variable | Default | Description |
|----------|---------|-------------|
| `SCAN_TARGET` | staged tree | Path to scan |
| `ASOPB_LLM_MODEL` | `azure/o4-mini` | LLM model |
| `ASOPB_SKIP_LLM` | (unset) | Set to `1` for deterministic only |
| `ASOPB_DOMAINS` | (all) | Comma-separated domain IDs |
| `ASOPB_ONLY_SCANNERS` | (all) | Whitelist scanners |
| `ASOPB_DISABLE_ANALYZERS` | `tls` | Skip specific analyzers |
| `ASOPB_SCORING_MODE` | `composite` | `composite` or `pipeline` |
| `ASOPB_PROFILE` | (none) | Scan profile name or YAML path |
| `ASOPB_TOKEN_BUDGET` | `0` (unlimited) | Token ceiling for T2 LLM grading |
| `REDTEAM_DIR` | (auto-detect) | Red-team results path |

## Reference: Domain Skills (LLM Prompt Templates)

Located in `examples/adept_asopb/src/asopb/skills/`:
- `d1_model_integrity.md` — Foundation model provenance and integrity
- `d2_orchestration.md` — Agent orchestration security
- `d3_tool_security.md` — Tool and MCP security
- `d4_identity.md` — Identity and authentication
- `d5_federation.md` — Federation and trust boundaries
- `d6_observability.md` — Observability and audit
- `d7_itot.md` — IT/OT convergence
- `d8_supply_chain.md` — Ecosystem and supply chain

## Reference: Key Files

| File | Purpose |
|------|---------|
| `examples/adept_asopb/src/asopb/cli.py` | CLI entry point (--profile flag) |
| `examples/adept_asopb/src/asopb/config.py` | EvalConfig, LLMConfig, ScannerConfig, AnalyzerConfig |
| `examples/adept_asopb/src/asopb/profiles.py` | ProfileRegistry, ScanProfile, built-in profiles |
| `examples/adept_asopb/src/asopb/scoring.py` | PipelineScorer (profile-aware scoring) |
| `examples/adept_asopb/src/asopb/evaluator.py` | Evaluator class (scan + analyze + score) |
| `examples/adept_asopb/src/asopb/domains/base.py` | Base domain evaluator (T1/T2/T3 scoring) |
| `examples/adept_asopb/src/asopb/redteam/promptfoo_ingester.py` | Promptfoo ingestion (profile-aware classification) |
| `examples/adept_asopb/tests/test_profiles.py` | Profile unit tests (16 tests) |
| `examples/adept_asopb/Makefile` | test-profiles-container, test-scoring-container |
| `scripts/release/Makefile` | asopb-evaluate target |
| `scripts/release/Dockerfile` | Scanner image build |
| `setup-claude-bedrock.sh` | Bedrock AWS credentials (NOT git-tracked) |
| `.env` | Azure OpenAI credentials |

## Reference: Historical ASPI Scores

| Date | Image | Model | Target | ASPI | Notes |
|------|-------|-------|--------|------|-------|
| 2026-05-17 | v4 | pipeline (no LLM) | staged | 90.4 | D5/D7/D8 only, deterministic |
| 2026-05-20 | v7b | azure/o4-mini | staged | 10.5 | Full 8-domain, .publish-exclude strips docs |
| 2026-05-20 | v7b | azure/o4-mini | pre-stage | 17.8 | Full 8-domain, scanner fixes confirmed |
