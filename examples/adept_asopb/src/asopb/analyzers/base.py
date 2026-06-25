"""
Analyzer Base Class

Analyzers are Layer 2 of the evaluation pipeline: they run external security
tools (GitXRay, Semgrep, Bandit, pip-audit, etc.) against the codebase and
parse their output into structured ScanResult objects.

Each analyzer is optional — if the external tool is not installed, the
analyzer reports itself as unavailable and the evaluation gracefully degrades.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from asopb.models import ScanResult


class AnalyzerBase(ABC):
    """Abstract base for all external tool analyzers."""

    name: str = "base"
    description: str = ""
    tool_command: str = ""    # e.g., "semgrep", "bandit", "pip-audit"

    def __init__(self, repo_path: Path, timeout: int = 300):
        self.repo_path = repo_path.resolve()
        self.timeout = timeout

    def is_available(self) -> bool:
        """Check if the external tool is installed and accessible."""
        if not self.tool_command:
            return False
        return shutil.which(self.tool_command) is not None

    @abstractmethod
    async def analyze(self) -> ScanResult:
        """Run the external tool and return parsed results.

        Implementations should:
        1. Construct the command with appropriate flags
        2. Call self.run_command() to execute
        3. Parse the output into ScanFinding objects
        4. Return a ScanResult
        """
        ...

    async def run_command(
        self,
        cmd: list[str],
        *,
        cwd: Optional[Path] = None,
        env: Optional[dict] = None,
        capture_stderr: bool = True,
    ) -> tuple[int, str, str]:
        """Execute an external tool with timeout.

        Returns:
            (return_code, stdout, stderr)
        """
        cwd = cwd or self.repo_path

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE if capture_stderr else None,
                env=env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout,
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            return proc.returncode or 0, stdout, stderr

        except asyncio.TimeoutError:
            proc.kill()
            return -1, "", f"Timeout after {self.timeout}s"
        except FileNotFoundError:
            return -1, "", f"Command not found: {cmd[0]}"
        except Exception as e:
            return -1, "", str(e)

    def _make_result(
        self,
        success: bool = True,
        error_message: Optional[str] = None,
        findings: Optional[list] = None,
        raw_output: Optional[str] = None,
        duration: Optional[float] = None,
        **kwargs,
    ) -> ScanResult:
        """Helper to construct a ScanResult."""
        return ScanResult(
            tool_name=self.name,
            success=success,
            error_message=error_message,
            findings=findings or [],
            raw_output=raw_output,
            duration_seconds=duration,
            **kwargs,
        )

    def _parse_json_output(self, output: str) -> Optional[dict]:
        """Safely parse JSON output from a tool."""
        try:
            return json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return None
