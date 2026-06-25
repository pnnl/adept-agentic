# Dual API Strategy

ADEPT supports two OpenAI-compatible APIs: the **Response API** (primary) and the **Assistants API** (legacy). Both are fully functional, but new development should target the Response API.

## Overview

The dual API strategy allows ADEPT to serve both modern streaming workloads and existing integrations that depend on the Assistants API resource model. The Response API provides a simpler architecture with better streaming support, while the Assistants API maintains backward compatibility with tools like OpenWebUI.

## API Comparison Matrix

| Criterion | Response API | Assistants API |
|-----------|-------------|----------------|
| Endpoint count | 1 | 4 resource types |
| Streaming | Full SSE (real-time) | Polling-based |
| State management | Simpler (single request) | Complex (threads + runs) |
| OpenAI compatibility | Stable API | Beta API |
| Tool calling | Native, inline | Run-step based |
| Testing complexity | Low | High |
| New development | Recommended | Not recommended |
| Existing integrations | -- | Supported |

The Response API wins on 8 of 11 evaluation criteria documented in the architecture decision record.

## Decision Tree

```
Is this new development?
  YES --> Use Response API
  NO  --> Does it integrate with an existing Assistants API client?
            YES --> Use Assistants API (legacy support)
            NO  --> Migrate to Response API
```

## Response API Usage

**Endpoint**: `POST /v1/responses/chat/completions`

```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        "https://your-adept-instance/v1/responses/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "default",
            "messages": [{"role": "user", "content": "Analyze this dataset"}],
            "stream": True,
            "thread_id": "thread_abc123"
        }
    )
```

Key advantages:

- Single endpoint for all operations (create, continue, stream)
- Real-time SSE streaming with tool call events
- Thread management via `thread_id` parameter
- No polling required

## Assistants API Usage

**Endpoints**: `/v1/assistants/*`, `/v1/threads/*`, `/v1/runs/*`

```python
# Create thread
thread = client.post("/v1/threads", json={})

# Add message
client.post(f"/v1/threads/{thread_id}/messages", json={
    "role": "user",
    "content": "Run BLAST analysis"
})

# Create run and poll
run = client.post(f"/v1/threads/{thread_id}/runs", json={
    "assistant_id": "asst_default"
})
```

!!! warning "Legacy Only"
    The Assistants API is maintained for backward compatibility. New projects should use the Response API for simpler architecture and better streaming.

## Migration Strategy

To migrate from Assistants API to Response API:

1. **Replace thread + message + run** with a single `/v1/responses/chat/completions` call
2. **Replace polling** with SSE streaming (set `stream: true`)
3. **Pass `thread_id`** directly in the request body for conversation continuity
4. **Remove assistant creation** -- the Response API uses a default agent configuration
5. **Update error handling** -- Response API returns standard OpenAI error format inline

## Architecture References

- Response API: `docs/architecture/RESPONSE_API_ARCHITECTURE.md`
- Assistants API: `docs/architecture/ASSISTANTS_API_ARCHITECTURE.md`
- Full comparison: `docs/architecture/DUAL_API_STRATEGY.md`
