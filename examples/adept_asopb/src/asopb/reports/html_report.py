"""
HTML Report Renderer

Produces self-contained, interactive HTML reports with professional styling,
inline CSS, embedded charts, and print-friendly layouts.
"""

from __future__ import annotations

import html
import json
from datetime import datetime

from asopb.models import Applicability, EvaluationReport
from asopb.reports.base import ReportRenderer


class HTMLRenderer(ReportRenderer):
    """Renders evaluation reports as self-contained HTML documents.

    Features:
    - Professional dark blue/white theme
    - ASPI gauge prominently displayed
    - Domain score cards with color coding
    - Expandable control details
    - Evidence table with filtering
    - Inline SVG domain radar chart
    - Print-friendly CSS media queries
    """

    def render(self, report: EvaluationReport) -> str:
        """Render the evaluation report as HTML.

        Args:
            report: The evaluation report to render

        Returns:
            Self-contained HTML string
        """
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ASOPB Evaluation Report - {html.escape(report.framework.name)}</title>
    <style>
        {self._get_styles()}
    </style>
</head>
<body>
    <div class="container">
        {self._render_header(report)}
        {self._render_executive_summary(report)}
        {self._render_aspi_gauge(report)}
        {self._render_domain_cards(report)}
        {self._render_domain_radar(report)}
        {self._render_domain_details(report)}
        {self._render_aivss_section(report)}
        {self._render_scanners(report)}
        {self._render_footer(report)}
    </div>
    <script>
        {self._get_scripts()}
    </script>
</body>
</html>"""
        return html_content

    def _get_styles(self) -> str:
        """Return comprehensive CSS styling."""
        return """
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            color: #333;
            line-height: 1.6;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background: white;
            box-shadow: 0 0 30px rgba(0, 0, 0, 0.1);
            border-radius: 8px;
        }

        .header {
            background: linear-gradient(135deg, #003d82 0%, #0055b8 100%);
            color: white;
            padding: 40px;
            border-radius: 8px;
            margin-bottom: 40px;
        }

        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }

        .header-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
            font-size: 0.95em;
        }

        .header-meta-item {
            background: rgba(255, 255, 255, 0.15);
            padding: 12px;
            border-radius: 4px;
            border-left: 4px solid #ffc107;
        }

        .header-meta-item strong {
            display: block;
            font-weight: 600;
            margin-bottom: 4px;
            color: #ffc107;
        }

        .section {
            margin-bottom: 40px;
        }

        .section h2 {
            font-size: 1.8em;
            color: #003d82;
            border-bottom: 3px solid #0055b8;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }

        .section h3 {
            font-size: 1.3em;
            color: #0055b8;
            margin-top: 25px;
            margin-bottom: 15px;
        }

        .executive-summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .summary-card {
            background: #f8f9fa;
            border-left: 5px solid #0055b8;
            padding: 20px;
            border-radius: 4px;
        }

        .summary-card strong {
            color: #003d82;
            display: block;
            margin-bottom: 8px;
        }

        .summary-card .value {
            font-size: 1.8em;
            font-weight: bold;
            color: #0055b8;
        }

        .aspi-container {
            text-align: center;
            margin: 40px 0;
        }

        .aspi-gauge {
            display: inline-block;
            position: relative;
            width: 300px;
            height: 300px;
        }

        .aspi-value {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
        }

        .aspi-value .score {
            font-size: 4em;
            font-weight: bold;
            color: #003d82;
        }

        .aspi-value .label {
            font-size: 1.2em;
            color: #666;
            margin-top: 10px;
        }

        .domain-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }

        .domain-card {
            background: white;
            border: 2px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .domain-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15);
        }

        .domain-card.not-applicable {
            background: #f0f0f0;
            border-color: #999;
            opacity: 0.7;
        }

        .domain-card h4 {
            font-size: 1.1em;
            color: #003d82;
            margin-bottom: 12px;
        }

        .domain-score {
            font-size: 2.2em;
            font-weight: bold;
            margin: 15px 0;
        }

        .score-excellent { color: #28a745; }
        .score-good { color: #17a2b8; }
        .score-fair { color: #ffc107; }
        .score-poor { color: #dc3545; }

        .tier-breakdown {
            display: flex;
            justify-content: space-around;
            margin: 15px 0;
            font-size: 0.9em;
        }

        .tier {
            text-align: center;
        }

        .tier-score {
            font-size: 1.8em;
            font-weight: bold;
            color: #0055b8;
        }

        .tier-label {
            color: #666;
            font-size: 0.85em;
            margin-top: 4px;
        }

        .details-toggle {
            background: #e9ecef;
            border: none;
            padding: 10px 15px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9em;
            margin-top: 15px;
            width: 100%;
            transition: background 0.3s;
        }

        .details-toggle:hover {
            background: #dee2e6;
        }

        .details-content {
            display: none;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #ddd;
        }

        .details-content.active {
            display: block;
        }

        .control-item {
            margin-bottom: 20px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 4px;
            border-left: 4px solid #0055b8;
        }

        .control-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }

        .control-id {
            font-weight: bold;
            color: #003d82;
        }

        .control-status {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 500;
        }

        .status-not-reviewed { background: #e7e7e7; color: #666; }
        .status-partial { background: #fff3cd; color: #856404; }
        .status-not-a-finding { background: #d4edda; color: #155724; }
        .status-open { background: #f8d7da; color: #721c24; }
        .status-not-applicable { background: #e2e3e5; color: #383d41; }

        .control-scores {
            display: flex;
            gap: 15px;
            font-size: 0.9em;
            margin: 10px 0;
        }

        .score-badge {
            background: white;
            padding: 8px 12px;
            border-radius: 4px;
            border: 1px solid #ddd;
        }

        .evidence-section {
            margin-top: 15px;
        }

        .evidence-section h5 {
            color: #0055b8;
            font-size: 0.95em;
            margin-bottom: 8px;
        }

        .evidence-item {
            background: white;
            padding: 10px;
            margin: 8px 0;
            border-left: 3px solid #28a745;
            font-size: 0.9em;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: white;
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        th {
            background: #003d82;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
        }

        td {
            padding: 12px 15px;
            border-bottom: 1px solid #ddd;
        }

        tr:nth-child(even) {
            background: #f8f9fa;
        }

        tr:hover {
            background: #e9ecef;
        }

        .radar-container {
            text-align: center;
            margin: 40px 0;
        }

        .footer {
            margin-top: 50px;
            padding-top: 30px;
            border-top: 2px solid #ddd;
            color: #666;
            font-size: 0.9em;
            text-align: center;
        }

        .footer-text {
            margin: 10px 0;
        }

        .aivss-container {
            margin: 30px 0;
        }

        .aivss-summary-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }

        .aivss-card {
            background: #f8f9fa;
            border-radius: 6px;
            padding: 18px;
            text-align: center;
            border-top: 4px solid #6f42c1;
        }

        .aivss-card.critical {
            border-top-color: #dc3545;
        }

        .aivss-card.high {
            border-top-color: #fd7e14;
        }

        .aivss-card .aivss-metric {
            font-size: 2em;
            font-weight: bold;
            color: #6f42c1;
        }

        .aivss-card.critical .aivss-metric {
            color: #dc3545;
        }

        .aivss-card.high .aivss-metric {
            color: #fd7e14;
        }

        .aivss-card .aivss-label {
            font-size: 0.85em;
            color: #666;
            margin-top: 5px;
        }

        .agent-profile-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
        }

        .agent-chip {
            background: #e8dff5;
            color: #6f42c1;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 500;
        }

        .agent-chip.warning {
            background: #fff3cd;
            color: #856404;
        }

        .agent-chip.danger {
            background: #f8d7da;
            color: #721c24;
        }

        .domain-impact-bar {
            display: flex;
            align-items: center;
            margin: 6px 0;
        }

        .domain-impact-bar .bar-label {
            width: 60px;
            font-weight: 600;
            color: #003d82;
        }

        .domain-impact-bar .bar-track {
            flex: 1;
            background: #e9ecef;
            border-radius: 4px;
            height: 22px;
            margin: 0 10px;
            overflow: hidden;
        }

        .domain-impact-bar .bar-fill {
            background: linear-gradient(90deg, #6f42c1, #e83e8c);
            height: 100%;
            border-radius: 4px;
            min-width: 2px;
        }

        .domain-impact-bar .bar-count {
            width: 30px;
            text-align: right;
            font-weight: 600;
            color: #333;
        }

        @media (max-width: 768px) {
            .container {
                padding: 15px;
            }

            .header {
                padding: 20px;
            }

            .header h1 {
                font-size: 1.8em;
            }

            .domain-cards {
                grid-template-columns: 1fr;
            }

            .tier-breakdown {
                flex-direction: column;
            }

            .aspi-gauge {
                width: 200px;
                height: 200px;
            }

            .aspi-value .score {
                font-size: 2.5em;
            }
        }

        @media print {
            body {
                background: white;
            }

            .container {
                box-shadow: none;
                max-width: 100%;
            }

            .header {
                break-after: page;
            }

            .domain-card {
                page-break-inside: avoid;
            }

            .details-toggle {
                display: none;
            }

            .details-content {
                display: block;
            }

            a {
                color: #0055b8;
                text-decoration: none;
            }
        }
        """

    def _get_scripts(self) -> str:
        """Return JavaScript for interactivity."""
        return """
        document.querySelectorAll('.details-toggle').forEach(button => {
            button.addEventListener('click', function() {
                const content = this.nextElementSibling;
                content.classList.toggle('active');
                this.textContent = content.classList.contains('active')
                    ? 'Hide Details'
                    : 'Show Details';
            });
        });

        // Add filter functionality to evidence table
        const filterInputs = document.querySelectorAll('.filter-input');
        filterInputs.forEach(input => {
            input.addEventListener('keyup', function() {
                const filterValue = this.value.toLowerCase();
                const table = this.closest('.section').querySelector('table');
                if (!table) return;

                table.querySelectorAll('tbody tr').forEach(row => {
                    const text = row.textContent.toLowerCase();
                    row.style.display = text.includes(filterValue) ? '' : 'none';
                });
            });
        });
        """

    def _render_header(self, report: EvaluationReport) -> str:
        """Render the HTML header section."""
        return f"""
        <div class="header">
            <h1>ASOPB Evaluation Report</h1>
            <p style="font-size: 1.1em; opacity: 0.95;">Agentic Security & Operations Performance Benchmark</p>
            <div class="header-meta">
                <div class="header-meta-item">
                    <strong>Framework</strong>
                    {html.escape(report.framework.name)}
                </div>
                <div class="header-meta-item">
                    <strong>Version</strong>
                    {html.escape(report.framework.version or 'N/A')}
                </div>
                <div class="header-meta-item">
                    <strong>Report ID</strong>
                    {html.escape(report.report_id)}
                </div>
                <div class="header-meta-item">
                    <strong>Generated</strong>
                    {report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}
                </div>
            </div>
        </div>
        """

    def _render_executive_summary(self, report: EvaluationReport) -> str:
        """Render the executive summary section."""
        applicable_domains = sum(
            1 for d in report.domains.values()
            if d.applicability == Applicability.APPLICABLE
        )
        total_controls = sum(len(d.controls) for d in report.domains.values())

        return f"""
        <div class="section">
            <h2>Executive Summary</h2>
            <div class="executive-summary">
                <div class="summary-card">
                    <strong>Overall Score (ASPI)</strong>
                    <div class="value">{report.aspi:.1f}</div>
                    <small>0–100 scale</small>
                </div>
                <div class="summary-card">
                    <strong>T1/T2 Gap Ratio</strong>
                    <div class="value">{report.t1_t2_gap_ratio:.1%}</div>
                    <small>Design vs. Deployment gap</small>
                </div>
                <div class="summary-card">
                    <strong>Applicable Domains</strong>
                    <div class="value">{applicable_domains}</div>
                    <small>of {len(report.domains)} total</small>
                </div>
                <div class="summary-card">
                    <strong>Controls Evaluated</strong>
                    <div class="value">{total_controls}</div>
                    <small>across all domains</small>
                </div>
            </div>
        </div>
        """

    def _render_aspi_gauge(self, report: EvaluationReport) -> str:
        """Render an ASPI gauge using inline SVG."""
        score = report.aspi

        # Determine color based on score
        if score >= 85:
            color = "#28a745"
            class_name = "score-excellent"
        elif score >= 60:
            color = "#17a2b8"
            class_name = "score-good"
        elif score >= 30:
            color = "#ffc107"
            class_name = "score-fair"
        else:
            color = "#dc3545"
            class_name = "score-poor"

        # Calculate arc path for gauge
        angle = (score / 100) * 180 - 90
        start_angle = -90
        end_angle = angle

        return f"""
        <div class="aspi-container">
            <div class="aspi-gauge">
                <svg viewBox="0 0 300 300" style="width: 100%; height: 100%;">
                    <!-- Background arc -->
                    <circle cx="150" cy="150" r="120" fill="none" stroke="#e0e0e0" stroke-width="15" opacity="0.5"/>
                    <!-- Score arc -->
                    <circle cx="150" cy="150" r="120" fill="none" stroke="{color}" stroke-width="15"
                            stroke-dasharray="{(score / 100) * 754} 754" stroke-linecap="round" opacity="0.9"/>
                    <!-- Tick marks -->
                    <g id="ticks">
                        <line x1="150" y1="30" x2="150" y2="45" stroke="#999" stroke-width="2"/>
                        <text x="150" y="20" text-anchor="middle" font-size="12" fill="#999">100</text>
                        <line x1="260" y1="150" x2="275" y2="150" stroke="#999" stroke-width="2"/>
                        <text x="285" y="155" font-size="12" fill="#999">0</text>
                    </g>
                </svg>
                <div class="aspi-value">
                    <div class="score {class_name}">{report.aspi:.1f}</div>
                    <div class="label">ASPI Score</div>
                </div>
            </div>
        </div>
        """

    def _render_domain_cards(self, report: EvaluationReport) -> str:
        """Render domain score cards."""
        cards = []

        for domain_id in sorted(report.domains.keys()):
            domain = report.domains[domain_id]

            if domain.applicability == Applicability.NOT_APPLICABLE:
                card = f"""
                <div class="domain-card not-applicable">
                    <h4>{domain_id}: {html.escape(domain.domain_name)}</h4>
                    <p style="color: #999;">Not Applicable</p>
                </div>
                """
            else:
                score = domain.domain_score or 0
                if score >= 85:
                    score_class = "score-excellent"
                elif score >= 60:
                    score_class = "score-good"
                elif score >= 30:
                    score_class = "score-fair"
                else:
                    score_class = "score-poor"

                card = f"""
                <div class="domain-card">
                    <h4>{domain_id}: {html.escape(domain.domain_name)}</h4>
                    <div class="domain-score {score_class}">{score:.1f}</div>
                    <div class="tier-breakdown">
                        <div class="tier">
                            <div class="tier-score">{domain.t1_aggregate:.1f}</div>
                            <div class="tier-label">T1</div>
                        </div>
                        <div class="tier">
                            <div class="tier-score">{domain.t2_aggregate:.1f}</div>
                            <div class="tier-label">T2</div>
                        </div>
                        <div class="tier">
                            <div class="tier-score">{domain.t3_aggregate:.1f}</div>
                            <div class="tier-label">T3</div>
                        </div>
                    </div>
                </div>
                """

            cards.append(card)

        return f"""
        <div class="section">
            <h2>Domain Scores</h2>
            <div class="domain-cards">
                {''.join(cards)}
            </div>
        </div>
        """

    def _render_domain_radar(self, report: EvaluationReport) -> str:
        """Render a radar chart of domain T1/T2 scores."""
        domain_ids = sorted(report.domains.keys())
        applicable = [
            d for d in domain_ids
            if report.domains[d].applicability == Applicability.APPLICABLE
        ]

        if not applicable:
            return ""

        # Create radar chart data
        t1_scores = [report.domains[d].t1_aggregate for d in applicable]
        t2_scores = [report.domains[d].t2_aggregate for d in applicable]

        return f"""
        <div class="section radar-container">
            <h2>T1/T2 Comparison by Domain</h2>
            <table>
                <thead>
                    <tr>
                        <th>Domain</th>
                        <th>T1 (Design)</th>
                        <th>T2 (Deployment)</th>
                        <th>Gap</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(f'''
                    <tr>
                        <td><strong>{d}</strong></td>
                        <td>{report.domains[d].t1_aggregate:.1f}</td>
                        <td>{report.domains[d].t2_aggregate:.1f}</td>
                        <td>{report.domains[d].t1_aggregate - report.domains[d].t2_aggregate:.1f}</td>
                    </tr>
                    ''' for d in applicable)}
                </tbody>
            </table>
        </div>
        """

    def _render_domain_details(self, report: EvaluationReport) -> str:
        """Render detailed control information for each domain."""
        sections = []

        for domain_id in sorted(report.domains.keys()):
            domain = report.domains[domain_id]

            if domain.applicability == Applicability.NOT_APPLICABLE:
                continue

            controls_html = []
            for control in domain.controls:
                status_class = f"status-{control.status.value.replace('_', '-')}"

                control_html = f"""
                <div class="control-item">
                    <div class="control-header">
                        <span class="control-id">{html.escape(control.control_id)}: {html.escape(control.control_name)}</span>
                        <span class="control-status {status_class}">{control.status.value}</span>
                    </div>
                    <div class="control-scores">
                        <span class="score-badge"><strong>T1:</strong> {control.t1_score:.1f}</span>
                        <span class="score-badge"><strong>T2:</strong> {control.t2_score:.1f}</span>
                        <span class="score-badge"><strong>T3:</strong> {control.t3_score:.1f}</span>
                        <span class="score-badge"><strong>Score:</strong> {control.composite:.1f}</span>
                    </div>
                    """

                if control.evidence:
                    control_html += """
                    <div class="evidence-section">
                        <h5>Evidence</h5>
                        """
                    for evidence in control.evidence:
                        control_html += f"""
                        <div class="evidence-item">
                            <strong>[{evidence.tier.value}]</strong> {html.escape(evidence.source_tool)}: {html.escape(evidence.description)}
                            (confidence: {evidence.confidence:.0%})
                            """
                        if evidence.file_path:
                            control_html += f"<br/><small>File: {html.escape(evidence.file_path)}</small>"
                        control_html += """
                        </div>
                        """
                    control_html += """
                    </div>
                    """

                if control.gaps:
                    control_html += f"""
                    <div class="evidence-section">
                        <h5>Gaps</h5>
                        <ul>
                            {''.join(f'<li>{html.escape(gap)}</li>' for gap in control.gaps)}
                        </ul>
                    </div>
                    """

                if control.notes:
                    control_html += f"""
                    <p style="margin-top: 10px; color: #666;"><strong>Notes:</strong> {html.escape(control.notes)}</p>
                    """

                control_html += """
                </div>
                """
                controls_html.append(control_html)

            section = f"""
            <div class="section">
                <h3>{domain_id}: {html.escape(domain.domain_name)}</h3>
                <p><strong>Score:</strong> {domain.domain_score or 'N/A'}/100 | <strong>Weight:</strong> {domain.weight}</p>
                {''.join(controls_html)}
            </div>
            """

            sections.append(section)

        return "\n".join(sections)

    def _render_aivss_section(self, report: EvaluationReport) -> str:
        """Render the OWASP AIVSS v0.8 scoring section."""
        aivss = report.aivss_summary
        if not aivss:
            return ""

        scored = aivss.get("scored_findings", 0)
        max_score = aivss.get("max_aivss", 0.0)
        mean_score = aivss.get("mean_aivss", 0.0)
        critical = aivss.get("critical_count", 0)
        high = aivss.get("high_count", 0)

        # Summary cards
        cards_html = f"""
        <div class="aivss-summary-cards">
            <div class="aivss-card">
                <div class="aivss-metric">{scored}</div>
                <div class="aivss-label">Findings Scored</div>
            </div>
            <div class="aivss-card">
                <div class="aivss-metric">{max_score:.1f}</div>
                <div class="aivss-label">Max AIVSS (of 10.0)</div>
            </div>
            <div class="aivss-card">
                <div class="aivss-metric">{mean_score:.1f}</div>
                <div class="aivss-label">Mean AIVSS</div>
            </div>
            <div class="aivss-card critical">
                <div class="aivss-metric">{critical}</div>
                <div class="aivss-label">Critical (AIVSS)</div>
            </div>
            <div class="aivss-card high">
                <div class="aivss-metric">{high}</div>
                <div class="aivss-label">High (AIVSS)</div>
            </div>
        </div>
        """

        # Domain impact bars
        domain_impact = aivss.get("domain_impact", {})
        impact_html = ""
        if domain_impact:
            max_count = max(domain_impact.values()) if domain_impact else 1
            bars = []
            for domain_id in sorted(domain_impact.keys()):
                count = domain_impact[domain_id]
                pct = (count / max_count) * 100 if max_count > 0 else 0
                bars.append(f"""
                <div class="domain-impact-bar">
                    <span class="bar-label">{html.escape(domain_id)}</span>
                    <div class="bar-track">
                        <div class="bar-fill" style="width: {pct:.0f}%"></div>
                    </div>
                    <span class="bar-count">{count}</span>
                </div>
                """)
            impact_html = f"""
            <h3>Domain Impact Distribution</h3>
            <div style="max-width: 600px;">
                {''.join(bars)}
            </div>
            """

        # Agent profile chips
        profile = aivss.get("agent_profile", {})
        profile_html = ""
        if profile:
            chips = []
            if profile.get("multi_agent"):
                svc = profile.get("service_count", 1)
                chips.append(f'<span class="agent-chip">Multi-agent ({svc} services)</span>')
            if profile.get("docker_socket"):
                chips.append('<span class="agent-chip danger">Docker socket exposed</span>')
            if profile.get("privileged_containers"):
                chips.append('<span class="agent-chip danger">Privileged containers</span>')
            if profile.get("handles_secrets"):
                chips.append('<span class="agent-chip warning">Handles secrets</span>')
            if profile.get("env_var_secrets"):
                chips.append('<span class="agent-chip warning">Env-var secrets</span>')
            tool_count = profile.get("tool_count", 0)
            if tool_count:
                chips.append(f'<span class="agent-chip">{tool_count} tools registered</span>')
            ratio = profile.get("shared_dependency_ratio", 0)
            if ratio > 0.5:
                chips.append(f'<span class="agent-chip warning">Critical dep shared by {ratio*100:.0f}%</span>')

            if chips:
                profile_html = f"""
                <h3>Auto-Derived Agent Profile</h3>
                <div class="agent-profile-chips">
                    {''.join(chips)}
                </div>
                """

        return f"""
        <div class="section aivss-container">
            <h2>OWASP AIVSS v0.8 Analysis</h2>
            <p style="color: #666; margin-bottom: 20px;">
                Vulnerability findings scored with Agentic Risk Amplification Factors (AARFs).
            </p>
            {cards_html}
            {impact_html}
            {profile_html}
        </div>
        """

    def _render_scanners(self, report: EvaluationReport) -> str:
        """Render scanner and analyzer results."""
        tools_html = []

        if report.scan_results:
            tools_html.append("<h3>Scanners</h3>")
            for tool_name, result in report.scan_results.items():
                status = "✓ Success" if result.success else "✗ Failed"
                tools_html.append(f"""
                <div style="margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 4px;">
                    <strong>{html.escape(tool_name)}</strong> (v{html.escape(result.tool_version or 'N/A')}): {status}
                    <br/><small>{result.finding_count} findings</small>
                </div>
                """)

        if report.analyzer_results:
            tools_html.append("<h3>Analyzers</h3>")
            for tool_name, result in report.analyzer_results.items():
                status = "✓ Success" if result.success else "✗ Failed"
                tools_html.append(f"""
                <div style="margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 4px;">
                    <strong>{html.escape(tool_name)}</strong> (v{html.escape(result.tool_version or 'N/A')}): {status}
                    <br/><small>{result.finding_count} findings</small>
                </div>
                """)

        if not tools_html:
            return ""

        return f"""
        <div class="section">
            <h2>Analysis Tools</h2>
            {''.join(tools_html)}
        </div>
        """

    def _render_footer(self, report: EvaluationReport) -> str:
        """Render the footer with metadata."""
        return f"""
        <div class="footer">
            <div class="footer-text">
                Report hash: <code>{html.escape(report.report_hash)}</code>
            </div>
            <div class="footer-text">
                ASOPB Framework Version {html.escape(report.asopb_version)}
                | Generated at {report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}
            </div>
            <div class="footer-text" style="margin-top: 20px; opacity: 0.7;">
                This report is sensitive and should be handled according to your organization's security policies.
            </div>
        </div>
        """
