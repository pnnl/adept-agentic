# Response API - Session Fork Metadata

**Version**: 1.0
**Last Updated**: January 22, 2026
**Status**: Phase 3B Complete

---

## Overview

The Response API includes **session fork metadata** to support the framework's **auto-compaction strategy**. When a conversation exceeds the configured token limit, the system automatically forks to a new sub-session instead of truncating messages. This non-destructive approach enables clients to seamlessly switch to the forked session and continue the conversation with reduced context.

**Key Features**:
- Automatic fork detection without client intervention (auto-compaction)
- Optional `session_fork` field in response (backward compatible)
- Detailed fork metadata including generation tracking
- Support for nested forks (fork of fork)

---

## Session Forking Explained

### Why Sessions Fork

When a conversation exceeds the configured token limit (default: 73,000 tokens), the orchestration service automatically:

1. **Creates a sub-session** with condensed context (bootstrap)
2. **Reduces token count by 80-90%** through intelligent summarization
3. **Preserves critical context** (system messages, recent turns, tool definitions)
4. **Returns fork metadata** to the client for seamless switching

### Fork Detection Threshold

The context manager includes multiple factors in fork detection:
- Message tokens (~3-5k for system message)
- Tool schema tokens (~9,579 tokens for 37 tools, ~258 tokens/tool)
- User input tokens (~100-1,000 per turn)
- **Total threshold**: Configured max_tokens (default: 73,000)

**Session 36 Fix**: Tool schema tokens are now correctly included in fork detection, improving accuracy by 18% (~13k more accurate token budgets).

---

## Response Format

### SessionForkMetadata Model

When a fork occurs, the Response API includes a `session_fork` field:

```python
class SessionForkMetadata(BaseModel):
    """Session fork metadata included in response when fork occurs."""

    forked_session_id: str          # New session ID to switch to
    parent_session_id: str          # Original session ID that was forked
    generation: int                 # Fork generation (1=first fork, 2=nested, etc.)
    fork_reason: str                # Why fork occurred (e.g., "token_limit_exceeded")
    bootstrap_message_count: int    # Number of messages in bootstrap
    forked_at_turn: Optional[int]   # Turn number when fork occurred
```

### Response Examples

#### Non-Streaming Response (Fork Occurred)

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1737518400,
  "model": "anthropic.claude-3-opus-20240229-v1:0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Based on the extensive protein analysis..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 75000,
    "completion_tokens": 150,
    "total_tokens": 75150
  },
  "session_fork": {
    "forked_session_id": "thread-123-sub-20260122051234-gen1",
    "parent_session_id": "thread-123",
    "generation": 1,
    "fork_reason": "token_limit_exceeded",
    "bootstrap_message_count": 3,
    "forked_at_turn": 8
  }
}
```

#### Non-Streaming Response (No Fork)

```json
{
  "id": "chatcmpl-abc124",
  "object": "chat.completion",
  "created": 1737518500,
  "model": "anthropic.claude-3-opus-20240229-v1:0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Protein folding is..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 5000,
    "completion_tokens": 100,
    "total_tokens": 5100
  }
}
```

**Note**: `session_fork` field is `null` or omitted when no fork occurs (backward compatible).

#### Streaming Response (Fork Occurred)

In streaming mode, fork metadata appears in the **final chunk**:

```json
data: {"id":"chatcmpl-abc125","object":"chat.completion.chunk","created":1737518600,"model":"anthropic.claude-3-opus-20240229-v1:0","choices":[{"index":0,"delta":{"content":"Based"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc125","object":"chat.completion.chunk","created":1737518600,"model":"anthropic.claude-3-opus-20240229-v1:0","choices":[{"index":0,"delta":{"content":" on"},"finish_reason":null}]}

... (more chunks)

data: {"id":"chatcmpl-abc125","object":"chat.completion.chunk","created":1737518600,"model":"anthropic.claude-3-opus-20240229-v1:0","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"session_fork":{"forked_session_id":"thread-456-sub-20260122051500-gen1","parent_session_id":"thread-456","generation":1,"fork_reason":"token_limit_exceeded","bootstrap_message_count":3,"forked_at_turn":10}}

data: [DONE]
```

---

## Client Implementation Patterns

### Pattern 1: Automatic Session Switching (Recommended)

**Use Case**: Transparent session management without user intervention.

```python
import requests

class AgenticClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {token}"}
        self.session_id = None
        self.fork_generation = 0

    def chat(self, message: str) -> str:
        """Send message and automatically handle session forks."""
        payload = {
            "model": "anthropic.claude-3-opus-20240229-v1:0",
            "messages": [{"role": "user", "content": message}],
            "session_id": self.session_id,
            "stream": False
        }

        response = requests.post(
            f"{self.base_url}/v1/responses/chat/completions",
            json=payload,
            headers=self.headers
        )
        response.raise_for_status()
        data = response.json()

        # Check for session fork
        if "session_fork" in data and data["session_fork"]:
            fork_info = data["session_fork"]
            old_session = self.session_id or "new session"
            self.session_id = fork_info["forked_session_id"]
            self.fork_generation = fork_info["generation"]

            print(f"⚠️ Session forked: {old_session} → {self.session_id}")
            print(f"   Generation: {self.fork_generation}")
            print(f"   Reason: {fork_info['fork_reason']}")
            print(f"   Bootstrap: {fork_info['bootstrap_message_count']} messages")
        elif not self.session_id and "id" in data:
            # First turn: capture session_id from response
            self.session_id = data.get("session_id", data["id"])

        return data["choices"][0]["message"]["content"]

# Usage
client = AgenticClient("http://localhost:8080", token="your-jwt-token")

# Conversation automatically handles forks
response1 = client.chat("Explain protein folding")
response2 = client.chat("What are the key mechanisms?")
# ... many turns later, fork occurs automatically
response10 = client.chat("Summarize the discussion")
# Client now using forked session transparently
```

### Pattern 2: Fork Detection with User Notification

**Use Case**: Notify users when conversation context is reduced.

```python
def chat_with_notification(client, message: str) -> tuple[str, bool]:
    """
    Send message and notify if session forked.

    Returns:
        tuple[str, bool]: (response_text, fork_occurred)
    """
    payload = {
        "model": "anthropic.claude-3-opus-20240229-v1:0",
        "messages": [{"role": "user", "content": message}],
        "session_id": client.session_id,
        "stream": False
    }

    response = requests.post(
        f"{client.base_url}/v1/responses/chat/completions",
        json=payload,
        headers=client.headers
    )
    response.raise_for_status()
    data = response.json()

    fork_occurred = False
    if "session_fork" in data and data["session_fork"]:
        fork_info = data["session_fork"]
        client.session_id = fork_info["forked_session_id"]
        fork_occurred = True

        # User-facing notification
        print("┌─────────────────────────────────────────────────────┐")
        print("│ ⚠️  Conversation context optimized                 │")
        print("│                                                     │")
        print(f"│ Older messages summarized to maintain focus.       │")
        print(f"│ Recent context preserved ({fork_info['bootstrap_message_count']} messages).            │")
        print("└─────────────────────────────────────────────────────┘")

    return data["choices"][0]["message"]["content"], fork_occurred

# Usage with notification
response, forked = chat_with_notification(client, "Long complex query...")
if forked:
    print("User was notified of context optimization")
```

### Pattern 3: Fork Logging and Analytics

**Use Case**: Track fork events for conversation analytics.

```python
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("agentic.client")

class ForkTracker:
    def __init__(self):
        self.fork_events = []

    def track_fork(self, fork_info: dict, conversation_id: str):
        """Log fork event for analytics."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "conversation_id": conversation_id,
            "parent_session": fork_info["parent_session_id"],
            "forked_session": fork_info["forked_session_id"],
            "generation": fork_info["generation"],
            "reason": fork_info["fork_reason"],
            "bootstrap_size": fork_info["bootstrap_message_count"],
            "turn_number": fork_info.get("forked_at_turn")
        }
        self.fork_events.append(event)

        logger.info(
            f"Session fork detected: gen={fork_info['generation']} "
            f"reason={fork_info['fork_reason']} "
            f"bootstrap={fork_info['bootstrap_message_count']} messages"
        )

    def get_fork_stats(self) -> dict:
        """Compute fork analytics."""
        if not self.fork_events:
            return {"total_forks": 0}

        return {
            "total_forks": len(self.fork_events),
            "max_generation": max(e["generation"] for e in self.fork_events),
            "avg_bootstrap_size": sum(e["bootstrap_size"] for e in self.fork_events) / len(self.fork_events),
            "fork_reasons": {e["reason"]: sum(1 for ev in self.fork_events if ev["reason"] == e["reason"]) for e in self.fork_events}
        }

# Usage
tracker = ForkTracker()

def chat_with_tracking(client, message: str, tracker: ForkTracker) -> str:
    # ... make request ...

    if "session_fork" in data and data["session_fork"]:
        tracker.track_fork(data["session_fork"], client.conversation_id)
        client.session_id = data["session_fork"]["forked_session_id"]

    return data["choices"][0]["message"]["content"]

# After conversation
stats = tracker.get_fork_stats()
print(f"Forks: {stats['total_forks']}, Max Generation: {stats['max_generation']}")
```

### Pattern 4: Streaming with Fork Detection

**Use Case**: Handle forks in streaming responses.

```python
import json

def chat_streaming(client, message: str):
    """Stream response and detect fork in final chunk."""
    payload = {
        "model": "anthropic.claude-3-opus-20240229-v1:0",
        "messages": [{"role": "user", "content": message}],
        "session_id": client.session_id,
        "stream": True
    }

    response = requests.post(
        f"{client.base_url}/v1/responses/chat/completions",
        json=payload,
        headers=client.headers,
        stream=True
    )
    response.raise_for_status()

    full_content = ""
    fork_info = None

    for line in response.iter_lines():
        if not line or line == b"data: [DONE]":
            continue

        if line.startswith(b"data: "):
            json_str = line[6:].decode("utf-8")
            chunk = json.loads(json_str)

            # Extract content delta
            if chunk["choices"][0]["delta"].get("content"):
                content = chunk["choices"][0]["delta"]["content"]
                print(content, end="", flush=True)
                full_content += content

            # Check for fork metadata in final chunk
            if "session_fork" in chunk and chunk["session_fork"]:
                fork_info = chunk["session_fork"]

    print()  # Newline after streaming

    # Handle fork after stream completes
    if fork_info:
        client.session_id = fork_info["forked_session_id"]
        print(f"\n⚠️ Session forked to: {fork_info['forked_session_id']}")

    return full_content

# Usage
response = chat_streaming(client, "Explain quantum mechanics in detail...")
# Stream prints in real-time, fork detected at end
```

---

## Fork Generation Tracking

### Understanding Generations

Sessions can fork multiple times, creating a hierarchy:

```
Base Session (thread-123)
  └─> Fork Gen 1 (thread-123-sub-20260122-gen1)
        └─> Fork Gen 2 (thread-123-sub-20260122-gen1-sub-20260122-gen2)
              └─> Fork Gen 3 (...)
```

**Generation Values**:
- `generation: 1` - First fork from base session
- `generation: 2` - Fork of a forked session (nested)
- `generation: 3+` - Deeper nesting (rare but supported)

### Nested Fork Example

```python
# Turn 1-8: Base session (thread-abc)
response1 = client.chat("Query 1")  # session_id = "thread-abc"
# ... 7 more turns ...

# Turn 9: First fork occurs
response9 = client.chat("Query 9")
# session_fork.generation = 1
# session_fork.forked_session_id = "thread-abc-sub-gen1"
# Client switches to forked session

# Turn 10-17: Forked session (thread-abc-sub-gen1)
response10 = client.chat("Query 10")  # session_id = "thread-abc-sub-gen1"
# ... 7 more turns ...

# Turn 18: Second fork (nested)
response18 = client.chat("Query 18")
# session_fork.generation = 2
# session_fork.parent_session_id = "thread-abc-sub-gen1"
# session_fork.forked_session_id = "thread-abc-sub-gen1-sub-gen2"
# Client switches to nested forked session
```

---

## Backward Compatibility

### Optional Field Behavior

The `session_fork` field is **optional** and follows these rules:

1. **Field Omitted**: When no fork occurs, `session_fork` is omitted from response
2. **Field Null**: Some implementations may return `"session_fork": null` instead
3. **Field Present**: Only populated when fork actually occurs

**Client Code Should**:
- Check for field existence: `if "session_fork" in data and data["session_fork"]:`
- Handle both `null` and omitted cases
- Never assume field is always present

### Legacy Clients

Clients that don't check for `session_fork` will continue to work but:
- ❌ Will send requests to stale parent session
- ❌ May receive "Session not found" errors
- ❌ Miss context optimization benefits

**Migration Path**: Update clients to detect and switch to forked sessions (see Pattern 1).

---

## Error Handling

### Common Fork-Related Errors

#### Error: Session Not Found

```json
{
  "error": {
    "message": "Session 'thread-123' not found",
    "type": "invalid_request_error",
    "param": "session_id",
    "code": "session_not_found"
  }
}
```

**Cause**: Client continued using parent session ID after fork.

**Solution**: Implement automatic session switching (Pattern 1).

#### Error: Invalid Session ID Format

```json
{
  "error": {
    "message": "Invalid session_id format",
    "type": "invalid_request_error",
    "param": "session_id",
    "code": "invalid_session_id"
  }
}
```

**Cause**: Malformed session ID passed to API.

**Solution**: Validate session ID matches pattern: `thread-{uuid}` or `thread-{uuid}-sub-{timestamp}-gen{N}`.

---

## Best Practices

### 1. Always Handle Forks
```python
# ✅ Good: Automatic fork handling
if "session_fork" in data and data["session_fork"]:
    client.session_id = data["session_fork"]["forked_session_id"]

# ❌ Bad: Ignoring fork metadata
response = data["choices"][0]["message"]["content"]
# Client continues using stale session_id
```

### 2. Log Fork Events
```python
# ✅ Good: Track forks for debugging
if fork_occurred:
    logger.info(f"Session forked: gen={fork_info['generation']}")

# ❌ Bad: Silent fork handling
# No visibility into when/why forks occur
```

### 3. Validate Session IDs
```python
# ✅ Good: Validate format before using
import re
SESSION_ID_PATTERN = r"^thread-[a-f0-9\-]+((?:-sub-\d+-gen\d+)*)$"
if not re.match(SESSION_ID_PATTERN, session_id):
    raise ValueError(f"Invalid session ID: {session_id}")

# ❌ Bad: Blindly accept any string
client.session_id = user_input  # Potential security issue
```

### 4. Handle Streaming Forks
```python
# ✅ Good: Check final chunk for fork metadata
for chunk in stream:
    if "session_fork" in chunk:
        client.session_id = chunk["session_fork"]["forked_session_id"]

# ❌ Bad: Only check first chunk
first_chunk = next(stream)
# Fork metadata is in LAST chunk, not first
```

---

## API Endpoint Reference

### POST /v1/responses/chat/completions

**Request Body**:
```json
{
  "model": "anthropic.claude-3-opus-20240229-v1:0",
  "messages": [
    {"role": "user", "content": "Your message"}
  ],
  "session_id": "thread-123",  // Optional: omit for new session
  "stream": false               // false=non-streaming, true=streaming
}
```

**Response Body** (Non-Streaming):
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1737518400,
  "model": "anthropic.claude-3-opus-20240229-v1:0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Response text"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 75000,
    "completion_tokens": 150,
    "total_tokens": 75150
  },
  "session_fork": {  // Optional: only present when fork occurs
    "forked_session_id": "thread-123-sub-20260122-gen1",
    "parent_session_id": "thread-123",
    "generation": 1,
    "fork_reason": "token_limit_exceeded",
    "bootstrap_message_count": 3,
    "forked_at_turn": 8
  }
}
```

**Status Codes**:
- `200 OK`: Success
- `400 Bad Request`: Invalid request parameters
- `401 Unauthorized`: Missing or invalid JWT token
- `404 Not Found`: Session not found (stale session ID)
- `500 Internal Server Error`: Server-side error

---

## Related Documentation

- **Architecture**: `docs/architecture/SESSION_FORKING_ARCHITECTURE.md` - Phase 3B implementation details
- **Migration Guide**: `docs/migration/PHASE3_MIGRATION_GUIDE.md` - Step-by-step client migration
- **Validation Report**: `docs/testing/PHASE3B_SESSION36_VALIDATION_REPORT_V4.md` - Test results and Fix 2 details
- **API Specification**: `docs/api/openapi.json` - OpenAPI 3.1.0 specification

---

## Changelog

### Version 1.0 (January 22, 2026)
- Initial release with Phase 3B fork metadata propagation
- Session 36 Fix 2: Tool schema token estimation
- Support for nested forks (generation tracking)
- Comprehensive client examples (Python)
- Streaming and non-streaming support

---

**End of Response API Fork Metadata Documentation**
