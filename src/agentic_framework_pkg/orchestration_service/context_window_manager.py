"""
Context Window Manager for preventing token overflow in conversations.

This module implements intelligent context window management to prevent
conversations from exceeding LLM token limits. It uses a three-tier strategy:
1. Recent messages: Keep full content
2. Middle messages: Summarize but keep tool references
3. Old messages: Archive with ultra-compact summary

Session 14 Part 16: Solving context window overflow issues.
"""

import json
import os
from typing import Dict, Any, List, Tuple, Optional, Literal
from enum import Enum
from datetime import datetime
import tiktoken
from ..logger_config import get_logger
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
    FunctionMessage,
)

logger = get_logger(__name__)


class WarningLevel(Enum):
    """Context usage warning levels."""

    SAFE = "safe"
    WARNING = "warning"
    CRITICAL = "critical"


class ContextWindowManager:
    """
    Manages conversation context to stay within token limits.

    Implements a sliding window with intelligent message preservation
    and summarization to prevent token overflow errors.
    """

    def __init__(
        self,
        max_tokens: int = None,
        warning_threshold: float = 0.75,
        critical_threshold: float = 0.90,
        preserve_last_n: int = 10,
        auto_manage: bool = True,
    ):
        """
        Initialize the context window manager.

        Args:
            max_tokens: Maximum tokens allowed (default from env)
            warning_threshold: Percentage threshold for warnings
            critical_threshold: Percentage threshold for critical state
            preserve_last_n: Number of recent messages to always preserve
            auto_manage: Whether to automatically manage context
        """
        self.max_tokens = max_tokens or int(os.getenv("CONTEXT_MAX_TOKENS", "150000"))
        self.buffer_tokens = int(os.getenv("CONTEXT_BUFFER_TOKENS", "10000"))
        self.target_tokens = self.max_tokens - self.buffer_tokens

        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.preserve_last_n = preserve_last_n
        self.auto_manage = auto_manage

        # Initialize tokenizer for accurate counting
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")  # GPT-4 encoding
        except Exception as e:
            logger.warning(
                f"Failed to load tiktoken encoding: {e}, using approximation"
            )
            self.encoding = None

        # Metrics tracking
        self.metrics = {
            "compressions_performed": 0,
            "tokens_saved": 0,
            "messages_summarized": 0,
            "overflow_prevented": 0,
        }

    def count_tokens(self, messages: List[BaseMessage]) -> int:
        """
        Count tokens in a list of messages.

        Args:
            messages: List of messages to count

        Returns:
            Total token count
        """
        if not messages:
            return 0

        try:
            if self.encoding:
                # Accurate token counting with tiktoken
                total_tokens = 0
                for message in messages:
                    # Convert message to string representation
                    content = self._message_to_string(message)
                    tokens = len(self.encoding.encode(content))

                    # Add overhead for message structure (role, etc.)
                    tokens += 4  # Approximate overhead per message

                    total_tokens += tokens

                return total_tokens
            else:
                # Fallback: Approximate 1 token per 4 characters
                total_chars = sum(len(self._message_to_string(m)) for m in messages)
                return total_chars // 4
        except Exception as e:
            logger.error(f"Error counting tokens: {e}")
            # Conservative estimate
            return len(str(messages)) // 3

    def _message_to_string(self, message: BaseMessage) -> str:
        """Convert a message to its string representation."""
        if isinstance(message, (HumanMessage, AIMessage, SystemMessage)):
            content = message.content
        elif isinstance(message, ToolMessage):
            content = f"Tool({message.tool_call_id}): {message.content}"
        elif isinstance(message, FunctionMessage):
            content = f"Function({message.name}): {message.content}"
        else:
            content = (
                str(message.content) if hasattr(message, "content") else str(message)
            )

        # Include tool calls if present
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_calls_str = json.dumps(message.tool_calls)
            content += f" [Tools: {tool_calls_str}]"

        return content

    def get_context_status(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        """
        Get current context window utilization status.

        Args:
            messages: Current message list

        Returns:
            Status dictionary with usage metrics
        """
        current_tokens = self.count_tokens(messages)
        utilization = current_tokens / self.max_tokens

        # Determine warning level
        if utilization >= self.critical_threshold:
            warning_level = WarningLevel.CRITICAL
        elif utilization >= self.warning_threshold:
            warning_level = WarningLevel.WARNING
        else:
            warning_level = WarningLevel.SAFE

        return {
            "current_tokens": current_tokens,
            "max_tokens": self.max_tokens,
            "target_tokens": self.target_tokens,
            "utilization_percent": utilization * 100,
            "messages_count": len(messages),
            "warning_level": warning_level.value,
            "available_tokens": self.max_tokens - current_tokens,
            "metrics": self.metrics.copy(),
        }

    async def manage_context_window(
        self, messages: List[BaseMessage], force_compression: bool = False
    ) -> Tuple[List[BaseMessage], Dict[str, Any]]:
        """
        Manage context window with intelligent compression.

        Args:
            messages: Current message list
            force_compression: Force compression even if under limit

        Returns:
            Tuple of (managed messages, action report)
        """
        status = self.get_context_status(messages)

        # Check if management is needed
        if not force_compression and status["warning_level"] == WarningLevel.SAFE.value:
            return messages, {
                "action": "none",
                "reason": "Context within safe limits",
                "status": status,
            }

        # Determine compression level based on utilization
        if status["warning_level"] == WarningLevel.CRITICAL.value or force_compression:
            compressed_messages = await self._aggressive_compress(messages)
            action = "aggressive_compression"
        else:
            compressed_messages = await self._moderate_compress(messages)
            action = "moderate_compression"

        # Update metrics
        new_tokens = self.count_tokens(compressed_messages)
        tokens_saved = status["current_tokens"] - new_tokens
        self.metrics["compressions_performed"] += 1
        self.metrics["tokens_saved"] += tokens_saved

        # Check if we prevented an overflow
        if status["current_tokens"] > self.max_tokens:
            self.metrics["overflow_prevented"] += 1

        return compressed_messages, {
            "action": action,
            "original_tokens": status["current_tokens"],
            "compressed_tokens": new_tokens,
            "tokens_saved": tokens_saved,
            "compression_ratio": (
                new_tokens / status["current_tokens"]
                if status["current_tokens"] > 0
                else 1.0
            ),
            "messages_before": len(messages),
            "messages_after": len(compressed_messages),
            "status": self.get_context_status(compressed_messages),
        }

    async def _moderate_compress(
        self, messages: List[BaseMessage]
    ) -> List[BaseMessage]:
        """
        Apply moderate compression - summarize middle section.

        Args:
            messages: Messages to compress

        Returns:
            Compressed message list
        """
        if len(messages) <= self.preserve_last_n + 1:
            return messages  # Too few messages to compress

        # Separate messages into sections
        system_messages = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        # Keep first and last messages
        if len(non_system) <= self.preserve_last_n * 2:
            # Not enough to create a meaningful middle section
            return messages

        first_messages = non_system[: self.preserve_last_n]
        recent_messages = non_system[-self.preserve_last_n :]
        middle_messages = non_system[self.preserve_last_n : -self.preserve_last_n]

        # Summarize middle section
        summary = await self._summarize_messages(
            middle_messages, detail_level="moderate"
        )

        # Create summary message
        summary_message = SystemMessage(
            content=f"[Context Summary of {len(middle_messages)} messages]\n{summary}"
        )

        # Reconstruct message list
        compressed = (
            system_messages + first_messages + [summary_message] + recent_messages
        )

        self.metrics["messages_summarized"] += len(middle_messages)

        return compressed

    async def _aggressive_compress(
        self, messages: List[BaseMessage]
    ) -> List[BaseMessage]:
        """
        Apply aggressive compression - keep only essential messages.

        Args:
            messages: Messages to compress

        Returns:
            Aggressively compressed message list
        """
        # Keep only system messages and very recent messages
        system_messages = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        # Keep only last N messages
        recent_messages = non_system[-self.preserve_last_n :] if non_system else []

        # Extract key information from all messages
        key_info = self._extract_key_information(messages)

        # Create comprehensive summary
        summary = await self._create_comprehensive_summary(messages, key_info)

        summary_message = SystemMessage(
            content=f"[Comprehensive Context Summary]\n{summary}\n\nKey Information:\n{json.dumps(key_info, indent=2)}"
        )

        # Reconstruct with minimal messages
        compressed = system_messages + [summary_message] + recent_messages

        self.metrics["messages_summarized"] += len(messages) - len(compressed) + 1

        return compressed

    def _extract_key_information(self, messages: List[BaseMessage]) -> Dict[str, Any]:
        """
        Extract key information from messages for preservation.

        Args:
            messages: Messages to analyze

        Returns:
            Dictionary of key information
        """
        key_info = {
            "files_mentioned": set(),
            "tools_used": set(),
            "errors_encountered": [],
            "key_decisions": [],
            "topics": set(),
        }

        for message in messages:
            content = self._message_to_string(message)

            # Extract file references
            if "file" in content.lower() or "upload" in content.lower():
                # Simple extraction - could be enhanced with regex
                words = content.split()
                for i, word in enumerate(words):
                    if word.lower() in [
                        "file",
                        "uploaded",
                        "processed",
                    ] and i + 1 < len(words):
                        potential_file = words[i + 1].strip(".,;:'\"")
                        if "." in potential_file:  # Likely a filename
                            key_info["files_mentioned"].add(potential_file)

            # Extract tool usage
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tool_call in message.tool_calls:
                    if isinstance(tool_call, dict):
                        key_info["tools_used"].add(tool_call.get("name", "unknown"))
                    elif hasattr(tool_call, "name"):
                        key_info["tools_used"].add(tool_call.name)

            # Extract errors
            if "error" in content.lower() or "failed" in content.lower():
                # Add first 100 chars of error context
                key_info["errors_encountered"].append(content[:100] + "...")

        # Convert sets to lists for JSON serialization
        key_info["files_mentioned"] = list(key_info["files_mentioned"])
        key_info["tools_used"] = list(key_info["tools_used"])
        key_info["topics"] = list(key_info["topics"])

        return key_info

    async def _summarize_messages(
        self,
        messages: List[BaseMessage],
        detail_level: Literal["brief", "moderate", "detailed"] = "moderate",
    ) -> str:
        """
        Summarize a list of messages.

        Args:
            messages: Messages to summarize
            detail_level: Level of detail in summary

        Returns:
            Summary string
        """
        # For now, create a simple summary
        # In production, this would use an LLM for intelligent summarization

        summary_parts = []

        # Count message types
        human_count = sum(1 for m in messages if isinstance(m, HumanMessage))
        ai_count = sum(1 for m in messages if isinstance(m, AIMessage))
        tool_count = sum(1 for m in messages if isinstance(m, ToolMessage))

        summary_parts.append(
            f"This section contained {human_count} user messages, "
            f"{ai_count} assistant responses, and {tool_count} tool executions."
        )

        # Extract key topics (simple keyword extraction)
        all_content = " ".join(self._message_to_string(m) for m in messages)

        # Add tool usage summary
        tools_used = set()
        for message in messages:
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tool_call in message.tool_calls:
                    if isinstance(tool_call, dict):
                        tools_used.add(tool_call.get("name", "unknown"))

        if tools_used:
            summary_parts.append(f"Tools used: {', '.join(tools_used)}")

        # Add brief content summary
        if detail_level in ["moderate", "detailed"]:
            # Take first and last user messages as context
            user_messages = [m for m in messages if isinstance(m, HumanMessage)]
            if user_messages:
                first_query = self._message_to_string(user_messages[0])[:100]
                last_query = (
                    self._message_to_string(user_messages[-1])[:100]
                    if len(user_messages) > 1
                    else ""
                )

                summary_parts.append(f"Discussion started with: {first_query}...")
                if last_query and last_query != first_query:
                    summary_parts.append(f"Most recent topic: {last_query}...")

        return "\n".join(summary_parts)

    async def _create_comprehensive_summary(
        self, messages: List[BaseMessage], key_info: Dict[str, Any]
    ) -> str:
        """
        Create a comprehensive summary for aggressive compression.

        Args:
            messages: All messages to summarize
            key_info: Extracted key information

        Returns:
            Comprehensive summary string
        """
        summary_parts = [
            f"Conversation Summary (Total: {len(messages)} messages)",
            "=" * 50,
        ]

        # Add key information summary
        if key_info["files_mentioned"]:
            summary_parts.append(
                f"Files processed: {', '.join(key_info['files_mentioned'])}"
            )

        if key_info["tools_used"]:
            summary_parts.append(f"Tools utilized: {', '.join(key_info['tools_used'])}")

        if key_info["errors_encountered"]:
            summary_parts.append(
                f"Errors encountered: {len(key_info['errors_encountered'])}"
            )

        # Add conversation flow summary
        summary_parts.append("\nConversation Flow:")

        # Get first and last meaningful exchanges
        user_messages = [m for m in messages if isinstance(m, HumanMessage)]
        if user_messages:
            first_msg = self._message_to_string(user_messages[0])[:200]
            summary_parts.append(f"- Started with: {first_msg}...")

            if len(user_messages) > 1:
                last_msg = self._message_to_string(user_messages[-1])[:200]
                summary_parts.append(f"- Currently discussing: {last_msg}...")

        # Add timestamp
        summary_parts.append(f"\nSummary created at: {datetime.now().isoformat()}")

        return "\n".join(summary_parts)

    def create_warning_message(self, status: Dict[str, Any]) -> Optional[str]:
        """
        Create a user-friendly warning message based on context status.

        Args:
            status: Context status dictionary

        Returns:
            Warning message or None if no warning needed
        """
        if status["warning_level"] == WarningLevel.CRITICAL.value:
            return (
                f"⚠️ Context window critical: {status['utilization_percent']:.1f}% used "
                f"({status['current_tokens']:,}/{status['max_tokens']:,} tokens). "
                "Consider starting a new conversation or allowing automatic compression."
            )
        elif status["warning_level"] == WarningLevel.WARNING.value:
            return (
                f"⚠️ Context window warning: {status['utilization_percent']:.1f}% used "
                f"({status['current_tokens']:,}/{status['max_tokens']:,} tokens). "
                "Approaching token limit."
            )
        return None


# Singleton instance for easy access
_manager_instance = None


def get_context_manager() -> ContextWindowManager:
    """Get or create the singleton context manager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ContextWindowManager()
    return _manager_instance
