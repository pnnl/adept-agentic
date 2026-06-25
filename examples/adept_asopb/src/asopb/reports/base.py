"""
Base Report Renderer Interface

Abstract base class for all report format implementations.
Defines the renderer contract and common utilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from asopb.models import EvaluationReport


class ReportRenderer(ABC):
    """Abstract base class for ASOPB report renderers.

    All renderers must implement render() to produce format-specific output
    and save() to persist the rendered output to disk.
    """

    @abstractmethod
    def render(self, report: EvaluationReport) -> str:
        """Render the evaluation report to a string in the specific format.

        Args:
            report: The evaluation report to render

        Returns:
            String representation of the report in the target format
        """
        pass

    def save(self, report: EvaluationReport, output_path: Path) -> Path:
        """Render the report and save it to disk.

        Args:
            report: The evaluation report to render and save
            output_path: Path where the report should be written

        Returns:
            The path where the report was saved (equal to output_path)
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rendered = self.render(report)
        output_path.write_text(rendered, encoding="utf-8")
        return output_path
