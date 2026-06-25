"""
D6: Observability and Audit Domain Evaluator

Evaluates system observability, monitoring, and audit capabilities.
Assesses logging, tracing, metrics, and alerting for agent activities,
security events, and system health.

Controls:
  D6.1: Structured logging of agent actions (are actions logged in structured format?)
  D6.2: Security event logging (are security events logged separately?)
  D6.3: Distributed tracing (can actions be traced across system?)
  D6.4: Metric collection and alerting (are metrics collected and alerts configured?)
  D6.5: Log tamper protection (are logs immutable/append-only?)
"""

from __future__ import annotations

import re
from typing import Optional

from asopb.config import EvalConfig
from asopb.models import (
    ControlDefinition,
    ControlEvidence,
    ControlScore,
    ControlStatus,
    EvidenceSource,
    EvidenceTier,
    ScanFinding,
    ScanResult,
    Severity,
)

from .base import DomainEvaluator


class D6ObservabilityEvaluator(DomainEvaluator):
    """Observability and Audit domain evaluator."""

    domain_id = "D6"
    domain_name = "Observability and Audit"
    weight = 1.0
    skill_file = "d6_observability.md"

    def define_controls(self) -> list[ControlDefinition]:
        """Define D6 controls for observability and audit."""
        return [
            ControlDefinition(
                control_id="D6.1",
                domain_id="D6",
                name="Structured Logging of Agent Actions",
                description=(
                    "All agent actions are logged in a structured format (JSON, "
                    "protobuf, etc.). Logs include: agent identity, timestamp, "
                    "action type, parameters, outcome, and duration."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Agent action logging schema is documented",
                    "Structured log format is specified",
                ],
                t2_criteria=[
                    "Structured logging library integrated in agent code",
                    "All agent action entry/exit points log structured events",
                    "Log schema validation and verification",
                ],
                nist_mapping=["AU-2", "AU-3"],
                owasp_mapping=["LLM06"],
                cwe_mapping=["CWE-778"],
                tags=["logging", "structured", "observability"],
            ),
            ControlDefinition(
                control_id="D6.2",
                domain_id="D6",
                name="Security Event Logging",
                description=(
                    "Security-relevant events are logged separately: authentication "
                    "attempts, authorization failures, capability escalation attempts, "
                    "anomalies, and policy violations."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Security event taxonomy is defined",
                    "Security log retention and alerting are specified",
                ],
                t2_criteria=[
                    "Security event logging at all auth/authz checkpoints",
                    "Separate security log stream or topic",
                    "Failed access attempts logged with context",
                ],
                nist_mapping=["AU-2", "AU-3", "AU-6"],
                owasp_mapping=["LLM06"],
                cwe_mapping=["CWE-778"],
                tags=["security-logging", "audit", "events"],
            ),
            ControlDefinition(
                control_id="D6.3",
                domain_id="D6",
                name="Distributed Tracing",
                description=(
                    "Agent actions are traceable across system boundaries. Trace IDs "
                    "and parent-child relationships are maintained throughout request "
                    "execution, enabling end-to-end request reconstruction."
                ),
                severity=Severity.MEDIUM,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Distributed tracing architecture is documented (OpenTelemetry, Jaeger, etc.)",
                    "Trace ID propagation across services is specified",
                ],
                t2_criteria=[
                    "Distributed tracing library (OpenTelemetry) integrated",
                    "Trace ID propagation in all inter-service calls",
                    "Trace exporter configured",
                ],
                nist_mapping=["AU-2"],
                owasp_mapping=["LLM06"],
                cwe_mapping=["CWE-778"],
                tags=["tracing", "observability", "debugging"],
            ),
            ControlDefinition(
                control_id="D6.4",
                domain_id="D6",
                name="Metric Collection and Alerting",
                description=(
                    "System metrics are collected: agent latency, error rates, "
                    "tool invocation counts, resource usage. Alerts are configured "
                    "for anomalies and threshold violations."
                ),
                severity=Severity.MEDIUM,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Metric collection strategy is documented",
                    "Alert thresholds and rules are defined",
                ],
                t2_criteria=[
                    "Metrics instrumentation in agent and orchestration code",
                    "Metrics exporter (Prometheus, CloudWatch) configured",
                    "Alert rules for anomalies and thresholds",
                ],
                nist_mapping=["SI-4"],
                owasp_mapping=["LLM06"],
                cwe_mapping=["CWE-778"],
                tags=["metrics", "monitoring", "alerting"],
            ),
            ControlDefinition(
                control_id="D6.5",
                domain_id="D6",
                name="Log Tamper Protection",
                description=(
                    "Audit logs are immutable or append-only. Tampering is detected. "
                    "Log integrity is verified via digital signatures or ledger technologies."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S3", "S4"],
                t1_criteria=[
                    "Log tamper detection mechanism is documented",
                    "Log storage is specified as append-only or immutable",
                ],
                t2_criteria=[
                    "Write-once log storage or append-only log stream",
                    "Log integrity verification (e.g., digital signatures, merkle trees)",
                    "Unauthorized modification detection and alerting",
                ],
                nist_mapping=["AU-9", "AU-10"],
                owasp_mapping=["LLM06"],
                cwe_mapping=["CWE-778"],
                tags=["log-integrity", "tamper-protection", "audit"],
            ),
        ]

    def required_scanners(self) -> list[str]:
        """Scanners required for D6 evaluation."""
        return ["observability", "codebase"]

    def required_analyzers(self) -> list[str]:
        """Analyzers that enhance D6 scoring."""
        return ["semgrep"]

    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score D6 controls using observability and logging analysis.

        Strategy:
          1. Use observability scanner to detect logging, tracing, and metrics patterns
          2. Use codebase scanner to find structured logging, security events, and integrity
          3. Use Semgrep for observability-related gaps and anti-patterns
          4. Map findings to specific controls
          5. Set T2 floor based on presence of critical patterns + evidence density
        """
        controls = self.define_controls()
        scores: list[ControlScore] = []

        # Extract findings by category for quick lookup
        observability_findings = self._extract_findings_by_category(
            scan_results.get("observability")
        )
        codebase_findings = self._extract_findings_by_category(
            scan_results.get("codebase")
        )
        semgrep_findings = self._extract_findings_by_category(
            analyzer_results.get("semgrep")
        )

        # D6.1: Structured Logging of Agent Actions
        score_d61 = self._score_d61(
            controls[0],
            observability_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d61)

        # D6.2: Security Event Logging
        score_d62 = self._score_d62(
            controls[1],
            observability_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d62)

        # D6.3: Distributed Tracing
        score_d63 = self._score_d63(
            controls[2],
            observability_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d63)

        # D6.4: Metric Collection and Alerting
        score_d64 = self._score_d64(
            controls[3],
            observability_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d64)

        # D6.5: Log Tamper Protection
        score_d65 = self._score_d65(
            controls[4],
            observability_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d65)

        return scores

    # ------------------------------------------------------------------
    # Per-Control Scoring Logic
    # ------------------------------------------------------------------

    def _score_d61(
        self,
        control_def: ControlDefinition,
        observability_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D6.1: Structured Logging of Agent Actions"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for structured logging library integration
        if observability_findings.get("structured_logging"):
            t2_floor = 5.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Structured logging library detected in codebase",
                confidence=0.8,
            ))

        # Check for JSON logging format usage
        if (
            observability_findings.get("json_logging")
            or codebase_findings.get("json_logging")
        ):
            t2_floor = max(t2_floor, 6.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="JSON-formatted logging implementation found",
                confidence=0.8,
            ))

        # Check for log schema definitions
        if (
            observability_findings.get("log_schema")
            or codebase_findings.get("log_schema")
        ):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Log schema definition or validation found",
                confidence=0.85,
            ))

        # Check for agent action logging patterns
        if codebase_findings.get("agent_action_logging"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Agent action entry/exit point logging detected",
                confidence=0.8,
            ))

        # Negative evidence: unstructured logging patterns
        if codebase_findings.get("unstructured_log"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Unstructured log statements detected (negative evidence)",
                confidence=0.75,
            ))
            # Cap T2 if significant unstructured logging present
            t2_floor = min(t2_floor, 4.0)

        # Check for Semgrep logging gaps
        if semgrep_findings.get("missing_logging"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified code paths missing structured logging",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No structured logging implementation found"] if t2_floor == 0 else [],
        )

    def _score_d62(
        self,
        control_def: ControlDefinition,
        observability_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D6.2: Security Event Logging"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for security-specific log streams or topics
        if observability_findings.get("security_log_stream"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Separate security log stream or topic detected",
                confidence=0.85,
            ))

        # Check for security event logging patterns
        if (
            observability_findings.get("security_event_logging")
            or codebase_findings.get("security_event_logging")
        ):
            t2_floor = max(t2_floor, 5.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Security event logging implementation found",
                confidence=0.8,
            ))

        # Check for authentication failure logging
        if codebase_findings.get("auth_failure_logging"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Authentication failure logging with context found",
                confidence=0.85,
            ))

        # Check for anomaly/violation logging
        if codebase_findings.get("anomaly_logging"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Anomaly and policy violation logging detected",
                confidence=0.8,
            ))

        # Negative evidence: missing security logging at auth checkpoints
        if semgrep_findings.get("missing_security_logging"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified auth checkpoints without security event logging",
                confidence=0.8,
            ))
            # Cap T2 if security logging gaps exist
            t2_floor = min(t2_floor, 3.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No security event logging found"] if t2_floor == 0 else [],
        )

    def _score_d63(
        self,
        control_def: ControlDefinition,
        observability_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D6.3: Distributed Tracing"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for distributed tracing library integration
        if observability_findings.get("distributed_tracing"):
            t2_floor = 5.5
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Distributed tracing library integration detected",
                confidence=0.8,
            ))

        # Check for OpenTelemetry specifically
        if (
            observability_findings.get("opentelemetry")
            or codebase_findings.get("opentelemetry")
        ):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="OpenTelemetry SDK integration found",
                confidence=0.85,
            ))

        # Check for trace ID propagation across services
        if codebase_findings.get("trace_propagation"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Trace ID propagation in inter-service communication",
                confidence=0.85,
            ))

        # Check for span creation patterns
        if codebase_findings.get("span_creation"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Trace span creation patterns found in code",
                confidence=0.8,
            ))

        # Check for trace exporter configuration
        if observability_findings.get("trace_exporter"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Trace exporter (Jaeger, OTLP, Zipkin) configured",
                confidence=0.85,
            ))

        # Negative evidence: missing trace propagation
        if semgrep_findings.get("missing_trace_propagation"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified inter-service calls without trace context propagation",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No distributed tracing implementation found"] if t2_floor == 0 else [],
        )

    def _score_d64(
        self,
        control_def: ControlDefinition,
        observability_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D6.4: Metric Collection and Alerting"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for metrics collection library integration
        if observability_findings.get("metrics_collection"):
            t2_floor = 5.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Metrics collection library detected in codebase",
                confidence=0.8,
            ))

        # Check for Prometheus instrumentation
        if (
            observability_findings.get("prometheus")
            or codebase_findings.get("prometheus")
        ):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Prometheus metrics instrumentation found",
                confidence=0.85,
            ))

        # Check for metrics exporter configuration
        if codebase_findings.get("metrics_exporter"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Metrics exporter (Prometheus, CloudWatch, StatsD) configured",
                confidence=0.8,
            ))

        # Check for alert rules configuration
        if (
            observability_findings.get("alert_rules")
            or codebase_findings.get("alert_rules")
        ):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Alert rules for anomalies and thresholds defined",
                confidence=0.8,
            ))

        # Negative evidence: no metrics at critical points
        if semgrep_findings.get("missing_metrics"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified critical code paths without metrics instrumentation",
                confidence=0.7,
            ))

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No metric collection or alerting found"] if t2_floor == 0 else [],
        )

    def _score_d65(
        self,
        control_def: ControlDefinition,
        observability_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D6.5: Log Tamper Protection"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for append-only log storage patterns
        if (
            observability_findings.get("append_only")
            or codebase_findings.get("append_only")
        ):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Append-only or write-once log storage detected",
                confidence=0.8,
            ))

        # Check for log immutability configuration
        if observability_findings.get("log_immutability"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:observability",
                description="Log immutability configuration found",
                confidence=0.85,
            ))

        # Check for log signing or digital signatures
        if codebase_findings.get("log_signing"):
            t2_floor = max(t2_floor, 8.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Log signing or digital signature verification implemented",
                confidence=0.9,
            ))

        # Check for merkle tree or hash chain integrity
        if codebase_findings.get("merkle_tree") or codebase_findings.get("hash_chain"):
            t2_floor = max(t2_floor, 8.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Merkle tree or hash chain log integrity verification found",
                confidence=0.9,
            ))

        # Check for log integrity verification mechanisms
        if codebase_findings.get("integrity_verification"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Log integrity verification mechanism detected",
                confidence=0.85,
            ))

        # Negative evidence: mutable log patterns
        if codebase_findings.get("mutable_log") or semgrep_findings.get("mutable_log"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Mutable log storage or log deletion patterns detected (negative evidence)",
                confidence=0.8,
            ))
            # Cap T2 if mutable log patterns present
            t2_floor = min(t2_floor, 2.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No log tamper protection found"] if t2_floor == 0 else [],
        )

    # ------------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------------

    def _extract_findings_by_category(
        self,
        scan_result: Optional[ScanResult],
    ) -> dict[str, list[ScanFinding]]:
        """Extract findings from a ScanResult and group by category."""
        if not scan_result:
            return {}
        by_category: dict[str, list[ScanFinding]] = {}
        for finding in scan_result.findings:
            if finding.category not in by_category:
                by_category[finding.category] = []
            by_category[finding.category].append(finding)
        return by_category
