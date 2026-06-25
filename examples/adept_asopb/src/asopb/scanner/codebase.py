"""
Codebase Scanner

Maps repository structure, detects languages, counts files, identifies frameworks,
and detects Docker presence and version information.
"""

from __future__ import annotations

import re
from pathlib import Path

from asopb.models import ScanResult, Severity
from asopb.scanner.base import ScannerBase


class CodebaseScanner(ScannerBase):
    """Analyzes codebase structure and framework presence.

    Detects:
    - Programming languages and file distributions
    - Framework presence (LangChain, AutoGen, CrewAI, LangGraph)
    - Docker/containerization
    - Version information (git tags, package.json, pyproject.toml, etc.)
    - Chapter/module organization
    """

    name = "codebase"
    description = "Codebase structure and framework detection"

    # Language file patterns
    LANGUAGE_PATTERNS = {
        "Python": ["**/*.py"],
        "JavaScript": ["**/*.js", "**/*.jsx"],
        "TypeScript": ["**/*.ts", "**/*.tsx"],
        "Go": ["**/*.go"],
        "Rust": ["**/*.rs"],
        "Java": ["**/*.java"],
        "C++": ["**/*.cpp", "**/*.cc", "**/*.h"],
        "C#": ["**/*.cs"],
    }

    # Framework detection patterns
    FRAMEWORK_PATTERNS = {
        "langchain": [
            r"from langchain",
            r"import langchain",
            r'"langchain"',
            r"'langchain'",
            r"langchain==",
            r"LangChain",
        ],
        "autogen": [
            r"import autogen",
            r"from autogen",
            r"pyautogen",
            r"AutoAgent",
            r'"autogen"',
        ],
        "crewai": [
            r"from crewai",
            r"import crewai",
            r"crewai_agent",
            r"CrewBase",
            r'"crewai"',
        ],
        "langgraph": [
            r"from langgraph",
            r"import langgraph",
            r"StateGraph",
            r"langgraph_agent",
            r'"langgraph"',
        ],
        "anthropic_sdk": [
            r"from anthropic",
            r"import anthropic",
            r"import Anthropic",
            r'"anthropic"',
            r"Anthropic\(",
        ],
        "openai_sdk": [
            r"from openai",
            r"import openai",
            r"from openai import",
            r'"openai"',
            r"OpenAI\(",
        ],
    }

    # Docker/container patterns
    CONTAINER_PATTERNS = {
        "dockerfile": ["Dockerfile", "Dockerfile.*"],
        "docker_compose": ["docker-compose.yml", "docker-compose.yaml"],
        "dockerignore": [".dockerignore"],
        "sandbox_dockerfile": ["Dockerfile.sandbox", "Dockerfile.*sandbox"],
    }

    # Version file patterns
    VERSION_PATTERNS = {
        "package.json": "package.json",
        "pyproject.toml": "pyproject.toml",
        "setup.py": "setup.py",
        "go.mod": "go.mod",
        "Cargo.toml": "Cargo.toml",
        "pom.xml": "pom.xml",
        ".git": ".git",
    }

    async def scan(self) -> ScanResult:
        """Execute codebase structure scan."""
        result = ScanResult(
            tool_name=self.name,
            tool_version="1.0.0",
        )

        try:
            # Analyze language distribution
            language_stats = self._analyze_languages()

            # Detect frameworks
            frameworks = self._detect_frameworks()

            # Check for Docker
            docker_files = self._find_container_files()

            # Extract version info
            version_info = self._extract_version_info()

            # Detect directory structure (chapters/modules)
            structure = self._analyze_structure()

            # Store findings
            result.summary_stats = {
                "languages": language_stats,
                "frameworks": frameworks,
                "container_files": docker_files,
                "version_info": version_info,
                "directory_structure": structure,
                "total_files": sum(language_stats.values()),
            }

            result.success = True

        except Exception as e:
            result.success = False
            result.error_message = str(e)

        return result

    def _analyze_languages(self) -> dict[str, int]:
        """Count files by programming language."""
        stats = {}
        for lang, patterns in self.LANGUAGE_PATTERNS.items():
            count = 0
            for pattern in patterns:
                count += self.count_files(pattern)
            if count > 0:
                stats[lang] = count
        return stats

    def _detect_frameworks(self) -> dict[str, bool]:
        """Detect presence of major frameworks via imports and dependencies."""
        frameworks = {}

        for framework, patterns in self.FRAMEWORK_PATTERNS.items():
            detected = False
            for pattern in patterns:
                matches = self.grep(
                    pattern,
                    glob="**/*.py",
                    ignore_case=True,
                    max_results=1,
                )
                if matches:
                    detected = True
                    break

            # Also check in requirements files
            if not detected:
                for req_file in ["requirements.txt", "setup.py", "pyproject.toml"]:
                    if self.file_exists(req_file):
                        content = self.read_file(req_file)
                        if content:
                            for pattern in patterns:
                                if re.search(
                                    pattern,
                                    content,
                                    re.IGNORECASE,
                                ):
                                    detected = True
                                    break
                    if detected:
                        break

            frameworks[framework] = detected

        return frameworks

    def _find_container_files(self) -> dict[str, list[str]]:
        """Find Docker and containerization files."""
        results = {}

        for container_type, patterns in self.CONTAINER_PATTERNS.items():
            found_files = []
            for pattern in patterns:
                found_files.extend(
                    [str(p.relative_to(self.repo_path)) for p in self.find_files(pattern)]
                )
            if found_files:
                results[container_type] = found_files

        return results

    def _extract_version_info(self) -> dict[str, str]:
        """Extract version information from various sources."""
        info = {}

        # Check pyproject.toml for version
        if self.file_exists("pyproject.toml"):
            content = self.read_file("pyproject.toml", max_lines=100)
            if content:
                m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                if m:
                    info["python_version"] = m.group(1)

        # Check package.json for version
        if self.file_exists("package.json"):
            content = self.read_file("package.json", max_lines=100)
            if content:
                m = re.search(r'"version"\s*:\s*"([^"]+)"', content)
                if m:
                    info["node_version"] = m.group(1)

        # Check for git tag
        if self.dir_exists(".git"):
            # Try to read git HEAD
            git_head = self.repo_path / ".git" / "HEAD"
            if git_head.is_file():
                try:
                    head_content = git_head.read_text().strip()
                    if head_content.startswith("ref:"):
                        info["git_ref"] = head_content.split("/")[-1]
                except OSError:
                    pass

        # Check for version files
        for version_file in ["VERSION", "version.txt", ".version"]:
            if self.file_exists(version_file):
                content = self.read_file(version_file, max_lines=10)
                if content:
                    info["version_file"] = content.strip().split("\n")[0]
                    break

        return info

    def _analyze_structure(self) -> dict[str, int]:
        """Analyze directory structure (chapters, modules, components)."""
        structure = {}

        # Count top-level directories (potential chapters/modules)
        try:
            for item in self.repo_path.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    # Count files in this directory
                    file_count = sum(
                        1 for _ in item.rglob("*") if _.is_file()
                    )
                    if file_count > 0:
                        structure[item.name] = file_count
        except OSError:
            pass

        return structure
