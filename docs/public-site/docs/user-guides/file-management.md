# File Management and Presigned URLs

ADEPT provides a comprehensive file management system with session-scoped storage, dual access interfaces, and time-limited presigned URLs for secure file sharing.

## Overview

The file system is designed around two principles:

1. **Session isolation** -- Each upload session gets its own directory, preventing cross-user data leakage.
2. **Dual interface** -- External clients use the REST API while agents use the MCP tool interface, both writing to the same unified metadata store.

## Uploading Files (REST API)

External clients (SDKs, notebooks, CLI tools) upload files via the OpenAI-compatible REST endpoint:

```bash
curl -X POST https://your-adept-server.example.com/v1/files \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@experiment_results.csv" \
  -F "purpose=assistants"
```

The response includes a `file_id` that can be referenced in subsequent agent conversations.

## File Registration

All uploaded files are registered in Redis with metadata including:

- `file_id` -- Unique identifier
- `owner_id` -- User who uploaded the file
- `current_path` -- Filesystem location
- `session_id` -- MCP session that owns the file
- `filename` -- Original filename
- `content_type` -- MIME type

Both the REST API and MCP tool write to the same `file_metadata:{file_id}` Redis keys, ensuring a single source of truth regardless of upload method.

## Presigned URLs

Presigned URLs provide time-limited, tamper-proof download links for files without requiring the recipient to authenticate.

### Generating a Presigned URL

Ask the agent directly:

```text
Generate a 2-hour download link for my uploaded file data.csv
```

Or use the tool programmatically:

```python
result = await GeneratePresignedURL.execute(
    file_id="550e8400-e29b-41d4-a716-446655440000",
    expiry_seconds=7200,
    disposition="inline",
    user_id="user_123",
    username="alice",
    groups=["scientists"],
)
```

### Security Properties

| Property | Implementation |
|----------|---------------|
| Tamper-proof | HMAC-SHA256 signed tokens |
| Time-limited | Configurable expiry (1 second to 24 hours) |
| Timing-safe | Constant-time signature validation |
| Ownership-scoped | Only file owners can generate URLs |

!!! warning "Expiration"
    Presigned URLs become invalid after the configured expiry. Generate a new URL if the previous one has expired.

## Session Isolation

Uploaded files are stored in session-scoped directories:

```
data/uploaded_files/{mcp_session_id}/
```

This structure ensures:

- Files from different users or sessions cannot collide
- Cleanup is straightforward when sessions expire
- File paths are predictable for agent tool access

## Dual Interface Pattern

ADEPT implements file registration through two complementary interfaces:

| Interface | Caller Type | Transport | Use Case |
|-----------|-------------|-----------|----------|
| **REST API** | External clients (SDKs, notebooks, curl) | HTTP with JWT auth | Programmatic uploads |
| **MCP Tool** | Agent workflows | Direct function call | Natural language file operations |

!!! note "Not Duplicates"
    These are intentionally separate interfaces for different caller types. Both write to the same Redis metadata schema, maintaining parity on critical fields (`owner_id`, `current_path`, `session_id`).
