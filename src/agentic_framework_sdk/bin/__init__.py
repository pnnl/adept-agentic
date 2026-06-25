"""
Agentic Framework SDK Binary Utilities

This module provides command-line utilities and initialization scripts
for the Agentic Framework SDK.
"""

__version__ = "1.0.0"

# Expose submodules for proper importing
from . import agentic_cli
from . import init_external_cli

__all__ = ['agentic_cli', 'init_external_cli', '__version__']