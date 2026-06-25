#!/usr/bin/env python3
"""
SLURM MCP Server Module Entry Point
===================================

Allows running the server with: python -m slurm_mcp
"""

from .app import main

if __name__ == "__main__":
    main()
