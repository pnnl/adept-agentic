"""
SLURM MCP Server Package
========================

A FastMCP server providing SLURM cluster management capabilities.
Adapted for ADEPT framework integration (no inbound auth, JWT-based outbound auth).
"""

from .app import app, main

__version__ = "0.2.0"
__all__ = ["app", "main"]
