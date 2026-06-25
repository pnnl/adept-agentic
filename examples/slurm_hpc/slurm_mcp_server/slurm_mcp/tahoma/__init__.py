"""Tahoma HPC cluster integration for ADEPT Slurm MCP server.

Tahoma supports both SSH-based and REST API (slurmrestd) job management.
"""

from .config import tahoma_config

__all__ = ["tahoma_config"]
