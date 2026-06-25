"""
ASOPB LLM Integration Layer

Provides async LLM-assisted evaluation with caching, rate limiting, and fallback support.

Key components:
  - LLMClient: Async wrapper around LiteLLM with caching and rate limiting
  - SkillLoader: Loads domain-specific evaluation skill markdown files

Usage:
    from asopb.config import EvalConfig, LLMConfig
    from asopb.llm import LLMClient, SkillLoader

    config = EvalConfig(llm=LLMConfig(model="claude-sonnet-4-20250514"))
    client = LLMClient(config.llm)
    skills = SkillLoader()

    # Load a skill
    d4_skill = skills.load("D4")

    # Get completion
    response = await client.complete(system=d4_skill, user="Evaluate this agent...")

    # Get JSON response
    result = await client.complete_json(system=d4_skill, user="...", schema={...})
"""

from asopb.llm.client import LLMClient
from asopb.llm.langfuse_integration import configure_langfuse, make_trace_metadata
from asopb.llm.langfuse_report import LangfuseReportGenerator
from asopb.llm.skill_loader import SkillLoader

__all__ = [
    "LLMClient",
    "LangfuseReportGenerator",
    "SkillLoader",
    "configure_langfuse",
    "make_trace_metadata",
]
