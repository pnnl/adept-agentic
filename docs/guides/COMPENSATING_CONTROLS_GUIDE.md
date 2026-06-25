# Compensating Controls Guide

## What It Does

The Compensating Control Fingerprint System (`scripts/release/compensating_controls.py`) provides integrity-verified false-positive suppression for the ASOPB scanner. Unlike simple allowlists, each suppression is anchored to a specific file + location + entity pattern with SHA-256 hashes that detect when the underlying file changes.

## When to Use

- After the ASOPB scan flags a finding you've verified as a false positive
- When a suppressed file is modified (the system detects staleness automatically)
- Before a release (validate all controls are still valid)
- In CI as a gate check (exit 1 if stale/invalidated controls exist)

## Quick Start

```bash
cd scripts/release

# Validate all controls against current codebase
python3 compensating_controls.py validate

# CI gate mode (fails on stale or invalidated)
python3 compensating_controls.py gate --fail-on stale,invalidated,expired

# List all controls with current status
python3 compensating_controls.py list --format table

# Add a new control
python3 compensating_controls.py add \
  --domain D5 --file src/pkg/module.py --line 42-50 \
  --entity "password_template" \
  --justification "Connection string template, not a real credential"

# Expire a control by ID
python3 compensating_controls.py expire D5-PWD-001 --reason "Module deleted in refactor"
```

## Prerequisites

- Python 3.11+
- `pydantic` installed (`pip install pydantic` or available in `adept-session` conda env)

## How It Works

### Fingerprint Model

Each compensating control stores:

| Field | Purpose |
|---|---|
| `control_id` | Unique ID (e.g., `D5-PWD-001`) |
| `domain` | ASOPB domain (`D5`, `D7`, or `D8`) |
| `file_path` | Relative path to the suppressed file |
| `location` | Line range (`start-end`) or regex pattern |
| `entity_pattern` | The suppressed entity/pattern text |
| `file_sha256` | SHA-256 of file contents at acceptance time |
| `fingerprint_hash` | Composite hash: `SHA-256(version|file_path|location|entity_pattern)` |
| `justification` | Why this is a false positive |
| `compensating_control` | What prevents misuse |
| `expiration_date` | Auto-expires after 90 days (configurable) |

### Validation Logic

When you run `validate`, the system checks each control in sequence:

1. **File existence** — Does the file still exist? If not: `invalidated` (CRITICAL)
2. **Expiration** — Has the expiration date passed? If yes: `expired` (WARNING)
3. **File hash** — Does the SHA-256 match? If not: `stale` (CRITICAL)
4. **Entity presence** — Is the pattern still at the specified location? If not: `invalidated` (CRITICAL)

If all checks pass: `active` (OK).

### Status Lifecycle

```
active → stale (file modified)
active → expired (past expiration_date)
active → invalidated (file deleted or entity moved)
```

## CLI Reference

### validate

Check all controls against the current codebase.

```bash
python3 compensating_controls.py validate [--repo-root PATH] [--manifest PATH] [--format text|json]
```

Exit codes: 0 = all OK, 1 = CRITICAL found, 2 = manifest missing/malformed.

### add

Create a new fingerprint entry. Automatically computes file hash and fingerprint.

```bash
python3 compensating_controls.py add \
  --domain D5|D7|D8 \
  --file PATH \
  --line START[-END] \
  --entity PATTERN \
  --justification TEXT \
  [--accepted-by NAME] \
  [--expiry-days N]
```

### list

Show all controls with their current validation status.

```bash
python3 compensating_controls.py list [--status active|stale|expired|invalidated] [--format table|json]
```

### expire

Mark a control as expired manually (before its auto-expiration date).

```bash
python3 compensating_controls.py expire CONTROL_ID [--reason TEXT]
```

### gate

CI gate mode. Exits 1 if any controls match the specified failure statuses.

```bash
python3 compensating_controls.py gate --fail-on stale,invalidated,expired [--format text|json]
```

### migrate

Convert entries from `.asopb-fp-suppressions.yaml` to fingerprinted manifest format.

```bash
python3 compensating_controls.py migrate [--source PATH] [--dry-run]
```

## Workflow: Adding a New Suppression

1. Run the ASOPB scan and identify a false positive:
   ```bash
   make docker-scan-staged
   python3 scripts/release/analyze_findings.py logs/scan-staged-*/ --actionable-only
   ```

2. Verify the finding is genuinely a false positive (not a real issue).

3. Add the compensating control:
   ```bash
   python3 compensating_controls.py add \
     --domain D5 \
     --file src/agentic_framework_pkg/core/secrets_manager.py \
     --line 45-52 \
     --entity "SECRET_FILE_PATH" \
     --justification "Path constant for secret file lookup, not a secret itself" \
     --accepted-by "paulrigor" \
     --expiry-days 90
   ```

4. Verify it was added:
   ```bash
   python3 compensating_controls.py list
   ```

5. Commit the updated manifest:
   ```bash
   git add scripts/release/.asopb-compensating-controls/manifest.json
   ```

## Workflow: Handling Stale Controls

When a file is modified, its hash changes and the control becomes `stale`:

```
$ python3 compensating_controls.py validate
CRITICAL: D5-PWD-001 — File modified (hash mismatch).
  Stored: 3a7f2b4c1d8e... Current: 9e1c4a5b2f3d...
```

**To resolve**:

1. Review the file change — does the entity still exist at the same location?
2. If yes (formatting change, unrelated edit): re-accept the control:
   ```bash
   python3 compensating_controls.py expire D5-PWD-001
   python3 compensating_controls.py add \
     --domain D5 --file <same-path> --line <same-range> \
     --entity <same-pattern> --justification <same-or-updated>
   ```
3. If no (entity moved or real finding now exists): expire and don't re-add:
   ```bash
   python3 compensating_controls.py expire D5-PWD-001 --reason "Entity removed in refactor"
   ```

## File Layout

```
scripts/release/
├── compensating_controls.py              # Main CLI + Pydantic models
├── .asopb-compensating-controls/
│   ├── manifest.json                     # Fingerprinted entries (source of truth)
│   └── schema.json                       # JSON Schema for CI validation
├── .asopb-fp-suppressions.yaml           # Legacy (frozen, backward compat)
└── tests/
    └── test_compensating_controls.py     # 32 unit tests
```

## Integration with Scan Pipeline

The compensating controls validator runs as a pre-scoring hook in `scan_pipeline.py`. When controls have CRITICAL integrity issues, advisory warnings are injected into the scan output (they don't directly affect ASPI, but are logged for review).

## Running Tests

```bash
# With conda (host)
conda run -n adept-session pytest scripts/release/tests/test_compensating_controls.py -v

# Expected: 32 tests pass
```

## Design Decisions

- **File hashes over line-based tracking**: Any modification to the file triggers re-review, even if the specific lines are unchanged. This is intentional — formatting tools (black, isort) will invalidate controls, which forces re-acceptance after format runs.
- **90-day expiration**: Controls auto-expire to force periodic review. Configurable via `--expiry-days`.
- **Category-level suppressions**: Some findings are category-wide (glob patterns). These use a sentinel hash value (`category-level-no-single-file`) since no single file hash applies.
- **Manifest over YAML**: The new `manifest.json` format supports structured validation. The legacy `.asopb-fp-suppressions.yaml` is preserved read-only for backward compatibility.
