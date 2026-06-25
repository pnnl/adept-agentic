"""Dead Import Cross-Reference Scanner — generic library module.

Detects test imports pointing to symbols that no longer exist in the source tree.
Standard linting (ruff F401) finds imports unused within a file but cannot detect
imports referencing functions/classes that have been renamed, moved, or deleted.

Two-phase analysis:
  Phase 1: Collect unused imports via ruff F401 (fast, low false-positive)
  Phase 2: Cross-reference each import against src/ to classify:
    - DEAD: symbol does not exist anywhere in src/
    - MOVED: symbol exists at a different module path
    - FIXTURE: pytest fixture (false positive from ruff)
    - UNUSED_VALID: symbol exists in source, just unused in the test file

This module contains the codebase-agnostic logic: data models, AST parsing, and
classification. The CLI layer lives in scripts/release/scan_dead_imports.py.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class ParsedImport:
    import_type: str  # "from" or "import"
    module: str
    symbol: str
    alias: Optional[str] = None


@dataclass
class ImportClassification:
    file: str
    line: int
    symbol: str
    original_module: str
    classification: Literal["DEAD", "MOVED", "FIXTURE", "UNUSED_VALID"]
    suggestion: Optional[str] = None
    found_at: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    total_findings: int = 0
    dead: list[ImportClassification] = field(default_factory=list)
    moved: list[ImportClassification] = field(default_factory=list)
    fixtures: list[ImportClassification] = field(default_factory=list)
    unused_valid: list[ImportClassification] = field(default_factory=list)


# ─── Phase 1: ruff F401 Collection ───────────────────────────────────────────


def collect_unused_imports(
    test_dir: str = "tests/",
    ruff_binary: str = "ruff",
) -> list[dict]:
    """Run ruff F401 on target directory and return findings."""
    try:
        result = subprocess.run(
            [ruff_binary, "check", test_dir, "--select", "F401",
             "--output-format", "json", "--quiet"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        print(f"ERROR: '{ruff_binary}' not found. Install with: pip install ruff", file=sys.stderr)
        sys.exit(2)
    except subprocess.TimeoutExpired:
        print("ERROR: ruff timed out after 60 seconds", file=sys.stderr)
        sys.exit(2)

    if not result.stdout:
        return []

    try:
        findings = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return [
        {
            "file": f.get("filename", ""),
            "line": f.get("location", {}).get("row", 0),
            "message": f.get("message", ""),
            "code": f.get("code", "F401"),
        }
        for f in findings
    ]


# ─── Phase 2a: Import Parsing ────────────────────────────────────────────────


def extract_symbol_from_message(message: str) -> Optional[str]:
    """Extract symbol name from ruff F401 message like '`foo` imported but unused'."""
    match = re.match(r"`([^`]+)`\s+imported but unused", message)
    if match:
        name = match.group(1)
        if "." in name:
            return name.split(".")[-1]
        return name
    return None


def parse_import_at_line(file_path: str, line_number: int) -> Optional[ParsedImport]:
    """Parse the import statement at a specific line in a file."""
    try:
        source = Path(file_path).read_text()
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return None

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if node.lineno != line_number:
            continue

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                return ParsedImport(
                    import_type="from",
                    module=module,
                    symbol=alias.name,
                    alias=alias.asname,
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                return ParsedImport(
                    import_type="import",
                    module=alias.name,
                    symbol=alias.name.split(".")[-1],
                    alias=alias.asname,
                )
    return None


# ─── Phase 2b: Module Resolution ─────────────────────────────────────────────


def resolve_module_path(module_dotpath: str, src_root: Path) -> Optional[Path]:
    """Resolve a dotted module path to a filesystem path under src_root."""
    if not module_dotpath:
        return None

    parts = module_dotpath.split(".")

    mod_path = src_root / "/".join(parts[:-1]) / f"{parts[-1]}.py" if len(parts) > 1 else src_root / f"{parts[0]}.py"
    if mod_path.exists():
        return mod_path

    pkg_path = src_root / "/".join(parts) / "__init__.py"
    if pkg_path.exists():
        return pkg_path

    for i in range(len(parts), 0, -1):
        candidate = src_root / "/".join(parts[:i])
        if candidate.with_suffix(".py").exists():
            return candidate.with_suffix(".py")
        if (candidate / "__init__.py").exists():
            return candidate / "__init__.py"

    return None


# ─── Phase 2c: Symbol Existence ──────────────────────────────────────────────


def symbol_exists_in_module(module_path: Path, symbol_name: str) -> bool:
    """Check if a symbol is defined in the given module file."""
    try:
        source = module_path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return False

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol_name:
                return True
        elif isinstance(node, ast.ClassDef):
            if node.name == symbol_name:
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol_name:
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol_name:
                return True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                effective_name = alias.asname or alias.name
                if effective_name == symbol_name:
                    return True
                if alias.name == symbol_name:
                    return True
    return False


# ─── Phase 2d: Fixture Detection ─────────────────────────────────────────────


def _is_pytest_fixture_decorator(decorator) -> bool:
    if isinstance(decorator, ast.Attribute):
        return decorator.attr == "fixture"
    if isinstance(decorator, ast.Call):
        return _is_pytest_fixture_decorator(decorator.func)
    if isinstance(decorator, ast.Name):
        return decorator.id == "fixture"
    return False


def collect_fixture_names(test_dir: Path) -> set[str]:
    """Collect all pytest fixture names from conftest.py files."""
    fixtures = set()
    for conftest in test_dir.rglob("conftest.py"):
        try:
            source = conftest.read_text()
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if _is_pytest_fixture_decorator(decorator):
                        fixtures.add(node.name)
    return fixtures


# ─── Phase 2e: Global Symbol Search ──────────────────────────────────────────


def find_symbol_globally(symbol_name: str, src_root: Path) -> list[str]:
    """Search all Python files under src_root for a symbol definition."""
    locations = []
    for py_file in src_root.rglob("*.py"):
        if symbol_exists_in_module(py_file, symbol_name):
            locations.append(str(py_file.relative_to(src_root)))
    return locations


# ─── Classification Engine ────────────────────────────────────────────────────


def classify_import(
    finding: dict,
    parsed: Optional[ParsedImport],
    src_root: Path,
    fixture_names: set[str],
) -> ImportClassification:
    """Classify a single unused import finding."""
    file_path = finding["file"]
    line = finding["line"]

    if parsed:
        symbol = parsed.symbol
        module = parsed.module
    else:
        symbol = extract_symbol_from_message(finding.get("message", "")) or "unknown"
        module = ""

    if symbol in fixture_names:
        return ImportClassification(file_path, line, symbol, module, "FIXTURE")

    if module:
        module_path = resolve_module_path(module, src_root)
        if module_path and symbol_exists_in_module(module_path, symbol):
            return ImportClassification(file_path, line, symbol, module, "UNUSED_VALID")

    global_locations = find_symbol_globally(symbol, src_root)
    if global_locations:
        return ImportClassification(
            file_path, line, symbol, module, "MOVED",
            suggestion=f"Found at: {', '.join(global_locations[:3])}",
            found_at=global_locations,
        )

    return ImportClassification(file_path, line, symbol, module, "DEAD")


# ─── Main Analysis ───────────────────────────────────────────────────────────


def run_analysis(
    test_dir: str = "tests/",
    src_root: Path = Path("src"),
    ruff_binary: str = "ruff",
) -> ScanResult:
    """Run full two-phase analysis and return classified results."""
    findings = collect_unused_imports(test_dir, ruff_binary)
    if not findings:
        return ScanResult()

    fixture_names = collect_fixture_names(Path(test_dir))
    result = ScanResult(total_findings=len(findings))

    for finding in findings:
        parsed = parse_import_at_line(finding["file"], finding["line"])
        classification = classify_import(finding, parsed, src_root, fixture_names)

        if classification.classification == "DEAD":
            result.dead.append(classification)
        elif classification.classification == "MOVED":
            result.moved.append(classification)
        elif classification.classification == "FIXTURE":
            result.fixtures.append(classification)
        else:
            result.unused_valid.append(classification)

    return result


# ─── Output Formatting ───────────────────────────────────────────────────────


def format_text(result: ScanResult, actionable_only: bool = False) -> str:
    """Format scan results as human-readable text."""
    lines = [
        "Dead Import Cross-Reference Report",
        "=" * 50,
        f"Total F401 findings: {result.total_findings}",
        f"  DEAD:         {len(result.dead):3d}  <- symbols no longer exist in source",
        f"  MOVED:        {len(result.moved):3d}  <- symbols exist at different path",
        f"  FIXTURE:      {len(result.fixtures):3d}  <- pytest fixture (false positive)",
        f"  UNUSED_VALID: {len(result.unused_valid):3d}  <- symbol exists, just unused in test",
        "",
    ]

    if result.dead:
        lines.append("DEAD IMPORTS (require action):")
        lines.append("-" * 50)
        for c in result.dead:
            lines.append(f"  {c.file}:{c.line}")
            lines.append(f"    from {c.original_module} import {c.symbol}")
            lines.append(f"    -> Symbol '{c.symbol}' not found anywhere in src/")
            lines.append("")

    if result.moved:
        lines.append("MOVED IMPORTS (suggest update):")
        lines.append("-" * 50)
        for c in result.moved:
            lines.append(f"  {c.file}:{c.line}")
            lines.append(f"    from {c.original_module} import {c.symbol}")
            lines.append(f"    -> {c.suggestion}")
            lines.append("")

    if not actionable_only:
        if result.fixtures:
            lines.append(f"FIXTURE (ignored): {len(result.fixtures)} imports are pytest fixtures")
        if result.unused_valid:
            lines.append(f"UNUSED_VALID: {len(result.unused_valid)} imports exist in source but unused in test")

    return "\n".join(lines)


def format_json(result: ScanResult) -> str:
    """Format scan results as JSON."""
    output = {
        "summary": {
            "total": result.total_findings,
            "dead": len(result.dead),
            "moved": len(result.moved),
            "fixture": len(result.fixtures),
            "unused_valid": len(result.unused_valid),
        },
        "dead_imports": [
            {"file": c.file, "line": c.line, "symbol": c.symbol,
             "module": c.original_module}
            for c in result.dead
        ],
        "moved_imports": [
            {"file": c.file, "line": c.line, "symbol": c.symbol,
             "module": c.original_module, "found_at": c.found_at}
            for c in result.moved
        ],
    }
    return json.dumps(output, indent=2)
