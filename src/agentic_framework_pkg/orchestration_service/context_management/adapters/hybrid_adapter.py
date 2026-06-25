"""Hybrid context manager adapter (reserved for Phase 3+).

Dual-layer architecture combining fast buffer + intelligent tracker.

Status: NOT IMPLEMENTED IN PHASE 1

Future Design (Phase 3):
- Fast layer: Heuristic token counting for real-time operations
- Slow layer: Background tiktoken counting + classification
- Lazy sync: Reconcile layers periodically
- Best of both: Performance + accuracy

Usage:
    # Phase 1: Raises NotImplementedError
    factory.create(mode="hybrid")  # Error!

    # Phase 3+: Will return HybridContextManagerAdapter
    factory.create(mode="hybrid")  # Works!

Author: Session 34 Implementation Team
Date: 2026-01-19
"""

from ..base_context_manager import BaseContextManager


class HybridContextManagerAdapter(BaseContextManager):
    """
    Placeholder for future hybrid implementation.

    Raises NotImplementedError for all methods in Phase 1.

    Phase 3+ Design:
    - Will combine SimpleContextManagerAdapter (fast) + AdvancedContextManagerAdapter (accurate)
    - Fast layer for queries (get_token_count, get_message_count)
    - Slow layer for accurate operations (truncate_context with classification)
    - Background sync between layers
    - Configurable sync frequency

    Implementation Timeline:
    - Phase 1: Not available (this stub)
    - Phase 2: Planning and design
    - Phase 3: Implementation
    - Phase 4: Production deployment
    """

    def __init__(self, *args, **kwargs):
        """
        Raise NotImplementedError for Phase 1.

        Args:
            *args: Any positional arguments (ignored)
            **kwargs: Any keyword arguments (ignored)

        Raises:
            NotImplementedError: Always raised in Phase 1
        """
        raise NotImplementedError(
            "HybridContextManagerAdapter is not available in Phase 1. "
            "Use 'simple' or 'advanced' mode. "
            "Hybrid mode will be implemented in Phase 3+. "
            "\n\n"
            "Roadmap:\n"
            "- Phase 1: simple and advanced modes available\n"
            "- Phase 2: Advanced features (classification, summarization)\n"
            "- Phase 3: Hybrid mode implementation\n"
            "- Phase 4: Production optimization\n"
            "\n"
            "See docs/implementation-plans/SESSION_34_PHASE1_CONTEXT_MANAGEMENT_FACTORY_PATTERN.md "
            "for complete roadmap."
        )

    # All other abstract methods intentionally not implemented
    # (will never be called due to __init__ raising NotImplementedError)
