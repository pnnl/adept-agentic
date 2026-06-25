# CVE Triage Guide

## What It Does

The `/triage-cve` skill guides developers through investigating and remediating CVE findings from ASOPB security scans. It covers lookup, reachability analysis, and remediation (upgrade or suppress).

## When to Use

- After `/scan-release` or `/scan-path` reports CVE findings in D8
- When Pipeline ASPI is below gate threshold due to supply chain findings
- When `scanner_selftest.py` version parity check (category 9) flags CVEs on pinned versions
- During periodic dependency maintenance
- Before a release when new CVEs appear in `uv.lock`

## Quick Start

```bash
# 1. Find the latest scan output
SCAN_DIR=$(ls -td logs/scan-staged-* | head -1)

# 2. View D8 findings grouped by package
python3 -c "
import json
from pathlib import Path
grype = json.loads((Path('$SCAN_DIR') / 'pass_grype.json').read_text())
findings = grype.get('findings', [])
pkgs = {}
for f in findings:
    pkgs.setdefault(f.get('package','?'), []).append(f)
for pkg, cves in sorted(pkgs.items(), key=lambda x: -len(x[1])):
    sev = set(f.get('severity','?') for f in cves)
    fixed = set(f.get('fixed_version','?') for f in cves if f.get('fixed_version'))
    print(f'{pkg}: {len(cves)} CVEs [{\"|\".join(sev)}] fix={\"|\".join(fixed) or \"none\"}')"

# 3. Upgrade fixable packages
uv lock --upgrade-package urllib3 --upgrade-package gitpython

# 4. Verify resolution
make stage
python3 scripts/release/gate_check.py $(ls -td logs/scan-staged-* | head -1) --verbose
```

## Classification Taxonomy

| Classification | Criteria | Action |
|---------------|----------|--------|
| Upgradeable | Fix version exists, no breaking changes | `uv lock --upgrade-package <pkg>` |
| Upgradeable (breaking) | Fix requires major version bump | Test upgrade path, may need code changes |
| Not reachable | Vulnerable code path unused in ADEPT | Add to `.grype.yaml` with compensating control |
| Transitive only | Pulled by another dep, not directly used | Check if parent dep has update |
| No fix available | No patched version exists | Accept risk or find alternative |
| Accept risk | Low severity + mitigated by architecture | Document in `.grype.yaml` |

## Reachability Check Pattern

For each CVE, determine if the vulnerable code path is exercised:

```bash
# 1. Is it a direct dependency?
grep "<package>" pyproject.toml

# 2. If transitive, what pulls it in?
grep -B 20 "name = \"<package>\"" uv.lock | grep "name = " | tail -5

# 3. Is the vulnerable API used?
grep -rn "<VulnerableClass>" src/ examples/ --include="*.py"

# 4. Is the package exposed via ADEPT service endpoints?
grep -rn "from <package>\|import <package>" src/ --include="*.py" | grep -v __pycache__
# Map hits to service tier:
#   src/.../agent_gateway/          → Tier 1 (internet-facing) — HIGH risk
#   src/.../orchestration_service/  → Tier 2 (internal) — MEDIUM risk
#   src/.../mcp_server/             → Tier 3 (no inbound network) — LOW risk
#   scripts/release/                → Scanner only (air-gapped batch) — MINIMAL risk
```

A CVE in a library only used inside the scanner container (no inbound traffic, air-gapped)
is informational. A CVE in a library serving HTTP requests in Tier 1 is critical.

## Adding a Compensating Control

When a CVE is not reachable, suppress it in `.grype.yaml`:

```yaml
ignore:
  # CVE-XXXX-XXXXX | SEVERITY | package version_range | Title
  #
  # Compensating Control:
  #   <Why not exploitable — specific code path analysis>
  #
  # Evidence:
  #   <grep command and result>
  #
  # Risk Acceptance:
  #   Accepted by: <name> (<role>), <date>
  #   Condition: <when to re-evaluate>
  #
  - vulnerability: CVE-XXXX-XXXXX
    package:
      name: <package>
```

## Testing After Remediation

1. `uv lock --check` — dependency resolution
2. `make validate-unit-priority` — core functionality
3. `make validate-service-health` — if HTTP/LLM packages changed
4. `make stage && python3 scripts/release/gate_check.py ...` — ASPI re-check
5. `python3 scripts/release/compensating_controls.py validate` — if suppressions added

## ASPI Impact

- Critical CVEs: weight=40, catastrophic penalty (gate-failing)
- High/Medium/Low: weight=2.5 (unverified), minimal impact per-finding
- Volume penalty: `2.5 * ln(1 + count)` — logarithmic, not linear
- Example: 43 unverified findings = 10.6 point deduction from D8

## Related

- Scoring model: `docs/security/ASPI_SCORING_REFERENCE.md`
- Compensating controls: `docs/guides/COMPENSATING_CONTROLS_GUIDE.md`
- Grype config: `scripts/release/.grype.yaml`
- Skill: `.claude/skills/triage-cve/SKILL.md`
