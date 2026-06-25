"""Multi-agent role personas for HPC workflow execution."""

from .executor import EXECUTOR_PERSONA
from .judge import JUDGE_PERSONA
from .observer import OBSERVER_PERSONA

__all__ = ["EXECUTOR_PERSONA", "JUDGE_PERSONA", "OBSERVER_PERSONA"]
