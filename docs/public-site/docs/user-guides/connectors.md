# ADEPT Connectors

The `adept-connectors` package provides a unified connector library for integrating IDE tools, chat clients, and custom applications with the ADEPT platform. It handles authentication, HTTP transport, session management, and per-client configuration.

## Installation

```bash
# Core only (auth, HTTP clients, session management)
pip install adept-connectors

# With Claude Desktop/Code support (FastMCP v2)
pip install adept-connectors[claude]

# With ChatGPT Actions support (FastAPI + OAuth2)
pip install adept-connectors[chatgpt]

# Auth proxy for zero-code IDE tools
pip install adept-connectors[proxy]

# Everything
pip install adept-connectors[all]
```

Requires Python 3.10 or later.

## Supported Clients

| Client | Integration Type | Config Model | Notes |
|--------|-----------------|--------------|-------|
| **Roo Code** (VS Code) | Auth Proxy | `ConnectorProfile` | Zero-code setup |
| **Continue.dev** (VS Code) | Auth Proxy | `ConnectorProfile` | Zero-code setup |
| **Cursor** | Auth Proxy | `ConnectorProfile` | Zero-code setup |
| **OBot.ai** | Auth Proxy | `ConnectorProfile` | Zero-code setup |
| **Claude Desktop / Code** | FastMCP v2 server | `AdeptConnectorConfig` | Full MCP bridge |
| **ChatGPT** (custom GPT) | REST + OpenAPI Actions | `AdeptConnectorConfig` | OAuth2 flow |
| **AG-UI clients** | Direct endpoint | `AdeptConnectorConfig` | Streaming protocol |
| **OpenWebUI** | Direct API | `ConnectorProfile` | OpenAI-compatible |
| **JupyterLab** | Direct API | `ConnectorProfile` | Notebook integration |

## Auth Proxy Usage

The auth proxy enables zero-code integration for IDE tools that support OpenAI-compatible endpoints. It handles Keycloak authentication transparently.

```bash
adept-auth-proxy \
  --upstream https://your-adept-server.example.com/v1 \
  --auth-method password \
  --username alice@example.com \
  --password secret
```

Then configure your IDE to use `http://localhost:19283/v1` as the OpenAI-compatible API endpoint. The proxy supports `password` (Keycloak ROPC) and `api_key` authentication methods.

## Claude Desktop Setup

The Claude connector uses FastMCP v2 to bridge Claude Desktop/Code with ADEPT's tool ecosystem:

```bash
# Install with Claude support
pip install adept-connectors[claude]

# Start the connector
adept-claude-connector \
  --base-url https://your-adept-server.example.com/v1 \
  --username alice@example.com \
  --password secret
```

The connector exposes ADEPT's MCP tools (file upload, RAG queries, code execution, scientific workflows) directly in Claude Desktop's tool palette.

## ChatGPT Integration

For ChatGPT custom GPTs, install `adept-connectors[chatgpt]`. The connector serves a FastAPI server with an OpenAPI schema that ChatGPT Actions can consume directly, providing OAuth2 authentication and natural language access to ADEPT tools.

## Configuration

Two configuration models are available:

- **`ConnectorProfile`** -- Lightweight config for direct API access (base URL + API key).
- **`AdeptConnectorConfig`** -- Full config for connectors managing their own Keycloak authentication (base URL + Keycloak URL + credentials + realm).

```python
from adept_connectors import ConnectorProfile, AdeptConnectorConfig

# Simple API key access
profile = ConnectorProfile(base_url="https://your-server.example.com/v1", api_key="sk-key")

# Full Keycloak-managed auth
config = AdeptConnectorConfig(
    base_url="https://your-server.example.com/v1",
    keycloak_url="https://your-server.example.com/auth",
    username="alice@example.com", password="secret", realm="adept",
)
```

## Package Structure

| Module | Contents |
|--------|----------|
| `core/config.py` | `ConnectorProfile`, `AdeptConnectorConfig` |
| `core/auth.py` | `AuthManager` (API key, JWT, Keycloak ROPC) |
| `core/session.py` | `SessionManager` (multi-tier IDs, fork, persistence) |
| `core/facade.py` | `AdeptFacade` (chat, AG-UI, files, tools) |
| `core/clients/` | HTTP abstractions (SSE, JSONL, files, MCP) |
| `connectors/claude/` | Claude Desktop -- FastMCP v2 bridge |
| `connectors/chatgpt/` | ChatGPT -- FastAPI + OpenAPI Actions + OAuth2 |
| `connectors/generic/` | Auth proxy for IDE tools |

## Security

All connector traffic routes through `nginx_proxy` which enforces:

- **TLS termination** with self-signed certificates (set `ADEPT_VERIFY_SSL=false` for local dev)
- **JWT authentication** via Keycloak (client credentials or ROPC flow)
- **Content-Security-Policy** headers on all responses (`img-src 'self' data: blob:`)

CSP headers are enforced by browsers, not HTTP clients. Connectors that consume JSON/SSE programmatically are unaffected by CSP. The policy prevents browser-side exfiltration when model output is rendered in a webview (e.g., plot embedding via presigned URLs in Claude Desktop remains functional since presigned URLs are same-origin).

## Development

```bash
git clone https://github.com/pnnl/adept-agentic.git
cd adept-agentic/examples/adept_connectors
pip install -e ".[all,dev]"
make test       # Unit + Integration + E2E
make test-all   # Full suite including UAT
```
