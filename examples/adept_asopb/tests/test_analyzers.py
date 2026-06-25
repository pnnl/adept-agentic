"""
Unit tests for external tool analyzers.

Tests:
- AnalyzerBase interface
- is_available() checks with mocked shutil.which
- Graceful degradation when tools are missing
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanFinding, ScanResult, Severity


class MockDockerfileAnalyzer(AnalyzerBase):
    """Mock Dockerfile analyzer for testing."""

    name = "dockerfile"
    description = "Analyzes Dockerfile for security issues"
    tool_command = "dockerfile-lint"

    async def analyze(self) -> ScanResult:
        """Mock analyze implementation."""
        if not self.is_available():
            return self._make_result(
                success=False,
                error_message="dockerfile-lint not installed",
            )

        findings = [
            ScanFinding(
                finding_id="dockerfile:1",
                category="privileged_flag",
                severity=Severity.HIGH,
                message="privileged: true found",
                file_path="docker-compose.yaml",
                line_number=10,
            ),
        ]

        return self._make_result(success=True, findings=findings)


class MockTLSAnalyzer(AnalyzerBase):
    """Mock TLS analyzer for testing."""

    name = "tls"
    description = "Analyzes TLS/SSL configuration"
    tool_command = "tls-checker"

    async def analyze(self) -> ScanResult:
        """Mock analyze implementation."""
        if not self.is_available():
            return self._make_result(
                success=False,
                error_message="tls-checker not installed",
            )

        findings = [
            ScanFinding(
                finding_id="tls:1",
                category="verify_false",
                severity=Severity.HIGH,
                message="verify=False in requests",
                file_path="src/client.py",
                line_number=45,
            ),
            ScanFinding(
                finding_id="tls:2",
                category="verify_false",
                severity=Severity.HIGH,
                message="InsecureSkipVerify in HTTP client",
                file_path="src/api.py",
                line_number=100,
            ),
        ]

        return self._make_result(success=True, findings=findings)


class TestAnalyzerBase:
    """Tests for AnalyzerBase interface."""

    def test_analyzer_initialization(self, tmp_path: Path):
        """Test analyzer initialization."""
        analyzer = MockDockerfileAnalyzer(tmp_path, timeout=300)

        assert analyzer.name == "dockerfile"
        assert analyzer.tool_command == "dockerfile-lint"
        assert analyzer.timeout == 300

    def test_analyzer_custom_timeout(self, tmp_path: Path):
        """Test custom timeout setting."""
        analyzer = MockDockerfileAnalyzer(tmp_path, timeout=600)

        assert analyzer.timeout == 600

    def test_analyzer_default_timeout(self, tmp_path: Path):
        """Test default timeout."""
        analyzer = MockDockerfileAnalyzer(tmp_path)

        assert analyzer.timeout == 300


class TestAnalyzerAvailability:
    """Tests for analyzer tool availability checking."""

    @patch("shutil.which")
    def test_is_available_tool_installed(self, mock_which, tmp_path: Path):
        """Test is_available when tool is installed."""
        mock_which.return_value = "/usr/bin/dockerfile-lint"

        analyzer = MockDockerfileAnalyzer(tmp_path)
        assert analyzer.is_available() is True

    @patch("shutil.which")
    def test_is_available_tool_not_installed(self, mock_which, tmp_path: Path):
        """Test is_available when tool is not installed."""
        mock_which.return_value = None

        analyzer = MockDockerfileAnalyzer(tmp_path)
        assert analyzer.is_available() is False

    @patch("shutil.which")
    def test_is_available_no_tool_command(self, mock_which, tmp_path: Path):
        """Test is_available when tool_command is not set."""

        class NoCommandAnalyzer(AnalyzerBase):
            name = "base"
            tool_command = ""

            async def analyze(self) -> ScanResult:
                return self._make_result()

        analyzer = NoCommandAnalyzer(tmp_path)
        assert analyzer.is_available() is False


class TestAnalyzerResults:
    """Tests for analyzer result creation."""

    def test_make_result_success(self, tmp_path: Path):
        """Test creating successful result."""
        analyzer = MockDockerfileAnalyzer(tmp_path)

        findings = [
            ScanFinding(
                finding_id="test:1",
                category="test",
                message="Test finding",
            ),
        ]

        result = analyzer._make_result(success=True, findings=findings)

        assert result.tool_name == "dockerfile"
        assert result.success is True
        assert len(result.findings) == 1
        assert result.error_message is None

    def test_make_result_failure(self, tmp_path: Path):
        """Test creating failed result."""
        analyzer = MockDockerfileAnalyzer(tmp_path)

        result = analyzer._make_result(
            success=False,
            error_message="Tool crashed",
        )

        assert result.success is False
        assert result.error_message == "Tool crashed"
        assert len(result.findings) == 0

    def test_make_result_with_metadata(self, tmp_path: Path):
        """Test creating result with metadata."""
        analyzer = MockDockerfileAnalyzer(tmp_path)

        result = analyzer._make_result(
            success=True,
            findings=[],
            raw_output="Tool output here",
            duration=15.5,
            tool_version="1.2.3",
        )

        assert result.raw_output == "Tool output here"
        assert result.duration_seconds == 15.5
        assert result.tool_version == "1.2.3"


class TestAnalyzerGracefulDegradation:
    """Tests for graceful degradation when tools are unavailable."""

    @pytest.mark.asyncio
    @patch("shutil.which")
    async def test_analyze_tool_unavailable(self, mock_which, tmp_path: Path):
        """Test analyze gracefully handles missing tools."""
        mock_which.return_value = None

        analyzer = MockDockerfileAnalyzer(tmp_path)
        result = await analyzer.analyze()

        assert result.success is False
        assert "dockerfile-lint not installed" in result.error_message
        assert len(result.findings) == 0

    @pytest.mark.asyncio
    @patch("shutil.which")
    async def test_analyze_tool_available(self, mock_which, tmp_path: Path):
        """Test analyze succeeds when tool is available."""
        mock_which.return_value = "/usr/bin/dockerfile-lint"

        analyzer = MockDockerfileAnalyzer(tmp_path)
        result = await analyzer.analyze()

        assert result.success is True
        assert len(result.findings) == 1

    @pytest.mark.asyncio
    @patch("shutil.which")
    async def test_multiple_findings(self, mock_which, tmp_path: Path):
        """Test analyzer with multiple findings."""
        mock_which.return_value = "/usr/bin/tls-checker"

        analyzer = MockTLSAnalyzer(tmp_path)
        result = await analyzer.analyze()

        assert result.success is True
        assert len(result.findings) == 2
        assert all(f.category == "verify_false" for f in result.findings)


class TestAnalyzerParsing:
    """Tests for analyzing and parsing tool output."""

    def test_parse_json_output_valid(self, tmp_path: Path):
        """Test parsing valid JSON output."""
        analyzer = MockDockerfileAnalyzer(tmp_path)

        json_str = '{"key": "value", "count": 42}'
        parsed = analyzer._parse_json_output(json_str)

        assert parsed == {"key": "value", "count": 42}

    def test_parse_json_output_invalid(self, tmp_path: Path):
        """Test parsing invalid JSON returns None."""
        analyzer = MockDockerfileAnalyzer(tmp_path)

        json_str = "not valid json"
        parsed = analyzer._parse_json_output(json_str)

        assert parsed is None

    def test_parse_json_output_empty(self, tmp_path: Path):
        """Test parsing empty JSON returns None."""
        analyzer = MockDockerfileAnalyzer(tmp_path)

        parsed = analyzer._parse_json_output("")
        assert parsed is None


class TestAnalyzerRegistry:
    """Tests for analyzer discovery and registration."""

    @pytest.mark.asyncio
    async def test_multiple_analyzers(self, tmp_path: Path):
        """Test running multiple different analyzers."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/tool"

            dockerfile_analyzer = MockDockerfileAnalyzer(tmp_path)
            tls_analyzer = MockTLSAnalyzer(tmp_path)

            dockerfile_result = await dockerfile_analyzer.analyze()
            tls_result = await tls_analyzer.analyze()

            assert dockerfile_result.tool_name == "dockerfile"
            assert tls_result.tool_name == "tls"
            assert len(dockerfile_result.findings) > 0
            assert len(tls_result.findings) > 0
