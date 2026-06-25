"""
Context Management for Token Limit Control

Implements sliding window context management to prevent token explosion
while preserving session tracking for observability platforms.
"""

import os
import json
import time
from enum import Enum
from typing import List, Tuple, Dict, Any, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, field
from ..logger_config import get_logger

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    FunctionMessage,
)

logger = get_logger(__name__)


class ForkReason(str, Enum):
    """Reason for sub-session fork."""
    TOKEN_LIMIT_EXCEEDED = "token_limit_exceeded"
    MANUAL_FORK = "manual_fork"
    TOOL_COMPLETION_BOUNDARY = "tool_completion_boundary"


@dataclass
class SessionLineage:
    """
    Lineage metadata for sub-session tracking.

    Uses parent-child tuple pattern (not full chain) for simpler maintenance.
    """
    current_session_id: str
    parent_session_id: Optional[str]
    generation: int
    fork_timestamp: datetime
    fork_reason: ForkReason
    parent_message_count: int
    parent_token_count: int
    bootstrap_strategy: str
    bootstrap_message_count: int
    bootstrap_summary: Optional[str] = None


@dataclass
class ContextConfig:
    """Configuration for context management."""

    # Existing context window configuration
    max_tokens: int = 150000  # Maximum tokens in active context
    min_messages: int = 10  # Minimum messages to keep
    summarization_threshold: int = 100000  # When to start summarizing
    window_strategy: str = "sliding"  # sliding|importance|hybrid
    enable_archiving: bool = True
    preserve_system: bool = True
    preserve_tools: bool = True

    # Post-task fork trigger configuration
    post_task_fork_enabled: bool = True  # Enable post-task context health checks
    post_task_fork_threshold_percent: float = 0.8  # Fork at 80% of max_tokens (120k for 150k limit)
    post_task_fork_safety_margin: int = 10000  # Safety margin in tokens

    # Token estimation configuration
    token_estimator_type: str = "tiktoken"  # tiktoken | approximation
    token_estimator_encoding: str = "cl100k_base"  # Encoding for GPT-4/Azure OpenAI
    token_estimator_cache_enabled: bool = True  # Enable token count caching
    token_estimator_cache_ttl: int = 300  # Cache TTL in seconds (5 minutes)

    @classmethod
    def from_env(cls) -> "ContextConfig":
        """Load configuration from environment variables."""
        return cls(
            # Existing configuration
            max_tokens=int(os.getenv("CONTEXT_MAX_TOKENS", "150000")),
            min_messages=int(os.getenv("CONTEXT_MIN_MESSAGES", "10")),
            summarization_threshold=int(
                os.getenv("CONTEXT_SUMMARIZATION_THRESHOLD", "100000")
            ),
            window_strategy=os.getenv("CONTEXT_STRATEGY", "sliding"),
            enable_archiving=os.getenv("CONTEXT_ENABLE_ARCHIVING", "true").lower()
            == "true",
            preserve_system=os.getenv("CONTEXT_PRESERVE_SYSTEM", "true").lower()
            == "true",
            preserve_tools=os.getenv("CONTEXT_PRESERVE_TOOLS", "true").lower()
            == "true",

            # Post-task fork trigger configuration
            post_task_fork_enabled=os.getenv("POST_TASK_FORK_ENABLED", "true").lower()
            == "true",
            post_task_fork_threshold_percent=float(
                os.getenv("POST_TASK_FORK_THRESHOLD_PERCENT", "0.8")
            ),
            post_task_fork_safety_margin=int(
                os.getenv("POST_TASK_FORK_SAFETY_MARGIN", "10000")
            ),

            # Token estimation configuration
            token_estimator_type=os.getenv("TOKEN_ESTIMATOR_TYPE", "tiktoken"),
            token_estimator_encoding=os.getenv("TOKEN_ESTIMATOR_ENCODING", "cl100k_base"),
            token_estimator_cache_enabled=os.getenv("TOKEN_ESTIMATOR_CACHE_ENABLED", "true").lower()
            == "true",
            token_estimator_cache_ttl=int(
                os.getenv("TOKEN_ESTIMATOR_CACHE_TTL", "300")
            ),
        )


@dataclass
class ContextMetadata:
    """Metadata about context truncation."""

    original_message_count: int
    truncated_message_count: int
    original_token_count: int
    truncated_token_count: int
    messages_removed: int = 0
    messages_summarized: int = 0
    truncation_strategy: str = "sliding"
    truncation_timestamp: datetime = field(default_factory=datetime.utcnow)
    archived_message_ids: List[str] = field(default_factory=list)
    session_lineage: Optional[SessionLineage] = None  # Phase 3: Sub-session lineage


class ContextManager:
    """
    Manages conversation context with configurable strategies.

    Prevents token explosion by intelligently truncating message history
    while preserving critical context and session tracking.
    """

    def __init__(
        self,
        config: Optional[ContextConfig] = None,
        token_estimator: Optional[Callable[[List[BaseMessage]], int]] = None
    ):
        """
        Initialize context manager with configuration.

        Args:
            config: Context configuration (defaults to env-based config)
            token_estimator: Optional custom token estimator function.
                           Defaults to _default_token_estimator if not provided.
                           Useful for testing scenarios where token estimation needs
                           to be more aggressive to trigger forks predictably.
        """
        self.config = config or ContextConfig.from_env()
        self.enabled = os.getenv("ENABLE_CONTEXT_MANAGEMENT", "false").lower() == "true"

        # Token estimation cache
        self._token_cache: Dict[str, int] = {}

        # Truncation history for observability and testing
        self.truncation_history: List[ContextMetadata] = []

        # Configurable token estimator (defaults to production estimator)
        self.token_estimator = token_estimator or self._default_token_estimator

        logger.info(
            f"ContextManager initialized: enabled={self.enabled}, "
            f"max_tokens={self.config.max_tokens}, "
            f"strategy={self.config.window_strategy}, "
            f"token_estimator={'custom' if token_estimator else 'default'}"
        )

    def _default_token_estimator(self, messages: List[BaseMessage]) -> int:
        """
        Production token estimator using 4 chars/token heuristic.

        This is the default estimator used in production. Tests can provide
        alternative estimators to make fork behavior more predictable.

        Args:
            messages: List of messages to estimate

        Returns:
            Estimated token count
        """
        total = 0
        for msg in messages:
            # Check cache first
            msg_id = id(msg)
            if msg_id in self._token_cache:
                total += self._token_cache[msg_id]
                continue

            # Estimate tokens
            msg_tokens = 4  # Message overhead

            # Content tokens (roughly 4 chars per token)
            if hasattr(msg, "content") and msg.content:
                msg_tokens += len(str(msg.content)) // 4

            # Tool calls tokens
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                msg_tokens += len(json.dumps(msg.tool_calls, default=str)) // 4

            # Additional content tokens
            if hasattr(msg, "additional_kwargs"):
                msg_tokens += len(json.dumps(msg.additional_kwargs, default=str)) // 4

            # Cache result
            self._token_cache[msg_id] = msg_tokens
            total += msg_tokens

        return total

    def estimate_tokens_accurate(self, messages: List[BaseMessage]) -> int:
        """
        Accurate token counting using tiktoken (cl100k_base encoding).

        This method provides accurate token counting for GPT-4 and Azure OpenAI
        models using the tiktoken library. It includes caching to minimize
        performance overhead.

        Args:
            messages: List of messages to estimate

        Returns:
            Accurate token count using tiktoken

        Note:
            Falls back to character approximation if tiktoken is unavailable.
        """
        if not messages:
            return 0

        try:
            # Lazy-load tiktoken encoding on first use
            if not hasattr(self, '_tiktoken_encoding'):
                import tiktoken
                self._tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
                logger.info("[CONTEXT_MGR] Initialized tiktoken encoding: cl100k_base")

            total_tokens = 0
            for msg in messages:
                # Generate cache key from message content hash
                content_str = self._message_to_string_for_tiktoken(msg)
                cache_key = f"tiktoken:{hash(content_str)}"

                # Check cache first (5-minute TTL handled by caller)
                if cache_key in self._token_cache:
                    total_tokens += self._token_cache[cache_key]
                    continue

                # Encode content with tiktoken
                token_count = len(self._tiktoken_encoding.encode(content_str))

                # Add overhead for message structure (role, metadata)
                token_count += 4  # Message envelope overhead

                # Cache result
                self._token_cache[cache_key] = token_count
                total_tokens += token_count

            logger.debug(
                f"[CONTEXT_MGR] Tiktoken count: {total_tokens} tokens "
                f"for {len(messages)} messages"
            )

            return total_tokens

        except ImportError:
            logger.warning(
                "[CONTEXT_MGR] tiktoken not available, falling back to approximation"
            )
            return self._default_token_estimator(messages)
        except Exception as e:
            logger.error(
                f"[CONTEXT_MGR] Error in tiktoken estimation: {e}, "
                f"falling back to approximation"
            )
            return self._default_token_estimator(messages)

    def _message_to_string_for_tiktoken(self, message: BaseMessage) -> str:
        """
        Convert a message to string representation for tiktoken encoding.

        Includes content, tool calls, and additional metadata for accurate
        token counting.

        Args:
            message: Message to convert

        Returns:
            String representation including all relevant content
        """
        parts = []

        # Main content
        if hasattr(message, "content") and message.content:
            parts.append(str(message.content))

        # Tool calls (if present)
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_calls_str = json.dumps(message.tool_calls, default=str)
            parts.append(f"[tool_calls: {tool_calls_str}]")

        # Additional kwargs (metadata, function calls, etc.)
        if hasattr(message, "additional_kwargs") and message.additional_kwargs:
            kwargs_str = json.dumps(message.additional_kwargs, default=str)
            parts.append(f"[metadata: {kwargs_str}]")

        # Tool call ID for ToolMessage
        if hasattr(message, "tool_call_id") and message.tool_call_id:
            parts.append(f"[tool_call_id: {message.tool_call_id}]")

        return " ".join(parts)

    def estimate_tokens(self, messages: List[BaseMessage]) -> int:
        """
        Estimate token count for messages using configured estimator.

        Delegates to self.token_estimator which defaults to _default_token_estimator
        but can be overridden for testing scenarios.

        Args:
            messages: List of messages to estimate

        Returns:
            Estimated token count
        """
        return self.token_estimator(messages)

    def _estimate_tool_schema_tokens(self, tools: List) -> int:
        """
        Estimate token overhead for tool schemas.

        Phase 3B Fix: Tool definitions are bound to the LLM after prepare_context()
        is called, causing the context manager to underestimate token usage by
        ~13k tokens (36 tools × 362 tokens/tool average).

        This method estimates tool schema tokens so fork detection can make
        accurate decisions about when to trigger session forks.

        Args:
            tools: List of tool objects (LangChain tool format)

        Returns:
            Estimated token count for tool schemas
        """
        if not tools:
            return 0

        total_tokens = 0
        for tool in tools:
            # Estimate tokens for tool definition:
            # - Tool name: ~5-10 tokens
            # - Tool description: ~50-100 tokens
            # - JSON schema: ~200-400 tokens
            # Average: ~362 tokens per tool (from Agent 1 investigation)

            # Use tool name + description for estimation
            tool_tokens = 10  # Base overhead for tool structure

            if hasattr(tool, "name"):
                tool_tokens += len(str(tool.name)) // 4

            if hasattr(tool, "description"):
                tool_tokens += len(str(tool.description)) // 4

            # Add estimated JSON schema overhead (~200 tokens average)
            tool_tokens += 200

            total_tokens += tool_tokens

        logger.debug(
            f"[CONTEXT_MGR] Tool schema estimate: {len(tools)} tools = {total_tokens} tokens "
            f"(~{total_tokens // len(tools) if tools else 0} tokens/tool)"
        )

        return total_tokens

    def _identify_critical_messages(
        self, messages: List[BaseMessage]
    ) -> Tuple[List[int], List[int], List[int]]:
        """
        Identify critical messages to preserve.

        CRITICAL FIX: Properly handles multi-tool-call scenarios where a single
        AIMessage can have multiple tool_calls, creating multiple ToolMessages
        that are NOT adjacent to the AIMessage.

        Returns:
            Tuple of (system_indices, tool_indices, recent_indices)
        """
        system_indices = []
        tool_indices = []
        recent_indices = []

        total_messages = len(messages)

        # Phase 1: Build map of tool_call_id -> AIMessage index
        # This handles multi-tool-call scenarios correctly
        tool_call_id_to_ai_index = {}

        logger.debug(f"[CONTEXT_MGR] Analyzing {total_messages} messages for critical preservation")

        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                # Map each tool_call_id to this AIMessage's index
                for tool_call in msg.tool_calls:
                    if isinstance(tool_call, dict):
                        tool_id = tool_call.get("id")
                    else:
                        tool_id = getattr(tool_call, "id", None)

                    if tool_id:
                        tool_call_id_to_ai_index[tool_id] = i
                        logger.debug(f"[CONTEXT_MGR]   [{i}] AIMessage with tool_call_id: {tool_id}")

        # Phase 2: Identify critical message indices
        for i, msg in enumerate(messages):
            # System messages
            if isinstance(msg, SystemMessage):
                system_indices.append(i)
                logger.debug(f"[CONTEXT_MGR]   [{i}] SystemMessage (critical)")

            # Tool-related messages (keep pairs)
            elif isinstance(msg, (ToolMessage, FunctionMessage)):
                tool_indices.append(i)

                # Find the AIMessage that made this tool call
                tool_call_id = getattr(msg, "tool_call_id", None)

                if tool_call_id and tool_call_id in tool_call_id_to_ai_index:
                    ai_index = tool_call_id_to_ai_index[tool_call_id]
                    if ai_index not in tool_indices:
                        tool_indices.append(ai_index)
                        logger.debug(
                            f"[CONTEXT_MGR]   [{i}] ToolMessage (tool_call_id={tool_call_id}) "
                            f"-> preserving AIMessage at [{ai_index}]"
                        )
                else:
                    logger.warning(
                        f"[CONTEXT_MGR]   [{i}] ToolMessage with orphaned tool_call_id={tool_call_id} "
                        f"(no matching AIMessage found)"
                    )

            # AIMessages with tool_calls are already added via tool_call_id_to_ai_index map
            # No need to add them again here

            # Recent messages (last N)
            if i >= total_messages - self.config.min_messages:
                recent_indices.append(i)

        logger.debug(
            f"[CONTEXT_MGR] Critical indices: system={len(system_indices)}, "
            f"tool={len(tool_indices)}, recent={len(recent_indices)}"
        )

        return system_indices, tool_indices, recent_indices

    async def truncate_context(
        self,
        messages: List[BaseMessage],
        preserve_system: Optional[bool] = None,
        preserve_tools: Optional[bool] = None,
    ) -> Tuple[List[BaseMessage], ContextMetadata]:
        """
        Intelligently truncate message history while preserving critical context.

        Args:
            messages: Full message history
            preserve_system: Whether to preserve system messages
            preserve_tools: Whether to preserve tool messages

        Returns:
            Tuple of (truncated_messages, metadata)
        """
        if not self.enabled:
            # Context management disabled, return as-is
            token_count = self.estimate_tokens(messages)
            metadata = ContextMetadata(
                original_message_count=len(messages),
                truncated_message_count=len(messages),
                original_token_count=token_count,
                truncated_token_count=token_count,
                truncation_strategy="none",
            )
            return messages, metadata

        # Use config defaults if not specified
        preserve_system = (
            preserve_system
            if preserve_system is not None
            else self.config.preserve_system
        )
        preserve_tools = (
            preserve_tools if preserve_tools is not None else self.config.preserve_tools
        )

        # Calculate current token count
        original_token_count = self.estimate_tokens(messages)
        original_message_count = len(messages)

        # If under limit, no truncation needed
        if original_token_count <= self.config.max_tokens:
            metadata = ContextMetadata(
                original_message_count=original_message_count,
                truncated_message_count=original_message_count,
                original_token_count=original_token_count,
                truncated_token_count=original_token_count,
                truncation_strategy="none",
            )
            # Record no-truncation event for observability
            self.truncation_history.append(metadata)
            return messages, metadata

        logger.info(
            f"Truncating context: {original_token_count} tokens "
            f"({original_message_count} messages) -> {self.config.max_tokens} max"
        )

        # Apply truncation strategy
        if self.config.window_strategy == "sliding":
            truncated_messages, metadata = await self._apply_sliding_window(
                messages, preserve_system, preserve_tools
            )
        elif self.config.window_strategy == "importance":
            truncated_messages, metadata = await self._apply_importance_based(
                messages, preserve_system, preserve_tools
            )
        else:  # hybrid
            truncated_messages, metadata = await self._apply_hybrid_strategy(
                messages, preserve_system, preserve_tools
            )

        # Update metadata
        metadata.original_message_count = original_message_count
        metadata.original_token_count = original_token_count
        metadata.truncation_strategy = self.config.window_strategy

        # Record truncation event for observability and testing
        self.truncation_history.append(metadata)

        logger.info(
            f"Context truncated: {metadata.original_message_count} -> "
            f"{metadata.truncated_message_count} messages, "
            f"{metadata.original_token_count} -> {metadata.truncated_token_count} tokens"
        )

        return truncated_messages, metadata

    async def _apply_sliding_window(
        self, messages: List[BaseMessage], preserve_system: bool, preserve_tools: bool
    ) -> Tuple[List[BaseMessage], ContextMetadata]:
        """
        Apply sliding window truncation strategy.

        Keeps most recent messages while preserving critical context.
        """
        # Identify critical messages
        system_indices, tool_indices, recent_indices = self._identify_critical_messages(
            messages
        )

        # Build set of indices to keep
        indices_to_keep = set(recent_indices)

        if preserve_system:
            indices_to_keep.update(system_indices)

        if preserve_tools:
            indices_to_keep.update(tool_indices)

        # Add messages from the end until we hit token limit
        current_tokens = 0
        final_indices = []

        # First add all critical messages
        for i in sorted(indices_to_keep):
            msg_tokens = self.estimate_tokens([messages[i]])
            if current_tokens + msg_tokens <= self.config.max_tokens:
                final_indices.append(i)
                current_tokens += msg_tokens

        # Then add more recent messages if space allows
        for i in range(len(messages) - 1, -1, -1):
            if i not in final_indices:
                msg_tokens = self.estimate_tokens([messages[i]])
                if current_tokens + msg_tokens <= self.config.max_tokens:
                    final_indices.append(i)
                    current_tokens += msg_tokens
                else:
                    break

        # Sort indices and build truncated message list
        final_indices.sort()
        truncated_messages = [messages[i] for i in final_indices]

        # Create metadata
        metadata = ContextMetadata(
            original_message_count=len(messages),
            truncated_message_count=len(truncated_messages),
            original_token_count=self.estimate_tokens(messages),
            truncated_token_count=current_tokens,
            messages_removed=len(messages) - len(truncated_messages),
            archived_message_ids=[
                str(id(messages[i]))
                for i in range(len(messages))
                if i not in final_indices
            ],
        )

        return truncated_messages, metadata

    async def _apply_importance_based(
        self, messages: List[BaseMessage], preserve_system: bool, preserve_tools: bool
    ) -> Tuple[List[BaseMessage], ContextMetadata]:
        """
        Apply importance-based truncation strategy.

        Scores messages by relevance and keeps high-value ones.
        """
        # For now, fall back to sliding window
        # TODO: Implement importance scoring
        return await self._apply_sliding_window(
            messages, preserve_system, preserve_tools
        )

    async def _apply_hybrid_strategy(
        self, messages: List[BaseMessage], preserve_system: bool, preserve_tools: bool
    ) -> Tuple[List[BaseMessage], ContextMetadata]:
        """
        Apply hybrid truncation strategy.

        Combines sliding window with summarization.
        """
        # For now, fall back to sliding window
        # TODO: Implement summarization
        return await self._apply_sliding_window(
            messages, preserve_system, preserve_tools
        )

    async def prepare_context(
        self,
        messages: List[BaseMessage],
        thread_id: Optional[str] = None,
        session_id: Optional[str] = None,
        available_tools: Optional[List] = None,
    ) -> Tuple[List[BaseMessage], Optional[str], ContextMetadata]:
        """
        Prepare context for LLM consumption.

        Phase 3: Returns tuple with optional new session ID if fork occurred.

        Args:
            messages: Full message history
            thread_id: Thread identifier for tracking
            session_id: Session identifier for tracking
            available_tools: Optional list of tools that will be bound to LLM.
                           If provided, tool schema tokens are included in fork threshold.

        Returns:
            Tuple of (prepared_messages, new_session_id_if_forked, metadata)
        """
        if not self.enabled:
            # Context management disabled, return as-is with no fork
            token_count = self.estimate_tokens(messages)
            metadata = ContextMetadata(
                original_message_count=len(messages),
                truncated_message_count=len(messages),
                original_token_count=token_count,
                truncated_token_count=token_count,
                truncation_strategy="none",
            )
            return messages, None, metadata

        # Calculate current token count
        original_token_count = self.estimate_tokens(messages)

        # Add tool schema tokens if tools are provided (Phase 3B fix)
        if available_tools:
            tool_schema_tokens = self._estimate_tool_schema_tokens(available_tools)
            original_token_count += tool_schema_tokens
            logger.debug(
                f"[CONTEXT_MGR] Including tool schema tokens: {tool_schema_tokens} "
                f"({len(available_tools)} tools)"
            )

        original_message_count = len(messages)

        # Check if fork needed (token limit exceeded)
        if original_token_count > self.config.max_tokens:
            logger.info(
                f"[SUB_SESSION_FORK] Token limit exceeded: {original_token_count} > {self.config.max_tokens}"
            )

            # Fork to sub-session
            parent_thread_id = thread_id or session_id
            if not parent_thread_id:
                logger.warning(
                    "[SUB_SESSION_FORK] No thread_id or session_id provided, cannot fork. "
                    "Falling back to destructive truncation."
                )
                # Fallback to Phase 2 behavior
                truncated_messages, metadata = await self.truncate_context(messages)
                return truncated_messages, None, metadata

            new_session_id, lineage, bootstrap_messages = await self._fork_to_sub_session(
                parent_thread_id=parent_thread_id,
                messages=messages,
            )

            # Create metadata for fork event
            metadata = ContextMetadata(
                original_message_count=original_message_count,
                truncated_message_count=len(bootstrap_messages),
                original_token_count=original_token_count,
                truncated_token_count=self.estimate_tokens(bootstrap_messages),
                messages_removed=original_message_count - len(bootstrap_messages),
                truncation_strategy="sub_session_fork",
                session_lineage=lineage,
            )

            # Record fork event
            self.truncation_history.append(metadata)

            logger.info(
                f"[SUB_SESSION_FORK] Forked to new session: {new_session_id} "
                f"(generation {lineage.generation}), bootstrap={len(bootstrap_messages)} messages"
            )

            return bootstrap_messages, new_session_id, metadata

        # No fork needed, use Phase 2 truncation if still over limit
        truncated_messages, metadata = await self.truncate_context(messages)

        # Log truncation event for observability
        if metadata.messages_removed > 0:
            logger.info(
                f"Context truncated for thread={thread_id}, session={session_id}: "
                f"removed {metadata.messages_removed} messages, "
                f"saved {metadata.original_token_count - metadata.truncated_token_count} tokens"
            )

        return truncated_messages, None, metadata

    def _extract_base_thread_id(self, thread_id: str) -> str:
        """
        Extract base thread ID from potentially sub-sessioned thread ID.

        Examples:
            "thread-abc" -> "thread-abc"
            "thread-abc-sub-1737489076" -> "thread-abc"
            "thread-abc-sub-1737489076-sub-1737491234" -> "thread-abc"

        Args:
            thread_id: Full thread ID (may include sub-session suffix)

        Returns:
            Base thread ID without sub-session suffixes
        """
        # Split on "-sub-" and take first part
        parts = thread_id.split("-sub-")
        return parts[0]

    def _extract_generation(self, thread_id: str) -> int:
        """
        Extract generation number from thread ID.

        Examples:
            "thread-abc" -> 0 (base generation)
            "thread-abc-sub-1737489076" -> 1 (first sub-session)
            "thread-abc-sub-1737489076-sub-1737491234" -> 2 (second sub-session)

        Args:
            thread_id: Full thread ID

        Returns:
            Generation number (0 for base, 1+ for sub-sessions)
        """
        # Count occurrences of "-sub-"
        return thread_id.count("-sub-")

    async def _fork_to_sub_session(
        self,
        parent_thread_id: str,
        messages: List[BaseMessage],
    ) -> Tuple[str, SessionLineage, List[BaseMessage]]:
        """
        Fork to new sub-session when token limit exceeded.

        Phase 3: Non-destructive approach to context management.

        Args:
            parent_thread_id: Parent thread ID to fork from
            messages: Full message history from parent session

        Returns:
            Tuple of (new_session_id, lineage_metadata, bootstrap_messages)
        """
        # Extract base thread ID and generation
        base_thread_id = self._extract_base_thread_id(parent_thread_id)
        parent_generation = self._extract_generation(parent_thread_id)
        new_generation = parent_generation + 1

        # Generate timestamp-based session ID
        timestamp = int(time.time())
        new_session_id = f"{base_thread_id}-sub-{timestamp}"

        logger.info(
            f"[SUB_SESSION_FORK] Creating sub-session: "
            f"parent={parent_thread_id} (gen {parent_generation}) -> "
            f"new={new_session_id} (gen {new_generation})"
        )

        # Create bootstrap context (Milestone 4 implementation)
        bootstrap_messages, summary_text = await self._create_bootstrap_context(
            messages=messages,
            parent_thread_id=parent_thread_id,
        )

        # Create lineage metadata
        lineage = SessionLineage(
            current_session_id=new_session_id,
            parent_session_id=parent_thread_id,
            generation=new_generation,
            fork_timestamp=datetime.utcnow(),
            fork_reason=ForkReason.TOKEN_LIMIT_EXCEEDED,
            parent_message_count=len(messages),
            parent_token_count=self.estimate_tokens(messages),
            bootstrap_strategy="hybrid",
            bootstrap_message_count=len(bootstrap_messages),
            bootstrap_summary=summary_text,  # Populated by _create_bootstrap_context
        )

        logger.info(
            f"[SUB_SESSION_FORK] Fork complete: {new_session_id}, "
            f"bootstrap={len(bootstrap_messages)} messages, "
            f"parent_tokens={lineage.parent_token_count}"
        )

        return new_session_id, lineage, bootstrap_messages

    async def _create_bootstrap_context(
        self,
        messages: List[BaseMessage],
        parent_thread_id: str,
    ) -> Tuple[List[BaseMessage], Optional[str]]:
        """
        Create bootstrap context using hybrid strategy.

        Phase 3 Milestone 4: Combines summary for old context with
        full fidelity for recent messages.

        Args:
            messages: Full message history from parent session
            parent_thread_id: Parent thread ID for context

        Returns:
            Tuple of (bootstrap_messages, summary_text)
        """
        if not messages:
            return [], None

        # Reserve tokens for workspace and summary
        workspace_reserve = 10000  # Reserve 10k tokens for LLM workspace
        summary_reserve = 2000  # Reserve 2k tokens for summary message
        token_budget = self.config.max_tokens - workspace_reserve - summary_reserve

        logger.info(
            f"[BOOTSTRAP] Token budget: {token_budget} "
            f"(max={self.config.max_tokens}, workspace={workspace_reserve}, summary={summary_reserve})"
        )

        # Calculate adaptive window: how many recent messages fit in budget
        recent_messages = []
        current_tokens = 0

        # Add messages from end until we hit budget
        for msg in reversed(messages):
            msg_tokens = self.estimate_tokens([msg])
            if current_tokens + msg_tokens <= token_budget:
                recent_messages.insert(0, msg)
                current_tokens += msg_tokens
            else:
                break

        # Ensure valid tool sequences (remove orphaned tool pairs)
        recent_messages = self._ensure_valid_tool_sequences(recent_messages)

        # Recalculate tokens after validation
        current_tokens = self.estimate_tokens(recent_messages)

        logger.info(
            f"[BOOTSTRAP] Recent messages: {len(recent_messages)}/{len(messages)} messages, "
            f"{current_tokens} tokens (after tool validation)"
        )

        # Generate summary for older messages (if any)
        summary_text = None
        older_messages = messages[: len(messages) - len(recent_messages)]
        if older_messages:
            logger.info(
                f"[BOOTSTRAP] Generating summary for {len(older_messages)} older messages"
            )
            summary_text = await self._generate_summary(older_messages)

            if summary_text:
                # Add summary as SystemMessage at the beginning
                summary_msg = SystemMessage(
                    content=f"[Context Summary] {summary_text}\n\n"
                    f"[Lineage Info] This is a sub-session forked from '{parent_thread_id}' "
                    f"due to token limit. The summary above covers the earlier part of the conversation. "
                    f"The messages below show the most recent context in full detail."
                )
                bootstrap_messages = [summary_msg] + recent_messages

                logger.info(
                    f"[BOOTSTRAP] Added summary message ({len(summary_text)} chars), "
                    f"total bootstrap: {len(bootstrap_messages)} messages"
                )
            else:
                # No summary available, just use recent messages
                bootstrap_messages = recent_messages
                logger.warning(
                    f"[BOOTSTRAP] No summary generated, using {len(recent_messages)} recent messages only"
                )
        else:
            # All messages fit in budget, no summary needed
            bootstrap_messages = recent_messages
            logger.info(
                f"[BOOTSTRAP] All {len(messages)} messages fit in budget, no summary needed"
            )

        return bootstrap_messages, summary_text

    async def _generate_summary(
        self,
        messages: List[BaseMessage],
    ) -> Optional[str]:
        """
        Generate summary of message history.

        Phase 3 Milestone 5: Uses LLM for summary with rule-based fallback.

        Args:
            messages: Messages to summarize

        Returns:
            Summary string, or None if no messages
        """
        if not messages:
            return None

        try:
            # Try LLM-based summary first
            return await self._generate_llm_summary(messages)
        except Exception as e:
            logger.warning(
                f"[SUMMARY_GENERATION] LLM summary failed: {e}, falling back to rule-based"
            )
            # Fallback to rule-based summary
            return self._generate_rule_based_summary(messages)

    async def _generate_llm_summary(
        self,
        messages: List[BaseMessage],
    ) -> str:
        """
        Generate summary using LLM.

        Args:
            messages: Messages to summarize

        Returns:
            LLM-generated summary
        """
        # Format messages for summary prompt
        formatted_messages = self._format_messages_for_summary(messages)

        # Create summary prompt
        summary_prompt = f"""Summarize the following conversation history concisely (2-3 sentences):

{formatted_messages}

Summary:"""

        # TODO: Use actual LLM from agent context
        # For now, raise NotImplementedError to trigger fallback
        raise NotImplementedError("LLM summary generation not yet integrated")

    def _generate_rule_based_summary(
        self,
        messages: List[BaseMessage],
    ) -> str:
        """
        Generate summary using rule-based heuristics.

        Fallback when LLM unavailable.

        Args:
            messages: Messages to summarize

        Returns:
            Rule-based summary
        """
        human_messages = [m for m in messages if isinstance(m, HumanMessage)]
        ai_messages = [m for m in messages if isinstance(m, AIMessage)]
        tool_messages = [m for m in messages if isinstance(m, (ToolMessage, FunctionMessage))]

        summary = (
            f"Previous conversation: {len(messages)} messages "
            f"({len(human_messages)} user, {len(ai_messages)} assistant, "
            f"{len(tool_messages)} tool calls)"
        )

        # Add topic hints from first and last user messages
        if human_messages:
            first_content = str(human_messages[0].content)[:100]
            last_content = str(human_messages[-1].content)[:100]
            summary += f". Topics discussed: '{first_content}...' to '{last_content}...'"

        return summary

    def _format_messages_for_summary(
        self,
        messages: List[BaseMessage],
    ) -> str:
        """
        Format messages for LLM summary prompt.

        Args:
            messages: Messages to format

        Returns:
            Formatted string for summary prompt
        """
        formatted = []
        for i, msg in enumerate(messages):
            if isinstance(msg, HumanMessage):
                content = str(msg.content)[:200]
                formatted.append(f"[{i}] User: {content}")
            elif isinstance(msg, AIMessage):
                content = str(msg.content)[:200] if msg.content else "[tool calls]"
                formatted.append(f"[{i}] Assistant: {content}")
            elif isinstance(msg, (ToolMessage, FunctionMessage)):
                formatted.append(f"[{i}] Tool: [result]")

        return "\n".join(formatted)

    def _ensure_valid_tool_sequences(
        self,
        messages: List[BaseMessage],
    ) -> List[BaseMessage]:
        """
        Ensure message sequence has valid tool call/response pairs.

        Phase 3 Milestone 4: Prevents tool message orphaning bug.

        If a ToolMessage is present, ensure its AIMessage with tool_calls is included.
        If an AIMessage with tool_calls is at the end without responses, remove it.

        Args:
            messages: Messages to validate

        Returns:
            Messages with valid tool sequences
        """
        if not messages:
            return messages

        # Phase 1: Build map of tool_call_id -> AIMessage index
        tool_call_id_to_ai_index = {}
        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if isinstance(tool_call, dict):
                        tool_id = tool_call.get("id")
                    else:
                        tool_id = getattr(tool_call, "id", None)
                    if tool_id:
                        tool_call_id_to_ai_index[tool_id] = i

        # Phase 2: Check for orphaned ToolMessages
        required_indices = set(range(len(messages)))
        orphaned_indices = set()

        for i, msg in enumerate(messages):
            if isinstance(msg, (ToolMessage, FunctionMessage)):
                tool_call_id = getattr(msg, "tool_call_id", None)
                if tool_call_id and tool_call_id not in tool_call_id_to_ai_index:
                    # Orphaned ToolMessage - remove it
                    orphaned_indices.add(i)
                    logger.warning(
                        f"[BOOTSTRAP] Removing orphaned ToolMessage at index {i} "
                        f"(tool_call_id={tool_call_id})"
                    )

        # Phase 3: Check for incomplete tool calls at end
        if messages and isinstance(messages[-1], AIMessage):
            if hasattr(messages[-1], "tool_calls") and messages[-1].tool_calls:
                # Last message is AIMessage with tool_calls but no responses
                # Check if any ToolMessages reference this AIMessage
                last_ai_tool_ids = set()
                for tool_call in messages[-1].tool_calls:
                    if isinstance(tool_call, dict):
                        tool_id = tool_call.get("id")
                    else:
                        tool_id = getattr(tool_call, "id", None)
                    if tool_id:
                        last_ai_tool_ids.add(tool_id)

                # Check if any ToolMessages in the list reference these tool_call_ids
                has_responses = False
                for msg in messages:
                    if isinstance(msg, (ToolMessage, FunctionMessage)):
                        tool_call_id = getattr(msg, "tool_call_id", None)
                        if tool_call_id in last_ai_tool_ids:
                            has_responses = True
                            break

                if not has_responses:
                    # No responses for last AIMessage's tool_calls - remove it
                    orphaned_indices.add(len(messages) - 1)
                    logger.warning(
                        "[BOOTSTRAP] Removing incomplete AIMessage with tool_calls at end "
                        "(no corresponding ToolMessages)"
                    )

        # Filter out orphaned messages
        if orphaned_indices:
            messages = [msg for i, msg in enumerate(messages) if i not in orphaned_indices]
            logger.info(
                f"[BOOTSTRAP] Removed {len(orphaned_indices)} orphaned messages, "
                f"keeping {len(messages)} valid messages"
            )

        return messages

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get context management metrics.

        Returns:
            Dictionary of metrics including truncation history
        """
        return {
            "enabled": self.enabled,
            "max_tokens": self.config.max_tokens,
            "min_messages": self.config.min_messages,
            "strategy": self.config.window_strategy,
            "cache_size": len(self._token_cache),
            "truncation_events": len(self.truncation_history),
            "total_messages_removed": sum(
                m.messages_removed for m in self.truncation_history
            ),
        }
