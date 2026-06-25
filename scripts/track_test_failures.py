#!/usr/bin/env python3
"""
Test Failure Tracking Script
=============================
Analyzes test failures from pytest output and categorizes them for efficient fixing.

Author: Development Team
Date: 2025-11-07
Phase: Phase 2 Test Infrastructure Improvements
"""

import re
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class TestFailure:
    """Represents a single test failure."""
    test_file: str
    test_name: str
    failure_type: str
    error_message: str
    line_number: Optional[int] = None
    category: Optional[str] = None
    suggested_fix: Optional[str] = None
    priority: str = "medium"


class TestFailureTracker:
    """Tracks and analyzes test failures."""

    # Common failure patterns and their categories
    FAILURE_PATTERNS = {
        # Async/Await Issues
        r"object bool can't be used in 'await' expression": {
            "category": "async_await",
            "priority": "high",
            "fix": "Remove await from non-coroutine function calls"
        },
        r"'MagicMock' object.*await": {
            "category": "async_mock",
            "priority": "high",
            "fix": "Use AsyncMock instead of MagicMock for async functions"
        },
        r"coroutine.*was never awaited": {
            "category": "async_await",
            "priority": "high",
            "fix": "Add await to coroutine call or use asyncio.run()"
        },

        # Import Issues
        r"NameError: name '(\w+)' is not defined": {
            "category": "missing_import",
            "priority": "critical",
            "fix": "Import missing module: {1}"
        },
        r"ImportError: cannot import name": {
            "category": "import_error",
            "priority": "critical",
            "fix": "Check if imported name exists in module"
        },
        r"ModuleNotFoundError": {
            "category": "missing_module",
            "priority": "critical",
            "fix": "Install missing module or fix import path"
        },

        # Mock Issues
        r"AttributeError:.*Mock.*has no attribute": {
            "category": "mock_config",
            "priority": "medium",
            "fix": "Configure mock with proper attributes/methods"
        },
        r"TypeError:.*not supported between.*Mock": {
            "category": "mock_return_value",
            "priority": "medium",
            "fix": "Set proper return_value for mock objects"
        },

        # Fixture Issues
        r"fixture.*not found": {
            "category": "missing_fixture",
            "priority": "high",
            "fix": "Define missing fixture in conftest.py or test file"
        },
        r"ScopeMismatch": {
            "category": "fixture_scope",
            "priority": "medium",
            "fix": "Align fixture scopes (function/module/session)"
        },

        # Assertion Failures
        r"AssertionError": {
            "category": "assertion",
            "priority": "low",
            "fix": "Update test expectations or fix implementation"
        },

        # Type Errors
        r"TypeError: .* missing \d+ required positional argument": {
            "category": "missing_argument",
            "priority": "medium",
            "fix": "Provide all required arguments to function"
        },

        # Attribute Errors
        r"AttributeError: module .* has no attribute '(\w+)'": {
            "category": "missing_attribute",
            "priority": "high",
            "fix": "Check if attribute {1} exists or was renamed"
        },

        # Permission Errors
        r"PermissionError": {
            "category": "permission",
            "priority": "high",
            "fix": "Check file/directory permissions"
        },
    }

    # Priority test files from Phase 2 Action Plan
    PRIORITY_FILES = [
        'tests/e2e/test_device_flow_cli.py',
        'tests/e2e/test_streamlit_file_upload_detection.py',
        'tests/unit/agentic_framework_pkg/agent_gateway/test_app.py',
        'tests/unit/agentic_framework_pkg/agent_gateway/test_auth.py',
        'tests/unit/agentic_framework_pkg/core/test_auth.py',
        'tests/unit/agentic_framework_pkg/mcp_server/test_main.py',
        'tests/unit/agentic_framework_pkg/orchestration_service/test_app.py',
        'tests/unit/agentic_framework_pkg/sandbox_mcp_server/test_main.py',
        'tests/unit/agentic_framework_sdk/test_client.py',
    ]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.failures: List[TestFailure] = []
        self.stats: Dict[str, int] = defaultdict(int)

    def run_tests(self, test_path: str = "tests/",
                  container: Optional[str] = None,
                  markers: Optional[str] = None) -> str:
        """Run pytest and capture output."""
        if container:
            # Run tests in Docker container
            cmd = [
                "docker", "exec", "-it", container,
                "pytest", test_path, "-v", "--tb=short"
            ]
        else:
            # Run tests locally
            cmd = ["pytest", test_path, "-v", "--tb=short"]

        if markers:
            cmd.extend(["-m", markers])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            return result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return "ERROR: Test execution timed out after 5 minutes"
        except Exception as e:
            return f"ERROR: Failed to run tests: {str(e)}"

    def parse_pytest_output(self, output: str) -> List[TestFailure]:
        """Parse pytest output to extract failures."""
        failures = []
        current_test = None
        current_error = []
        in_error = False

        for line in output.split('\n'):
            # Check for test failure line
            if 'FAILED' in line or 'ERROR' in line:
                # Save previous failure if exists
                if current_test and current_error:
                    failure = self._create_failure(current_test, '\n'.join(current_error))
                    if failure:
                        failures.append(failure)

                # Parse new failure
                match = re.match(r'(FAILED|ERROR)\s+(.+?)::(test_\w+)', line)
                if match:
                    current_test = {
                        'status': match.group(1),
                        'file': match.group(2),
                        'test': match.group(3)
                    }
                    current_error = []
                    in_error = True
            elif in_error and line.strip():
                # Collect error details
                current_error.append(line)
                # Check if we've reached the end of the error
                if line.startswith('=') or line.startswith('-'):
                    in_error = False

        # Don't forget the last failure
        if current_test and current_error:
            failure = self._create_failure(current_test, '\n'.join(current_error))
            if failure:
                failures.append(failure)

        return failures

    def _create_failure(self, test_info: Dict, error_text: str) -> Optional[TestFailure]:
        """Create a TestFailure object from test info and error text."""
        failure = TestFailure(
            test_file=test_info['file'],
            test_name=test_info['test'],
            failure_type=test_info['status'],
            error_message=error_text[:500]  # Truncate long errors
        )

        # Categorize the failure
        for pattern, info in self.FAILURE_PATTERNS.items():
            match = re.search(pattern, error_text, re.IGNORECASE)
            if match:
                failure.category = info['category']
                failure.priority = info['priority']

                # Format suggested fix with captured groups
                fix = info['fix']
                if match.groups():
                    try:
                        fix = fix.format(*match.groups())
                    except:
                        pass
                failure.suggested_fix = fix
                break

        # If no category found, mark as unknown
        if not failure.category:
            failure.category = "unknown"
            failure.priority = "low"

        # Boost priority for files in priority list
        if failure.test_file in self.PRIORITY_FILES:
            if failure.priority == "low":
                failure.priority = "medium"
            elif failure.priority == "medium":
                failure.priority = "high"

        return failure

    def analyze_failures(self, failures: List[TestFailure]) -> Dict:
        """Analyze failures and generate statistics."""
        stats = {
            "total_failures": len(failures),
            "by_category": defaultdict(int),
            "by_priority": defaultdict(int),
            "by_file": defaultdict(int),
            "priority_files_affected": set(),
            "categories": {}
        }

        for failure in failures:
            stats["by_category"][failure.category] += 1
            stats["by_priority"][failure.priority] += 1
            stats["by_file"][failure.test_file] += 1

            if failure.test_file in self.PRIORITY_FILES:
                stats["priority_files_affected"].add(failure.test_file)

            # Group failures by category for detailed view
            if failure.category not in stats["categories"]:
                stats["categories"][failure.category] = []
            stats["categories"][failure.category].append(failure)

        # Convert sets to lists for JSON serialization
        stats["priority_files_affected"] = list(stats["priority_files_affected"])

        return stats

    def generate_report(self, failures: List[TestFailure],
                       stats: Dict, format: str = "text") -> str:
        """Generate a report of test failures."""
        if format == "json":
            return self._generate_json_report(failures, stats)
        elif format == "markdown":
            return self._generate_markdown_report(failures, stats)
        else:
            return self._generate_text_report(failures, stats)

    def _generate_text_report(self, failures: List[TestFailure], stats: Dict) -> str:
        """Generate a text report."""
        lines = []
        lines.append("=" * 80)
        lines.append("TEST FAILURE TRACKING REPORT")
        lines.append("=" * 80)
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append("")

        # Summary
        lines.append(f"Total Failures: {stats['total_failures']}")
        lines.append("")

        # By Priority
        lines.append("Failures by Priority:")
        for priority in ["critical", "high", "medium", "low"]:
            count = stats["by_priority"].get(priority, 0)
            if count > 0:
                lines.append(f"  {priority.upper()}: {count}")
        lines.append("")

        # By Category
        lines.append("Failures by Category:")
        for category, count in sorted(stats["by_category"].items(),
                                     key=lambda x: x[1], reverse=True):
            lines.append(f"  {category}: {count}")
        lines.append("")

        # Priority Files
        if stats["priority_files_affected"]:
            lines.append("Priority Files with Failures:")
            for file in stats["priority_files_affected"]:
                count = stats["by_file"][file]
                lines.append(f"  - {file} ({count} failures)")
            lines.append("")

        # Detailed Failures by Category
        lines.append("=" * 80)
        lines.append("DETAILED FAILURES BY CATEGORY")
        lines.append("=" * 80)

        for category in ["critical", "high", "medium", "low"]:
            category_failures = [f for f in failures if f.priority == category]
            if category_failures:
                lines.append("")
                lines.append(f"[{category.upper()} PRIORITY]")
                lines.append("-" * 40)

                for failure in category_failures[:10]:  # Limit to 10 per category
                    lines.append(f"\nFile: {failure.test_file}")
                    lines.append(f"Test: {failure.test_name}")
                    lines.append(f"Category: {failure.category}")
                    if failure.suggested_fix:
                        lines.append(f"Fix: {failure.suggested_fix}")
                    lines.append(f"Error: {failure.error_message[:200]}...")

        return "\n".join(lines)

    def _generate_markdown_report(self, failures: List[TestFailure], stats: Dict) -> str:
        """Generate a markdown report."""
        lines = []
        lines.append("# Test Failure Tracking Report")
        lines.append("")
        lines.append(f"**Generated**: {datetime.now().isoformat()}")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(f"**Total Failures**: {stats['total_failures']}")
        lines.append("")

        # Priority Breakdown
        lines.append("### Priority Breakdown")
        lines.append("")
        lines.append("| Priority | Count |")
        lines.append("|----------|-------|")
        for priority in ["critical", "high", "medium", "low"]:
            count = stats["by_priority"].get(priority, 0)
            lines.append(f"| {priority.capitalize()} | {count} |")
        lines.append("")

        # Category Breakdown
        lines.append("### Category Breakdown")
        lines.append("")
        lines.append("| Category | Count | Typical Fix |")
        lines.append("|----------|-------|-------------|")

        category_fixes = {
            "async_await": "Fix async/await patterns",
            "async_mock": "Use AsyncMock instead of MagicMock",
            "missing_import": "Add missing imports",
            "import_error": "Fix import paths",
            "mock_config": "Configure mock objects properly",
            "missing_fixture": "Define missing fixtures",
            "assertion": "Update test expectations",
        }

        for category, count in sorted(stats["by_category"].items(),
                                     key=lambda x: x[1], reverse=True):
            fix = category_fixes.get(category, "Investigate and fix")
            lines.append(f"| {category} | {count} | {fix} |")
        lines.append("")

        # Priority Files
        if stats["priority_files_affected"]:
            lines.append("## Priority Files Requiring Attention")
            lines.append("")
            for file in stats["priority_files_affected"]:
                count = stats["by_file"][file]
                lines.append(f"- `{file}` - {count} failures")
            lines.append("")

        # Action Items
        lines.append("## Recommended Action Items")
        lines.append("")

        action_items = []
        if stats["by_priority"].get("critical", 0) > 0:
            action_items.append("1. **Fix critical failures first** - These are blocking issues")
        if stats["by_category"].get("missing_import", 0) > 0:
            action_items.append("2. **Run import validation script** - Fix all missing imports")
        if stats["by_category"].get("async_await", 0) > 0:
            action_items.append("3. **Fix async/await patterns** - Use AsyncMock for async tests")
        if stats["by_category"].get("mock_config", 0) > 0:
            action_items.append("4. **Configure mocks properly** - Set return values and attributes")

        for item in action_items:
            lines.append(item)

        lines.append("")

        # Detailed Failures
        lines.append("## Detailed Failures (Top 10)")
        lines.append("")

        # Sort failures by priority
        sorted_failures = sorted(failures,
                                key=lambda x: {"critical": 0, "high": 1,
                                             "medium": 2, "low": 3}.get(x.priority, 4))

        for i, failure in enumerate(sorted_failures[:10], 1):
            icon = {"critical": "🔴", "high": "🟠",
                   "medium": "🟡", "low": "🟢"}.get(failure.priority, "⚪")

            lines.append(f"### {i}. {icon} {failure.test_name}")
            lines.append("")
            lines.append(f"- **File**: `{failure.test_file}`")
            lines.append(f"- **Category**: {failure.category}")
            lines.append(f"- **Priority**: {failure.priority}")
            if failure.suggested_fix:
                lines.append(f"- **Suggested Fix**: {failure.suggested_fix}")
            lines.append("")
            lines.append("**Error**:")
            lines.append("```")
            lines.append(failure.error_message[:300])
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    def _generate_json_report(self, failures: List[TestFailure], stats: Dict) -> str:
        """Generate a JSON report."""
        report = {
            "generated": datetime.now().isoformat(),
            "summary": {
                "total_failures": stats["total_failures"],
                "by_priority": dict(stats["by_priority"]),
                "by_category": dict(stats["by_category"]),
                "priority_files_affected": stats["priority_files_affected"]
            },
            "failures": [asdict(f) for f in failures]
        }
        return json.dumps(report, indent=2)

    def save_report(self, report: str, filename: str):
        """Save report to file."""
        with open(filename, 'w') as f:
            f.write(report)
        print(f"Report saved to {filename}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Track and analyze test failures')
    parser.add_argument('--test-path', default='tests/',
                       help='Path to tests directory (default: tests/)')
    parser.add_argument('--container',
                       help='Docker container name to run tests in')
    parser.add_argument('--markers',
                       help='Pytest markers to filter tests')
    parser.add_argument('--format', choices=['text', 'markdown', 'json'],
                       default='text',
                       help='Output format (default: text)')
    parser.add_argument('--output', '-o',
                       help='Output file (default: stdout)')
    parser.add_argument('--input', '-i',
                       help='Read pytest output from file instead of running tests')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    parser.add_argument('--priority-only', action='store_true',
                       help='Only show failures in priority files')

    args = parser.parse_args()

    tracker = TestFailureTracker(verbose=args.verbose)

    # Get test output
    if args.input:
        with open(args.input, 'r') as f:
            output = f.read()
    else:
        print("Running tests...")
        output = tracker.run_tests(
            test_path=args.test_path,
            container=args.container,
            markers=args.markers
        )

    # Parse failures
    print("Parsing test output...")
    failures = tracker.parse_pytest_output(output)

    if args.priority_only:
        failures = [f for f in failures if f.test_file in tracker.PRIORITY_FILES]

    # Analyze
    print("Analyzing failures...")
    stats = tracker.analyze_failures(failures)

    # Generate report
    print("Generating report...")
    report = tracker.generate_report(failures, stats, args.format)

    # Output
    if args.output:
        tracker.save_report(report, args.output)
    else:
        print(report)

    # Exit with error code if failures found
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()