"""
Server-side fork mapping persistence for context compaction sub-session resolution.

When context auto-compaction forks a session (parent → parent-sub-TIMESTAMP),
the mapping is stored in Redis so subsequent requests on the parent thread_id
are transparently routed to the latest sub-session.

Key patterns:
  fork:{parent_session_id} → child_session_id
  fork_meta:{parent_session_id} → JSON metadata (generation, reason, timestamp)

Database: Redis DB 0 (same as tool configurations)

This makes forking opaque to all clients — no client changes required.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from ..logger_config import get_logger
from .redis_client import get_tools_redis_client

logger = get_logger(__name__)


@dataclass
class ForkChainNode:
    """Represents a single node in a session fork chain.

    Attributes:
        session_id: The session ID for this node.
        generation: Fork generation number (0 for root, 1 for first fork, etc.).
        fork_reason: Why this fork occurred (e.g. "token_limit_exceeded"), or None for root/legacy.
        fork_timestamp: ISO 8601 timestamp of when the fork occurred, or None for root/legacy.
        parent_session_id: The parent session ID, or None for the root node.
        is_terminal: Whether this is the last (most recent) node in the chain.
    """

    session_id: str
    generation: int
    fork_reason: Optional[str]
    fork_timestamp: Optional[str]
    parent_session_id: Optional[str]
    is_terminal: bool


# Safety limit for detecting corrupted (circular) fork chains.
# Fork chains are inherently acyclic — each child ID contains a newer timestamp —
# so legitimate chains can grow without bound as users continue conversations.
# This constant is ONLY used as a fallback if the seen-set cycle detection
# somehow misses a cycle (defensive programming).  It is deliberately large
# so that it never interferes with normal usage.
_MAX_FORK_CHAIN_HOPS = 10_000


async def persist_fork_mapping(
    parent_id: str,
    child_id: str,
    generation: int,
    fork_reason: str,
) -> None:
    """
    Store a parent→child fork mapping in Redis.

    Args:
        parent_id: The original (parent) session ID.
        child_id: The new (forked) sub-session ID.
        generation: Sub-session generation number (1, 2, ...).
        fork_reason: Why the fork occurred (e.g. "token_limit_exceeded").
    """
    try:
        redis_client = await get_tools_redis_client()
        key = f"fork:{parent_id}"
        await redis_client.set(key, child_id)

        # Store fork metadata for introspection tools
        meta_key = f"fork_meta:{parent_id}"
        meta = {
            "generation": generation,
            "fork_reason": fork_reason,
            "fork_timestamp": datetime.utcnow().isoformat(),
            "child_id": child_id,
        }
        await redis_client.set(meta_key, json.dumps(meta))

        logger.info(
            f"[FORK_MAPPING] Persisted: {parent_id} -> {child_id} "
            f"(generation={generation}, reason={fork_reason})"
        )
    except Exception as e:
        # Non-fatal: fork resolution will fall back to original session_id
        logger.error(f"[FORK_MAPPING] Failed to persist {parent_id} -> {child_id}: {e}")


def resolve_root_session_id(session_id: str) -> str:
    """Extract the root session ID by stripping all -sub- fork suffixes.

    O(1) string parsing — no Redis lookup needed. The root is the portion
    before the first '-sub-' occurrence.

    Examples:
        "streamlit_abc123" → "streamlit_abc123"
        "streamlit_abc123-sub-1781216938" → "streamlit_abc123"
        "streamlit_abc123-sub-1781216938-sub-1781218595" → "streamlit_abc123"
    """
    idx = session_id.find("-sub-")
    if idx == -1:
        return session_id
    return session_id[:idx]


async def resolve_fork(session_id: str) -> str:
    """
    Follow the fork chain to the terminal (latest) sub-session.

    Returns session_id unchanged if no fork mapping exists or Redis is
    unavailable (graceful degradation).

    Args:
        session_id: The session ID to resolve.

    Returns:
        The terminal sub-session ID, or the original session_id if no fork.
    """
    try:
        redis_client = await get_tools_redis_client()
    except Exception as e:
        logger.warning(f"[FORK_RESOLUTION] Redis unavailable, returning original: {e}")
        return session_id

    current = session_id
    seen = {session_id}  # cycle detection — fork chains are acyclic by design
    hop = 0
    while True:
        try:
            child = await redis_client.get(f"fork:{current}")
        except Exception as e:
            logger.warning(
                f"[FORK_RESOLUTION] Redis error at hop {hop}, "
                f"returning {current}: {e}"
            )
            return current

        if child is None:
            # End of chain (or no fork exists)
            break

        # Redis returns bytes; decode if needed
        if isinstance(child, bytes):
            child = child.decode("utf-8")

        # Cycle detection: if we've seen this ID before, the chain is corrupt
        if child in seen:
            logger.error(
                f"[FORK_RESOLUTION] Cycle detected at hop {hop}: "
                f"{current} -> {child} (already visited). "
                f"Returning {current}."
            )
            return current

        logger.debug(f"[FORK_RESOLUTION] Hop {hop}: {current} -> {child}")
        seen.add(child)
        current = child
        hop += 1

        # Defensive backstop — should never fire for legitimate chains
        if hop >= _MAX_FORK_CHAIN_HOPS:
            logger.error(
                f"[FORK_RESOLUTION] Defensive limit ({_MAX_FORK_CHAIN_HOPS}) "
                f"reached resolving {session_id}, returning {current}"
            )
            break

    return current


def _estimate_generation_from_id(session_id: str) -> int:
    """Estimate fork generation from the session ID suffix pattern.

    Convention: each fork appends ``-sub-<timestamp>``, so counting
    occurrences of ``-sub-`` gives the generation number.  This is a
    best-effort heuristic used when ``fork_meta:`` keys are missing
    (legacy forks created before metadata persistence was added).
    """
    return session_id.count("-sub-")


async def resolve_fork_chain(session_id: str) -> List[ForkChainNode]:
    """Walk the full fork chain from *session_id* to the terminal node.

    Unlike :func:`resolve_fork` which returns only the terminal session ID,
    this function returns every node in the chain with metadata (generation,
    fork reason, timestamp).  Nodes are ordered root-first.

    Legacy forks (created before ``fork_meta:`` persistence) degrade
    gracefully: ``fork_reason`` and ``fork_timestamp`` will be ``None``,
    and ``generation`` is estimated from the ``-sub-`` count in the ID.

    Args:
        session_id: Any session ID in the chain (typically the root).

    Returns:
        List of :class:`ForkChainNode` from root to terminal.  If no fork
        exists, returns a single-element list containing the input session.
    """
    try:
        redis_client = await get_tools_redis_client()
    except Exception as e:
        logger.warning(f"[FORK_CHAIN] Redis unavailable, returning single node: {e}")
        return [
            ForkChainNode(
                session_id=session_id,
                generation=0,
                fork_reason=None,
                fork_timestamp=None,
                parent_session_id=None,
                is_terminal=True,
            )
        ]

    nodes: List[ForkChainNode] = []
    current = session_id
    seen = {session_id}
    hop = 0
    prev_meta: Optional[dict] = None  # metadata from previous node's outgoing fork

    while True:
        # Read optional metadata for the *outgoing* fork from current
        meta: Optional[dict] = None
        try:
            raw_meta = await redis_client.get(f"fork_meta:{current}")
            if raw_meta:
                if isinstance(raw_meta, bytes):
                    raw_meta = raw_meta.decode("utf-8")
                meta = json.loads(raw_meta)
        except Exception:
            pass  # metadata is optional; graceful degradation

        # Build node for *current*
        if hop == 0:
            # Root node
            generation = _estimate_generation_from_id(current)
            node = ForkChainNode(
                session_id=current,
                generation=generation,
                fork_reason=None,
                fork_timestamp=None,
                parent_session_id=None,
                is_terminal=False,  # tentative; corrected after loop
            )
        else:
            # Non-root: use metadata from the *parent's* outgoing fork edge
            generation = _estimate_generation_from_id(current)
            node = ForkChainNode(
                session_id=current,
                generation=generation,
                fork_reason=prev_meta.get("fork_reason") if prev_meta else None,
                fork_timestamp=prev_meta.get("fork_timestamp") if prev_meta else None,
                parent_session_id=nodes[-1].session_id if nodes else None,
                is_terminal=False,
            )

        nodes.append(node)

        # Remember this node's outgoing-fork metadata for the *next* node
        prev_meta = meta

        # Follow the fork chain
        try:
            child = await redis_client.get(f"fork:{current}")
        except Exception as e:
            logger.warning(f"[FORK_CHAIN] Redis error at hop {hop}: {e}")
            break

        if child is None:
            break

        if isinstance(child, bytes):
            child = child.decode("utf-8")

        if child in seen:
            logger.error(f"[FORK_CHAIN] Cycle detected at hop {hop}: {current} -> {child}")
            break

        seen.add(child)
        current = child
        hop += 1

        if hop >= _MAX_FORK_CHAIN_HOPS:
            logger.error(
                f"[FORK_CHAIN] Defensive limit ({_MAX_FORK_CHAIN_HOPS}) "
                f"reached resolving chain from {session_id}"
            )
            break

    # Mark the last node as terminal
    if nodes:
        nodes[-1].is_terminal = True

    return nodes


async def get_fork_chain_session_ids(session_id: str) -> List[str]:
    """Return ALL session IDs in the fork chain, regardless of starting position.

    Resolves to the root first (via string parsing), then walks forward
    through the full chain. This means calling with a terminal fork ID
    returns the complete lineage [root, fork1, fork2, ..., terminal].

    Args:
        session_id: Any session ID in the chain (root, middle, or terminal).

    Returns:
        Ordered list of session IDs from root to terminal.
    """
    root_id = resolve_root_session_id(session_id)
    chain = await resolve_fork_chain(root_id)
    return [node.session_id for node in chain]
