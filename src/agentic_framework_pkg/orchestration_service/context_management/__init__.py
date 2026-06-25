"""Context Management Factory Pattern - Phase 1 Implementation.

This package implements a factory pattern for context management that enables
zero-breaking-changes migration from single-layer to dual-layer architecture.

Modes:
- simple: Fast buffer layer (heuristic token counting, ~0.1ms)
- advanced: Intelligent tracker (tiktoken counting, ~8ms)
- hybrid: Dual-layer (Phase 3+, not available in Phase 1)

Configuration:
    Set mode via environment variable:
    export CONTEXT_MANAGEMENT_MODE=simple  # default
    export CONTEXT_MANAGEMENT_MODE=advanced
    export CONTEXT_MANAGEMENT_MODE=hybrid  # Phase 3+

Usage:
    # Factory pattern (recommended)
    from agentic_framework_pkg.orchestration_service.context_management import (
        ContextManagerFactory,
        ContextManagerConfig,
        TruncationStrategy,
    )

    # Create factory (singleton)
    factory = ContextManagerFactory()

    # Create manager with default mode
    manager = factory.create()

    # Configure and use
    config = ContextManagerConfig(
        thread_id="thread-123",
        max_context_tokens=140000,
        truncation_strategy=TruncationStrategy.SLIDING_WINDOW
    )

    # Add messages
    from langchain_core.messages import HumanMessage, AIMessage
    messages = [
        HumanMessage(content="Hello!"),
        AIMessage(content="Hi! How can I help you?")
    ]
    await manager.add_messages(messages, config)

    # Get token count
    token_count = await manager.get_token_count(config)
    print(f"Context has {token_count} tokens")

    # Truncate if needed
    if token_count > config.max_context_tokens:
        result = await manager.truncate_context(config)
        print(f"Removed {result.tokens_removed} tokens in {result.latency_ms:.2f}ms")

Author: Session 34 Implementation Team
Date: 2026-01-19
Phase: 1
Version: 1.0.0
"""

# Core factory and base class
from .context_manager_factory import ContextManagerFactory
from .base_context_manager import BaseContextManager

# Configuration classes
from .config import (
    ContextManagementMode,
    TruncationStrategy,
    ContextManagerConfig,
    TruncationResult,
)

# Adapter implementations
from .adapters import (
    SimpleContextManagerAdapter,
    AdvancedContextManagerAdapter,
    HybridContextManagerAdapter,
)

__all__ = [
    # Factory
    "ContextManagerFactory",
    # Base class
    "BaseContextManager",
    # Configuration
    "ContextManagementMode",
    "TruncationStrategy",
    "ContextManagerConfig",
    "TruncationResult",
    # Adapters
    "SimpleContextManagerAdapter",
    "AdvancedContextManagerAdapter",
    "HybridContextManagerAdapter",
]

__version__ = "1.0.0"
__phase__ = 1
