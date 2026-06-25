---
name: scan-path
description: Run ASOPB security scan on an arbitrary directory and report findings with ASPI score
disable-model-invocation: true
allowed-tools: Bash(make *) Bash(python3 scripts/release/*) Bash(bash scripts/release/*) Bash(docker logs*) Bash(docker ps*) Bash(docker run*) Bash(docker stop*) Bash(git *) Bash(ls *) Bash(find *) Bash(cat *) Bash(tail *) Bash(wc *) Read Glob Grep
---

You are assisting an ADEPT developer with running the ASOPB security scan on an arbitrary directory (not the staged release tree). This is the ad-hoc scan workflow for scanning source repos, third-party code, or any host path.

Do not use emojis in any output.

## Quick Start (Preferred)

The simplest invocation from the project root:

```bash
# Any directory on the host filesystem can be scanned
make scan-path SCAN_TARGET=examples/biofoundation_mcp_server
make scan-path SCAN_TARGET=examples/slurm_mcp_server
make scan-path SCAN_TARGET=src/agentic_framework_pkg/orchestration_service
make scan-path SCAN_TARGET=/path/to/some-third-party-repo
```

Or with custom passes and gate threshold:

```bash
make scan-path SCAN_TARGET=/absolute/path/to/dir PASSES=enhanced GATE=70
```

This single command runs the full 4-phase pipeline:
1. Scanner container (air-gapped, produces pass_*.json)
2. ASPI gate check (score vs threshold)
3. Summary report (per-pass breakdown)
4. HIGH findings breakdown (grouped by pattern)

## Pass Group Options

| PASSES value | Passes included | Duration | Use case |
|-------------|-----------------|----------|----------|
| `enhanced` (default) | regex, secrets, trufflehog, grype, dockerfile_deps, vulture, egress | ~5-10s | Quick security posture check |
| `lightweight` | regex, secrets | ~2s | Fast credential scan |
| `all` | All 9 passes including ML (NER/PII, toxicity) | 30-75 min | Full pre-release coverage |

## Direct Script Invocation

The wrapper script can also be called directly:

```bash
bash scripts/release/scan_path.sh <target_dir> [passes] [gate_threshold]

# Examples:
bash scripts/release/scan_path.sh examples/biofoundation_mcp_server
bash scripts/release/scan_path.sh /absolute/path enhanced 70
bash scripts/release/scan_path.sh examples/slurm_mcp_server all 90
```

## Step-by-Step (Manual)

### Step 1: Identify the scan target

The target can be any directory: an MCP server plugin, a service module, a third-party repo, or any host path.

```bash
# Examples of valid targets (biofoundation is just one of many)
SCAN_TARGET="examples/biofoundation_mcp_server"
SCAN_TARGET="examples/slurm_mcp_server"
SCAN_TARGET="src/agentic_framework_pkg/sandbox_mcp_server"
SCAN_TARGET="/path/to/external-dependency-audit"

find "$SCAN_TARGET" -type f | wc -l
```

### Step 2: Run the scan

```bash
make scan-path SCAN_TARGET="$SCAN_TARGET" PASSES=enhanced GATE=70
```

The output directory is printed at the end: `logs/scan-path-<dirname>-<timestamp>/`

### Step 3: Downstream analysis

After the scan completes, additional analysis is available:

```bash
SCAN_DIR=$(ls -td logs/scan-path-* | head -1)

# Re-run gate check with different threshold
python3 scripts/release/gate_check.py "$SCAN_DIR" --no-report --gate 90 --verbose

# Full FP analysis with simulation
python3 scripts/release/analyze_findings.py "$SCAN_DIR" --simulate

# Actionable findings only (after FP suppression)
python3 scripts/release/analyze_findings.py "$SCAN_DIR" --actionable-only

# Detailed findings breakdown by pass
python3 scripts/release/scan_report.py findings "$SCAN_DIR" --severity high --examples 5

# Per-pass summary
python3 scripts/release/scan_report.py summary "$SCAN_DIR"

# From scripts/release/ Makefile:
cd scripts/release && make scan-gate SCAN_DIR="$SCAN_DIR" GATE=90
cd scripts/release && make scan-analyze SCAN_DIR="$SCAN_DIR"
cd scripts/release && make report-dir SCAN_DIR="$SCAN_DIR"
```

### Step 4: Report to developer

Provide:
1. Scan target path and file count
2. ASPI score and stage (S1-S4)
3. Gate status (PASS/FAIL with threshold)
4. Domain breakdown (D5, D8, D7)
5. Total findings vs. per-pass breakdown
6. Top categories of findings
7. Recommended next steps (suppress FPs, upgrade deps, exclude log files)

## Critical Notes

### Air-Gapped Execution

The scanner runs with `--network=none`. All ML models are pre-cached in the 8.33GB image. No network access is needed or permitted during static analysis.

### Self-Test

The scanner automatically validates its internal dependencies before scanning. Results are in `selftest_results.json`. A non-zero failure count is informational (version parity checks against upstream).

### Image Freshness

Scanner scripts are mounted from host at runtime (via SCANNER_MOUNTS), so the image does NOT need rebuilding when scanner code changes. Only rebuild if:
- ML model versions change
- Binary tools (trufflehog, grype) need updating
- Base Python packages change

```bash
# Check image age
docker inspect adept-release-scanner:latest --format '{{.Created}}' | cut -d'T' -f1

# Rebuild if needed
cd scripts/release && make docker-build
```

### Missing Pass Files

`gate_check.py` treats missing pass files as zero findings (score 100). If you ran `enhanced` passes, only those pass files will exist. The ASPI score reflects ONLY the passes that ran.

### Memory for ML Passes

When using `PASSES=all`:
- `--shm-size=4g` REQUIRED (PyTorch DataLoader uses /dev/shm)
- `--memory=8g` REQUIRED to prevent silent OOM kills
- ML passes take 20-65 minutes depending on file count

## Output Structure

```
logs/scan-path-<dirname>-<timestamp>/
  pass_regex.json           # Regex pattern findings
  pass_secrets.json         # detect-secrets findings
  pass_trufflehog.json      # TruffleHog credential findings
  pass_grype.json           # CVE/vulnerability findings
  pass_vulture.json         # Dead code detection
  pass_dockerfile_deps.json # Dockerfile dependency analysis
  pass_egress.json          # Network egress detection
  pipeline_manifest.json    # Scan metadata (files, duration, passes)
  selftest_results.json     # Scanner self-test results
  report.json               # Full pipeline report (stdout capture)
  stderr.log                # Scanner stderr output
```

## Scoring Reference

- Formula: `domain_score = max(0, 100 - SUM(weight * ln(1 + count)))`
- Composite: `ASPI = D5 * 0.4 + D8 * 0.4 + D7 * 0.2`
- Stages: S4>=90, S3>=70, S2>=50, S1<50
- See `docs/security/ASPI_SCORING_REFERENCE.md` for full reference

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "invalid reference format" | Running from wrong directory or missing Docker image | Use absolute path for SCAN_TARGET; verify `docker images adept-release-scanner:latest` |
| Scanner produces 0 output | Path not accessible inside container | Use absolute host path (not relative); check stderr.log |
| ASPI=100 but findings expected | Only ran lightweight passes | Use `PASSES=enhanced` or `PASSES=all` |
| ML passes missing from output | OOM kill during inference | Use `PASSES=all` with `--memory=8g --shm-size=4g` |
| Credential findings in log files | Validation logs contain tokens | Add log files to `.publish-exclude` or exclude from scan target |
| Permission denied on target | Volume mount issue | Ensure target path is world-readable |
