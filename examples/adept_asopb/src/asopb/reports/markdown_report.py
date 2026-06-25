"""
Markdown Report Renderer

Produces professional, human-readable evaluation reports in Markdown format.
Includes executive summary, domain breakdowns, control details, and evidence tables.
"""

from __future__ import annotations

from datetime import datetime

from asopb.models import Applicability, EvaluationReport
from asopb.reports.base import ReportRenderer


class MarkdownRenderer(ReportRenderer):
    """Renders evaluation reports as professional Markdown documents.

    Includes:
    - Title and timestamp
    - Executive summary with ASPI score and gap analysis
    - Domain-by-domain breakdown
    - Detailed control scores and evidence
    - Analyzer availability table
    - Warnings section
    """

    def render(self, report: EvaluationReport) -> str:
        """Render the evaluation report as Markdown.

        Args:
            report: The evaluation report to render

        Returns:
            Markdown string representation of the report
        """
        parts = []

        # Header
        parts.append(self._render_header(report))

        # Executive Summary
        parts.append(self._render_executive_summary(report))

        # Domain Summary Table
        parts.append(self._render_domain_summary(report))

        # Domain Details
        parts.append(self._render_domain_details(report))

        # AIVSS Summary (if available)
        if report.aivss_summary:
            parts.append(self._render_aivss_summary(report))

        # Analyzer Availability
        parts.append(self._render_analyzers(report))

        # Warnings
        if report.warnings:
            parts.append(self._render_warnings(report))

        return "\n".join(parts)

    def _render_header(self, report: EvaluationReport) -> str:
        """Render the report header with title and metadata."""
        lines = [
            f"# ASOPB Evaluation Report",
            "",
            f"**Framework:** {report.framework.name}",
            f"**Version:** {report.framework.version or 'N/A'}",
            f"**Report ID:** `{report.report_id}`",
            f"**Generated:** {report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**ASOPB Framework Version:** {report.asopb_version}",
            "",
        ]
        return "\n".join(lines)

    def _render_executive_summary(self, report: EvaluationReport) -> str:
        """Render the executive summary section."""
        lines = [
            "## Executive Summary",
            "",
            f"**ASPI Score:** {report.aspi}/100",
            f"**T1/T2 Gap Ratio:** {report.t1_t2_gap_ratio:.1%}",
            "",
            "### Key Findings",
            "",
        ]

        # Provide interpretation
        if report.aspi >= 85:
            stage = "Stage 4 (Advanced)"
            interpretation = "Comprehensive security posture with strong design and deployment evidence"
        elif report.aspi >= 60:
            stage = "Stage 3 (Mature)"
            interpretation = "Well-established security controls with solid deployment evidence"
        elif report.aspi >= 30:
            stage = "Stage 2 (Developing)"
            interpretation = "Basic security controls partially implemented"
        else:
            stage = "Stage 1 (Initial)"
            interpretation = "Minimal or no systematic security controls"

        lines.append(f"- **Inferred Stage:** {stage}")
        lines.append(f"- **Assessment:** {interpretation}")
        lines.append(f"- **Applicable Domains:** {sum(1 for d in report.domains.values() if d.applicability == Applicability.APPLICABLE)}")
        lines.append(f"- **Total Controls Evaluated:** {sum(len(d.controls) for d in report.domains.values())}")
        lines.append(f"- **Evaluation Duration:** {report.evaluation_duration_seconds:.1f}s" if report.evaluation_duration_seconds else "")
        lines.append(f"- **LLM Tokens Used:** {report.llm_tokens_used:,}")
        lines.append("")

        return "\n".join(filter(None, lines))

    def _render_domain_summary(self, report: EvaluationReport) -> str:
        """Render the domain summary table (like Table 5 in the paper)."""
        lines = [
            "## Domain Score Summary",
            "",
            "| Domain | Name | Applicable | T1 | T2 | T3 | Score | Weight |",
            "|--------|------|------------|-----|-----|-----|-------|--------|",
        ]

        for domain_id in sorted(report.domains.keys()):
            domain = report.domains[domain_id]
            applicable = "Yes" if domain.applicability == Applicability.APPLICABLE else "N/A"

            if domain.domain_score is None:
                score_str = "N/A"
            else:
                score_str = f"{domain.domain_score:.1f}"

            lines.append(
                f"| {domain_id} | {domain.domain_name} | {applicable} | "
                f"{domain.t1_aggregate:.1f} | {domain.t2_aggregate:.1f} | {domain.t3_aggregate:.1f} | "
                f"{score_str} | {domain.weight:.1f} |"
            )

        lines.append("")
        return "\n".join(lines)

    def _render_domain_details(self, report: EvaluationReport) -> str:
        """Render detailed breakdown for each domain."""
        lines = ["## Domain Details", ""]

        for domain_id in sorted(report.domains.keys()):
            domain = report.domains[domain_id]

            lines.append(f"### {domain_id}: {domain.domain_name}")
            lines.append("")

            if domain.applicability == Applicability.NOT_APPLICABLE:
                lines.append("**Applicability:** Not Applicable")
                lines.append("")
                continue

            lines.append(f"**Score:** {domain.domain_score:.1f}/100 | **Weight:** {domain.weight}")
            lines.append(
                f"**T1 (Design):** {domain.t1_aggregate:.1f} | "
                f"**T2 (Deployment):** {domain.t2_aggregate:.1f} | "
                f"**T3 (Adversarial):** {domain.t3_aggregate:.1f}"
            )

            if domain.summary:
                lines.append("")
                lines.append(f"**Summary:** {domain.summary}")

            lines.append("")
            lines.append("#### Controls")
            lines.append("")

            # Control table for this domain
            lines.append("| Control | Status | T1 | T2 | T3 | Score | Evidence |")
            lines.append("|---------|--------|-----|-----|-----|-------|----------|")

            for control in domain.controls:
                evidence_count = len(control.evidence)
                evidence_str = f"{evidence_count} item(s)" if evidence_count > 0 else "None"
                lines.append(
                    f"| {control.control_id} | {control.status.value} | "
                    f"{control.t1_score:.1f} | {control.t2_score:.1f} | {control.t3_score:.1f} | "
                    f"{control.composite:.1f} | {evidence_str} |"
                )

            lines.append("")

            # Detailed control info
            for control in domain.controls:
                lines.append(f"##### {control.control_id}: {control.control_name}")
                lines.append("")
                lines.append(f"- **Status:** {control.status.value}")
                lines.append(f"- **Composite Score:** {control.composite:.1f}/100")
                lines.append(f"- **T1 (Design):** {control.t1_score:.1f} | T1 Floor: {control.t1_floor:.1f}")
                lines.append(f"- **T2 (Deployment):** {control.t2_score:.1f} | T2 Floor: {control.t2_floor:.1f}")
                lines.append(f"- **T3 (Adversarial):** {control.t3_score:.1f}")

                if control.notes:
                    lines.append(f"- **Notes:** {control.notes}")

                # Evidence
                if control.evidence:
                    lines.append("")
                    lines.append("**Evidence:**")
                    for idx, evidence in enumerate(control.evidence, 1):
                        lines.append(
                            f"  {idx}. [{evidence.tier.value}] {evidence.source_tool}: {evidence.description} "
                            f"(confidence: {evidence.confidence:.0%})"
                        )
                        if evidence.file_path:
                            lines.append(f"     - File: `{evidence.file_path}`")
                            if evidence.line_range:
                                lines.append(f"     - Lines: {evidence.line_range[0]}-{evidence.line_range[1]}")

                # Gaps
                if control.gaps:
                    lines.append("")
                    lines.append("**Gaps:**")
                    for gap in control.gaps:
                        lines.append(f"  - {gap}")

                # Remediation
                if control.remediation:
                    lines.append("")
                    lines.append("**Remediation:**")
                    for rem in control.remediation:
                        lines.append(f"  - {rem}")

                lines.append("")

        return "\n".join(lines)

    def _render_aivss_summary(self, report: EvaluationReport) -> str:
        """Render the OWASP AIVSS v0.8 scoring summary."""
        aivss = report.aivss_summary
        if not aivss:
            return ""

        lines = [
            "## OWASP AIVSS v0.8 Analysis",
            "",
            "Vulnerability findings scored with Agentic Risk Amplification Factors (AARFs).",
            "",
            f"- **Findings Scored:** {aivss.get('scored_findings', 0)}",
            f"- **Max AIVSS:** {aivss.get('max_aivss', 0.0):.1f}/10.0",
            f"- **Mean AIVSS:** {aivss.get('mean_aivss', 0.0):.1f}/10.0",
            f"- **Critical (AIVSS):** {aivss.get('critical_count', 0)}",
            f"- **High (AIVSS):** {aivss.get('high_count', 0)}",
            "",
        ]

        # Domain impact breakdown
        domain_impact = aivss.get("domain_impact", {})
        if domain_impact:
            lines.append("### Domain Impact Distribution")
            lines.append("")
            lines.append("| Domain | Amplified Findings |")
            lines.append("|--------|-------------------|")
            for domain_id in sorted(domain_impact.keys()):
                count = domain_impact[domain_id]
                lines.append(f"| {domain_id} | {count} |")
            lines.append("")

        # Agent profile characteristics
        profile = aivss.get("agent_profile", {})
        if profile:
            lines.append("### Agent Profile (Auto-Derived)")
            lines.append("")
            characteristics = []
            if profile.get("multi_agent"):
                characteristics.append(f"Multi-agent ({profile.get('service_count', 1)} services)")
            if profile.get("docker_socket"):
                characteristics.append("Docker socket exposed")
            if profile.get("privileged_containers"):
                characteristics.append("Privileged containers")
            if profile.get("handles_secrets"):
                characteristics.append("Handles secrets/credentials")
            if profile.get("env_var_secrets"):
                characteristics.append("Secrets in environment variables")
            tool_count = profile.get("tool_count", 0)
            if tool_count:
                characteristics.append(f"{tool_count} tools registered")
            ratio = profile.get("shared_dependency_ratio", 0)
            if ratio > 0.5:
                characteristics.append(f"Critical dependency shared by {ratio*100:.0f}% of services")

            for c in characteristics:
                lines.append(f"- {c}")
            lines.append("")

        return "\n".join(lines)

    def _render_analyzers(self, report: EvaluationReport) -> str:
        """Render the analyzer availability table."""
        lines = [
            "## Analysis Tools",
            "",
            "### Available Scanners & Analyzers",
            "",
        ]

        if report.scan_results:
            lines.append("**Scanners:**")
            lines.append("")
            for tool_name, result in report.scan_results.items():
                status = "Success" if result.success else "Failed"
                lines.append(f"- {tool_name} (v{result.tool_version or 'N/A'}): {status} - {result.finding_count} findings")

            lines.append("")

        if report.analyzer_results:
            lines.append("**Analyzers:**")
            lines.append("")
            for tool_name, result in report.analyzer_results.items():
                status = "Success" if result.success else "Failed"
                lines.append(f"- {tool_name} (v{result.tool_version or 'N/A'}): {status} - {result.finding_count} findings")

            lines.append("")

        if report.analyzers_skipped:
            lines.append("**Skipped Analyzers:**")
            lines.append("")
            for skipped in report.analyzers_skipped:
                lines.append(f"- {skipped}")

            lines.append("")

        return "\n".join(lines)

    def _render_warnings(self, report: EvaluationReport) -> str:
        """Render the warnings section."""
        lines = [
            "## Warnings",
            "",
        ]

        for warning in report.warnings:
            lines.append(f"- {warning}")

        lines.append("")
        return "\n".join(lines)
