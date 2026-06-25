"""Deception SSH transport — thin wrapper over shared FabricSSHTransport.

The actual implementation lives in slurm_mcp.fabric_transport.
This module re-exports it for backward compatibility with tools.py imports.
"""

from ..fabric_transport import FabricSSHTransport

__all__ = ["FabricSSHTransport"]
