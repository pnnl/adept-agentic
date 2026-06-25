"""
JSON Report Renderer

Outputs the complete EvaluationReport as formatted JSON.
Machine-readable format suitable for programmatic analysis and integration.
"""

from __future__ import annotations

import json

from asopb.models import EvaluationReport
from asopb.reports.base import ReportRenderer


class JSONRenderer(ReportRenderer):
    """Renders evaluation reports as JSON.

    Supports both compact and pretty-printed output.
    Preserves all report data including evidence, scan results, and metadata.
    """

    def __init__(self, pretty: bool = True, indent: int = 2):
        """Initialize the JSON renderer.

        Args:
            pretty: Whether to pretty-print the JSON (default True)
            indent: Number of spaces for indentation (default 2)
        """
        self.pretty = pretty
        self.indent = indent if pretty else None

    def render(self, report: EvaluationReport) -> str:
        """Render the evaluation report as JSON.

        Args:
            report: The evaluation report to render

        Returns:
            JSON string representation of the report
        """
        data = report.model_dump(mode="json", by_alias=False)
        if self.pretty:
            return json.dumps(data, indent=self.indent, default=str)
        else:
            return json.dumps(data, separators=(",", ":"), default=str)
