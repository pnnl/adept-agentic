# LangGraph Agent Execution Architecture

**Audience**: Platform AI Engineers
**Prerequisites**: Python, async/await, basic familiarity with LLM APIs
**Purpose**: Explains the agentic SDK foundations ADEPT builds on, and how the platform implements agent execution

---

## Foundation: LangChain vs LangGraph

### LangChain — Components Library

LangChain is a library of standardized components for working with LLMs: model wrappers (`ChatOpenAI`, `ChatAnthropic`), prompt templates (`ChatPromptTemplate`), output parsers, tool interfaces (`BaseTool`), document loaders, retrievers, and vector stores.

The core abstraction is the **chain** — a linear pipeline of steps composed with the pipe operator:

```python
chain = prompt | llm | parser
result = chain.invoke({"input": "What is DNA?"})
```

Chains are **stateless** and **acyclic**. Data flows in one direction. There is no built-in mechanism for a chain to loop back to a previous step, persist state between invocations, or make dynamic routing decisions mid-execution.

ADEPT uses LangChain components pervasively — `BaseTool` for tool interfaces, `BaseMessage` / `AIMessage` / `HumanMessage` for conversation state, `ChatPromptTemplate` for prompt construction, and LangChain-compatible LLM wrappers via `LLMAgnosticClient`.

### LangGraph — Stateful Execution Runtime

LangGraph is a runtime for **stateful, cyclical graphs** built on top of LangChain's components. The core abstraction is the `StateGraph`: a set of **nodes** (async functions) connected by **edges** (transitions), operating on a shared `TypedDict` state that accumulates across steps.

Three capabilities LangGraph adds that LangChain chains cannot provide:

1. **Cycles** — A node can route back to a previous node. This is what makes agent loops possible: the model calls a tool, observes the result, and decides whether to call another tool or stop. LangChain chains are DAGs and cannot loop.

2. **Persistent state** — The `StateGraph` carries a typed state object through every node. Combined with a **checkpointer** (PostgreSQL, SQLite, or in-memory), the graph can be paused mid-execution, serialized to storage, and resumed across HTTP requests. LangChain chains have no built-in persistence between invocations.

3. **Conditional routing** — `add_conditional_edges()` lets a function inspect the current state and choose which node to visit next. This enables dynamic multi-way routing that LangChain's simpler `RunnableBranch` cannot express mid-graph.

**In summary**: LangChain provides the nouns (models, tools, messages, prompts). LangGraph provides the verb — the execution engine that orchestrates those components in loops with memory.

---

## The ReAct Pattern

**ReAct** (Reasoning + Acting) is a prompting pattern where an LLM alternates between three steps in a loop:

1. **Think** — Reason about the current state and decide what to do next
2. **Act** — Call a tool based on that reasoning
3. **Observe** — Receive the tool's output and incorporate it into context

The loop repeats until the LLM decides it has enough information to produce a final answer (or hits a safety limit).

LangGraph's `create_react_agent` implements this as a minimal two-node graph:

```
→ [agent] → has tool calls? → yes → [tools] → back to [agent]
                             → no  → END
```

The LLM controls all routing decisions — it decides which tools to call, when to loop, and when to stop. There is no external logic governing the flow beyond checking whether the last message contains tool calls.

This pattern is effective for single-turn tool use but has no built-in protection against infinite loops, no context window management, and no way to override the LLM's routing decisions.

---

## ADEPT's Main Agent: Guarded ReAct Graph

ADEPT's primary agent (`ScientificWorkflowAgent`) does **not** use `create_react_agent`. Instead, it builds a custom `StateGraph` with three nodes and a conditional routing function that can override the LLM's decisions.

**Implementation**: `orchestration_service/scientific_workflow/graph_builder.py`

```python
# graph_builder.py:1194-1206
def build(self) -> StateGraph:
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", self.call_model)
    workflow.add_node("action", self._custom_tool_node)
    workflow.add_node("terminate", self.termination_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent", self.should_continue,
        {"continue": "action", "terminate": "terminate", "end": END}
    )
    workflow.add_edge("action", "agent")
    workflow.add_edge("terminate", END)
    return workflow
```

**Graph structure:**

```
→ [agent] → should_continue() → "continue" → [action] → back to [agent]
                               → "terminate" → [terminate] → END
                               → "end"       → END
```

### Node responsibilities

| Node | Function | Purpose |
|------|----------|---------|
| `agent` | `call_model()` | Invokes the LLM with current message history. Handles context truncation, orphaned tool call repair, and pre-LLM session forking when context exceeds budget. |
| `action` | `_custom_tool_node()` | Executes tool calls requested by the agent. Implements split-stream output handling (large outputs written to ephemeral files, sanitized summaries returned to LLM), plot sanitization, and async task management. |
| `terminate` | `termination_node()` | Generates a user-facing error message when infinite loop is detected. Provides diagnostic information about which tool was looping. |

### Conditional routing: `should_continue()`

The `should_continue()` function (`graph_builder.py:324-421`) inspects the agent's last message and returns one of three outcomes:

- **`"continue"`** — The message contains tool calls; proceed to the action node.
- **`"end"`** — The message has no tool calls; the agent is done.
- **`"terminate"`** — Dual-criteria loop detection (Session 57) has identified a stuck loop. Two detection paths:
  1. **Identical calls**: Same `(tool_name, args_hash)` appears 3+ times in the last 10 messages — deterministic tool with same input always produces same output.
  2. **Same name with errors**: Same tool called 3+ times with different args, but all recent ToolMessages for that tool contain errors — failing retries that won't self-resolve.

  Productive iteration (same tool, different args, all succeeding) is **not** terminated. This prevents false-positive termination of iterative workflows like `ExecuteCode` called multiple times with different code to fix errors.

This is the key architectural difference from vanilla ReAct: the conditional edge can **override the LLM's implicit decision to keep looping**. A standard `create_react_agent` has no such guardrail.

**Note**: `should_continue()` is a conditional edge function. LangGraph does **not** persist state mutations from routing functions. The `termination_node()` compensates with a 4-tier fallback chain that re-analyzes messages directly when `state["termination_reason"]` is empty (see Session 57 Bug 2 fix).

### What the custom nodes add beyond ReAct

| Capability | Standard ReAct | ADEPT's Guarded ReAct |
|---|---|---|
| Infinite loop detection | None | `should_continue()` with dual-criteria detection: args hashing + error checking (Session 57) |
| Context window management | None | Dual-layer buffer + tracker, pre-LLM forking |
| Large output handling | Returns raw output | Split-stream: ephemeral files + sanitized summaries |
| Orphaned tool call repair | None | `OrphanedToolCallsLLMWrapper` fixes malformed sequences |
| Termination with diagnostics | Silent failure or hang | Custom `terminate` node with 4-tier fallback for tool attribution |

---

## Multi-Agent Orchestration

ADEPT's multi-agent system (`orchestration_service/multi_agent_manager.py`) implements a **hierarchical supervisor pattern** with two execution modes. In both modes, **worker agents** are `create_react_agent` instances with the full 18 built-in MCP tools plus ACL-filtered external tools.

### Graph Mode — Dynamic Supervisor Routing

A custom `StateGraph` where a supervisor node uses **structured output** (a `route` function call returning an enum of worker names or `FINISH`) to dynamically dispatch to worker nodes via conditional edges.

**Implementation**: `multi_agent_manager.py:145-197`

```python
workflow = StateGraph(AgentState)

# Add worker nodes
for agent, name, thread_id in worker_agents:
    workflow.add_node(name, partial(agent_node, agent=agent, name=name, thread_id=thread_id))

# Add supervisor with structured output routing
workflow.add_node("supervisor", supervisor_chain)
for member in members:
    workflow.add_edge(member, "supervisor")  # Workers always return to supervisor

conditional_map = {k: k for k in members}
conditional_map["FINISH"] = END
workflow.add_conditional_edges("supervisor", lambda x: x["next"], conditional_map)
workflow.set_entry_point("supervisor")
```

**Graph structure:**

```
→ [supervisor] → state["next"] → [worker_A] → [supervisor]
                               → [worker_B] → [supervisor]
                               → FINISH     → END
```

After each worker completes, a deterministic edge returns control to the supervisor, which observes the accumulated results in `AgentState.messages` and decides the next worker or terminates. This gives the supervisor **per-turn adaptive routing** — it can change strategy based on intermediate results.

### Router Mode — Plan-Then-Execute

A two-tier `create_react_agent` hierarchy. A **planner agent** (ReAct with no tools) generates a step-by-step plan. A **supervisor agent** (ReAct with `AgentRunnerTool` instances) executes the plan by invoking worker agents as tool calls.

**Implementation**: `multi_agent_manager.py:533-611`

```
[planner] → plan → [supervisor (ReAct)] → tool_call: run_chemist_agent      → [worker ReAct]
                                         → tool_call: run_data_scientist_agent → [worker ReAct]
                                         → final answer                       → END
```

Each `AgentRunnerTool` wraps a worker's `create_react_agent` and invokes it with its own checkpointed thread ID. The supervisor sees worker outputs as tool call results.

### Mode comparison

| Aspect | Graph Mode | Router Mode |
|--------|-----------|-------------|
| Supervisor implementation | Custom `StateGraph` with structured output | `create_react_agent` with `AgentRunnerTool` |
| Routing decisions | Per-turn, adaptive (observes intermediate results) | Plan-driven (follows pre-generated plan) |
| Cost | Higher (supervisor LLM called after every worker) | Lower (planner called once, supervisor follows plan) |
| Flexibility | Can reroute mid-execution based on results | Follows plan; less adaptive to unexpected outputs |
| Worker implementation | `create_react_agent` | `create_react_agent` |

### Shared characteristics

- **`RolePersona`** assigns each worker an `llm_purpose` (e.g., `coding_agent` → Opus, `agent_main` → Sonnet) for cost-optimized model routing per role
- **State isolation** via hierarchical thread IDs on a shared singleton `AsyncPostgresSaver` checkpointer (`{session_id}::supervisor`, `{session_id}::worker_name`)
- **`OrphanedToolCallsLLMWrapper`** applied to all LLMs (supervisor and workers) to repair malformed tool call sequences that break LangGraph's state machine
- **Tool inheritance** — workers receive the full 18 built-in MCP tools plus the user's ACL-filtered external tools

---

## Checkpointer Architecture

All agent graphs (main agent, supervisors, workers) share a **singleton `AsyncPostgresSaver` checkpointer** created once at service startup. State isolation is achieved through unique thread IDs, not separate database connections.

**Thread ID conventions:**

| Agent | Thread ID Format |
|-------|-----------------|
| Main agent | `{thread_id}` |
| Graph mode supervisor | `{multi_agent_session_id}::supervisor_graph` |
| Router mode supervisor | `{multi_agent_session_id}::supervisor` |
| Worker agents | `{mcp_session_id}::{multi_agent_session_id}::{role_name}` |

This reduces PostgreSQL connections from 40-100 (per-request instantiation) to 12-30 (shared singleton), an 80% reduction.

**Details**: See `docs/architecture/ASYNCPOSTGRESSAVER_ARCHITECTURE_ANALYSIS.md` and the Connection Lifecycle section of `CLAUDE.md`.

---

## Key Source Files

| File | Purpose |
|------|---------|
| `orchestration_service/scientific_workflow/graph_builder.py` | Main agent custom `StateGraph` (3 nodes, conditional edges, split-stream) |
| `orchestration_service/scientific_workflow/langchain_agent.py` | `ScientificWorkflowAgent` — graph compilation, tool loading, async init |
| `orchestration_service/multi_agent_manager.py` | Multi-agent supervisor (graph + router modes), `RolePersona`, worker creation |
| `orchestration_service/multi_agent/tools.py` | `AgentRunnerTool`, `delegate_task_to_gateway` (A2A delegation) |
| `orchestration_service/scientific_workflow/agent_state.py` | `AgentState` TypedDict definition |
| `orchestration_service/persistence.py` | `AsyncPostgresSaver` checkpointer |
| `core/llm_agnostic_layer.py` | `LLMAgnosticClient` — LLM purpose routing, cost tracking |

---

## Further Reading

- **LangGraph StateGraph deep-dive**: `docs/workshop/LANGGRAPH_STATEGRAPH_GUIDE.md`
- **Checkpointer singleton pattern**: `docs/implementation-plans/SessionLevelSingletonCheckpointerPattern_20251217.md`
- **Multi-tier session management**: `docs/architecture/MULTI_TIER_SESSION_MANAGEMENT.md`
- **Context management architecture**: `docs/architecture/CONTEXT_MANAGEMENT_ARCHITECTURE_PLAN.md`
- **Contract testing for agent classes**: `docs/testing/CRITICAL_CLASS_UNIT_TEST_AUDIT.md`

---

**Last Updated**: February 2026
