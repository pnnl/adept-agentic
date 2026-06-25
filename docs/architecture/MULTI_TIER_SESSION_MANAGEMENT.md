# Multi-Tier Session Management Architecture

**Status**: Production
**Last Updated**: 2026-01-24
**Related**: [SESSION_LIFECYCLE.md](./SESSION_LIFECYCLE.md), [SESSION_FORKING_ARCHITECTURE.md](./SESSION_FORKING_ARCHITECTURE.md)

---

## Overview

The ADEPT framework implements a **multi-tier session management system** that provides hierarchical isolation and context propagation across different operational scopes: conversations, tool executions, multi-agent teams, and inter-gateway communication.

This architecture enables:
- ✅ Proper state isolation between concurrent operations
- ✅ Cross-session data correlation for observability
- ✅ Cascading multi-agent workflows (teams analyzing other teams)
- ✅ Comprehensive telemetry and debugging capabilities

---

## Session Hierarchy

### Four-Tier Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Tier 1: session_id (Main Conversation Thread)              │
│  - Primary user-agent conversation                          │
│  - LangGraph checkpoint thread_id                           │
│  - Persisted in PostgreSQL checkpoints table                │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Tier 2: mcp_session_id (Tool Execution Context)      │  │
│  │  - Session-scoped MCP tool resources                  │  │
│  │  - File uploads, vector stores, temp directories     │  │
│  │  - Sandbox containers, code execution environments   │  │
│  │                                                        │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │ Tier 3: multi_agent_session_id (Team Scope)    │  │  │
│  │  │  - Multi-agent team coordination               │  │  │
│  │  │  - Worker agent pool and supervisor             │  │  │
│  │  │  - Cross-agent communication context            │  │  │
│  │  │                                                  │  │  │
│  │  │  ┌───────────────────────────────────────────┐  │  │  │
│  │  │  │ Tier 4: gateway_session_id (A2A Mesh)   │  │  │  │
│  │  │  │  - Agent-to-Agent inter-gateway calls    │  │  │  │
│  │  │  │  - Service mesh communication            │  │  │  │
│  │  │  │  - Distributed tracing context           │  │  │  │
│  │  │  └───────────────────────────────────────────┘  │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Session ID Format Conventions

| Tier | Format | Example | Scope |
|------|--------|---------|-------|
| **session_id** | `session_{uuid}` | `session_abc123-def456-...` | Main conversation thread |
| **mcp_session_id** | `mcp_{uuid}` | `mcp_xyz789-uvw012-...` | Tool execution context |
| **multi_agent_session_id** | `multi-agent:{uuid}` | `multi-agent:abc123-def456-...` | Multi-agent team |
| **supervisor_thread_id** | `{multi_agent_session_id}::supervisor` | `multi-agent:abc123::supervisor` | Team supervisor |
| **worker_thread_id** | `{mcp_session_id}::{multi_agent_session_id}::{role}` | `mcp_xyz::multi-agent:abc::chemist` | Worker agent |
| **gateway_session_id** | `gateway_{uuid}` | `gateway_pqr345-stu678-...` | A2A communication |

---

## Tier 1: session_id (Main Conversation Thread)

### Purpose
Primary identifier for user-agent conversations and LangGraph checkpoint threads.

### Lifecycle
- **Created**: At first user message to agent
- **Scope**: Entire conversation history
- **Persisted**: PostgreSQL `checkpoints` table (`thread_id` column)
- **Destroyed**: On explicit thread deletion or TTL expiration

### Usage
```python
# Create agent with session_id
agent = await ScientificWorkflowAgent.create(
    thread_id_override=session_id,
    mcp_session_id=mcp_session_id,
    checkpointer=hybrid_service.checkpointer
)

# Query checkpoints for session
checkpoint_tuple = await checkpointer.aget_tuple({
    "configurable": {"thread_id": session_id}
})
```

### Key Features
- LangGraph loop iterations persisted as checkpoints
- Checkpoint metadata includes `source` (`input`, `loop`) and `step` number
- Enables conversation history retrieval and resumption
- Supports session forking for parallel exploration

---

## Tier 2: mcp_session_id (Tool Execution Context)

### Purpose
Session-scoped isolation for MCP tool resources (files, vector stores, containers).

### Lifecycle
- **Created**: Per conversation (typically `mcp_{session_id}`)
- **Scope**: All MCP tool invocations within conversation
- **Resources**: File uploads, ChromaDB collections, sandbox containers
- **Destroyed**: On session cleanup or container restart

### Session-Isolated Resources

#### File Upload Directories
```
./data/uploaded_files/{mcp_session_id}/
├── input_data.csv
├── analysis_results.json
└── generated_plots/
```

#### ChromaDB Collections
```python
collection_name = f"rag_collection_{mcp_session_id}"
chroma_client.get_or_create_collection(name=collection_name)
```

#### Sandbox Containers
```python
# llm-sandbox creates session-scoped containers
sandbox = SandboxService(session_id=mcp_session_id)
result = await sandbox.execute_code(code, language="python")
```

#### GitXray Processing
```python
temp_dir = f"/tmp/gitxray_{mcp_session_id}/"
output_file = f"{temp_dir}/analysis_{mcp_session_id}.json"
```

### Usage
```python
# MCP tool call with session context
result = await csv_rag_tool.execute(
    query="Analyze protein sequences",
    mcp_session_id=mcp_session_id  # Isolates vector store
)
```

### Critical Requirements
- ✅ All MCP tools must create session-scoped resources
- ✅ No shared state between concurrent sessions
- ✅ Cleanup on session termination to prevent resource leaks
- ✅ Proper error handling for resource conflicts

---

## Tier 3: multi_agent_session_id (Team Scope)

### Purpose
Coordination context for multi-agent teams (router/graph mode).

### Lifecycle
- **Created**: When `CreateMultiAgentSession` tool is called
- **Scope**: All workers + supervisor in team
- **Format**: `multi-agent:{uuid}` (colon-separated for Langfuse metadata)
- **Destroyed**: On team completion or timeout

### Components

#### Supervisor Thread
```python
supervisor_thread_id = f"{multi_agent_session_id}::supervisor"

# Router mode: create_react_agent with checkpointer
supervisor = create_react_agent(
    model=llm,
    tools=worker_tools,
    checkpointer=hybrid_service.checkpointer
)

# Graph mode: LangGraph workflow with supervisor node
workflow.compile(checkpointer=hybrid_service.checkpointer)
```

#### Worker Threads
```python
worker_thread_id = f"{mcp_session_id}::{multi_agent_session_id}::{role_name}"

worker_agent = await ScientificWorkflowAgent.create(
    thread_id_override=worker_thread_id,
    mcp_session_id=mcp_session_id,
    checkpointer=hybrid_service.checkpointer
)
```

### Execution Modes

#### Router Mode
- Static plan generation followed by supervised execution
- Supervisor delegates tasks to workers sequentially
- Plan stored in supervisor checkpoint metadata

#### Graph Mode
- Dynamic LangGraph-based task routing
- State machine logic with supervisor node
- Workers connected as graph nodes with conditional edges

### Usage
```python
# CreateMultiAgentSession tool call
result = await CreateMultiAgentSession.execute(
    roles=["chemist", "data scientist", "code reviewer"],
    task="Analyze protein sequences and generate visualizations",
    mode="router",  # or "graph"
    mcp_session_id=mcp_session_id,
    user_id=user_id
)

# Returns multi_agent_session_id for tracking
multi_agent_session_id = result["multi_agent_session_id"]
```

### Checkpoint Pattern
```
checkpoints table:
┌────────────────────────────────────────────┬──────────────┬──────────┐
│ thread_id                                  │ checkpoint_id│ metadata │
├────────────────────────────────────────────┼──────────────┼──────────┤
│ session_abc123                             │ 1f0f95d6...  │ step: 0  │
│ multi-agent:xyz789::supervisor             │ 1f0f95d7...  │ step: 1  │
│ mcp_abc::multi-agent:xyz789::chemist       │ 1f0f95d8...  │ step: 0  │
│ mcp_abc::multi-agent:xyz789::data_scientist│ 1f0f95d9...  │ step: 0  │
└────────────────────────────────────────────┴──────────────┴──────────┘
```

---

## Tier 4: gateway_session_id (A2A Mesh)

### Purpose
Agent-to-Agent inter-gateway communication in distributed deployments.

### Lifecycle
- **Created**: When agent_gateway forwards request to another gateway
- **Scope**: Cross-gateway RPC calls in service mesh
- **Format**: `gateway_{uuid}`
- **Destroyed**: On request completion

### Usage
```python
# Gateway Registry lookup
gateways = await registry_client.discover_gateways(
    capability="scientific-analysis",
    min_replicas=1
)

# A2A call with gateway_session_id
response = await gateway_client.forward_request(
    target_gateway_url=gateways[0]["url"],
    gateway_session_id=f"gateway_{uuid.uuid4()}",
    original_session_id=session_id,
    payload=request_data
)
```

### Use Cases
- Multi-region agent deployments
- Load balancing across gateway replicas
- Federated agent networks
- Cross-tenant agent collaboration

---

## State Persistence Strategy

### PostgreSQL Checkpointer

**Table**: `checkpoints`

**Schema**:
```sql
CREATE TABLE checkpoints (
    thread_id TEXT,           -- Any tier session ID
    checkpoint_id UUID,       -- Unique checkpoint identifier
    parent_checkpoint_id UUID,
    checkpoint BYTEA,         -- Serialized agent state
    metadata JSONB,           -- {source, step, parents}
    PRIMARY KEY (thread_id, checkpoint_id)
);
```

**Indexes**:
```sql
CREATE INDEX idx_checkpoints_thread ON checkpoints(thread_id);
CREATE INDEX idx_checkpoints_metadata ON checkpoints USING gin(metadata);
```

### Shared Singleton Checkpointer Pattern

**Critical Design Decision** (Session 26, 2025-12-18):
- ✅ **One checkpointer instance** per orchestration service
- ✅ **State isolation via thread_id**, NOT separate checkpointer instances
- ✅ **Connection pool efficiency**: 2 connections vs 40-100 with per-request instantiation

**Before**:
```python
# ❌ WRONG: Per-request instantiation
checkpointer = AsyncPostgresSaver()  # Creates 2 new DB connections
```

**After**:
```python
# ✅ CORRECT: Shared singleton
from ...hybrid_orchestration import hybrid_service
checkpointer = hybrid_service.checkpointer  # Reuses existing connections
```

**Connection Savings**:
- Router operations: 13 instantiations → 1 shared = **26 connections saved**
- Multi-agent sessions: 2 instantiations → 1 shared = **4 connections saved**
- **Total reduction**: 80-85% connection savings under typical load

---

## Telemetry and Observability

### Langfuse Integration

All session tiers propagate to Langfuse telemetry:

```json
{
  "trace_id": "2010581ed9ad9560674279b89c273737",
  "session_id": "session_abc123-def456-...",
  "metadata": {
    "adept_mcp_session_id": "mcp_xyz789-uvw012-...",
    "multi_agent_session_id": "multi-agent:abc123-def456-...",
    "supervisor_thread_id": "multi-agent:abc123::supervisor",
    "worker_roles": ["chemist", "data scientist"],
    "execution_time_ms": 27129,
    "worker_count": 3,
    "execution_mode": "router",
    "status": "success"
  }
}
```

### Utility Introspection Tools

Three tools provide cross-session observability:

#### 1. QueryUserSessions
```python
result = await QueryUserSessions.execute(
    user_id="user123",
    date_from="2026-01-01T00:00:00Z",
    include_telemetry=True  # Cross-reference Langfuse
)
# Returns: session metadata + token usage + costs
```

#### 2. GetSessionHistory
```python
result = await GetSessionHistory.execute(
    session_id="session_abc123-def456-...",
    user_id="user123",
    limit=50
)
# Returns: checkpoint history + messages + tool calls
```

#### 3. QueryLangfuseTelemetry
```python
result = await QueryLangfuseTelemetry.execute(
    user_id="user123",
    session_id="session_abc123-def456-...",
    mcp_session_id="mcp_xyz789-uvw012-..."
)
# Returns: traces + spans + token usage + costs
```

---

## Cascading Multi-Agent Workflows

### Pattern: Teams Analyzing Other Teams

**Use Case**: Operations team introspects production agent execution

```python
# Stage 1: Task Execution Team
stage1_result = await agent.arun(
    user_input="""Create a multi-agent team with:
    - Weather Researcher (uses websearch API)
    - Coding Agent (generates Python code)
    - Librarian (uses PubChem API)
    """,
    session_id=stage1_session_id,
    mcp_session_id=stage1_mcp_session_id
)

# Extract Stage 1 session IDs
stage1_multi_agent_session_id = extract_session_id(stage1_result)

# Stage 2: Observability Team
stage2_result = await agent.arun(
    user_input=f"""Create an observability team with:
    - Checkpoint Analyst
    - Session Analyst
    - Telemetry Analyst

    Analyze the previous team:
    - session_id: {stage1_session_id}
    - mcp_session_id: {stage1_mcp_session_id}
    - multi_agent_session_id: {stage1_multi_agent_session_id}

    Use utility introspection tools to query:
    - Total checkpoints created
    - Tool usage patterns
    - Token costs and resource utilization
    """,
    session_id=stage2_session_id,  # Different session!
    mcp_session_id=stage2_mcp_session_id
)
```

### Validation Evidence

**Test**: `tests/e2e/test_cascading_multiagent_observability.py`

**Results** (2026-01-24):
- ✅ Stage 1: 40 checkpoints (main) + 5 checkpoints (supervisor)
- ✅ Stage 2: 22 checkpoints (main) + 5 checkpoints (supervisor)
- ✅ Stage 2 successfully queried Stage 1 session data
- ✅ Cross-session correlation validated
- ✅ 6 Langfuse traces captured with metadata
- ✅ 258 seconds total execution time

**Report**: [CASCADING_MULTIAGENT_VALIDATION_REPORT_20260124.md](../testing/e2e-validation-reports/CASCADING_MULTIAGENT_VALIDATION_REPORT_20260124.md)

---

## Session Isolation Guarantees

### Concurrent Session Safety

**PostgreSQL Row-Level Isolation**:
```sql
-- Different thread_ids = different rows = no conflicts
SELECT * FROM checkpoints WHERE thread_id = 'session_abc123';
SELECT * FROM checkpoints WHERE thread_id = 'session_xyz789';
```

**MCP Resource Isolation**:
```bash
# Different mcp_session_ids = different directories = no conflicts
./data/uploaded_files/mcp_abc123/
./data/uploaded_files/mcp_xyz789/
```

**Sandbox Container Isolation**:
```python
# Different mcp_session_ids = different containers = no conflicts
container_name = f"sandbox_{mcp_session_id}"
```

### Thread ID Uniqueness Validation

**Test**: `tests/unit/orchestration_service/test_checkpointer_state_isolation.py`

**Assertions**:
```python
# Verify thread IDs are unique
assert stage1_session_id != stage2_session_id
assert stage1_multi_agent_session_id != stage2_multi_agent_session_id

# Verify no checkpoint ID collisions
stage1_checkpoints = await checkpointer.alist({"configurable": {"thread_id": stage1_session_id}})
stage2_checkpoints = await checkpointer.alist({"configurable": {"thread_id": stage2_session_id}})
assert len(set(stage1_checkpoints) & set(stage2_checkpoints)) == 0
```

---

## Best Practices

### 1. Always Propagate Session Context

**Good**:
```python
async def my_mcp_tool(query: str, mcp_session_id: str) -> Dict:
    temp_dir = f"/tmp/processing_{mcp_session_id}/"
    os.makedirs(temp_dir, exist_ok=True)
    # Process with session-scoped resources
```

**Bad**:
```python
async def my_mcp_tool(query: str) -> Dict:
    temp_dir = "/tmp/processing/"  # ❌ Shared across all sessions!
    # Risk of cross-session data leakage
```

### 2. Use Shared Singleton Checkpointer

**Good**:
```python
from ...hybrid_orchestration import hybrid_service
agent = await ScientificWorkflowAgent.create(
    thread_id_override=session_id,
    checkpointer=hybrid_service.checkpointer  # ✅ Shared singleton
)
```

**Bad**:
```python
from ...persistence import AsyncPostgresSaver
checkpointer = AsyncPostgresSaver()  # ❌ Per-request instantiation
agent = await ScientificWorkflowAgent.create(
    thread_id_override=session_id,
    checkpointer=checkpointer
)
```

### 3. Clean Up Session Resources

**Good**:
```python
try:
    result = await tool.execute(mcp_session_id=mcp_session_id)
finally:
    # Clean up session resources
    cleanup_session_files(mcp_session_id)
    cleanup_vector_store(mcp_session_id)
```

**Bad**:
```python
result = await tool.execute(mcp_session_id=mcp_session_id)
# ❌ No cleanup - resource leak!
```

### 4. Validate Session Isolation in Tests

**Good**:
```python
@pytest.mark.asyncio
async def test_concurrent_sessions():
    session1_id = f"session_{uuid.uuid4()}"
    session2_id = f"session_{uuid.uuid4()}"

    # Run concurrently
    results = await asyncio.gather(
        agent.arun(session_id=session1_id, ...),
        agent.arun(session_id=session2_id, ...)
    )

    # Verify isolation
    assert session1_checkpoints != session2_checkpoints
```

---

## Architecture Decisions

### ADR-001: Multi-Tier Session IDs
**Decision**: Use hierarchical session IDs instead of single global ID
**Rationale**: Enables fine-grained isolation while supporting cross-tier correlation
**Consequences**: Requires all tools to propagate session context, increased complexity
**Status**: Accepted

### ADR-002: Shared Singleton Checkpointer
**Decision**: Use single checkpointer instance with thread_id isolation
**Rationale**: 80-85% reduction in PostgreSQL connections
**Consequences**: Requires careful thread_id management
**Status**: Accepted (Session 26, 2025-12-18)

### ADR-003: PostgreSQL for Checkpoints
**Decision**: Use PostgreSQL (not Redis/S3) for checkpoint persistence
**Rationale**: ACID guarantees, JSONB metadata queries, integration with existing DB
**Consequences**: Higher latency than Redis, requires connection pooling
**Status**: Accepted

### ADR-004: Cascading Workflow Support
**Decision**: Enable Stage 2 teams to query Stage 1 session data
**Rationale**: Critical for operations, debugging, and cost analysis teams
**Consequences**: Requires utility introspection tools and telemetry integration
**Status**: Accepted (Session 41, 2026-01-24)

---

## Related Documentation

### Architecture
- [SESSION_LIFECYCLE.md](./SESSION_LIFECYCLE.md) - Session creation and destruction
- [SESSION_FORKING_ARCHITECTURE.md](./SESSION_FORKING_ARCHITECTURE.md) - Session branching
- [ASYNCPOSTGRESSAVER_ARCHITECTURE_ANALYSIS.md](./ASYNCPOSTGRESSAVER_ARCHITECTURE_ANALYSIS.md) - Checkpointer deep dive

### Implementation Plans
- [SessionLevelSingletonCheckpointerPattern_20251217.md](../implementation-plans/SessionLevelSingletonCheckpointerPattern_20251217.md)
- [SESSION_26_PHASE3_COMPLETION_SUMMARY.md](../implementation-plans/SESSION_26_PHASE3_COMPLETION_SUMMARY.md)
- [SESSION_26_PHASE4_COMPLETION_SUMMARY.md](../implementation-plans/SESSION_26_PHASE4_COMPLETION_SUMMARY.md)

### Testing
- [CASCADING_MULTIAGENT_VALIDATION_REPORT_20260124.md](../testing/e2e-validation-reports/CASCADING_MULTIAGENT_VALIDATION_REPORT_20260124.md)
- [DOCKER_TEST_EXECUTION_REFERENCE.md](../testing/DOCKER_TEST_EXECUTION_REFERENCE.md)

### Code References
- `src/agentic_framework_pkg/orchestration_service/hybrid_orchestration.py:46` - Shared checkpointer
- `src/agentic_framework_pkg/orchestration_service/multi_agent_manager.py` - Multi-agent session management
- `src/agentic_framework_pkg/orchestration_service/utility_mcp_tools/session_introspection.py` - Introspection tools
- `tests/e2e/test_cascading_multiagent_observability.py` - Cascading workflow validation

---

**Status**: Production-Ready
**Validation**: Comprehensive E2E tests pass
**Performance**: 80-85% connection reduction vs previous architecture
**Last Validated**: 2026-01-24
