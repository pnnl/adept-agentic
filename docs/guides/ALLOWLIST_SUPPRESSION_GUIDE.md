# Allowlist Suppression Guide

## What It Does

The Allowlist module (`asopb.quality.allowlist`) provides declarative category-level false positive suppression for ASOPB scanner findings. Rules are defined in `.asopb-allowlist.yaml` and evaluated post-scan to remove known false positives before scoring.

## When to Use

- When a scanner pass (ner_pii, secrets, trufflehog, toxicity, regex) generates repeatable false positives
- When the pattern is expressible as simple criteria (type, file glob, pattern substring, score threshold, entity length)
- When suppression should be auditable by non-developers (declarative YAML vs. Python code)
- NOT for patterns requiring algorithmic logic (use `fp_patterns.py` instead)
- NOT for one-off instance-level findings (use baseline `.asopb-baseline.json` instead)

## Quick Start

```bash
cd scripts/release

# Run pipeline with allowlist suppression
python3 scan_pipeline.py /tmp/adept-release-stage --passes regex --allowlist .asopb-allowlist.yaml

# Validate allowlist structure without running a scan
python3 -c "
from pathlib import Path
import sys; sys.path.insert(0, '../../examples/adept_asopb/src')
from asopb.quality.allowlist import load_allowlist, validate_allowlist

al = load_allowlist(Path('.asopb-allowlist.yaml'))
print(f'Loaded: {al.total_rules} rules, version={al.schema_version}, hash={al.content_hash[:16]}...')

issues = validate_allowlist(al)
errors = [i for i in issues if i.severity == 'ERROR']
warnings = [i for i in issues if i.severity == 'WARNING']
print(f'Validation: {len(errors)} errors, {len(warnings)} warnings')
for e in errors:
    print(f'  ERROR [{e.category}:{e.rule_index}]: {e.message}')
"
```

## Prerequisites

- Python 3.11+
- `pyyaml` and `pydantic` installed (available in `adept-session` conda env or scanner Docker image)
- `asopb` package installed or source tree available at `examples/adept_asopb/src/`

## Allowlist YAML Format

```yaml
# .asopb-allowlist.yaml
# Rules organized by scanner pass (category)
# Each rule suppresses findings matching ALL specified criteria (AND logic)
# First matching rule wins (evaluated in order)

ner_pii:
  - type: "PII:PASSWORD"
    file_patterns: ["*.py", "*.sh"]
    reason: "DeBERTa model cannot distinguish code syntax from passwords"

  - type: "PII:IBAN"
    reason: "Zero true positives — model misidentifies paths and hex strings"

  - type: "PII:USERNAME"
    max_entity_length: 4
    reason: "Model fragments code identifiers into false username detections"

  - type: "PII:EMAIL"
    pattern: "@example."
    reason: "RFC 2606 reserved example domains"

secrets:
  - pattern: "secretName:"
    reason: "Kubernetes secret resource name reference"

toxicity:
  - file_patterns: ["*.py", "*.sh"]
    min_score: 0.95
    reason: "Technical terms in code"

regex:
  - category: "institutional"
    file_patterns: ["LICENSE*", "pyproject.toml"]
    reason: "Required for DOE open-source release compliance"
```

## Rule Criteria Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Finding type must match exactly (e.g., "PII:PASSWORD") |
| `category` | string | Finding category must match exactly (e.g., "institutional") |
| `file_patterns` | list[str] | File path must match at least one glob (basename or full path) |
| `pattern` | string | Substring must appear in entity or content field |
| `min_score` | float (0.0-1.0) | Finding score must be >= this threshold |
| `max_entity_length` | int (>= 1) | Entity string length must be <= this value |
| `reason` | string (required) | Human-readable justification for suppression |

All specified criteria must match for a rule to suppress a finding (AND logic). Omitted criteria are not checked.

## How Matching Works

1. Pipeline produces raw findings per pass
2. For each finding, the engine iterates rules in the finding's pass category
3. Each rule checks all specified criteria against the finding
4. First matching rule suppresses the finding (annotated with `suppressed_by: "allowlist"`)
5. If no rule matches the finding's pass category, ALL categories are checked (cross-category matching)
6. Suppressed findings are moved to `result.suppressed_findings` (not counted toward ASPI score)
7. The allowlist content hash is recorded in the pipeline manifest for traceability

## Versioning and Integrity

| Field | Where | Purpose |
|-------|-------|---------|
| `schema_version` | `Allowlist.schema_version` | Tracks YAML format version (currently 1) |
| `content_hash` | `Allowlist.content_hash` | SHA-256 of YAML file content, computed at load time |
| `allowlist_hash` | `MatchResult.allowlist_hash` | Included in each suppression decision for audit trail |
| `allowlist_hash` | `PipelineResult.allowlist_hash` | Recorded in pipeline manifest for traceability |

The content hash enables:
- Detecting when rules changed between scans
- Tracing each suppression decision to a specific allowlist version
- Validating that scan results were produced with a known set of rules

## Adding a New Rule

1. Identify the false positive pattern (type, file pattern, content substring)
2. Choose the appropriate category section in `.asopb-allowlist.yaml`
3. Add the rule with all relevant criteria and a clear `reason`
4. Validate:
   ```bash
   python3 -c "
   from pathlib import Path
   import sys; sys.path.insert(0, '../../examples/adept_asopb/src')
   from asopb.quality.allowlist import load_allowlist, validate_allowlist
   issues = validate_allowlist(load_allowlist(Path('.asopb-allowlist.yaml')))
   assert not [i for i in issues if i.severity == 'ERROR'], f'Errors: {issues}'
   print('Allowlist valid')
   "
   ```
5. Test the rule against a scan to confirm it suppresses intended findings
6. Verify it does NOT suppress legitimate findings (check remaining active findings)

## Validation Checks

The validator detects:

| Issue | Severity | Description |
|-------|----------|-------------|
| Unknown category | WARNING | Category name not in (ner_pii, secrets, trufflehog, toxicity, regex) |
| Missing reason | ERROR | Rule has empty or missing `reason` field |
| No matching criteria | ERROR | Rule has no type, pattern, file_patterns, or category |
| Invalid min_score | ERROR | `min_score` outside [0.0, 1.0] range |
| Invalid max_entity_length | ERROR | `max_entity_length` less than 1 |

## Decision Tree: Which Layer?

```
Is the FP detectable only via Python logic (regex, context windows)?
  YES -> fp_patterns.py (Layer 1, programmatic)
  NO  |
      v
Can it be expressed as type + file_patterns + pattern + score/length?
  YES -> .asopb-allowlist.yaml (Layer 2, declarative) <-- THIS GUIDE
  NO  |
      v
Is it a verified FP too specific for a category rule?
  YES -> .asopb-baseline.json (Layer 3, instance-level)
  NO  |
      v
Is it an accepted risk requiring governance + expiration?
  YES -> compensating_controls manifest.json (Layer 4, governance)
```

## Library API Reference

```python
from asopb.quality.allowlist import (
    SCHEMA_VERSION,           # int: current schema version (1)
    Allowlist,                # Pydantic model: complete parsed allowlist
    AllowlistCategory,        # Pydantic model: named category with rules
    AllowlistRule,            # Pydantic model: single suppression rule
    MatchResult,              # Dataclass: match outcome with traceability
    ValidationIssue,          # Dataclass: validation error/warning
    compute_allowlist_hash,   # Compute SHA-256 of allowlist file
    load_allowlist,           # Parse YAML file -> Allowlist (or None)
    matches_finding,          # Check finding against allowlist rules
    validate_allowlist,       # Validate allowlist structure
)
```

## Pipeline Integration

```bash
# Full scan with allowlist suppression
python3 scan_pipeline.py /tmp/adept-release-stage \
  --passes all \
  --allowlist .asopb-allowlist.yaml \
  --output-dir /tmp/scan-results

# Output includes suppression summary:
#   Suppressed: 447 findings (allowlist hash: abe3bd5071a1...)
#     ner_pii: 320 suppressed
#     secrets: 95 suppressed
#     regex: 32 suppressed
```

## Related Documentation

- Architecture: `docs/architecture/ASOPB_SUPPRESSION_INFRASTRUCTURE.md`
- FP reduction plan: `docs/architecture/ASOPB_SCANNER_FALSE_POSITIVE_REDUCTION_PLAN.md`
- Compensating controls: `docs/guides/COMPENSATING_CONTROLS_GUIDE.md`
- Dead imports: `docs/guides/DEAD_IMPORT_CLEANUP_GUIDE.md`
- Library tests: `examples/adept_asopb/tests/test_quality_allowlist.py`
- CLI integration tests: `scripts/release/tests/test_scan_pipeline.py`
