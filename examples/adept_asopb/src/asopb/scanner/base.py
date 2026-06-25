"""
Scanner Base Class

Scanners are Layer 1 of the evaluation pipeline: fast, local, no external
dependencies.  They perform regex/AST-based fact extraction against the
codebase and produce structured ScanResult objects.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from asopb.logging import get_logger
from asopb.models import ScanFinding, ScanResult, Severity

_logger = get_logger(__name__)


@dataclass
class GrepMatch:
    """A single match from a regex search across the codebase."""
    file_path: str        # Relative to repo root
    line_number: int
    line_content: str
    match_text: str


class ScannerBase(ABC):
    """Abstract base for all codebase scanners.

    Subclasses implement `scan()` to extract domain-specific facts from the
    codebase.  Utility methods for grep, file finding, and reading are
    provided for convenience.
    """

    name: str = "base"
    description: str = ""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path.resolve()
        if not self.repo_path.is_dir():
            raise ValueError(f"Repository path does not exist: {self.repo_path}")
        _logger.debug(f"[{self.name}] initialized — repo_path={self.repo_path}")

    @abstractmethod
    async def scan(self) -> ScanResult:
        """Execute the scan and return structured findings."""
        ...

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    DEFAULT_EXCLUDE_DIRS = [
        # VCS
        ".git", ".svn", ".hg",
        # Python
        "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache",
        ".tox", "*.egg-info", ".eggs", ".nox", ".ruff_cache",
        # Node.js / TypeScript
        "node_modules", ".next", ".nuxt", ".turbo", ".parcel-cache",
        "bower_components",
        # Rust
        "target",
        # Go
        "vendor",
        # C / C++ / Fortran
        "CMakeFiles", ".ccache", "*.dSYM",
        # .NET / Visual Basic / C#
        "bin", "obj", "packages", ".vs",
        # Java / Kotlin
        ".gradle", ".mvn",
        # Build output (generic)
        "dist", "build", "out", "_build",
        # Data / logs / Docker
        "data", "logs", ".docker", "containerd",
        # IDE / editor
        ".idea", ".vscode",
        # Misc
        "*.pyc", "coverage", ".coverage", "htmlcov",
    ]

    BINARY_EXTENSIONS = frozenset([
        # Archives / packages
        ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zip", ".7z", ".rar",
        ".whl", ".egg", ".jar", ".war", ".ear",
        # Compiled / object
        ".so", ".dylib", ".dll", ".o", ".a", ".lib", ".pyc", ".pyo",
        ".class", ".exe", ".elf",
        # Images / media
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flac",
        # Data / serialized
        ".parquet", ".pkl", ".pickle", ".npy", ".npz", ".h5", ".hdf5",
        ".db", ".sqlite", ".sqlite3", ".lmdb", ".arrow", ".feather",
        # Fonts
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
        # ML model weights
        ".pt", ".pth", ".onnx", ".safetensors", ".ckpt",
        # Misc binary
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx",
        ".iso", ".img", ".vmdk", ".qcow2",
    ])

    # Size threshold: files above this are checked for binary content via null-byte heuristic
    _BINARY_CHECK_SAMPLE_SIZE = 8192

    @staticmethod
    def _is_binary(path: Path) -> bool:
        """Detect binary files by checking for null bytes in the first 8KB.

        This is the same heuristic used by git and grep. A text file renamed
        to .png will NOT be skipped — only truly binary content is excluded.
        """
        try:
            with open(path, "rb") as f:
                chunk = f.read(ScannerBase._BINARY_CHECK_SAMPLE_SIZE)
            return b"\x00" in chunk
        except OSError:
            return True

    def grep(
        self,
        pattern: str,
        *,
        glob: Optional[str] = None,
        ignore_case: bool = False,
        max_results: int = 500,
        exclude_dirs: Optional[list[str]] = None,
    ) -> list[GrepMatch]:
        """Regex search across the repository using ripgrep if available, else re."""
        exclude_dirs = exclude_dirs or self.DEFAULT_EXCLUDE_DIRS

        matches: list[GrepMatch] = []
        flags = re.IGNORECASE if ignore_case else 0
        compiled = re.compile(pattern, flags)

        files = self._walk_files(glob, exclude_dirs)
        files_searched = 0
        files_errored = 0
        t0 = time.perf_counter()
        _logger.debug(f"[{self.name}] grep: pattern={pattern!r}, {len(files)} files to search")

        for file_path in files:
            try:
                text = file_path.read_text(errors="replace")
            except (OSError, UnicodeDecodeError):
                files_errored += 1
                continue

            files_searched += 1
            for i, line in enumerate(text.splitlines(), start=1):
                m = compiled.search(line)
                if m:
                    rel_path = str(file_path.relative_to(self.repo_path))
                    matches.append(GrepMatch(
                        file_path=rel_path,
                        line_number=i,
                        line_content=line.strip(),
                        match_text=m.group(0),
                    ))
                    if len(matches) >= max_results:
                        elapsed = time.perf_counter() - t0
                        _logger.info(
                            f"[{self.name}] grep hit max_results={max_results} after "
                            f"{files_searched}/{len(files)} files — {elapsed:.2f}s"
                        )
                        return matches

        elapsed = time.perf_counter() - t0
        _logger.info(
            f"[{self.name}] grep complete: {len(matches)} matches in "
            f"{files_searched} files ({files_errored} errors) — {elapsed:.2f}s"
        )
        return matches

    def find_files(self, glob_pattern: str) -> list[Path]:
        """Find files matching a glob pattern relative to repo root."""
        return sorted(self.repo_path.glob(glob_pattern))

    def read_file(self, rel_path: str | Path, max_lines: int = 5000) -> Optional[str]:
        """Read a file's contents, returning None if not found."""
        full_path = self.repo_path / rel_path
        if not full_path.is_file():
            return None
        try:
            lines = full_path.read_text(errors="replace").splitlines()
            return "\n".join(lines[:max_lines])
        except OSError:
            return None

    def file_exists(self, rel_path: str | Path) -> bool:
        """Check if a file exists in the repo."""
        return (self.repo_path / rel_path).is_file()

    def dir_exists(self, rel_path: str | Path) -> bool:
        """Check if a directory exists in the repo."""
        return (self.repo_path / rel_path).is_dir()

    def count_files(self, glob_pattern: str) -> int:
        """Count files matching a glob pattern."""
        return len(self.find_files(glob_pattern))

    def _walk_files(
        self,
        glob_pattern: Optional[str] = None,
        exclude_dirs: Optional[list[str]] = None,
    ) -> list[Path]:
        """Walk the repo, optionally filtering by glob and excluding dirs."""
        exclude_dirs = set(exclude_dirs or self.DEFAULT_EXCLUDE_DIRS)

        t0 = time.perf_counter()
        if glob_pattern:
            candidates = self.find_files(glob_pattern)
        else:
            candidates = list(self.repo_path.rglob("*"))

        total = len(candidates)
        _logger.info(f"[{self.name}] _walk_files: {total} candidates (glob={glob_pattern!r})")

        results = []
        skipped_dir = 0
        skipped_nonfile = 0
        skipped_binary = 0
        for p in candidates:
            if not p.is_file():
                skipped_nonfile += 1
                continue
            parts = set(p.relative_to(self.repo_path).parts)
            if parts & exclude_dirs:
                skipped_dir += 1
                continue
            if p.suffix.lower() in self.BINARY_EXTENSIONS:
                skipped_binary += 1
                continue
            if p.stat().st_size > 1_000_000 and self._is_binary(p):
                skipped_binary += 1
                continue
            results.append(p)

        elapsed = time.perf_counter() - t0
        _logger.info(
            f"[{self.name}] _walk_files complete: "
            f"{len(results)} files kept, {skipped_dir} excluded (dir filter), "
            f"{skipped_binary} binary, {skipped_nonfile} non-files — {elapsed:.2f}s"
        )
        return results

    def _make_finding(
        self,
        category: str,
        message: str,
        *,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        snippet: Optional[str] = None,
        severity: Severity = Severity.MEDIUM,
        confidence: float = 0.8,
        metadata: Optional[dict] = None,
    ) -> ScanFinding:
        """Helper to construct a ScanFinding with auto-generated ID."""
        finding_id = f"{self.name}:{category}:{file_path or 'global'}:{line_number or 0}"
        return ScanFinding(
            finding_id=finding_id,
            category=category,
            severity=severity,
            file_path=file_path,
            line_number=line_number,
            message=message,
            snippet=snippet,
            confidence=confidence,
            metadata=metadata or {},
        )
