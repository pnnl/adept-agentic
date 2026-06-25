# ADEPT Agentic Framework API Documentation

## Overview

This directory contains comprehensive OpenAPI 3.1.0 specifications for all API endpoints exposed by the ADEPT Agentic Framework. The framework provides a production-ready, three-tier secure architecture with OpenAI-compatible APIs, simplified Response API, Knowledge Base operations, and MCP protocol support.

## API Specifications

### [openapi.json](./openapi.json) - Public API Specification

Covers all user-facing endpoints including:
- **Response API** (recommended) - Simplified chat completions
- **Chat Completions** - OpenAI-compatible chat API
- **Assistants API** (deprecated) - OpenAI Assistants compatibility
- **Threads & Messages** - Conversation management
- **Runs & Run Steps** - Execution tracking
- **Models** - Available LLM models
- **Files** - Upload and management
- **Knowledge Bases** - RAG operations (RAGFlow/ChromaDB)
- **Embeddings** - Text embeddings generation
- **Tools** - Tool discovery
- **Gateways** - A2A mesh communication
- **User Keys** - API key management
- **MCP Protocol** - Model Context Protocol
- **Health** - Service health checks

### [openapi-admin.json](./openapi-admin.json) - Admin API Specification

Covers administrative endpoints (requires `admin` role):
- **Tool Management** - Register and manage external tools
- **Session Management** - Statistics and cleanup operations
- **Internal APIs** - Service-to-service communication

## Architecture

### Three-Tier Secure Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Tier 1: NGINX Proxy + Agent Gateway (Port 8080/8081)       │
│  - Keycloak JWT validation                                   │
│  - RBAC via groups claim                                     │
│  - Transparent proxying to orchestration service             │
└───────────────────┬─────────────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────────────┐
│  Tier 2: Orchestration Service (Port 8084)                   │
│  - Full OpenAI API implementation                            │
│  - PostgreSQL-backed persistence (LangGraph checkpoints)     │
│  - Multi-agent orchestration                                 │
│  - Dynamic tool management                                   │
└───────────────────┬─────────────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────────────┐
│  Tier 3: MCP Tool Servers (Stateless)                        │
│  - mcp_server: Scientific tools (BLAST, UniProt, PubChem)   │
│  - hpc_mcp_server: HPC pipelines (Nextflow, GitXray)        │
│  - sandbox_mcp_server: Secure code execution                │
└─────────────────────────────────────────────────────────────┘
```

### Entry Points

| Entry Point | URL | Purpose |
|------------|-----|---------|
| **Production** | `http://localhost:8080` | NGINX proxy (recommended) |
| **Development** | `http://localhost:8081` | Agent Gateway (direct) |
| **Internal** | `http://localhost:8084` | Orchestration Service (internal only) |

## Authentication

### Keycloak JWT Authentication

All API endpoints require Bearer token authentication using Keycloak JWT tokens.

#### Obtaining a Token (ROPC Flow - End Users)

```bash
# Obtain JWT token
export KEYCLOAK_URL="http://localhost:8180"
export USERNAME="your-username"
export PASSWORD="your-password"

TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/agentic-framework/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=login-client" \
  -d "grant_type=password" \
  -d "username=${USERNAME}" \
  -d "password=${PASSWORD}" \
  | jq -r '.access_token')

echo "Token: ${TOKEN}"
```

#### Obtaining a Token (Client Credentials - Services)

```bash
# For service-to-service authentication
export CLIENT_ID="your-client-id"
export CLIENT_SECRET="your-client-secret"

TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/agentic-framework/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "grant_type=client_credentials" \
  | jq -r '.access_token')
```

#### Using the Token

Include the token in the `Authorization` header for all API requests:

```bash
curl -X POST http://localhost:8080/v1/responses/chat/completions \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### RBAC Groups

The JWT token includes a `groups` claim for role-based access control:

| Group | Access Level |
|-------|-------------|
| `admin` | Full access including admin endpoints |
| `user` | Standard user access to public APIs |
| `data-scientists` | Access to scientific tools and knowledge bases |
| `notebook-users` | JupyterLab access |
| `gateway-service` | Service-to-service communication |

## Using the OpenAPI Specifications

### Swagger UI (Interactive Documentation)

You can use the OpenAPI specs with Swagger UI for interactive API exploration:

```bash
# Using Docker
docker run -p 8082:8080 \
  -e SWAGGER_JSON=/specs/openapi.json \
  -v $(pwd)/docs/api:/specs \
  swaggerapi/swagger-ui

# Access at: http://localhost:8082
```

### Postman

1. Open Postman
2. Click **Import** → **File**
3. Select `docs/api/openapi.json` or `docs/api/openapi-admin.json`
4. Configure authentication:
   - Type: Bearer Token
   - Token: `<your-jwt-token>`

### ReDoc

Generate static HTML documentation:

```bash
npx redoc-cli bundle docs/api/openapi.json -o docs/api/index.html
```

### Generate Client SDKs

Use OpenAPI Generator to create client libraries:

```bash
# Python client
docker run --rm -v $(pwd):/local openapitools/openapi-generator-cli generate \
  -i /local/docs/api/openapi.json \
  -g python \
  -o /local/generated/python-client

# TypeScript client
docker run --rm -v $(pwd):/local openapitools/openapi-generator-cli generate \
  -i /local/docs/api/openapi.json \
  -g typescript-axios \
  -o /local/generated/typescript-client
```

## API Examples

### Example 1: Response API (Recommended)

The Response API is the simplified, recommended interface for chat completions:

```python
import os
from openai import OpenAI

# Initialize client
client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=os.getenv("KEYCLOAK_TOKEN")  # JWT token as API key
)

# Create completion
response = client.responses.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the capital of France?"}
    ],
    temperature=0.7,
    max_tokens=1000
)

print(response.choices[0].message.content)
```

### Example 2: Assistants API (Deprecated)

OpenAI-compatible Assistants API (maintained for compatibility):

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key=os.getenv("KEYCLOAK_TOKEN")
)

# Create assistant
assistant = client.beta.assistants.create(
    name="Math Tutor",
    instructions="You are a helpful math tutor.",
    model="gpt-4",
    tools=[{"type": "code_interpreter"}]
)

# Create thread
thread = client.beta.threads.create()

# Add message
message = client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="What is 25 * 4?"
)

# Run assistant
run = client.beta.threads.runs.create(
    thread_id=thread.id,
    assistant_id=assistant.id
)

# Wait for completion and retrieve messages
# ... polling logic ...
```

### Example 3: Knowledge Base Operations

Create and query RAG knowledge bases:

```bash
# Create knowledge base
curl -X POST http://localhost:8080/v1/knowledge_bases/create \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Research Papers",
    "description": "Collection of scientific papers",
    "backend_type": "ragflow",
    "chunk_size": 1000,
    "chunk_overlap": 200
  }'

# Ingest document
curl -X POST http://localhost:8080/v1/knowledge_bases/ingest \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "kb_id=kb_abc123" \
  -F "file=@research_paper.pdf"

# Query knowledge base
curl -X POST http://localhost:8080/v1/knowledge_bases/query/kb_abc123 \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the key findings about protein folding?",
    "top_k": 5
  }'
```

### Example 4: Admin Tool Registration

Register external tools (requires `admin` role):

```bash
curl -X POST http://localhost:8080/v1/tools/register \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "external_calculator",
    "description": "Performs advanced mathematical calculations",
    "type": "http",
    "endpoint": "http://calculator-service:8090/calculate",
    "parameters_schema": {
      "type": "object",
      "properties": {
        "expression": {
          "type": "string",
          "description": "Mathematical expression to evaluate"
        }
      },
      "required": ["expression"]
    },
    "acl": {
      "allowed_groups": ["admin", "data-scientists"],
      "denied_groups": []
    }
  }'
```

## API Endpoint Categories

### Response API (Recommended)
- `POST /v1/responses/chat/completions` - Chat completion
- `POST /v1/responses/completions` - Text completion

### Chat Completions
- `POST /v1/chat/completions` - OpenAI-compatible chat

### Assistants (Deprecated)
- `POST /v1/assistants` - Create assistant
- `GET /v1/assistants` - List assistants
- `GET /v1/assistants/{assistant_id}` - Get assistant
- `POST /v1/assistants/{assistant_id}` - Update assistant
- `DELETE /v1/assistants/{assistant_id}` - Delete assistant

### Threads
- `POST /v1/threads` - Create thread
- `GET /v1/threads/{thread_id}` - Get thread
- `POST /v1/threads/{thread_id}` - Update thread
- `DELETE /v1/threads/{thread_id}` - Delete thread

### Messages
- `GET /v1/threads/{thread_id}/messages` - List messages
- `POST /v1/threads/{thread_id}/messages` - Create message
- `GET /v1/threads/{thread_id}/messages/{message_id}` - Get message

### Runs
- `POST /v1/threads/{thread_id}/runs` - Create run
- `GET /v1/threads/{thread_id}/runs/{run_id}` - Get run
- `POST /v1/threads/{thread_id}/runs/{run_id}/cancel` - Cancel run
- `POST /v1/threads/{thread_id}/runs/{run_id}/submit_tool_outputs` - Submit tool outputs
- `GET /v1/threads/{thread_id}/runs/{run_id}/steps` - List run steps

### Files
- `POST /v1/files` - Upload file
- `GET /v1/files` - List files
- `GET /v1/files/{file_id}` - Get file metadata
- `GET /v1/files/{file_id}/content` - Download file
- `DELETE /v1/files/{file_id}` - Delete file

### Knowledge Bases
- `POST /v1/knowledge_bases/create` - Create KB
- `POST /v1/knowledge_bases/ingest` - Ingest document
- `POST /v1/knowledge_bases/query/{kb_id}` - Query KB
- `GET /v1/knowledge_bases/list` - List KBs
- `GET /v1/knowledge_bases/{kb_id}` - Get KB details
- `DELETE /v1/knowledge_bases/{kb_id}` - Delete KB

### Tools
- `GET /v1/tools` - List available tools (user-authorized)
- `POST /v1/tools/register` - Register external tool (admin)
- `DELETE /v1/tools/{tool_name}` - Delete tool (admin)
- `PUT /v1/tools/{tool_name}/acl` - Update tool ACL (admin)

### Health & Management
- `GET /health` - Service health check
- `GET /management/info` - Service information

## Error Handling

All errors follow OpenAI-compatible error format:

```json
{
  "error": {
    "message": "Invalid API key provided",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_api_key"
  }
}
```

### Common Error Codes

| HTTP Status | Error Type | Description |
|------------|------------|-------------|
| 400 | `invalid_request_error` | Invalid request parameters |
| 401 | `authentication_error` | Invalid or missing JWT token |
| 403 | `permission_denied` | Insufficient permissions (RBAC) |
| 404 | `not_found` | Resource not found |
| 429 | `rate_limit_error` | Rate limit exceeded |
| 500 | `internal_server_error` | Server error |

## Session Management

The framework supports multi-tier session identifiers for proper state isolation:

### Session ID Types

| Session ID | Purpose | Scope |
|-----------|---------|-------|
| `session_id` | Basic conversation/thread | Single user conversation |
| `mcp_session_id` | MCP tool execution | Stateful tool operations |
| `multi_agent_session_id` | Multi-agent coordination | Multi-agent sessions |
| `gateway_session_id` | A2A communication | Inter-gateway sessions |

### Session Headers

When making requests, you can specify session IDs for state management:

```bash
curl -X POST http://localhost:8080/v1/responses/chat/completions \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Session-ID: user-session-123" \
  -H "X-MCP-Session-ID: mcp-session-456" \
  -H "Content-Type: application/json" \
  -d '{ ... }'
```

## Rate Limiting

The framework implements rate limiting at the Agent Gateway level:

- Default: 100 requests per minute per user
- Configurable via environment variables
- Rate limit headers included in responses:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`

## Further Documentation

### Implementation Details
- [Platform AI Engineer Onboarding](../PLATFORM_AI_ENGINEER_ONBOARDING.md)
- [Architecture Documentation](../architecture/)
- [Deployment Guides](../deployment/)

### Development
- [CLAUDE.md](../../CLAUDE.md) - Development patterns and best practices
- [Architecture Documentation](../architecture/)

### Support
- GitHub Issues: [Report bugs or request features](https://github.com/pnnl/adept-agentic/issues)
- Documentation: [Full documentation](../)

## Changelog

### Version 1.0.20260601 (2026-05-31)
- Regenerated OpenAPI specs from live services
- Added A2A gateway mesh endpoints
- Added AG-UI streaming protocol endpoints
- Added content filter and security hardening endpoints
- Updated architecture to reflect three-tier network model

### Version 1.0.0 (2026-01-07)
- Initial OpenAPI 3.1.0 specifications
- Complete endpoint documentation for public and admin APIs
- Authentication and RBAC documentation
- Usage examples and client SDK generation guides
