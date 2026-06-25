---
name: triage-cve
description: Investigate and triage CVEs from Grype/TruffleHog scan findings — lookup, reachability, remediation
disable-model-invocation: true
allowed-tools: Bash(python3 *) Bash(grep *) Bash(find *) Bash(cat *) Bash(ls *) Bash(uv *) Bash(pip *) Bash(git *) Bash(docker *) Read Write Edit Glob Grep WebFetch WebSearch
---

You are assisting an ADEPT developer with investigating and triaging CVE findings from ASOPB security scans. This skill walks through lookup, reachability analysis, and remediation for each finding.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.

## Scoring Context

See **`docs/security/ASPI_SCORING_REFERENCE.md`** for how CVE findings affect Pipeline ASPI.

Key points:
- Only **Critical** CVEs penalize D8 at weight=40 (gate-failing)
- High/Medium/Low are advisory only (weight=2.5 as unverified, minimal ASPI impact)
- Suppressed CVEs (in `.grype.yaml`) are excluded from scoring entirely
- TruffleHog unverified secrets also contribute to D8 at weight=2.5

## CI Enforcement Context

The ASOPB CI workflow (`.github/workflows/asopb-pre-release-scan.yml`) **blocks PRs** when Critical CVEs are detected:

- The `grype-scan` job runs Grype against the staged release tree
- The `report` job checks `grype-scan.outputs.critical` — if non-zero, the PR is blocked
- Error message directs developers to this `/triage-cve` skill for investigation
- Remediation options: upgrade the package, add a compensating control to `.grype.yaml`, or suppress with justification

**Common CI trigger scenarios**:
1. New dependency added with known Critical CVE
2. Existing dependency's pinned version newly classified as Critical (NVD reclassification)
3. Transitive dependency pulled in by a direct dependency update

**Workflow**: CI blocks PR -> developer invokes `/triage-cve` -> investigate reachability -> upgrade or suppress -> re-push -> CI re-runs -> gate passes

The publish workflow (`.github/workflows/publish-public-release.yml`) also has an ASPI gate that will fail if unresolved findings push ASPI below 90.

## Phase 1: Load Findings

**Input sources** (choose one):
- Scan output from `/scan-release` or `/scan-path` (primary)
- Self-test version parity output: `python3 scripts/release/scanner_selftest.py --format json` (category 9 reports CVEs via OSV.dev on pinned scanner dependencies)

Identify the scan output directory:

```bash
SCAN_DIR=$(ls -td $PROJECT_ROOT/logs/scan-staged-* | head -1)
echo "Using: $SCAN_DIR"
```

Extract D8 findings:

```bash
python3 -c "
import json
from pathlib import Path

scan_dir = Path('$SCAN_DIR')
grype = json.loads((scan_dir / 'pass_grype.json').read_text())
findings = grype.get('findings', [])

# Group by package
pkgs = {}
for f in findings:
    pkg = f.get('package', '?')
    pkgs.setdefault(pkg, []).append(f)

print(f'Total CVE findings: {len(findings)}')
print(f'Unique packages: {len(pkgs)}')
print()
for pkg, cves in sorted(pkgs.items(), key=lambda x: -len(x[1])):
    versions = set(f.get('installed_version', '?') for f in cves)
    fixed = set(f.get('fixed_version', '?') for f in cves if f.get('fixed_version'))
    sev = set(f.get('severity', '?') for f in cves)
    print(f'  {pkg} ({\",\".join(versions)}) — {len(cves)} CVEs [{\"|\".join(sev)}]')
    if fixed:
        print(f'    Fix available: {\"|\".join(fixed)}')
"
```

Present the grouped findings to the developer. Ask which packages to investigate.

## Phase 2: CVE Lookup

For each CVE or package the developer wants to investigate:

### 2a. Check GHSA/NVD details

```bash
# Look up GHSA advisory
gh api /advisories?ghsa_id=GHSA-XXXX-XXXX-XXXX 2>/dev/null | python3 -m json.tool | head -40

# Or search by CVE ID
gh api "/advisories?cve_id=CVE-2026-XXXXX" 2>/dev/null | python3 -m json.tool | head -40
```

If `gh api` doesn't return results, use web search:
```bash
# Search GitHub Security Advisories
# WebSearch: "GHSA-wp53-j4wj-2cfg python-multipart"
```

Report to the developer:
- **Severity**: CVSS score and vector
- **Description**: What the vulnerability enables
- **Affected versions**: Range of vulnerable versions
- **Fixed version**: Minimum safe version
- **Exploit complexity**: Is it remotely exploitable? Requires authentication?

### 2b. Check current pinned version

```bash
# Check uv.lock for the package
grep -A 5 "name = \"<package>\"" $PROJECT_ROOT/uv.lock | head -10

# Check pyproject.toml for direct dependency
grep "<package>" $PROJECT_ROOT/pyproject.toml $PROJECT_ROOT/examples/*/pyproject.toml 2>/dev/null
```

## Phase 3: Reachability Analysis

Determine if the vulnerable code path is reachable in ADEPT:

### 3a. Check if it's a direct or transitive dependency

```bash
# Direct dependency?
grep "<package>" $PROJECT_ROOT/pyproject.toml

# If not found — it's transitive. Find what pulls it in:
grep -B 20 "name = \"<package>\"" $PROJECT_ROOT/uv.lock | grep "name = " | tail -5
```

### 3b. Check if the vulnerable code path is used

The CVE description names a specific class, function, or feature. Search for usage:

```bash
# Search for the vulnerable API/class/function
grep -rn "<VulnerableClass>" $PROJECT_ROOT/src/ $PROJECT_ROOT/examples/ --include="*.py"

# Example: CVE in fastmcp's OpenAPIProvider
grep -rn "OpenAPIProvider" $PROJECT_ROOT/src/ $PROJECT_ROOT/examples/ --include="*.py"
```

### 3c. Check service endpoint exposure

Determine whether the vulnerable library is reachable via any ADEPT service endpoint.
A library only in the scanner container (air-gapped, no inbound) has near-zero attack surface
compared to one serving HTTP traffic in Tier 1 or Tier 2.

```bash
# Is the package imported in application services (src/)?
grep -rn "from <package>\|import <package>" $PROJECT_ROOT/src/ --include="*.py" | grep -v __pycache__

# If found, which service tier uses it?
# Map file path to tier:
#   src/.../agent_gateway/     → Tier 1 (internet-facing, JWT-authenticated)
#   src/.../orchestration_service/ → Tier 2 (internal, behind gateway)
#   src/.../mcp_server/        → Tier 3 (stateless, --network=none in production)
#   src/.../hpc_mcp_server/    → Tier 3
#   src/.../sandbox_mcp_server/ → Tier 3 (privileged, isolated)
#   src/.../gateway_registry/  → Internal service (application network only)

# Is it ONLY in the scanner container (scripts/release/)?
grep -rn "from <package>\|import <package>" $PROJECT_ROOT/scripts/release/ --include="*.py"
```

**Exposure classification**:

| Location | Inbound Traffic | Network Mode | Risk Level |
|----------|----------------|--------------|------------|
| Tier 1 (agent_gateway) | External (internet) | Bridge | HIGH — directly exploitable |
| Tier 2 (orchestration_service) | Internal (from gateway) | Application network | MEDIUM — requires auth bypass |
| Tier 3 (MCP servers) | None (tool calls only) | `--network=none` | LOW — no inbound vector |
| Scanner container | None (batch job) | `--network=none` (static), egress-only (dynamic) | MINIMAL — no inbound |
| Dev tooling only | N/A | Host | NONE — not in deployed stack |

If the package is only used in the scanner container or dev tooling, the CVE is informational
(supply chain hygiene) but not exploitable via ADEPT endpoints.

### 3d. Check network reachability

If the CVE requires network access to exploit:

```bash
# Is the package used in an internet-facing service?
grep -rn "import <package>" $PROJECT_ROOT/src/ --include="*.py" -l

# Cross-reference with service architecture:
# Tier 1 (gateway) — internet-facing
# Tier 2 (orchestration) — internal only
# Tier 3 (MCP servers) — no network (--network=none in production)
```

### 3e. Classification

Based on the analysis, classify each CVE:

| Classification | Criteria | Action |
|---------------|----------|--------|
| **Upgradeable** | Fix version exists, no breaking changes | `uv lock --upgrade-package <pkg>` |
| **Upgradeable (breaking)** | Fix version exists, major version bump | Test upgrade, may require code changes |
| **Not reachable** | Vulnerable code path unused in ADEPT | Add to `.grype.yaml` with compensating control |
| **Transitive only** | Only pulled by another dep, not directly used | Check if parent dep has update |
| **No fix available** | No patched version exists yet | Accept risk or find alternative package |
| **Accept risk** | Low severity + mitigated by architecture | Add to `.grype.yaml` with justification |

## Phase 4: Remediate

### 4a. Upgrade (preferred)

```bash
# Upgrade specific package
uv lock --upgrade-package <package>

# Verify the CVE is resolved
grep -A 3 "name = \"<package>\"" $PROJECT_ROOT/uv.lock

# Run tests to verify no breakage
mkdir -p logs && nohup make validate-unit-priority > logs/cve_upgrade_test_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### 4b. Add compensating control (when upgrade not possible)

Add to `.grype.yaml` following the existing format:

```yaml
ignore:
  # CVE-XXXX-XXXXX | SEVERITY | package version_range | Short title
  #
  # Compensating Control:
  #   <Why this CVE is not exploitable in ADEPT — specific code path analysis>
  #
  # Evidence:
  #   <grep command and result showing the vulnerable API is not used>
  #
  # Risk Acceptance:
  #   Accepted by: <developer name> (<role>), <date>
  #   Condition: <when this suppression should be re-evaluated>
  #   Re-evaluate if: <trigger condition>
  #
  - vulnerability: CVE-XXXX-XXXXX
    package:
      name: <package>
```

### 4c. Add to compensating_controls.py (for ASOPB tracking)

If the CVE is significant enough to track in the compensating controls registry:

```bash
python3 $PROJECT_ROOT/scripts/release/compensating_controls.py add \
  --cve "CVE-XXXX-XXXXX" \
  --package "<package>" \
  --justification "<why not reachable>" \
  --accepted-by "<developer>" \
  --condition "<re-evaluate trigger>"
```

## Phase 5: Verify Remediation

After upgrades or suppressions:

```bash
# Re-run Grype scan on staged tree
make stage && make docker-scan-staged

# Or quick Grype-only check (faster, no ML passes)
docker run --rm \
  -v /tmp/adept-release-stage-$(date +%Y%m%d):/scan:ro \
  adept-release-scanner:latest \
  /scan --passes grype --format json --output-dir /output

# Re-compute ASPI
python3 $PROJECT_ROOT/scripts/release/gate_check.py $SCAN_DIR --verbose
```

## Phase 6: Report

Provide the developer with:

1. **Findings triaged**: N total, N upgraded, N suppressed, N accepted
2. **ASPI impact**: Before vs after remediation
3. **Remaining risk**: Any CVEs without fix or suppression
4. **Recommendations**: Package alternatives, monitoring suggestions

## Quick Reference: Common Remediation Commands

```bash
# Upgrade all packages with available fixes
uv lock --upgrade

# Upgrade specific package only
uv lock --upgrade-package urllib3 --upgrade-package gitpython

# Check what version a fix requires
pip index versions <package> 2>/dev/null | head -5

# Verify suppression works
grep -c "vulnerability:" $PROJECT_ROOT/scripts/release/.grype.yaml

# Validate compensating controls are still valid
python3 $PROJECT_ROOT/scripts/release/compensating_controls.py validate
```

## Testing Strategy

After any CVE remediation (upgrade or suppression), validate with these tiers:

### Tier 1: Dependency Resolution (immediate)

```bash
# Verify lock file resolves cleanly
uv lock --check

# Verify no conflicts
uv pip compile pyproject.toml --quiet
```

### Tier 2: Unit Tests (required)

```bash
# Run priority unit tests (covers critical modules)
mkdir -p logs && nohup make validate-unit-priority > logs/cve_unit_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Tier 3: Integration Tests (if package is used in service code)

```bash
# If urllib3/aiohttp/requests upgraded — test HTTP paths
mkdir -p logs && nohup make validate-service-health > logs/cve_integration_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# If langchain-core/litellm upgraded — test LLM paths
mkdir -p logs && nohup make validate-response-api-tool-calls > logs/cve_llm_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Tier 4: ASPI Re-scan (required for release gate)

```bash
# Re-stage and scan (quick Grype-only for D8 verification)
make stage
python3 scripts/release/scan_grype.py /tmp/adept-release-stage-$(date +%Y%m%d) --format json > /tmp/grype_recheck.json
python3 scripts/release/gate_check.py /tmp/grype_recheck.json --verbose
```

### Tier 5: Compensating Control Validation (if suppressions added)

```bash
# Verify all compensating controls are structurally valid
python3 scripts/release/compensating_controls.py validate

# Verify .grype.yaml parses correctly
python3 -c "import yaml; yaml.safe_load(open('scripts/release/.grype.yaml'))"
```

## Documentation Updates

After completing CVE triage, update these documents:

### Required

1. **Sprint tracker** (`docs/implementation-sprints/SPRINT_FY26Q3_STATUS.md`):
   - Add CVE triage session entry with counts and ASPI delta

2. **CVE runbook** (`docs/security/CVE_2026_COPY_FAIL_DIRTY_FRAG_REMEDIATION.md` or new runbook):
   - Document any new Critical CVEs with full compensating control narrative

3. **`.grype.yaml`** (if suppressions added):
   - Follow the existing format: CVE ID, compensating control, evidence, risk acceptance, re-evaluate condition

4. **GitHub issues**:
   - Comment on #78 (CVE remediation) with findings and resolution
   - Comment on #79 (standalone ASOPB) if new patterns discovered

### Optional (if significant)

5. **Dependabot assessment** (`docs/security/DEPENDABOT_VULNERABILITY_ASSESSMENT_*.md`):
   - Cross-reference with GitHub Dependabot alerts

6. **CHANGELOG** (`docs/CHANGELOG.md`):
   - If package upgrades change behavior

## TruffleHog Unverified Findings

TruffleHog findings in D8 are typically false positives from documentation or example files. Triage approach:

1. Check if the file is in the staged release tree (if excluded by `.publish-exclude`, it's informational only)
2. Check if the "secret" is a placeholder, example, or documentation string
3. If real: rotate immediately and add to `.gitignore` or `.publish-exclude`
4. If false positive: add pattern to `fp_patterns.py` or specific path to allowlist

```bash
# Check if finding file is in staged tree
grep "<filename>" /tmp/adept-release-stage-*/file_list.txt 2>/dev/null

# Check .publish-exclude
grep "<path_pattern>" $PROJECT_ROOT/.publish-exclude
```
