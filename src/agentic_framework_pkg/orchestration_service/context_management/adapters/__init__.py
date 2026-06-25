"""Adapter implementations for context management factory pattern.

This package contains adapter implementations that wrap existing context manager
implementations with the unified BaseContextManager interface.

Available adapters:
- SimpleContextManagerAdapter: Wraps context_manager.py (fast heuristic)
- AdvancedContextManagerAdapter: Wraps context_window_manager.py (accurate tiktoken)
- HybridContextManagerAdapter: Dual-layer implementation (Phase 3+, not available)

Author: Session 34 Implementation Team
Date: 2026-01-19
"""

from .simple_adapter import SimpleContextManagerAdapter
from .advanced_adapter import AdvancedContextManagerAdapter
from .hybrid_adapter import HybridContextManagerAdapter

__all__ = [
    "SimpleContextManagerAdapter",
    "AdvancedContextManagerAdapter",
    "HybridContextManagerAdapter",
]
