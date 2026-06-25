"""Configuration dataclasses and enums for context management.

This module defines the configuration types used by the context management factory pattern.
It provides mode selection enums and configuration dataclasses for context operations.

Author: Session 34 Implementation Team
Date: 2026-01-19
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ContextManagementMode(str, Enum):
    """
    Supported context management modes.

    Modes:
        SIMPLE: Fast buffer layer using heuristic token counting (context_manager.py).
                Performance: ~0.1ms for 150K tokens, ±10% accuracy.
                Use case: High-throughput production workloads.

        ADVANCED: Intelligent tracker using accurate tiktoken counting (context_window_manager.py).
                  Performance: ~8ms for 150K tokens, exact accuracy.
                  Use case: Precise token budgets, future classification/summarization.

        HYBRID: Dual-layer architecture (fast buffer + intelligent tracker).
                Status: Not available in Phase 1, coming in Phase 3+.
                Use case: Best of both worlds (performance + accuracy).

    Environment Configuration:
        Set via CONTEXT_MANAGEMENT_MODE env var:
        - export CONTEXT_MANAGEMENT_MODE=simple    # Default
        - export CONTEXT_MANAGEMENT_MODE=advanced
        - export CONTEXT_MANAGEMENT_MODE=hybrid    # NotImplementedError in Phase 1

    Example:
        >>> mode = ContextManagementMode("simple")
        >>> mode.value
        'simple'
    """

    SIMPLE = "simple"
    ADVANCED = "advanced"
    HYBRID = "hybrid"


class TruncationStrategy(str, Enum):
    """
    Supported truncation strategies for context management.

    Strategies:
        SLIDING_WINDOW: Remove oldest messages to fit token budget.
                        Available: Phase 1 (both simple and advanced modes).
                        Performance: ~5ms for 100 messages.
                        Use case: Simple FIFO truncation.

        TOKEN_AWARE: Smart selection based on token budget allocation.
                     Available: Phase 2+ (advanced mode only).
                     Performance: ~100ms for 100 messages.
                     Use case: Budget-constrained scenarios with importance weighting.

        IMPORTANCE_BASED: Classify messages (DELETE/SUMMARIZE/RETAIN) and selectively remove.
                          Available: Phase 2+ (advanced mode only).
                          Performance: ~200ms for 100 messages (includes LLM call).
                          Use case: Preserve important context while aggressive truncation.

        HYBRID: Combination of token-aware and importance-based strategies.
                Available: Phase 3+ (hybrid mode only).
                Performance: ~150ms for 100 messages.
                Use case: Optimal balance between performance and quality.

    Example:
        >>> strategy = TruncationStrategy.SLIDING_WINDOW
        >>> strategy.value
        'sliding_window'
    """

    SLIDING_WINDOW = "sliding_window"
    TOKEN_AWARE = "token_aware"
    IMPORTANCE_BASED = "importance_based"
    HYBRID = "hybrid"


@dataclass
class ContextManagerConfig:
    """
    Configuration for context manager operations.

    This dataclass encapsulates all configuration needed for context management operations
    across different modes and strategies. It supports multi-tier session architecture
    for proper isolation in distributed systems.

    Attributes:
        thread_id: Primary thread identifier (required).
                   Maps to LangGraph checkpointer thread_id.

        session_id: User session identifier (optional).
                    Maps to user_sessions table primary key.

        mcp_session_id: MCP tool execution session (optional).
                        Provides session isolation for stateful tool operations.

        multi_agent_session_id: Multi-agent coordination session (optional).
                                Groups related worker agents.

        gateway_session_id: A2A inter-gateway communication session (optional).
                            For agent-to-agent mesh communication.

        max_context_tokens: Maximum token budget for context (default: 150000).
                            Reserve 10K for new input: effective budget = 140K.

        truncation_strategy: Strategy to use for truncation (default: SLIDING_WINDOW).
                             Phase 1: Only SLIDING_WINDOW supported.
                             Phase 2+: TOKEN_AWARE, IMPORTANCE_BASED available.

    Example:
        >>> config = ContextManagerConfig(
        ...     thread_id="thread-123",
        ...     session_id="session-456",
        ...     max_context_tokens=140000,
        ...     truncation_strategy=TruncationStrategy.SLIDING_WINDOW
        ... )
        >>> config.thread_id
        'thread-123'
    """

    thread_id: str
    session_id: Optional[str] = None
    mcp_session_id: Optional[str] = None
    multi_agent_session_id: Optional[str] = None
    gateway_session_id: Optional[str] = None
    max_context_tokens: int = 150000
    truncation_strategy: TruncationStrategy = TruncationStrategy.SLIDING_WINDOW

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.thread_id:
            raise ValueError("thread_id is required")

        if self.max_context_tokens <= 0:
            raise ValueError(f"max_context_tokens must be positive, got {self.max_context_tokens}")

        # Validate truncation strategy is a valid enum value
        if isinstance(self.truncation_strategy, str):
            try:
                self.truncation_strategy = TruncationStrategy(self.truncation_strategy)
            except ValueError:
                valid_strategies = ", ".join([s.value for s in TruncationStrategy])
                raise ValueError(
                    f"Invalid truncation_strategy: {self.truncation_strategy}. "
                    f"Valid strategies: {valid_strategies}"
                )


@dataclass
class TruncationResult:
    """
    Result metadata from truncation operation.

    This dataclass captures comprehensive metrics about a truncation operation,
    enabling observability, debugging, and performance analysis.

    Attributes:
        tokens_before: Token count before truncation.
        tokens_after: Token count after truncation.
        tokens_removed: Number of tokens removed (tokens_before - tokens_after).
        messages_before: Message count before truncation.
        messages_after: Message count after truncation.
        messages_removed: Number of messages removed (messages_before - messages_after).
        strategy_used: Actual strategy used for truncation.
        latency_ms: Truncation operation latency in milliseconds.
        metadata: Strategy-specific metadata (e.g., classification breakdown,
                  archive references, importance scores).

    Example:
        >>> result = TruncationResult(
        ...     tokens_before=152000,
        ...     tokens_after=140000,
        ...     tokens_removed=12000,
        ...     messages_before=100,
        ...     messages_after=85,
        ...     messages_removed=15,
        ...     strategy_used=TruncationStrategy.SLIDING_WINDOW,
        ...     latency_ms=5.2,
        ...     metadata={"mode": "simple", "thread_id": "thread-123"}
        ... )
        >>> result.tokens_removed
        12000
    """

    tokens_before: int
    tokens_after: int
    tokens_removed: int
    messages_before: int
    messages_after: int
    messages_removed: int
    strategy_used: TruncationStrategy
    latency_ms: float
    metadata: dict

    def __post_init__(self):
        """Validate result after initialization."""
        if self.tokens_removed < 0:
            raise ValueError(f"tokens_removed cannot be negative: {self.tokens_removed}")
        if self.messages_removed < 0:
            raise ValueError(f"messages_removed cannot be negative: {self.messages_removed}")
        if self.latency_ms < 0:
            raise ValueError(f"latency_ms cannot be negative: {self.latency_ms}")

    @property
    def compression_ratio(self) -> float:
        """
        Calculate compression ratio (tokens_after / tokens_before).

        Returns:
            Compression ratio as float (0.0 to 1.0).
            Returns 1.0 if tokens_before is 0 (no compression).

        Example:
            >>> result.tokens_before = 150000
            >>> result.tokens_after = 140000
            >>> result.compression_ratio
            0.9333333333333333
        """
        if self.tokens_before == 0:
            return 1.0
        return self.tokens_after / self.tokens_before

    @property
    def removal_percentage(self) -> float:
        """
        Calculate removal percentage (tokens_removed / tokens_before * 100).

        Returns:
            Removal percentage as float (0.0 to 100.0).
            Returns 0.0 if tokens_before is 0 (nothing removed).

        Example:
            >>> result.tokens_before = 150000
            >>> result.tokens_removed = 12000
            >>> result.removal_percentage
            8.0
        """
        if self.tokens_before == 0:
            return 0.0
        return (self.tokens_removed / self.tokens_before) * 100
