# Assistants API Architecture

**Status**: ✅ Supported (Legacy compatibility)
**Compatibility**: OpenAI Assistants API (Beta) compatible
**Strategy**: Keep as-is, focus Response API for new implementations
**Last Updated**: Session 52 (2026-02-09)

---

## Overview

The **Assistants API** (`/v1/assistants/*`, `/v1/threads/*`, `/v1/runs/*`) provides OpenAI-compatible assistant management with stateful conversations. While fully functional, **new implementations should use the Response API** for simplicity and better streaming support.

**Key Principle**: Assistants API is **maintained for backward compatibility** but not the focus of new development.

---

## Architecture

### Three-Resource Model

The Assistants API uses a hierarchical resource structure:

```
Assistant (persistent configuration)
    ↓
Thread (conversation session)
    ↓
Run (execution instance)
        ↓
    Messages (conversation history)
```

### Service Responsibilities

**Tier 1: Agent Gateway** (`src/agentic_framework_pkg/agent_gateway/`)
- JWT authentication
- Transparent proxy to Tier 2
- No business logic

**Tier 2: Orchestration Service** (`src/agentic_framework_pkg/orchestration_service/`)
- Assistant CRUD operations
- Thread management
- Run orchestration
- PostgreSQL persistence

**Key Files**:
- `routers/v1/beta_compatibility.py` - Beta endpoints (`/v1/beta/assistants/*`)
- `routers/v1/assistants.py` - Stable endpoints (`/v1/assistants/*`)
- `routers/v1/threads.py` - Thread management
- `routers/v1/runs.py` - Run execution
- `openai_pagination.py` - Cursor-based pagination

---

## API Endpoints

### Assistant Management

#### Create Assistant

```http
POST /v1/assistants
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "My Scientific Assistant",
  "model": "agentic-framework:scientific-agent-v1",
  "description": "Helps with scientific research",
  "instructions": "You are a helpful scientific research assistant.",
  "tools": [
    {"type": "code_interpreter"},
    {"type": "file_search"}
  ],
  "metadata": {"domain": "chemistry"}
}
```

**Response**:
```json
{
  "id": "asst_abc123",
  "object": "assistant",
  "created_at": 1234567890,
  "name": "My Scientific Assistant",
  "model": "agentic-framework:scientific-agent-v1",
  "description": "Helps with scientific research",
  "instructions": "You are a helpful scientific research assistant.",
  "tools": [
    {"type": "code_interpreter"},
    {"type": "file_search"}
  ],
  "metadata": {"domain": "chemistry"}
}
```

#### List Assistants

```http
GET /v1/assistants?limit=20&order=desc
Authorization: Bearer <token>
```

**Response** (cursor-based pagination):
```json
{
  "object": "list",
  "data": [
    {
      "id": "asst_abc123",
      "object": "assistant",
      "name": "My Scientific Assistant",
      ...
    }
  ],
  "first_id": "asst_abc123",
  "last_id": "asst_xyz789",
  "has_more": false
}
```

#### Retrieve Assistant

```http
GET /v1/assistants/{assistant_id}
Authorization: Bearer <token>
```

#### Update Assistant

```http
POST /v1/assistants/{assistant_id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Updated Name",
  "instructions": "Updated instructions"
}
```

#### Delete Assistant

```http
DELETE /v1/assistants/{assistant_id}
Authorization: Bearer <token>
```

**Response**:
```json
{
  "id": "asst_abc123",
  "object": "assistant.deleted",
  "deleted": true
}
```

---

### Thread Management

#### Create Thread

```http
POST /v1/threads
Authorization: Bearer <token>
Content-Type: application/json

{
  "messages": [
    {
      "role": "user",
      "content": "Hello, I need help with chemistry"
    }
  ],
  "metadata": {"session": "web-app-123"}
}
```

**Response**:
```json
{
  "id": "thread_abc123",
  "object": "thread",
  "created_at": 1234567890,
  "metadata": {"session": "web-app-123"}
}
```

#### Retrieve Thread

```http
GET /v1/threads/{thread_id}
Authorization: Bearer <token>
```

#### Update Thread

```http
POST /v1/threads/{thread_id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "metadata": {"updated": "true"}
}
```

#### Delete Thread

```http
DELETE /v1/threads/{thread_id}
Authorization: Bearer <token>
```

---

### Message Management

#### Create Message

```http
POST /v1/threads/{thread_id}/messages
Authorization: Bearer <token>
Content-Type: application/json

{
  "role": "user",
  "content": "What is the molecular formula for caffeine?"
}
```

**Response**:
```json
{
  "id": "msg_abc123",
  "object": "thread.message",
  "created_at": 1234567890,
  "thread_id": "thread_abc123",
  "role": "user",
  "content": [
    {
      "type": "text",
      "text": {
        "value": "What is the molecular formula for caffeine?",
        "annotations": []
      }
    }
  ],
  "metadata": {}
}
```

#### List Messages

```http
GET /v1/threads/{thread_id}/messages?limit=20&order=desc
Authorization: Bearer <token>
```

**Response** (cursor-based pagination):
```json
{
  "object": "list",
  "data": [
    {
      "id": "msg_abc123",
      "object": "thread.message",
      "role": "user",
      "content": [...]
    },
    {
      "id": "msg_xyz789",
      "object": "thread.message",
      "role": "assistant",
      "content": [...]
    }
  ],
  "first_id": "msg_abc123",
  "last_id": "msg_xyz789",
  "has_more": false
}
```

#### Retrieve Message

```http
GET /v1/threads/{thread_id}/messages/{message_id}
Authorization: Bearer <token>
```

---

### Run Management

#### Create Run

```http
POST /v1/threads/{thread_id}/runs
Authorization: Bearer <token>
Content-Type: application/json

{
  "assistant_id": "asst_abc123",
  "instructions": "Answer concisely",
  "stream": false
}
```

**Response**:
```json
{
  "id": "run_abc123",
  "object": "thread.run",
  "created_at": 1234567890,
  "thread_id": "thread_abc123",
  "assistant_id": "asst_abc123",
  "status": "queued",
  "required_action": null,
  "last_error": null,
  "model": "agentic-framework:scientific-agent-v1",
  "instructions": "Answer concisely",
  "metadata": {}
}
```

#### Run Status Lifecycle

```
queued → in_progress → completed
                    ↓
               requires_action (tool approval)
                    ↓
               cancelling → cancelled
                    ↓
                  failed → expired
```

#### Retrieve Run

```http
GET /v1/threads/{thread_id}/runs/{run_id}
Authorization: Bearer <token>
```

#### List Runs

```http
GET /v1/threads/{thread_id}/runs?limit=20&order=desc
Authorization: Bearer <token>
```

#### Submit Tool Outputs

```http
POST /v1/threads/{thread_id}/runs/{run_id}/submit_tool_outputs
Authorization: Bearer <token>
Content-Type: application/json

{
  "tool_outputs": [
    {
      "tool_call_id": "call_abc123",
      "output": "{\"result\": \"success\"}"
    }
  ]
}
```

#### Cancel Run

```http
POST /v1/threads/{thread_id}/runs/{run_id}/cancel
Authorization: Bearer <token>
```

---

## Beta Compatibility Endpoints

ADEPT supports **both beta and stable endpoints** for backward compatibility:

| Beta Endpoint | Stable Endpoint | Status |
|---------------|-----------------|--------|
| `/v1/beta/assistants/*` | `/v1/assistants/*` | Both supported |
| `/v1/beta/threads/*` | `/v1/threads/*` | Both supported |

**Implementation**: `src/agentic_framework_pkg/orchestration_service/routers/v1/beta_compatibility.py`

---

## State Management

### PostgreSQL Tables

**Assistants**:
```sql
CREATE TABLE assistants (
    id VARCHAR PRIMARY KEY,
    name VARCHAR,
    model VARCHAR,
    description TEXT,
    instructions TEXT,
    tools JSONB,
    metadata JSONB,
    created_at TIMESTAMP,
    user_id VARCHAR
);
```

**Threads**:
```sql
CREATE TABLE threads (
    id VARCHAR PRIMARY KEY,
    metadata JSONB,
    created_at TIMESTAMP,
    user_id VARCHAR
);
```

**Runs**:
```sql
CREATE TABLE runs (
    id VARCHAR PRIMARY KEY,
    thread_id VARCHAR REFERENCES threads(id),
    assistant_id VARCHAR REFERENCES assistants(id),
    status VARCHAR,
    model VARCHAR,
    instructions TEXT,
    tools JSONB,
    metadata JSONB,
    created_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    user_id VARCHAR
);
```

**Messages** (stored in checkpoints table):
- LangGraph checkpointing with thread_id
- Conversation history persisted across requests

---

## Error Handling

### OpenAI-Compatible Errors

```json
{
  "error": {
    "message": "Assistant not found",
    "type": "invalid_request_error",
    "param": "assistant_id",
    "code": "resource_not_found"
  }
}
```

**HTTP Status Codes**:
- `400`: Invalid request
- `401`: Authentication failure
- `404`: Resource not found (assistant/thread/run)
- `422`: Validation error
- `500`: Internal server error

**Implementation**: `src/agentic_framework_pkg/orchestration_service/openai_error_handler.py`

---

## Pagination

### Cursor-Based Pagination

**Request**:
```http
GET /v1/assistants?limit=10&order=desc&after=asst_abc123
```

**Response**:
```json
{
  "object": "list",
  "data": [...],
  "first_id": "asst_def456",
  "last_id": "asst_xyz789",
  "has_more": true
}
```

**Next Page**:
```http
GET /v1/assistants?limit=10&order=desc&after=asst_xyz789
```

**Implementation**: `src/agentic_framework_pkg/orchestration_service/openai_pagination.py`

**Parameters**:
- `limit`: Number of items (default 20, max 100)
- `order`: Sort order (`asc` or `desc`)
- `after`: Cursor for next page
- `before`: Cursor for previous page

---

## Tool Support

### Built-In Tools

The Assistants API supports OpenAI-compatible tool types:

| Tool Type | Description | Implementation |
|-----------|-------------|----------------|
| `code_interpreter` | Python code execution | sandbox_mcp_server |
| `file_search` | Vector search over uploaded files | CSV RAG tool (mcp_server) |
| `function` | Custom function calling | ScientificWorkflowAgent tools |

**Example Tool Configuration**:
```json
{
  "tools": [
    {"type": "code_interpreter"},
    {"type": "file_search"},
    {
      "type": "function",
      "function": {
        "name": "uniprot_lookup",
        "description": "Lookup protein information",
        "parameters": {
          "type": "object",
          "properties": {
            "accession": {"type": "string"}
          }
        }
      }
    }
  ]
}
```

### Tool Execution Flow

1. **Run Created**: User creates run with `assistant_id`
2. **Agent Invocation**: ScientificWorkflowAgent processes messages
3. **Tool Call**: Agent decides to call tool (e.g., code_interpreter)
4. **Status Update**: Run status becomes `requires_action`
5. **Tool Approval** (if configured): User submits tool outputs
6. **Execution**: Tool executes via MCP server
7. **Completion**: Run status becomes `completed`

---

## Comparison with Response API

| Feature | Assistants API | Response API |
|---------|----------------|--------------|
| **Endpoint Complexity** | High (4 resource types) | Low (1 endpoint) |
| **Request Pattern** | Create resources + Poll runs | Single request with streaming |
| **Streaming Support** | Limited (run events only) | Full SSE support |
| **State Management** | Assistant + Thread + Run | Thread + Messages |
| **Tool Calling** | Via assistant tools | Native OpenAI format |
| **Pagination** | Cursor-based | N/A (streaming) |
| **OpenAI Compatibility** | Beta API | Stable API |
| **Recommended For** | Legacy integrations | **New implementations** |

---

## When to Use Assistants API

### ✅ Use Assistants API When:

1. **Existing Integration**: You already have OpenAI Assistants API code
2. **Assistant Management**: You need persistent assistant configurations
3. **Run Tracking**: You need explicit run status and history
4. **OpenWebUI Integration**: OpenWebUI uses Assistants API
5. **Backward Compatibility**: Migrating from OpenAI Assistants API

### ❌ Avoid Assistants API When:

1. **New Project**: Starting fresh (use Response API instead)
2. **Real-Time Streaming**: Need instant feedback (Response API has better streaming)
3. **Simplicity**: Want fewer concepts and endpoints
4. **Tool Calling**: Need advanced tool orchestration (Response API is more flexible)

---

## Migration to Response API

### Assistant → No Equivalent (Use Model Name)

**Before**:
```python
assistant = client.beta.assistants.create(
    name="My Assistant",
    model="gpt-4",
    instructions="You are helpful"
)
```

**After**:
```python
# No assistant resource needed
# Instructions go in system message
model = "agentic-framework:scientific-agent-v1"
```

### Thread → Thread

**Before**:
```python
thread = client.beta.threads.create()
```

**After**:
```python
thread = client.threads.create()  # Same endpoint
```

### Run → Response API Request

**Before**:
```python
run = client.beta.threads.runs.create(
    thread_id=thread.id,
    assistant_id=assistant.id
)

# Poll for completion
while run.status != "completed":
    run = client.beta.threads.runs.retrieve(
        thread_id=thread.id,
        run_id=run.id
    )
```

**After**:
```python
response = client.responses.chat.completions.create(
    model="agentic-framework:scientific-agent-v1",
    messages=[{"role": "user", "content": "Hello"}],
    thread_id=thread.id,
    stream=True  # Real-time streaming, no polling
)
```

### Complete Example

**Before (Assistants API)**:
```python
import openai

client = openai.OpenAI(base_url="http://localhost:8083/v1", api_key=token)

# Create assistant
assistant = client.beta.assistants.create(
    name="Math Tutor",
    model="agentic-framework:scientific-agent-v1",
    instructions="You are a helpful math tutor"
)

# Create thread
thread = client.beta.threads.create()

# Add message
client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="Solve 2x + 5 = 15"
)

# Create and poll run
run = client.beta.threads.runs.create(
    thread_id=thread.id,
    assistant_id=assistant.id
)

while run.status != "completed":
    run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

# Get messages
messages = client.beta.threads.messages.list(thread_id=thread.id)
```

**After (Response API)**:
```python
import openai

client = openai.OpenAI(base_url="http://localhost:8083/v1", api_key=token)

# Create thread
thread = client.threads.create()

# Send message with streaming
response = client.responses.chat.completions.create(
    model="agentic-framework:scientific-agent-v1",
    messages=[
        {"role": "system", "content": "You are a helpful math tutor"},
        {"role": "user", "content": "Solve 2x + 5 = 15"}
    ],
    thread_id=thread.id,
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

**Benefits**:
- **Fewer lines**: 8 lines vs 20+ lines
- **No polling**: Streaming provides real-time feedback
- **Simpler**: 1 resource (thread) vs 3 resources (assistant + thread + run)
- **Faster**: Direct response vs polling loop

---

## Testing

### E2E Tests

**Assistants API Test Suite**:
- `tests/e2e/test_api_gateway_affirmative.py` (7 assistant endpoint tests)
- `tests/e2e/test_authentication_flows.py` (12 assistant API auth tests)

**Run Tests**:
```bash
make validate-data  # Management-plane operations (assistants CRUD)
```

### Known Issues

**Session 52 Analysis**:
- Tests reference Assistants API endpoints
- No migration needed (keep as-is per user decision)
- Focus new work on Response API

---

## Best Practices

### 1. Prefer Response API for New Work

```python
# ✅ RECOMMENDED: Use Response API
response = client.responses.chat.completions.create(...)

# ⚠️ LEGACY: Assistants API (backward compatibility only)
run = client.beta.threads.runs.create(...)
```

### 2. Use Streaming for Real-Time Feedback

```python
# ✅ BETTER: Response API with streaming
response = client.responses.chat.completions.create(stream=True, ...)

# ⚠️ SLOWER: Assistants API with polling
run = client.beta.threads.runs.create(...)
while run.status != "completed":
    run = client.beta.threads.runs.retrieve(...)
```

### 3. Minimize Resource Creation

```python
# ✅ EFFICIENT: Reuse threads
thread_id = "user-123-session"

# ❌ INEFFICIENT: Create assistant per request
assistant = client.beta.assistants.create(...)
```

---

## Related Documentation

### Architecture
- **Response API**: `docs/architecture/RESPONSE_API_ARCHITECTURE.md`
- **Dual API Strategy**: `docs/architecture/DUAL_API_STRATEGY.md`
- **OpenAI Error Handler**: `src/agentic_framework_pkg/orchestration_service/openai_error_handler.py`
- **OpenAI Pagination**: `src/agentic_framework_pkg/orchestration_service/openai_pagination.py`

### Implementation Files
- **Beta Endpoints**: `src/agentic_framework_pkg/orchestration_service/routers/v1/beta_compatibility.py`
- **Assistants Router**: `src/agentic_framework_pkg/orchestration_service/routers/v1/assistants.py`
- **Threads Router**: `src/agentic_framework_pkg/orchestration_service/routers/v1/threads.py`
- **Runs Router**: `src/agentic_framework_pkg/orchestration_service/routers/v1/runs.py`

### Testing
- **API Gateway Tests**: `tests/e2e/test_api_gateway_affirmative.py`
- **Authentication Tests**: `tests/e2e/test_authentication_flows.py`

---

## Changelog

- **2026-02-09 (Session 52)**: Documented as legacy API, recommend Response API for new work
- **Session 14**: Multi-stream fix applies to both APIs
- **Session 26**: Singleton checkpointer pattern applies to both APIs
- **Initial Release**: Full OpenAI Assistants API (Beta) compatibility
