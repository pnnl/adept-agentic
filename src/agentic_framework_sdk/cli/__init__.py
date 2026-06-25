"""
CLI interface for Agentic Framework SDK

Interactive chat client and command-line tools for scientific AI workflows.
"""

from .main import cli as main, AgenticCLI

__all__ = ["main", "AgenticCLI"]