# Dead Import Cleanup Guide

## What It Does

The Dead Import Cross-Reference Scanner (`scripts/release/scan_dead_imports.py`) detects test imports that reference symbols no longer existing in the source tree. Standard linting (ruff F401) finds imports unused within a file, but cannot detect imports pointing to functions or classes that have been renamed, moved, or deleted from `src/`.

## When to Use

- After renaming or moving functions/classes in `src/`
- After deleting modules from `src/`
- Before a release (catches stale test mocks referencing deleted code)
- As part of CI gate checks (exit code 1 on DEAD imports)

## Quick Start

```bash
cd scripts/release

# Basic scan (all classifications)
python3 scan_dead_imports.py --target ../../tests/ --src ../../src/

# Show only actionable findings (hides FIXTURE and UNUSED_VALID)
python3 scan_dead_imports.py --target ../../tests/ --src ../../src/ --actionable-only

# JSON output for tooling
python3 scan_dead_imports.py --target ../../tests/ --src ../../src/ --format json

# Gate mode (exit 1 if DEAD imports found)
python3 scan_dead_imports.py --target ../../tests/ --src ../../src/ --gate
```

## Prerequisites

- Python 3.11+
- `ruff` installed (`pip install ruff` or available in `adept-session` conda env)
- Run from repo root or use `--target` and `--src` to specify paths

## How It Works

### Phase 1: Collect Unused Imports

Runs `ruff check --select F401` on the target directory (typically `tests/`) to find all unused imports. This is fast and has a low false-positive rate.

### Phase 2: Cross-Reference Classification

For each unused import, the scanner searches the source tree using AST parsing:

| Classification | Meaning | Action Required |
|---|---|---|
| `DEAD` | Symbol does not exist anywhere in `src/` | Fix or remove the import |
| `MOVED` | Symbol exists but at a different module path | Update the import path |
| `FIXTURE` | pytest fixture (ruff false positive) | None (informational) |
| `UNUSED_VALID` | Symbol exists in source, just unused in test file | Optional cleanup |

## Understanding the Output

### Text Output (default)

```
Dead Import Cross-Reference Report
====================================

DEAD IMPORTS (3)
  tests/unit/test_old_module.py:5
    from agentic_framework_pkg.core.old_helper import compute_hash
    Classification: DEAD — symbol 'compute_hash' does not exist in src/

  tests/unit/test_api.py:12
    from agentic_framework_pkg.agent_gateway.utils import validate_token_v1
    Classification: DEAD — symbol 'validate_token_v1' does not exist in src/

MOVED IMPORTS (1)
  tests/e2e/test_workflow.py:8
    from agentic_framework_pkg.mcp_server.tools import blast_search
    Classification: MOVED — found at agentic_framework_pkg.mcp_server.tools.bioinformatics_tools
    Suggestion: Update import to 'from agentic_framework_pkg.mcp_server.tools.bioinformatics_tools import blast_search'

Summary: 4 total (3 DEAD, 1 MOVED, 0 FIXTURE, 0 UNUSED_VALID)
```

### JSON Output

```json
{
  "total_findings": 4,
  "dead": [
    {
      "file": "tests/unit/test_old_module.py",
      "line": 5,
      "symbol": "compute_hash",
      "original_module": "agentic_framework_pkg.core.old_helper",
      "classification": "DEAD",
      "suggestion": null,
      "found_at": []
    }
  ],
  "moved": [...],
  "fixtures": [...],
  "unused_valid": [...]
}
```

## CLI Reference

```
usage: scan_dead_imports.py [-h] [--target PATH] [--src PATH]
                           [--actionable-only] [--format {text,json}]
                           [--gate] [--ruff-binary PATH]

Options:
  --target PATH        Directory to scan for imports (default: tests/)
  --src PATH           Source root to cross-reference against (default: src/)
  --actionable-only    Only show DEAD and MOVED (hide FIXTURE/UNUSED_VALID)
  --format {text,json} Output format (default: text)
  --gate               Exit with code 1 if any DEAD imports found
  --ruff-binary PATH   Path to ruff binary (default: ruff)
```

## Common Remediation Patterns

### DEAD Import

The symbol was deleted from source. The test import and likely the test itself are stale.

**Fix**: Remove the import. If the test references the symbol, either:
1. Delete the test (if it tested deleted functionality)
2. Update to test the replacement functionality

### MOVED Import

The symbol was moved to a different module (refactored).

**Fix**: Update the import path. The scanner provides a `suggestion` field with the new location.

```python
# Before (MOVED):
from agentic_framework_pkg.mcp_server.tools import blast_search

# After (fixed):
from agentic_framework_pkg.mcp_server.tools.bioinformatics_tools import blast_search
```

### FIXTURE (no action)

pytest fixtures imported via `conftest.py` or plugin mechanisms. ruff flags them as unused because they're injected by the test framework, not called directly.

### UNUSED_VALID (optional)

The symbol exists in source but isn't used in the test file. This often happens when:
- A test was partially rewritten but old imports weren't cleaned up
- The import was for a test that was commented out or deleted

**Fix**: Remove the import (standard linting cleanup). Not critical.

## Integration with CI

### GitHub Actions

The scanner runs as part of the ASOPB pre-release scan workflow. In CI, use gate mode:

```yaml
- name: Check for dead imports
  run: |
    python3 scripts/release/scan_dead_imports.py \
      --target tests/ --src src/ --gate --actionable-only
```

### Makefile Target

```bash
# From scripts/release/
make test-dead-imports  # Runs 34 unit tests for the scanner itself

# From project root (scan the actual codebase)
cd scripts/release && python3 scan_dead_imports.py --target ../../tests/ --src ../../src/ --gate
```

## Running Tests

The scanner has its own test suite:

```bash
# With conda (host)
conda run -n adept-session pytest scripts/release/tests/test_scan_dead_imports.py -v

# Expected: 34 tests pass
```

## Limitations

- Requires `ruff` to be installed (not included in scanner Docker image by default for Phase 1)
- Only scans Python files (`.py`)
- Cannot detect dynamic imports (`importlib.import_module(...)`)
- MOVED classification uses AST symbol name matching — if the symbol was renamed during the move, it will appear as DEAD instead of MOVED
- conftest.py session fixtures that call `git config --global` require git to be installed (use `conda run -n adept-session` on host, not deps-base container)
