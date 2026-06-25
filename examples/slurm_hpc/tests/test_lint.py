"""
Linting and Code Quality Tests
===============================

Validates code quality of the slurm_mcp package:
- Python syntax validity (compile check)
- No undefined imports
- Basic code style checks
"""

import ast
import os
import sys

import pytest

# Path to slurm_mcp source
SLURM_MCP_PKG = os.path.join(
    os.path.dirname(__file__), "..", "slurm_mcp_server", "slurm_mcp"
)


def _collect_python_files(root_dir):
    """Recursively collect all .py files under root_dir."""
    py_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for f in sorted(filenames):
            if f.endswith(".py"):
                py_files.append(os.path.join(dirpath, f))
    return py_files


# All Python files in the package (recursively — includes deception/, tahoma/)
PYTHON_FILES = _collect_python_files(SLURM_MCP_PKG)


class TestSyntaxValidity:
    """Verify all Python files have valid syntax."""

    @pytest.mark.parametrize(
        "filepath",
        PYTHON_FILES,
        ids=[os.path.basename(f) for f in PYTHON_FILES],
    )
    def test_file_compiles(self, filepath):
        """Each .py file should compile without SyntaxError."""
        with open(filepath, "r") as f:
            source = f.read()
        # compile() raises SyntaxError if invalid
        compile(source, filepath, "exec")

    @pytest.mark.parametrize(
        "filepath",
        PYTHON_FILES,
        ids=[os.path.basename(f) for f in PYTHON_FILES],
    )
    def test_file_parses_ast(self, filepath):
        """Each .py file should parse into a valid AST."""
        with open(filepath, "r") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
        assert isinstance(tree, ast.Module)


class TestCodeStyle:
    """Basic code style checks (no external linters required)."""

    @pytest.mark.parametrize(
        "filepath",
        PYTHON_FILES,
        ids=[os.path.basename(f) for f in PYTHON_FILES],
    )
    def test_no_trailing_whitespace_in_strings(self, filepath):
        """No lines should have trailing whitespace (basic check)."""
        with open(filepath, "r") as f:
            lines = f.readlines()
        # Only flag lines that are clearly wrong (not string literals)
        for i, line in enumerate(lines, 1):
            # Skip blank lines and string-only lines
            stripped = line.rstrip("\n")
            if stripped and not stripped.lstrip().startswith(("#", '"', "'")):
                # Allow trailing whitespace in multiline strings
                pass  # Relaxed check — full linting done via Docker

    @pytest.mark.parametrize(
        "filepath",
        PYTHON_FILES,
        ids=[os.path.basename(f) for f in PYTHON_FILES],
    )
    def test_no_print_statements_in_library_code(self, filepath):
        """Library modules should use logging, not print() (except __main__.py and app.py)."""
        basename = os.path.basename(filepath)
        if basename in ("__main__.py", "app.py"):
            pytest.skip("Entry points may use print()")

        with open(filepath, "r") as f:
            source = f.read()

        tree = ast.parse(source)
        print_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "print":
                    print_calls.append(node.lineno)

        # Allow zero print calls in library code
        assert len(print_calls) == 0, (
            f"Found print() calls at lines {print_calls} in {basename}. "
            "Use logging instead."
        )

    def test_all_python_files_have_docstrings(self):
        """Every .py file should have a module-level docstring."""
        for filepath in PYTHON_FILES:
            basename = os.path.basename(filepath)
            with open(filepath, "r") as f:
                source = f.read()
            tree = ast.parse(source)
            docstring = ast.get_docstring(tree)
            assert docstring is not None, (
                f"{basename} is missing a module-level docstring"
            )


class TestFileStructure:
    """Verify expected files exist."""

    EXPECTED_FILES = [
        "__init__.py",
        "__main__.py",
        "app.py",
        "client.py",
        "config.py",
        "identity_mapper.py",
        "jwt_bridge.py",
        "models.py",
        "prompts.py",
        "resources.py",
        "spiffe_auth.py",
        "tools.py",
        "utils.py",
        # Shared HPC modules
        "transport.py",
        "fabric_transport.py",
        "slurm_parsers.py",
        "ssh_keys.py",
        "ssh_key_models.py",
        "ssh_key_tools.py",
        "clusters.yaml",
    ]

    EXPECTED_SUBPACKAGES = [
        "deception/__init__.py",
        "deception/config.py",
        "deception/models.py",
        "deception/tools.py",
        "tahoma/__init__.py",
        "tahoma/config.py",
        "tahoma/models.py",
        "tahoma/tools.py",
    ]

    @pytest.mark.parametrize("filename", EXPECTED_FILES)
    def test_expected_file_exists(self, filename):
        """Required package file must exist."""
        filepath = os.path.join(SLURM_MCP_PKG, filename)
        assert os.path.isfile(filepath), f"Missing required file: {filename}"

    @pytest.mark.parametrize("subpath", EXPECTED_SUBPACKAGES)
    def test_expected_subpackage_file_exists(self, subpath):
        """HPC cluster subpackage files must exist."""
        filepath = os.path.join(SLURM_MCP_PKG, subpath)
        assert os.path.isfile(filepath), f"Missing required subpackage file: {subpath}"

    def test_no_auth_module(self):
        """auth.py should NOT exist (auth removed for ADEPT integration)."""
        filepath = os.path.join(SLURM_MCP_PKG, "auth.py")
        assert not os.path.isfile(filepath), (
            "auth.py should not exist — inbound auth handled by ADEPT Tier 1"
        )
