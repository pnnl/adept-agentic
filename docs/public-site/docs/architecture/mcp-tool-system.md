# MCP Tool System

## Overview

ADEPT uses the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) as its
standard for tool communication between the orchestration layer and execution servers.
The platform provides 28+ built-in tools distributed across three specialized servers,
with support for dynamic registration of external tools at runtime.

## Built-in Tools

Tools are organized by domain across three stateless MCP servers:

| Server | Domain | Tools |
|--------|--------|-------|
| `mcp_server` | Scientific research | BLAST, UniProt, PubChem, AlphaFold, web search, file management, CSV/PDF RAG |
| `hpc_mcp_server` | HPC pipelines | Nextflow workflow execution, video transcription, repository analysis |
| `sandbox_mcp_server` | Code execution | Secure Python/R execution, calculations, plot generation |

Each server exposes tools via the `@mcp.tool()` decorator pattern, making them
automatically discoverable through the MCP JSON-RPC protocol.

## Tool Discovery

ADEPT uses `MCPToolDiscovery` for runtime introspection of available tools:

```python
# Runtime discovery via JSON-RPC tools/list
discovered_tools = await mcp_discovery.discover_all_tools()
```

The discovery system:

- Queries each MCP server's `tools/list` JSON-RPC endpoint
- Caches results with configurable TTL for performance
- Falls back gracefully when servers are unreachable
- Eliminates dual maintenance of tool configuration

!!! info "Single Source of Truth"
    Tool definitions live exclusively in `@mcp.tool()` decorators on the MCP servers.
    No separate configuration files need to be maintained.

## Dynamic Registration

External tools can be registered at runtime via the `/admin/tools/*` API endpoints:

```bash
# Register an external MCP tool
POST /v1/admin/tools/register
{
  "name": "custom_analysis",
  "type": "mcp",
  "endpoint": "https://tools.example.com/mcp",
  "description": "Custom domain analysis tool"
}
```

Tool configurations are persisted in Redis, surviving service restarts without
requiring redeployment.

## ACL-Based Access Control

Tool access is governed by user group membership from Keycloak JWT claims:

1. User authenticates and receives JWT with `groups` claim
2. Orchestration service extracts groups from the authenticated context
3. Tool manager filters available tools based on ACL rules
4. Only authorized tools are exposed to the agent for that session

```yaml
# Example ACL configuration
tool: blast_search
allowed_groups: ["scientists", "admin"]
```

## External Tools

ADEPT supports three protocols for external tool integration:

| Protocol | Use Case | Communication |
|----------|----------|---------------|
| **MCP** | Structured tool servers | JSON-RPC over HTTP/SSE |
| **HTTP** | REST APIs and webhooks | Standard HTTP requests |
| **stdio** | Local CLI tools | stdin/stdout piping |

External tools are combined with built-in tools and passed to worker agents
during multi-agent session creation.

## Session Isolation

Each MCP server enforces strict session-scoped resource isolation:

- **File uploads**: Stored in `data/uploaded_files/{mcp_session_id}/`
- **Code execution**: Session-scoped containers and filesystems
- **RAG indexes**: Session-isolated vector stores
- **Temporary files**: Cleaned up on session termination

!!! warning "Security Boundary"
    Session isolation prevents cross-user data leakage. Each tool invocation
    receives the session context and must scope all resources accordingly.

Multi-tier session identifiers (`session_id`, `mcp_session_id`, `multi_agent_session_id`)
propagate through all tool calls to maintain proper isolation boundaries.
