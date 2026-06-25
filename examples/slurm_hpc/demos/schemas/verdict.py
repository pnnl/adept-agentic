"""Structured verdict models for the workflow judge."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class StepVerdict(BaseModel):
    """Verdict for a single workflow step."""

    step: Literal[
        "file_staging", "sif_provisioning", "fba_execution", "result_retrieval"
    ]
    passed: bool
    evidence: str = Field(description="Tool call result excerpt supporting the verdict")
    reasoning: str = Field(description="Why this step passed or failed")


class FinalVerdict(BaseModel):
    """Final workflow verdict emitted by the judge."""

    final_verdict: Literal["PASS", "PARTIAL", "FAIL"]
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(description="One-sentence summary of workflow outcome")
    job_ids: list[str] = Field(
        default_factory=list, description="All Slurm job IDs observed"
    )
    optimal_value: Optional[float] = Field(
        default=None, description="FBA optimal value if retrieved"
    )
    step_verdicts: list[StepVerdict] = Field(
        default_factory=list, description="Per-step verdicts"
    )


class ObserverAnomaly(BaseModel):
    """Anomaly report from the execution observer."""

    anomaly: str = Field(description="Category: retry_loop, hallucinated_id, session_drift, ignored_failure, path_violation, none")
    detail: str = Field(description="What was observed")
    severity: Literal["info", "warning", "critical"]
