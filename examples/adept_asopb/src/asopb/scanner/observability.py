"""
Observability Scanner

Detects logging, tracing, and monitoring infrastructure including
Langfuse, OpenTelemetry, and audit trail patterns.
"""

from __future__ import annotations

import re

from asopb.models import ScanResult, Severity
from asopb.scanner.base import ScannerBase


class ObservabilityScanner(ScannerBase):
    """Detects observability, logging, and tracing infrastructure.

    Identifies:
    - Langfuse integration for LLM observability
    - OpenTelemetry/OTEL tracing
    - Logger configuration and setup
    - Chain-of-thought (CoT) capture patterns
    - Cost tracking and token accounting
    - Audit logging and forensics patterns
    - Structured logging frameworks
    - Error tracking and exception handling
    - Performance monitoring
    """

    name = "observability"
    description = "Logging, tracing, and observability pattern detection"

    # Langfuse patterns
    LANGFUSE_PATTERNS = [
        r"langfuse",
        r"Langfuse",
        r"from langfuse",
        r"import.*Langfuse",
        r"langfuse\.api",
        r"langfuse\(",
        r'"langfuse"',
        r"'langfuse'",
    ]

    # OpenTelemetry patterns
    OTEL_PATTERNS = [
        r"opentelemetry",
        r"otel",
        r"from opentelemetry",
        r"import.*opentelemetry",
        r"OpenTelemetry",
        r"TracerProvider",
        r"SpanProcessor",
        r"get_tracer",
        r"trace\.get_tracer",
        r"@instrument",
    ]

    # Logger configuration patterns
    LOGGER_PATTERNS = [
        r"logging\.config",
        r"logger_config",
        r"logger\.config",
        r"logging\.basicConfig",
        r"logging\.getLogger",
        r"getLogger\(",
        r"logger\s*=\s*",
        r"logger\.setup",
        r"setup_logging",
        r"configure_logging",
        r"StreamHandler",
        r"FileHandler",
    ]

    # Chain-of-thought capture patterns
    COT_PATTERNS = [
        r"cot",
        r"chain.of.thought",
        r"chain_of_thought",
        r"reasoning.*trace",
        r"trace.*step",
        r"thought.*process",
        r"step.*by.*step",
        r"reasoning_steps",
        r"intermediate.*result",
        r"reasoning_path",
    ]

    # Cost tracking patterns
    COST_TRACKING_PATTERNS = [
        r"cost.*track",
        r"token.*count",
        r"token.*usage",
        r"api.*cost",
        r"billing",
        r"usage.*metric",
        r"cost_per_token",
        r"total_cost",
        r"input_token",
        r"output_token",
        r"price_per_\d+k",
    ]

    # Audit logging patterns
    AUDIT_PATTERNS = [
        r"audit.*log",
        r"audit_log",
        r"audit\s*\(",
        r"log_audit",
        r"forensic",
        r"event.*log",
        r"action.*log",
        r"access.*log",
        r"who.*did.*what",
        r"user.*action",
        r"actor.*action",
    ]

    # Structured logging patterns
    STRUCTURED_LOG_PATTERNS = [
        r"structlog",
        r"json.*log",
        r"JSONFormatter",
        r"json_serializable",
        r"structured.*log",
        r"logstash",
        r"ELK\s*stack",
        r"log.*json",
    ]

    # Exception/error tracking patterns
    ERROR_TRACKING_PATTERNS = [
        r"sentry",
        r"Sentry",
        r"Rollbar",
        r"error.*track",
        r"exception.*track",
        r"error.*handler",
        r"exception.*handler",
        r"try.*except",
        r"@error_handler",
    ]

    # Performance monitoring patterns
    PERF_PATTERNS = [
        r"prometheus",
        r"Prometheus",
        r"datadog",
        r"DataDog",
        r"newrelic",
        r"performance.*metric",
        r"latency.*track",
        r"throughput.*metric",
        r"response.*time",
        r"@profiled",
        r"@timed",
    ]

    async def scan(self) -> ScanResult:
        """Execute observability scanner."""
        result = ScanResult(
            tool_name=self.name,
            tool_version="1.0.0",
        )

        findings = []
        stats = {
            "langfuse_detected": False,
            "otel_detected": False,
            "logger_config_patterns": 0,
            "cot_patterns": 0,
            "cost_tracking": 0,
            "audit_logging": 0,
            "structured_logging": 0,
            "error_tracking": 0,
            "performance_monitoring": 0,
        }

        try:
            # Langfuse detection
            langfuse_matches = self.grep(
                "|".join(self.LANGFUSE_PATTERNS),
                glob="**/*",
                ignore_case=True,
                max_results=1,
            )
            if langfuse_matches:
                stats["langfuse_detected"] = True
                findings.append(
                    self._make_finding(
                        "langfuse_integration",
                        f"Langfuse observability detected: {langfuse_matches[0].match_text}",
                        file_path=langfuse_matches[0].file_path,
                        line_number=langfuse_matches[0].line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # OpenTelemetry detection
            otel_matches = self.grep(
                "|".join(self.OTEL_PATTERNS),
                glob="**/*",
                ignore_case=True,
                max_results=1,
            )
            if otel_matches:
                stats["otel_detected"] = True
                findings.append(
                    self._make_finding(
                        "otel_tracing",
                        f"OpenTelemetry tracing detected: {otel_matches[0].match_text}",
                        file_path=otel_matches[0].file_path,
                        line_number=otel_matches[0].line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Logger configuration
            logger_matches = self.grep(
                "|".join(self.LOGGER_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["logger_config_patterns"] = len(logger_matches)
            for match in logger_matches[:5]:
                findings.append(
                    self._make_finding(
                        "logger_configuration",
                        f"Logger configuration pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Chain-of-thought patterns
            cot_matches = self.grep(
                "|".join(self.COT_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["cot_patterns"] = len(cot_matches)
            for match in cot_matches[:3]:
                findings.append(
                    self._make_finding(
                        "cot_capture",
                        f"Chain-of-thought capture pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Cost tracking
            cost_matches = self.grep(
                "|".join(self.COST_TRACKING_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["cost_tracking"] = len(cost_matches)
            for match in cost_matches[:3]:
                findings.append(
                    self._make_finding(
                        "cost_tracking",
                        f"Cost/token tracking pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Audit logging
            audit_matches = self.grep(
                "|".join(self.AUDIT_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["audit_logging"] = len(audit_matches)
            for match in audit_matches[:3]:
                findings.append(
                    self._make_finding(
                        "audit_logging",
                        f"Audit logging pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Structured logging
            struct_matches = self.grep(
                "|".join(self.STRUCTURED_LOG_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["structured_logging"] = len(struct_matches)
            for match in struct_matches[:3]:
                findings.append(
                    self._make_finding(
                        "structured_logging",
                        f"Structured logging framework: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Error tracking
            error_matches = self.grep(
                "|".join(self.ERROR_TRACKING_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["error_tracking"] = len(error_matches)
            for match in error_matches[:3]:
                findings.append(
                    self._make_finding(
                        "error_tracking",
                        f"Error/exception tracking: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Performance monitoring
            perf_matches = self.grep(
                "|".join(self.PERF_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["performance_monitoring"] = len(perf_matches)
            for match in perf_matches[:3]:
                findings.append(
                    self._make_finding(
                        "performance_monitoring",
                        f"Performance monitoring: {match.match_text}",
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
