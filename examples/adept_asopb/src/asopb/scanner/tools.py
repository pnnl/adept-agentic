"""
Tools Scanner

Detects MCP/tool registration patterns, ACL filtering, scoping mechanisms,
and command injection vectors.
"""

from __future__ import annotations

import re

from asopb.models import ScanResult, Severity
from asopb.scanner.base import ScannerBase


class ToolScanner(ScannerBase):
    """Detects tool/function registration and security patterns.

    Identifies:
    - Tool registration calls and patterns
    - ACL/access control filtering
    - Per-caller tool scoping
    - Flat tool lists (potential consolidation risks)
    - Tool-to-agent binding
    - Command injection vectors
    - Subprocess calls with unsafe shell=True
    - Tool discovery and introspection patterns
    """

    name = "tools"
    description = "Tool registration and MCP pattern detection"

    # Tool registration patterns
    TOOL_REGISTRATION_PATTERNS = [
        r"register_tool\(",
        r"register_tools\(",
        r"register_function\(",
        r"@tool",
        r"@function",
        r"@mcp\.tool",
        r"define_tool\(",
        r"add_tool\(",
        r"tools\.append\(",
        r"tools\.register\(",
        r"ToolRegistry\(",
        r"ToolProvider",
        r"def\s+register.*tool",
    ]

    # ACL/access control patterns
    ACL_PATTERNS = [
        r"acl",
        r"access_list",
        r"check_acl",
        r"verify_acl",
        r"acl_filter",
        r"allowed_tools",
        r"allowed_functions",
        r"forbidden_tools",
        r"tool_whitelist",
        r"tool_blacklist",
        r"caller_permissions",
        r"check_permission",
        r"has_access",
        r"is_allowed",
    ]

    # Per-caller scoping patterns
    SCOPING_PATTERNS = [
        r"per_caller",
        r"per_user",
        r"caller_id",
        r"user_id.*tool",
        r"scoped.*tool",
        r"caller_tools",
        r"user_tools",
        r"filter.*caller",
        r"filter.*user",
        r"get_tools.*caller",
        r"get_tools.*user",
    ]

    # Flat tool list patterns
    FLAT_TOOLS_PATTERNS = [
        r"ALL_TOOLS\s*=",
        r"TOOLS\s*=\s*\[",
        r"tools\s*=\s*\[.*\]",
        r"tool_list\s*=\s*\[",
        r"available_tools\s*=\s*\[",
    ]

    # Tool-to-agent binding patterns
    BINDING_PATTERNS = [
        r"agent\.tools\s*=",
        r"bind_tools\(",
        r"set_tools\(",
        r"agent_tools",
        r"tools_for_agent",
        r"agent_capabilities",
        r"capability_binding",
    ]

    # Command injection vectors
    COMMAND_INJECTION_PATTERNS = [
        r"subprocess\s*\.\s*run\([^)]*shell\s*=\s*True",
        r"os\.system\(",
        r"os\.popen\(",
        r"exec\(",
        r"eval\(",
        r"compile\(",
        r"__import__\(",
        r"importlib\.import_module\(.*f['\"]",
        r"shell\s*=\s*True",
        r"shell.*=.*True",
    ]

    # Subprocess safety checks
    SUBPROCESS_SAFE_PATTERNS = [
        r"shell\s*=\s*False",
        r"check\s*=\s*True",
        r"subprocess\.run\(\s*\[",
        r"subprocess\.check_call\(\s*\[",
        r"shlex\.quote",
        r"shlex\.split",
    ]

    # Tool discovery/introspection patterns
    DISCOVERY_PATTERNS = [
        r"list_tools\(",
        r"get_tools\(",
        r"discover_tools",
        r"introspect",
        r"list_capabilities",
        r"get_available",
        r"tool_schema",
        r"tool_metadata",
        r"__all__\s*=",
    ]

    async def scan(self) -> ScanResult:
        """Execute tools scanner."""
        result = ScanResult(
            tool_name=self.name,
            tool_version="1.0.0",
        )

        findings = []
        stats = {
            "tool_registrations": 0,
            "acl_patterns": 0,
            "scoped_tools": 0,
            "flat_tool_lists": 0,
            "tool_bindings": 0,
            "command_injection_vectors": 0,
            "unsafe_subprocess": 0,
            "safe_subprocess": 0,
            "discovery_patterns": 0,
        }

        try:
            # Tool registration detection
            registration_matches = self.grep(
                "|".join(self.TOOL_REGISTRATION_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["tool_registrations"] = len(registration_matches)
            for match in registration_matches[:5]:
                findings.append(
                    self._make_finding(
                        "tool_registration",
                        f"Tool registration pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # ACL detection
            acl_matches = self.grep(
                "|".join(self.ACL_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["acl_patterns"] = len(acl_matches)
            for match in acl_matches[:5]:
                findings.append(
                    self._make_finding(
                        "acl_filtering",
                        f"ACL/access control pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Per-caller scoping
            scoping_matches = self.grep(
                "|".join(self.SCOPING_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["scoped_tools"] = len(scoping_matches)
            for match in scoping_matches[:3]:
                findings.append(
                    self._make_finding(
                        "per_caller_scoping",
                        f"Per-caller scoping pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Flat tool list detection (potential risk)
            flat_matches = self.grep(
                "|".join(self.FLAT_TOOLS_PATTERNS),
                glob="**/*.py",
                ignore_case=False,
            )
            stats["flat_tool_lists"] = len(flat_matches)
            for match in flat_matches[:5]:
                findings.append(
                    self._make_finding(
                        "flat_tool_list",
                        f"Flat tool list (may need scoping): {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.MEDIUM,
                        confidence=0.7,
                    )
                )

            # Tool-to-agent binding
            binding_matches = self.grep(
                "|".join(self.BINDING_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["tool_bindings"] = len(binding_matches)
            for match in binding_matches[:3]:
                findings.append(
                    self._make_finding(
                        "tool_binding",
                        f"Tool binding pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Command injection vectors
            injection_matches = self.grep(
                "|".join(self.COMMAND_INJECTION_PATTERNS),
                glob="**/*.py",
                ignore_case=False,
            )
            stats["command_injection_vectors"] = len(injection_matches)
            for match in injection_matches[:5]:
                findings.append(
                    self._make_finding(
                        "command_injection_vector",
                        f"Potential command injection: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.CRITICAL,
                        confidence=0.65,
                    )
                )

            # Safe subprocess patterns
            safe_matches = self.grep(
                "|".join(self.SUBPROCESS_SAFE_PATTERNS),
                glob="**/*.py",
                ignore_case=False,
            )
            stats["safe_subprocess"] = len(safe_matches)

            # Count unsafe subprocess (already in injection_matches, but be explicit)
            # Check for subprocess.run/call without safety checks
            unsafe_subprocess_matches = self.grep(
                r"subprocess\s*\.\s*(?:run|call|Popen)\s*\(",
                glob="**/*.py",
                ignore_case=False,
            )
            if unsafe_subprocess_matches:
                # Cross-check: if it has shell=True or shell=true, it's unsafe
                unsafe_count = 0
                for match in unsafe_subprocess_matches:
                    # Simple heuristic: count as potentially unsafe if no obvious safety check
                    if "shell" not in match.line_content.lower():
                        unsafe_count += 1
                stats["unsafe_subprocess"] = unsafe_count

            # Tool discovery/introspection
            discovery_matches = self.grep(
                "|".join(self.DISCOVERY_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["discovery_patterns"] = len(discovery_matches)
            for match in discovery_matches[:3]:
                findings.append(
                    self._make_finding(
                        "tool_discovery",
                        f"Tool discovery/introspection pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            result.findings = findings
            result.summary_stats = stats
            result.success = True

        except Exception as e:
            result.success = False
            result.error_message = str(e)

        return result
