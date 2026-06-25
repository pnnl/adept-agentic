---
name: scan-release
description: Run ASOPB scan on staged release tree and report findings with ASPI score
disable-model-invocation: true
allowed-tools: Bash(make stage*) Bash(make docker-scan*) Bash(python3 scripts/release/*) Bash(docker logs*) Bash(docker ps*) Bash(docker run*) Bash(docker stop*) Bash(git *) Bash(ls *) Bash(find *) Bash(cat *) Bash(tail *) Bash(wc *) Read Glob Grep
---

You are assisting an ADEPT developer with running the ASOPB security scan on the staged release tree. This is the scan-only subset of `/prepare-release` — no dry-run or publish steps.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

## Critical: Execution Patterns

**All long-running commands MUST use absolute paths for log output.** The scanner runs from `scripts/release/` but logs must land in `$PROJECT_ROOT/logs/`.

```bash
PROJECT_ROOT=$(pwd)
```

**Docker containers outlive nohup.** When running `docker run ... &`, the background task reports "completed" when the shell detaches, NOT when the container finishes. Always monitor with `docker ps` and `docker logs <id> --tail 10`.

**Air-gapped mode (`--network=none`) blocks `secrets` and `trufflehog` passes** if detect-secrets or trufflehog need network-based initialization. For full scans, omit `--network=none` unless specifically testing air-gap compliance.

**Image freshness check.** Scanner code (`scanner_logging.py`, `scan_pipeline.py`, `scan_ner_pii.py`,
`scan_toxicity.py`) and the ASOPB library (`examples/adept_asopb/src/asopb/`) are baked into the
Docker image at build time. If any of these files have changed since the last `make docker-build`,
the running image is stale. Before scanning, always verify:

```bash
# Check image build date vs source changes
docker inspect adept-release-scanner:latest --format '{{.Created}}' | cut -d'T' -f1
git log -1 --format=%ci -- scripts/release/scan_*.py scripts/release/scanner_logging.py examples/adept_asopb/src/asopb/

# If image is older than source, rebuild:
cd $PROJECT_ROOT/scripts/release && make docker-build
# This runs: sync-asopb → check-asopb → docker build (syncs canonical ASOPB into image)
```

## Critical: Execution Patterns

**All long-running commands MUST use absolute paths for log output.** The scanner runs from `scripts/release/` but logs must land in `$PROJECT_ROOT/logs/`.

```bash
PROJECT_ROOT=$(pwd)
```

**Docker containers outlive nohup.** When running `docker run ... &`, the background task reports "completed" when the shell detaches, NOT when the container finishes. Always monitor with `docker ps` and `docker logs <id> --tail 10`.

**Air-gapped mode (`--network=none`) blocks `secrets` and `trufflehog` passes** if detect-secrets or trufflehog need network-based initialization. For full scans, omit `--network=none` unless specifically testing air-gap compliance.

**Image freshness check.** Scanner code (`scanner_logging.py`, `scan_pipeline.py`, `scan_ner_pii.py`,
`scan_toxicity.py`) and the ASOPB library (`examples/adept_asopb/src/asopb/`) are baked into the
Docker image at build time. If any of these files have changed since the last `make docker-build`,
the running image is stale. Before scanning, always verify:

```bash
# Check image build date vs source changes
docker inspect adept-release-scanner:latest --format '{{.Created}}' | cut -d'T' -f1
git log -1 --format=%ci -- scripts/release/scan_*.py scripts/release/scanner_logging.py examples/adept_asopb/src/asopb/

# If image is older than source, rebuild:
cd $PROJECT_ROOT/scripts/release && make docker-build
# This runs: sync-asopb → check-asopb → docker build (syncs canonical ASOPB into image)
```

## Step 1: Stage the release tree

```bash
cd $PROJECT_ROOT/scripts/release && make stage
```

Verify output (MUST use `-L` to follow symlinks):
```bash
find -L /tmp/adept-release-stage -type f | wc -l
```

Confirm the symlink resolves and the STAGE_DIR matches today's date:
```bash
readlink /tmp/adept-release-stage
ls /tmp/adept-release-stage-$(date +%Y%m%d) | head -5
```

If the date-suffixed dir does not exist, `make stage` creates it AND updates the symlink.

## Step 2: Run the 10-pass scan

**Preferred method** (explicit, captures all output):

```bash
SCAN_DIR=$PROJECT_ROOT/logs/scan-staged-$(date +%Y%m%d-%H%M%S)
mkdir -p "$SCAN_DIR"

docker run --rm --shm-size=4g --memory=8g \
  -v /tmp/adept-release-stage-$(date +%Y%m%d):/scan:ro \
  -v "$SCAN_DIR":/output \
  -v $PROJECT_ROOT/scripts/release:/app/scripts/release:ro \
  -v $PROJECT_ROOT/examples/adept_asopb/src:/app/asopb_src:ro \
  -e PYTHONPATH=/app/scripts/release:/app/asopb_src \
  adept-release-scanner:latest \
  /scan --passes all --format json --output-dir /output \
  > "$SCAN_DIR/stdout.log" 2> "$SCAN_DIR/stderr.log"
```

Run this with nohup if non-blocking:
```bash
nohup docker run --rm --shm-size=4g --memory=8g \
  ... \
  > "$SCAN_DIR/stdout.log" 2> "$SCAN_DIR/stderr.log" &
echo $! > "$SCAN_DIR/docker.pid"
```

**Alternative** (Makefile target — simpler but has date-mismatch risk):
```bash
cd $PROJECT_ROOT/scripts/release && make docker-scan-staged
```

**Monitor progress** (container runs independently of nohup):
```bash
# Find running scanner container
docker ps --filter "ancestor=adept-release-scanner:latest" --format "{{.ID}} {{.Status}}"

# Tail its logs
docker logs $(docker ps -q --filter "ancestor=adept-release-scanner:latest") --tail 20 2>&1
```

Wait for completion. See timing/resource reference below.

## Resource Requirements

**CRITICAL: Memory for ML passes.** The scanner WILL be silently killed by Docker/cgroup if
insufficient memory is allocated. There is NO Python exception — the process simply vanishes
mid-inference after model weights load successfully. Symptoms: `pass_ner_pii.json` and
`pass_toxicity.json` missing from output, stderr shows model loading but no scan progress.

**RAM** (sequential model loading — pipeline enforces this):
| Model | Task | Params | Disk | Peak RSS |
|-------|------|--------|------|----------|
| dslim/bert-base-NER | NER (PER/ORG/LOC) | 110M | 430MB | ~1.2GB |
| Isotonic/deberta-v3-base | PII (54 types) | 200M | 750MB | ~1.8GB |
| unitary/toxic-bert (detoxify) | Toxicity (6 labels) | 110M | 430MB | ~1.2GB |

- Combined peak (NER+PII concurrent): **~3.5 GB** RSS
- All models + PyTorch overhead: **~5-6 GB** total container memory
- `--shm-size=4g` REQUIRED (PyTorch DataLoader uses /dev/shm for IPC; Docker default is 64MB)
- `--memory=8g` REQUIRED to prevent silent OOM kills during ML inference

**Pre-flight memory check** (runs automatically as prerequisite of `docker-scan-staged`):
```bash
cd $PROJECT_ROOT/scripts/release && make check-memory
```

The Makefile auto-detects host RAM and sets `--memory=8g` (>=16GB host), `--memory=6g`
(>=8GB host), or `--memory=4g` (>=4GB host). Below 4GB, the check will fail with guidance.

**Timing** (2,187-file staged tree reference):
| Phase Group | Passes | Expected Duration | Notes |
|-------------|--------|-------------------|-------|
| `[fast]` | regex, secrets | 1-2 min | Regex-based, sub-second per file |
| `[io_bound]` | trufflehog, grype, dockerfile_deps, vulture, egress | 2-5 min | Run concurrently |
| `[ml]` | ner_pii, toxicity | 20-65 min | ~100-200ms/chunk, models loaded sequentially (5-15s each) |
| **Total** | all | **30-75 min** | Depends on tree size and file content density |

**Do not panic** if you see `[100/1095] files scanned...` and nothing else for 20+ minutes. ML passes process files sequentially at ~100-200ms per text chunk. Monitor with `docker logs` (see above).

## Step 3: Locate and verify scan output

```bash
SCAN_DIR=$(ls -td $PROJECT_ROOT/logs/scan-staged-* | head -1)
echo "Scan output: $SCAN_DIR"
ls "$SCAN_DIR"
```

Expected files: `pass_regex.json`, `pass_secrets.json`, `pass_trufflehog.json`, `pass_grype.json`, `pass_ner_pii.json`, `pass_toxicity.json`, `pass_vulture.json`, `pass_dockerfile_deps.json`, `pass_egress.json`, `stderr.log`, `report.json`

**CRITICAL: Verify ALL passes completed before reporting ASPI.**

`gate_check.py` treats missing pass files as "zero findings" (score 100). This means a
scan that only completed regex+secrets will report ASPI=100 — a false positive. You MUST
verify completeness before trusting the score:

```bash
# Required minimum: these 7 pass files must exist with non-zero size
for pass in regex secrets trufflehog grype vulture ner_pii toxicity; do
  f="$SCAN_DIR/pass_${pass}.json"
  if [ ! -s "$f" ]; then echo "MISSING: $f — scan incomplete!"; fi
done
```

**Verify scan completed from stderr** (must show all three phase groups):
```bash
grep -E "^\s+(regex|secrets|trufflehog|grype|vulture|ner_pii|toxicity):" "$SCAN_DIR/stderr.log"
```

If `ner_pii` or `toxicity` are missing, the ML passes crashed:
1. Check dmesg for OOM: `dmesg | tail -20 | grep -i "oom\|killed"`
2. Check container memory: was `--memory=8g` passed? (run `make -n docker-scan-staged | grep memory`)
3. Check stderr for model load: if weights loaded but no "Complete" line, container was killed mid-inference
4. Fix: increase `--memory` and `--shm-size`, re-run

## Step 4: Compute ASPI and check gate

```bash
python3 $PROJECT_ROOT/scripts/release/gate_check.py "$SCAN_DIR" --no-report --verbose
```

Report the ASPI score, stage classification, and domain breakdown to the developer.

## Step 5: Analyze findings (if below gate or requested)

```bash
# Full analysis with FP breakdown
python3 $PROJECT_ROOT/scripts/release/analyze_findings.py "$SCAN_DIR" --simulate

# Actionable findings only (after all FP suppression)
python3 $PROJECT_ROOT/scripts/release/analyze_findings.py "$SCAN_DIR" --actionable-only
```

## Step 6: Report summary

Provide the developer with:
1. ASPI score and stage (S1-S4)
2. Gate status (PASS/FAIL with threshold)
3. Domain breakdown (D5, D8, D7)
4. Total findings vs. actionable findings
5. Top categories of actionable findings (if any)
6. Recommended next steps

## Step 7: Supplemental checks (optional, recommended)

### Dead Import Scanner

Detects imports referencing symbols that no longer exist in source. Run on tests/ to catch stale mocks.

```bash
PYTHONPATH=$PROJECT_ROOT/examples/adept_asopb/src \
  python3 $PROJECT_ROOT/scripts/release/scan_dead_imports.py \
  --target $PROJECT_ROOT/tests/ --src $PROJECT_ROOT/src/ --actionable-only
```

### Allowlist Validator

Validates that `.asopb-allowlist.yaml` has no structural errors and reports rule coverage.

```bash
PYTHONPATH=$PROJECT_ROOT/examples/adept_asopb/src python3 -c "
from asopb.quality.allowlist import load_allowlist, validate_allowlist
from pathlib import Path
al = load_allowlist(Path('$PROJECT_ROOT/scripts/release/.asopb-allowlist.yaml'))
print(f'Allowlist: {al.total_rules} rules, hash={al.content_hash[:16]}..., version={al.schema_version}')
issues = validate_allowlist(al)
errors = [i for i in issues if i.severity == 'ERROR']
if errors:
    for e in errors: print(f'  ERROR [{e.category}:{e.rule_index}]: {e.message}')
    import sys; sys.exit(1)
print('Validation: PASS (0 errors)')
"
```

If validation errors exist, fix them in `.asopb-allowlist.yaml` before proceeding with the scan.

### Compensating Controls Validator

Verifies that false-positive suppressions are still valid (file hashes match, entities present).

```bash
PYTHONPATH=$PROJECT_ROOT/examples/adept_asopb/src \
  python3 $PROJECT_ROOT/scripts/release/compensating_controls.py validate
```

If any controls are `stale` or `invalidated`, they need re-acceptance or removal before release.

### DAST Cross-Referenced Report (if ADEPT stack running)

If the ADEPT stack is running and DAST results exist (from `make dast-full` or `make asopb-redteam-live`), generate the cross-referenced report that correlates promptfoo results with Docker service logs:

```bash
# Check if DAST results exist
ls $PROJECT_ROOT/logs/promptfoo-live-*/results.json \
   $PROJECT_ROOT/logs/dast-adept-*/promptfoo_results.json 2>/dev/null | tail -1

# If results found, generate cross-referenced report
python3 $PROJECT_ROOT/scripts/release/report_dast_cross_reference.py --html --format both
```

This produces:
- `dast_report.json`: Machine-readable with per-probe server correlation
- `dast_report.md`: Markdown summary for PR comments
- `dast_report.html`: Interactive analytics dashboard (Chart.js timeline, OWASP radar, filterable probe table)

If no DAST results exist, report:
"No DAST results found. Run `cd scripts/release && make dast-full` to scan the live ADEPT stack (requires: running stack + synced credentials)."

If results exist but Docker logs are unavailable (stack stopped), the report degrades gracefully to results-only mode with a warning banner.

### Version Parity Check

Checks if scanner dependencies are behind upstream and looks up CVEs on pinned versions.
This is automatically included in the self-test (runs before every scan), but can also be
run independently for proactive supply chain awareness:

```bash
cd $PROJECT_ROOT/scripts/release
python3 scanner_selftest.py --format json 2>/dev/null | \
  python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
parity = [c for c in data['checks'] if c['name'].startswith('parity:')]
behind = [c for c in parity if c['status'] == 'WARN']
print(f'Version parity: {len(parity)} deps checked, {len(behind)} behind upstream')
for c in behind:
    line = f'  {c[\"name\"].split(\":\",2)[2]}: {c[\"installed\"]} -> {c[\"upstream_latest\"]}'
    if 'cves' in c:
        line += f' [{len(c[\"cves\"])} CVEs]'
    print(line)
"
```

If CVEs are found on pinned versions, use `/triage-cve` to investigate remediation options.

## CI Integration Context

This local scan workflow complements the CI pipeline in `.github/workflows/asopb-pre-release-scan.yml`:

**Relationship to CI**:
- CI Phase 1 (regex scan) runs on every PR — lightweight, deterministic, blocking gate
- CI Phase 2 (ML + Grype + red-team) runs in parallel advisory jobs (non-blocking except Critical CVEs)
- Local `/scan-release` runs the FULL 10-pass pipeline (30-75 min) for complete coverage before publish
- The publish workflow (`.github/workflows/publish-public-release.yml`) has an ASPI gate job that must pass before public release

**Self-test precondition**:
- CI runs `scanner_selftest.py --skip-parity` before any Phase 2 jobs (validates image integrity)
- Local scans should also verify image freshness (see "Image freshness check" above)
- If self-test fails in CI, all Phase 2 jobs are skipped (image treated as unavailable)

**Critical CVE enforcement**:
- CI blocks PRs if Grype finds any **Critical** CVEs (D8 weight=40, gate-failing)
- High/Medium/Low CVEs are advisory only in CI
- Use `/triage-cve` to investigate and remediate Critical CVE findings

**ASPI history**:
- CI uploads a JSON artifact (`aspi-history-<sha>`) with scores for every scan run
- Query historical scores via GitHub API: `gh api repos/.../actions/artifacts --jq '.artifacts[] | select(.name | startswith("aspi-history-"))'`
- 365-day retention for trend analysis

**Promptfoo red-team**:
- In CI: advisory only (`continue-on-error: true`), expensive due to backend LLM calls
- In `/scan-release`: NOT included (requires `--promptfoo-target` and live endpoint)
- In `/prepare-release`: REQUIRED as a gate step before publish — uses `/promptfoo-check`
- Run ad-hoc: `make asopb-redteam` or invoke `/promptfoo-check` skill

## Reference: Scoring Model

See **`docs/security/ASPI_SCORING_REFERENCE.md`** for the complete ASPI scoring reference, including:
- Pipeline ASPI vs Full ASPI vs Ad-hoc scan distinctions
- Domain weights, composite formula, and stage classification
- Gate thresholds and FP suppression stack
- Relationship between Grype-only, full pipeline, and evaluator scores

Quick reference (Pipeline ASPI):
- Formula: `domain_score = max(0, 100 - SUM(weight * ln(1 + count)))`
- Composite: `ASPI = D5 * 0.4 + D8 * 0.4 + D7 * 0.2`
- Gate: >= 95 for release publish
- Stages: S4>=90, S3>=70, S2>=50, S1<50

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Only `pass_regex.json` + `pass_secrets.json` in output | ML passes killed by OOM | Use `--shm-size=4g --memory=8g`; run `make check-memory` |
| `report.json` is 0 bytes | Container killed before pipeline completed | Check `dmesg` for OOM kill; increase memory |
| stderr shows model weights loading, then nothing | Silent OOM during inference (no Python traceback) | Increase `--memory=8g`; verify with `docker stats` during run |
| `gate_check.py` reports ASPI=100 but ML passes missing | gate_check treats missing files as zero findings | Verify all 7+ pass files exist before trusting score |
| `STAGE_DIR` not found | Date rolled over between stage and scan | Re-run `make stage` or use symlink path |
| `ModuleNotFoundError: asopb.quality` | Missing PYTHONPATH | Add `-e PYTHONPATH=/app/asopb_src` or set on host |
| `ModuleNotFoundError: asopb.models` (CI Phase 1) | Bare runner without pydantic | scan_pipeline.py handles this gracefully (returns None) |

## Instrumentation

The ML passes (`scan_ner_pii.py`, `scan_toxicity.py`) now log structured progress via
`scanner_logging.get_logger()`. Key telemetry points:
- Model load start/complete with wall-clock time and RSS
- File scan start with file count
- Progress every 200 files (NER/PII) or 10 batches (toxicity)
- Completion with total findings, elapsed time, and peak RSS

If a pass crashes silently, the LAST logged line in stderr reveals exactly where:
- After "Loading models" but before "model loaded" = model init OOM
- After "model loaded" but before "Scanning N files" = file enumeration issue
- After "Scanning" but before "Complete" = inference OOM (increase --memory)
| `detect-secrets` hangs | Air-gapped mode + binary needs network init | Remove `--network=none` |
| ML pass OOM | Concurrent model loading | Verify `--shm-size=2g`; pipeline forces sequential ML |
