"""
ASOPB Red-Team Plugin Framework

Factory pattern for red-team tools, attack simulators, and external report ingesters.
"""

from asopb.redteam.base import (
    RedTeamPluginBase,
    RedTeamRegistry,
    ReportIngesterBase,
    SimulatorPluginBase,
)
from asopb.redteam.promptfoo_ingester import PromptfooIngester

try:
    from asopb.redteam.langfuse_sink import LangfuseSink
except ImportError:
    LangfuseSink = None

__all__ = [
    "RedTeamPluginBase",
    "SimulatorPluginBase",
    "ReportIngesterBase",
    "RedTeamRegistry",
    "PromptfooIngester",
    "LangfuseSink",
]
