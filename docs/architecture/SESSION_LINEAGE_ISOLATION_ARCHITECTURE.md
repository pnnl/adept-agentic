# Session Lineage Isolation Architecture

**Status**: Active
**Created**: Session 57, Phase 3 (2026-02-14)
**Authors**: Session 57 implementation + architecture review
**Supersedes**: Partial coverage in `MULTI_TIER_SESSION_MANAGEMENT.md`, `SESSION_FORKING_ARCHITECTURE.md`

---

## 1. Core Principle: Layered Session Isolation

The orchestration layer manages two categories of session identity that must not leak across boundaries.

### Stable Identity (tool-visible)

Session IDs that tools, file systems, and external services see:

| ID | Scope | Created By |
|----|-------|------------|
| `mcp_session_id` | Tool persistence, file directories, Redis metadata | `responses.py` (pre-fork) |
| `multi_agent_session_id` | Team coordination | `create_multi_agent_session_impl()` (independent UUID) |
| `gateway_session_id` | A2A delegation routing | Client (explicit only) |

### Volatile Identity (orchestration-internal)

Session IDs that exist only for checkpoint/state management:

| ID | Scope | Created By |
|----|-------|------------|
| Fork sub-session IDs (`{parent}-sub-{timestamp}`) | Context compaction artifacts | `graph_builder.py` → `context_manager.prepare_context()` |
| Fork chain mappings (`fork:{parent} → child`) | Redis lookup chain | `persist_fork_mapping()` |
| LangGraph checkpoint `thread_id` | May follow forks for state continuity | `responses.py` (post-fork) |

### Boundary Rule

**Volatile identity NEVER propagates to the tool/execution layer.** The orchestration layer resolves volatile state internally and presents only stable identity downstream.

---

## 2. The 4-Tier Session Hierarchy

Defined in `session_hierarchy.py` as `SessionTier` enum and `SessionHierarchy` dataclass.

| Tier | Field | Scope | Created By | Fork-Sensitive? |
|------|-------|-------|------------|-----------------|
| 1 — Basic | `session_id` | Checkpoint thread | Client or auto-generated | **Yes** — follows forks for LangGraph state |
| 2 — Tool | `mcp_session_id` | File I/O, Redis metadata | `responses.py` (pre-fork) | **No** — must be fork-agnostic |
| 3 — Team | `multi_agent_session_id` | Worker coordination | `create_multi_agent_session_impl` | **No** — independent UUID |
| 4 — Gateway | `gateway_session_id` | A2A delegation | Client (explicit only) | **No** — external routing concern |

### Key Design Decisions

- **Tier 1 (`session_id`) is the only fork-sensitive tier.** It follows the fork chain so that LangGraph checkpoints read/write to the correct sub-session.
- **Tier 2 (`mcp_session_id`) is immutable once assigned.** It uses the original (pre-fork) session ID so that file system paths, Redis `file_metadata:*` keys, and sandbox session directories remain stable across context compactions.
- **Tier 3 and 4 are independent.** They are generated separately and never derived from Tier 1 or Tier 2.

---

## 3. Session ID Propagation Rules

### Rule 1: Fork IDs are invisible below the orchestration boundary

`responses.py` resolves forks for `session_id` (checkpoint use) but uses `original_session_id` for tool layer operations.

```python
# responses.py:276-287
original_session_id = session_id          # STABLE (pre-fork)
resolved_session_id = await resolve_fork(session_id)
if resolved_session_id != session_id:
    session_id = resolved_session_id      # VOLATILE (follows fork chain)

mcp_session = request.mcp_session_id or original_session_id  # STABLE
```

MCP tools, file management, and sandbox all receive the stable parent ID.

### Rule 2: Tools receive session context via closure binding, not LLM arguments

`MCPToolWrapper.__init__` captures `mcp_session_id` at factory time. `_arun()` injects it into `params_for_tool_call` — the LLM cannot override it.

```python
# mcp_langchain_tools.py:554-561
params_for_tool_call = kwargs.copy()
params_for_tool_call["mcp_session_id"] = self.mcp_session_id  # captured at init
```

### Rule 3: Multi-agent sessions inherit the parent's stable `mcp_session_id`

`create_multi_agent_session_impl()` stores `mcp_session_id` in session_data. Worker agents inherit via `_recreate_session_runnables()`.

Worker `thread_id` format: `{mcp_session_id}::{multi_agent_session_id}::{role}` — uses the stable parent MCP ID, not a forked ID.

### Rule 4: A2A delegation preserves original hierarchy, adds gateway layer

`create_for_a2a_delegation()` copies all original tier IDs:
- `session_id` — preserved
- `mcp_session_id` — preserved (file isolation stable across gateways)
- `multi_agent_session_id` — preserved if present
- Only adds `gateway_session_id` and `delegation_chain`

### Rule 5: Delegation chain depth should be bounded

Current state: `delegation_chain: List[str]` in `SessionHierarchy` (line 60) has no depth limit. See [Risk 1](#risk-1-a2a-delegation-chain--unbounded-growth) below.

---

## 4. Growth Analysis: Where Session IDs Can Expand

| Pattern | Current Growth | Bounded? | Risk |
|---------|---------------|----------|------|
| Fork chain (Redis `fork:{parent} → child`) | 1 Redis key per fork | **No — unbounded by design** | None — users can continue conversations indefinitely |
| Fork suffix (`-sub-{ts}`) | Linear per fork | No practical limit | None — each suffix is unique |
| Worker `thread_id` (`mcp::multi::role`) | Fixed 3-part concat | Yes (deterministic) | Low |
| A2A `delegation_chain` | 1 entry per hop | **No — unbounded** | **High** (see Risk 1) |
| Composite sandbox prefix | Truncated to 8 chars per tier | Yes (fixed width) | Low |
| Multi-agent within A2A | Independent UUID, no nesting | Yes | Low |

### Fork Chain Scalability

Fork chains grow by one Redis key per context compaction. Since context compaction typically occurs when the context window fills (every ~30-100 turns depending on tool output size), a conversation with 1000 turns might produce ~10-30 forks.

The `resolve_fork()` function uses **cycle detection** (seen-set) rather than a hop count limit. This means:
- Legitimate chains of any length resolve correctly
- Circular references (data corruption) are detected in O(chain_length) with O(chain_length) memory
- A defensive backstop at 10,000 hops exists but should never fire for legitimate chains

---

## 5. Invariants

1. **`mcp_session_id` is immutable once assigned** — never changes across forks, multi-agent creation, or A2A delegation.
2. **Fork resolution is idempotent** — calling `resolve_fork()` on an already-resolved (terminal) ID returns it unchanged.
3. **Tool session context is captured at binding time** — not influenced by subsequent forks during the same request.
4. **`gateway_session_id` is explicit-only** — never auto-generated or defaulted (prevents accidental A2A delegation mode).
5. **Worker `mcp_session_id` equals parent `mcp_session_id`** — file isolation is shared within a team.
6. **Fork chains are acyclic** — each child ID contains a timestamp strictly newer than the parent. Cycle detection is a safety net, not a normal-path mechanism.

---

## 6. Session ID Flow Diagram

```
Client Request (session_id = "streamlit_5f58...")
│
▼ responses.py
├─ original_session_id = "streamlit_5f58..."     ← STABLE (pre-fork)
├─ session_id = resolve_fork(...)                ← VOLATILE (follows fork chain)
│   = "streamlit_5f58...-sub-177..."
│
├─ Checkpoint ops: use session_id (volatile)     ← LangGraph, PostgreSQL
│
├─ Tool layer: use original_session_id (stable)  ← MCPToolWrapper, files, Redis
│   mcp_session = original_session_id
│
└─ Multi-agent creation:
    CreateMultiAgentSession(mcp_session_id = original_session_id)
    │
    └─ Workers:
        mcp_session_id = original_session_id     ← INHERITED (stable)
        multi_agent_session_id = "multi-agent:{uuid}"  ← INDEPENDENT
        thread_id = "{stable}::{team}::{role}"   ← COMPOSITE (bounded)
```

### Fork Resolution Detail

```
resolve_fork("streamlit_5f58...")
│
├─ Redis GET fork:streamlit_5f58...
│   → "streamlit_5f58...-sub-1771098917"
│
├─ Redis GET fork:streamlit_5f58...-sub-1771098917
│   → "streamlit_5f58...-sub-1771103042"
│
├─ Redis GET fork:streamlit_5f58...-sub-1771103042
│   → None (end of chain)
│
└─ Returns: "streamlit_5f58...-sub-1771103042"
    (3 hops, cycle-detection set = {original, sub-1, sub-2, sub-3})
```

---

## 7. Implementation Reference

### Key Source Files

| File | Role | Key Lines |
|------|------|-----------|
| `orchestration_service/routers/v1/responses.py` | Fork resolution + `original_session_id` preservation | 276-287 |
| `orchestration_service/context_compaction_fork_mapping.py` | `resolve_fork()` with cycle detection, `persist_fork_mapping()` | 56-118 |
| `orchestration_service/session_hierarchy.py` | `SessionHierarchy` dataclass, 4-tier model | 34-213 |
| `orchestration_service/session_manager.py` | `MultiTierSessionManager`, hierarchy resolution | 83-396 |
| `orchestration_service/scientific_workflow/graph_builder.py` | Fork detection in `call_model()`, double-fork guard | 147-198 |
| `orchestration_service/scientific_workflow/mcp_langchain_tools.py` | `MCPToolWrapper._arun()` — `mcp_session_id` injection | 554-569 |
| `orchestration_service/multi_agent_manager.py` | Worker creation with `mcp_session_id` propagation | 350-445 |
| `mcp_server/tools/file_management_tools.py` | Redis fallback for fork-related file discovery | 105-142 |

### Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_context_compaction_fork_mapping.py` | 12 unit tests | Persist, resolve, cycle detection, long chains, Redis failures |
| `test_graph_builder.py::TestCallModelDoubleForkGuard` | 3 tests | Double-fork guard within single graph execution |
| `test_context_compaction_fork_mapping_integration.py` | 7 tests | Real Redis integration |
| `test_fork_resolution_e2e.py` | 7 tests | End-to-end fork + file operations |

---

## 8. Known Risks and Future Work

### Risk 1: A2A delegation chain — unbounded growth

**Current state**: `delegation_chain: List[str]` in `SessionHierarchy` (line 60) has no depth limit.

**Location**: `session_hierarchy.py:60`, `session_manager.py:387`

**Impact**: If gateway A delegates to B, B delegates to C, C delegates to D, etc., the chain grows linearly. Each entry is a gateway ID string (~36 bytes for UUID), so practical memory impact is low, but unbounded growth is an architectural smell.

**Recommendation**: Add `MAX_A2A_DELEGATION_DEPTH` constant and enforce in `_resolve_a2a_session_hierarchy()`. A reasonable default would be 10 (10 gateway hops covers any realistic federation topology).

### Risk 2: `linked_response_session` uses forked ID

**Current state**: `responses.py:310` sets `linked_response_session: session_id` which is the forked (volatile) ID.

**Impact**: Low — only used as checkpoint-level metadata linkage, not for tool operations. The linkage correctly tracks which checkpoint thread the multi-agent session was created from.

**Recommendation**: Acceptable as-is. Document for future reference.

### Risk 3: Pre-Phase-3 multi-agent sessions may store forked `mcp_session_id`

**Current state**: Any multi-agent session created between Phase 1 (fork resolution enabled) and Phase 3 (file layer fix applied) may have a forked `mcp_session_id` persisted in `session_data`.

**Impact**: One-time migration concern. Workers recreated from such sessions would use the old forked ID for file lookups.

**Recommendation**: Self-healing — the next session creation uses the correct stable ID. No active migration needed.

---

## 9. Relationship to Other Architecture Documents

| Document | Relationship |
|----------|-------------|
| `MULTI_TIER_SESSION_MANAGEMENT.md` | Describes the 4-tier model in general terms; this document adds fork isolation semantics |
| `SESSION_FORKING_ARCHITECTURE.md` | Describes the forking mechanism; this document adds the isolation boundary rules |
| `POST_TASK_FORK_TRIGGER_ARCHITECTURE.md` | Describes when forks are triggered; this document describes how fork IDs are contained |
| `CONTEXT_MANAGEMENT_ARCHITECTURE_PLAN.md` | Broader context management strategy; this document focuses on session ID isolation |
| `docs/bugfixes/SESSION_57_SUB_SESSION_FORK_LOOP_FIX.md` | Implementation details of the Phase 1-3 bugfix that motivated this architecture document |
