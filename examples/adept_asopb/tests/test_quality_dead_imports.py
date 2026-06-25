"""Unit tests for asopb.quality.dead_imports library module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from asopb.quality.dead_imports import (
    ImportClassification,
    ParsedImport,
    ScanResult,
    classify_import,
    collect_fixture_names,
    collect_unused_imports,
    extract_symbol_from_message,
    find_symbol_globally,
    format_json,
    format_text,
    parse_import_at_line,
    resolve_module_path,
    run_analysis,
    symbol_exists_in_module,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_project():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        src = root / "src" / "pkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "module.py").write_text(
            "def active_function():\n    pass\n\n"
            "class ActiveClass:\n    pass\n"
        )
        (src / "other.py").write_text(
            "def moved_function():\n    pass\n"
        )

        tests = root / "tests"
        tests.mkdir()
        (tests / "test_example.py").write_text(
            "from pkg.module import active_function\n"
            "from pkg.module import deleted_function\n"
            "from pkg.module import moved_function\n"
            "from pkg.module import ActiveClass\n"
            "import os\n"
        )
        (tests / "conftest.py").write_text(
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def sample_fixture():\n"
            "    return 42\n\n"
            "@pytest.fixture(scope='session')\n"
            "def session_fixture():\n"
            "    return 'session'\n"
        )
        yield root


@pytest.fixture
def src_root(tmp_project):
    return tmp_project / "src"


@pytest.fixture
def tests_dir(tmp_project):
    return tmp_project / "tests"


# ─── Symbol Message Extraction ───────────────────────────────────────────────


class TestSymbolExtraction:
    def test_simple_symbol(self):
        assert extract_symbol_from_message("`foo` imported but unused") == "foo"

    def test_dotted_symbol(self):
        assert extract_symbol_from_message("`pkg.module.bar` imported but unused") == "bar"

    def test_no_match(self):
        assert extract_symbol_from_message("something else") is None

    def test_empty_string(self):
        assert extract_symbol_from_message("") is None


# ─── Import Parsing ──────────────────────────────────────────────────────────


class TestImportParsing:
    def test_from_import(self, tests_dir):
        test_file = str(tests_dir / "test_example.py")
        parsed = parse_import_at_line(test_file, 1)
        assert parsed is not None
        assert parsed.import_type == "from"
        assert parsed.module == "pkg.module"
        assert parsed.symbol == "active_function"

    def test_plain_import(self, tests_dir):
        test_file = str(tests_dir / "test_example.py")
        parsed = parse_import_at_line(test_file, 5)
        assert parsed is not None
        assert parsed.import_type == "import"
        assert parsed.symbol == "os"

    def test_nonexistent_line(self, tests_dir):
        test_file = str(tests_dir / "test_example.py")
        parsed = parse_import_at_line(test_file, 999)
        assert parsed is None

    def test_nonexistent_file(self):
        parsed = parse_import_at_line("/nonexistent/file.py", 1)
        assert parsed is None

    def test_syntax_error_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def broken(\n")
            f.flush()
            parsed = parse_import_at_line(f.name, 1)
            assert parsed is None


# ─── Module Resolution ───────────────────────────────────────────────────────


class TestModuleResolution:
    def test_resolve_package_module(self, src_root):
        path = resolve_module_path("pkg.module", src_root)
        assert path is not None
        assert path.name == "module.py"

    def test_resolve_package_init(self, src_root):
        path = resolve_module_path("pkg", src_root)
        assert path is not None
        assert path.name == "__init__.py"

    def test_resolve_nonexistent(self, src_root):
        path = resolve_module_path("nonexistent.module", src_root)
        assert path is None

    def test_resolve_empty_string(self, src_root):
        path = resolve_module_path("", src_root)
        assert path is None


# ─── Symbol Existence ────────────────────────────────────────────────────────


class TestSymbolExists:
    def test_function_exists(self, src_root):
        module = src_root / "pkg" / "module.py"
        assert symbol_exists_in_module(module, "active_function") is True

    def test_class_exists(self, src_root):
        module = src_root / "pkg" / "module.py"
        assert symbol_exists_in_module(module, "ActiveClass") is True

    def test_constant_exists(self, src_root):
        module = src_root / "pkg" / "module.py"
        module.write_text("MY_CONST = 42\n")
        assert symbol_exists_in_module(module, "MY_CONST") is True

    def test_symbol_not_found(self, src_root):
        module = src_root / "pkg" / "module.py"
        assert symbol_exists_in_module(module, "nonexistent") is False

    def test_reexported_symbol(self, src_root):
        init = src_root / "pkg" / "__init__.py"
        init.write_text("from pkg.module import active_function\n")
        assert symbol_exists_in_module(init, "active_function") is True

    def test_nonexistent_file(self):
        assert symbol_exists_in_module(Path("/nonexistent.py"), "foo") is False


# ─── Fixture Detection ───────────────────────────────────────────────────────


class TestFixtureDetection:
    def test_collects_fixtures(self, tests_dir):
        fixtures = collect_fixture_names(tests_dir)
        assert "sample_fixture" in fixtures
        assert "session_fixture" in fixtures

    def test_non_fixture_functions_excluded(self, tests_dir):
        (tests_dir / "conftest.py").write_text(
            "def helper():\n    pass\n"
        )
        fixtures = collect_fixture_names(tests_dir)
        assert "helper" not in fixtures

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as d:
            fixtures = collect_fixture_names(Path(d))
            assert fixtures == set()


# ─── Global Symbol Search ────────────────────────────────────────────────────


class TestGlobalSearch:
    def test_finds_symbol_in_src(self, src_root):
        locations = find_symbol_globally("active_function", src_root)
        assert len(locations) >= 1
        assert any("module.py" in loc for loc in locations)

    def test_symbol_not_in_src(self, src_root):
        locations = find_symbol_globally("nonexistent_symbol", src_root)
        assert locations == []

    def test_moved_function_found_elsewhere(self, src_root):
        locations = find_symbol_globally("moved_function", src_root)
        assert len(locations) >= 1
        assert any("other.py" in loc for loc in locations)


# ─── Classification ──────────────────────────────────────────────────────────


class TestClassification:
    def test_fixture_classified(self, src_root, tests_dir):
        finding = {"file": "test.py", "line": 1, "message": "`sample_fixture` imported but unused"}
        parsed = ParsedImport("from", "conftest", "sample_fixture")
        fixtures = collect_fixture_names(tests_dir)
        result = classify_import(finding, parsed, src_root, fixtures)
        assert result.classification == "FIXTURE"

    def test_unused_valid_classified(self, src_root):
        finding = {"file": "test.py", "line": 1, "message": "`active_function` imported but unused"}
        parsed = ParsedImport("from", "pkg.module", "active_function")
        result = classify_import(finding, parsed, src_root, set())
        assert result.classification == "UNUSED_VALID"

    def test_dead_import_classified(self, src_root):
        finding = {"file": "test.py", "line": 1, "message": "`deleted_function` imported but unused"}
        parsed = ParsedImport("from", "pkg.module", "deleted_function")
        result = classify_import(finding, parsed, src_root, set())
        assert result.classification == "DEAD"

    def test_moved_import_classified(self, src_root):
        finding = {"file": "test.py", "line": 1, "message": "`moved_function` imported but unused"}
        parsed = ParsedImport("from", "pkg.module", "moved_function")
        result = classify_import(finding, parsed, src_root, set())
        assert result.classification == "MOVED"
        assert "other.py" in result.suggestion

    def test_no_parsed_import_uses_message(self, src_root):
        finding = {"file": "test.py", "line": 1, "message": "`active_function` imported but unused"}
        result = classify_import(finding, None, src_root, set())
        assert result.symbol == "active_function"


# ─── Output Formatting ──────────────────────────────────────────────────────


class TestFormatting:
    def test_text_output_includes_counts(self):
        result = ScanResult(
            total_findings=3,
            dead=[ImportClassification("t.py", 1, "foo", "mod", "DEAD")],
            moved=[ImportClassification("t.py", 2, "bar", "mod", "MOVED", suggestion="Found at: other.py", found_at=["other.py"])],
            unused_valid=[ImportClassification("t.py", 3, "baz", "mod", "UNUSED_VALID")],
        )
        text = format_text(result)
        assert "Total F401 findings: 3" in text
        assert "DEAD:" in text
        assert "MOVED:" in text

    def test_json_output_parseable(self):
        result = ScanResult(
            total_findings=2,
            dead=[ImportClassification("t.py", 1, "foo", "mod", "DEAD")],
            moved=[ImportClassification("t.py", 2, "bar", "mod", "MOVED", found_at=["x.py"])],
        )
        output = format_json(result)
        data = json.loads(output)
        assert data["summary"]["total"] == 2
        assert data["summary"]["dead"] == 1
        assert data["summary"]["moved"] == 1
        assert len(data["dead_imports"]) == 1
        assert len(data["moved_imports"]) == 1

    def test_actionable_only_hides_detail_sections(self):
        result = ScanResult(
            total_findings=2,
            fixtures=[ImportClassification("t.py", 1, "fx", "mod", "FIXTURE")],
            unused_valid=[ImportClassification("t.py", 2, "uv", "mod", "UNUSED_VALID")],
        )
        text = format_text(result, actionable_only=True)
        assert "FIXTURE (ignored)" not in text
        assert "imports exist in source but unused in test" not in text

    def test_text_shows_fixtures_when_not_actionable_only(self):
        result = ScanResult(
            total_findings=1,
            fixtures=[ImportClassification("t.py", 1, "fx", "mod", "FIXTURE")],
        )
        text = format_text(result, actionable_only=False)
        assert "FIXTURE (ignored)" in text


# ─── Integration (mocked ruff) ──────────────────────────────────────────────


class TestIntegration:
    @patch("asopb.quality.dead_imports.collect_unused_imports")
    def test_run_analysis_empty(self, mock_collect, src_root, tests_dir):
        mock_collect.return_value = []
        result = run_analysis(str(tests_dir), src_root)
        assert result.total_findings == 0

    @patch("asopb.quality.dead_imports.collect_unused_imports")
    def test_run_analysis_classifies(self, mock_collect, tmp_project):
        src_root = tmp_project / "src"
        tests_dir = tmp_project / "tests"
        test_file = str(tests_dir / "test_example.py")

        mock_collect.return_value = [
            {"file": test_file, "line": 1, "message": "`active_function` imported but unused", "code": "F401"},
            {"file": test_file, "line": 2, "message": "`deleted_function` imported but unused", "code": "F401"},
            {"file": test_file, "line": 3, "message": "`moved_function` imported but unused", "code": "F401"},
        ]

        result = run_analysis(str(tests_dir), src_root)
        assert result.total_findings == 3
        classifications = {c.symbol: c.classification for c in
                          result.dead + result.moved + result.unused_valid + result.fixtures}
        assert classifications.get("active_function") == "UNUSED_VALID"
        assert classifications.get("deleted_function") == "DEAD"
        assert classifications.get("moved_function") == "MOVED"

    @patch("asopb.quality.dead_imports.collect_unused_imports")
    def test_run_analysis_detects_fixtures(self, mock_collect, tmp_project):
        tests_dir = tmp_project / "tests"
        src_root = tmp_project / "src"
        test_file = tests_dir / "test_fx.py"
        test_file.write_text("from conftest import sample_fixture\n")

        mock_collect.return_value = [
            {"file": str(test_file), "line": 1, "message": "`sample_fixture` imported but unused", "code": "F401"},
        ]

        result = run_analysis(str(tests_dir), src_root)
        assert result.total_findings == 1
        assert len(result.fixtures) == 1
        assert result.fixtures[0].symbol == "sample_fixture"
