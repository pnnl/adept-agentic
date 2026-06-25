"""Base abstract class for context management implementations.

This module defines the contract that all context manager adapters must implement.
It provides a unified API for context operations across different implementation strategies.

Design Principles:
- Mode-agnostic interface (works for simple, advanced, hybrid)
- Async-first (all I/O operations are async)
- Type-safe (comprehensive type hints)
- Config-based (explicit configuration passing)

Usage:
    # Factory pattern (recommended)
    factory = ContextManagerFactory()
    manager = factory.create(mode="simple")

    # Direct instantiation (testing only)
    from .adapters.simple_adapter import SimpleContextManagerAdapter
    manager = SimpleContextManagerAdapter(checkpointer=checkpointer)

Author: Session 34 Implementation Team
Date: 2026-01-19
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from langchain_core.messages import BaseMessage

from .config import (
    TruncationStrategy,
    TruncationResult,
    ContextManagerConfig,
)


class BaseContextManager(ABC):
    """
    Abstract base class for all context manager implementations.

    Subclasses must implement:
    - SimpleContextManagerAdapter: Wraps context_manager.py (fast buffer layer)
    - AdvancedContextManagerAdapter: Wraps context_window_manager.py (intelligent tracker)
    - HybridContextManagerAdapter: Dual-layer architecture (Phase 3+)

    All methods are async to support I/O operations (database, checkpointer, etc.).

    Implementation Requirements:
    1. All abstract methods must be implemented by subclasses
    2. Methods should be idempotent where possible
    3. Error handling should be consistent across implementations
    4. Performance metrics should be tracked (latency_ms in results)
    5. Thread-safety is the responsibility of the caller

    Example:
        >>> # Via factory (recommended)
        >>> factory = ContextManagerFactory()
        >>> manager = factory.create(mode="simple")
        >>>
        >>> # Configure and use
        >>> config = ContextManagerConfig(
        ...     thread_id="thread-123",
        ...     max_context_tokens=140000
        ... )
        >>> messages = await manager.get_messages(config)
        >>> token_count = await manager.get_token_count(config)
    """

    @abstractmethod
    async def add_messages(
        self, messages: List[BaseMessage], config: ContextManagerConfig
    ) -> None:
        """
        Add messages to the context.

        This method appends new messages to the existing context for the given thread.
        It does not automatically truncate; call truncate_context() separately if needed.

        Args:
            messages: List of LangChain messages to add (HumanMessage, AIMessage, etc.)
            config: Context manager configuration (contains thread_id and session hierarchy)

        Raises:
            ValueError: If messages list is empty or contains invalid message types
            RuntimeError: If context manager is not initialized or checkpointer unavailable
            TypeError: If messages are not BaseMessage instances

        Example:
            >>> from langchain_core.messages import HumanMessage, AIMessage
            >>> messages = [
            ...     HumanMessage(content="What is context management?"),
            ...     AIMessage(content="Context management handles conversation history...")
            ... ]
            >>> await manager.add_messages(messages, config)
        """
        pass

    @abstractmethod
    async def get_messages(self, config: ContextManagerConfig) -> List[BaseMessage]:
        """
        Retrieve all messages for the given context.

        Returns messages in chronological order (oldest to newest).
        This method does not modify the context.

        Args:
            config: Context manager configuration (contains thread_id)

        Returns:
            List of messages in chronological order.
            Returns empty list if thread_id not found or no messages exist.

        Raises:
            ValueError: If thread_id is invalid (empty string, None)
            RuntimeError: If context manager is not initialized

        Example:
            >>> messages = await manager.get_messages(config)
            >>> len(messages)
            100
            >>> messages[0].content
            'First message content'
        """
        pass

    @abstractmethod
    async def truncate_context(
        self,
        config: ContextManagerConfig,
        strategy: Optional[TruncationStrategy] = None,
    ) -> TruncationResult:
        """
        Truncate context to fit within token budget.

        Removes messages according to the specified strategy until the context fits
        within max_context_tokens. The operation is performed in-place (modifies
        the context in the checkpointer).

        Args:
            config: Context manager configuration (includes max_context_tokens)
            strategy: Override strategy (uses config.truncation_strategy if None)

        Returns:
            TruncationResult with comprehensive metadata:
            - tokens_before/after: Token counts
            - messages_before/after: Message counts
            - strategy_used: Actual strategy used
            - latency_ms: Operation latency
            - metadata: Implementation-specific details

        Raises:
            ValueError: If strategy is not supported by the implementation
            RuntimeError: If truncation fails or context manager not initialized
            NotImplementedError: If strategy is not available in current phase

        Phase Availability:
            - Phase 1: SLIDING_WINDOW only (both simple and advanced modes)
            - Phase 2+: TOKEN_AWARE, IMPORTANCE_BASED (advanced mode only)
            - Phase 3+: HYBRID (hybrid mode only)

        Example:
            >>> # Basic usage (uses config.truncation_strategy)
            >>> result = await manager.truncate_context(config)
            >>> print(f"Removed {result.tokens_removed} tokens in {result.latency_ms:.2f}ms")
            Removed 12000 tokens in 5.23ms
            >>>
            >>> # Override strategy
            >>> result = await manager.truncate_context(
            ...     config,
            ...     strategy=TruncationStrategy.TOKEN_AWARE  # Phase 2+
            ... )
        """
        pass

    @abstractmethod
    async def get_token_count(self, config: ContextManagerConfig) -> int:
        """
        Get current token count for the context.

        Token counting method depends on implementation:
        - SimpleAdapter: Fast heuristic (4 chars/token, ~0.1ms)
        - AdvancedAdapter: Accurate tiktoken (cl100k_base, ~8ms)
        - HybridAdapter: Uses fast layer for queries (Phase 3+)

        Args:
            config: Context manager configuration (contains thread_id)

        Returns:
            Token count as integer.
            Returns 0 if thread_id not found or no messages exist.

        Raises:
            ValueError: If thread_id is invalid
            RuntimeError: If context manager is not initialized

        Performance Characteristics:
            - Simple mode: O(n) where n is total characters, ~0.1ms for 600K chars
            - Advanced mode: O(n) where n is messages, ~8ms for 100 messages

        Example:
            >>> token_count = await manager.get_token_count(config)
            >>> print(f"Current context: {token_count} tokens")
            Current context: 142567 tokens
        """
        pass

    @abstractmethod
    async def get_message_count(self, config: ContextManagerConfig) -> int:
        """
        Get current message count for the context.

        Args:
            config: Context manager configuration (contains thread_id)

        Returns:
            Message count as integer.
            Returns 0 if thread_id not found or no messages exist.

        Raises:
            ValueError: If thread_id is invalid
            RuntimeError: If context manager is not initialized

        Example:
            >>> message_count = await manager.get_message_count(config)
            >>> print(f"Context has {message_count} messages")
            Context has 95 messages
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """
        Clean up resources (if any).

        Called during service shutdown or adapter disposal.
        Subclasses should:
        - Close database connections
        - Flush pending operations
        - Release file handles
        - Clean up temporary resources

        This method is synchronous (not async) to support usage in __del__ and
        context manager __exit__.

        Example:
            >>> manager = factory.create(mode="simple")
            >>> try:
            ...     # Use manager
            ...     await manager.add_messages(messages, config)
            ... finally:
            ...     manager.close()
        """
        pass

    @abstractmethod
    def get_implementation_info(self) -> Dict[str, Any]:
        """
        Get metadata about the implementation.

        Returns implementation-specific metadata for debugging, monitoring,
        and observability purposes.

        Returns:
            Dict with keys:
            - mode: "simple", "advanced", or "hybrid"
            - token_counting_method: "heuristic", "tiktoken", or "hybrid"
            - avg_latency_ms: Average operation latency (float)
            - underlying_class: Wrapped class name (str)
            - strategies_supported: List of supported TruncationStrategy values
            - phase: Current implementation phase (int)
            - version: Adapter version string
            - additional implementation-specific metadata

        Example:
            >>> info = manager.get_implementation_info()
            >>> print(info["mode"])
            'simple'
            >>> print(info["token_counting_method"])
            'heuristic'
            >>> print(info["avg_latency_ms"])
            0.1
            >>> print(info["strategies_supported"])
            ['sliding_window']
        """
        pass

    # Optional helper methods with default implementations

    def supports_strategy(self, strategy: TruncationStrategy) -> bool:
        """
        Check if this implementation supports a given strategy.

        Args:
            strategy: TruncationStrategy to check

        Returns:
            True if strategy is supported, False otherwise

        Example:
            >>> manager.supports_strategy(TruncationStrategy.SLIDING_WINDOW)
            True
            >>> manager.supports_strategy(TruncationStrategy.TOKEN_AWARE)
            False  # Phase 1 only supports SLIDING_WINDOW
        """
        info = self.get_implementation_info()
        supported_strategies = info.get("strategies_supported", [])
        return strategy.value in supported_strategies

    def get_mode(self) -> str:
        """
        Get the mode of this context manager.

        Returns:
            Mode string: "simple", "advanced", or "hybrid"

        Example:
            >>> manager.get_mode()
            'simple'
        """
        info = self.get_implementation_info()
        return info.get("mode", "unknown")

    def get_token_counting_method(self) -> str:
        """
        Get the token counting method used by this implementation.

        Returns:
            Method string: "heuristic", "tiktoken", or "hybrid"

        Example:
            >>> manager.get_token_counting_method()
            'heuristic'
        """
        info = self.get_implementation_info()
        return info.get("token_counting_method", "unknown")

    def __repr__(self) -> str:
        """
        String representation for debugging.

        Returns:
            String with mode and class name

        Example:
            >>> repr(manager)
            '<SimpleContextManagerAdapter mode=simple>'
        """
        info = self.get_implementation_info()
        mode = info.get("mode", "unknown")
        return f"<{self.__class__.__name__} mode={mode}>"

    def __str__(self) -> str:
        """
        Human-readable string representation.

        Returns:
            String with mode and token counting method

        Example:
            >>> str(manager)
            'ContextManager(mode=simple, token_counting=heuristic)'
        """
        info = self.get_implementation_info()
        mode = info.get("mode", "unknown")
        method = info.get("token_counting_method", "unknown")
        return f"ContextManager(mode={mode}, token_counting={method})"
