# ADEPT Connectors

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: BSD-2-Clause](https://img.shields.io/badge/license-BSD--2--Clause-green.svg)](LICENSE)
[![PyPI version](https://img.shields.io/pypi/v/adept-connectors.svg)](https://pypi.org/project/adept-connectors/)

Unified connector library for the [ADEPT](https://github.com/pnnl/adept-agentic/wiki) (Agentic Discovery and Exploration Platform for Tools) platform — authentication, HTTP clients, session management, image rendering, and a high-level facade API.

**[Documentation](https://github.com/pnnl/adept-agentic/wiki/ADEPT-Connectors)** |
**[Onboarding Guide](docs/ONBOARDING_GUIDE.md)** |
**[Changelog](CHANGELOG.md)** |
**[Issues](https://github.com/pnnl/adept-agentic/issues)**

## Quick Start

```bash
# Core only (auth, clients, sessions, facade)
pip install adept-connectors

# With Claude Desktop support
pip install adept-connectors[claude]

# With ChatGPT Actions support
pip install adept-connectors[chatgpt]

# Auth proxy for zero-code IDE tools (Roo Code, Continue.dev, Cursor)
pip install adept-connectors[proxy]

# Everything
pip install adept-connectors[all]
```

### Minimal example

```python
from adept_connectors import ConnectorProfile, AuthManager

profile = ConnectorProfile(
    base_url="https://your-adept-server.example.com/v1",
    api_key="sk-your-api-key",
)
```

### Auth proxy for IDE tools

```bash
# Start the proxy (handles Keycloak auth transparently)
adept-auth-proxy \
  --upstream https://your-adept-server.example.com/v1 \
  --auth-method password \
  --username alice@example.com \
  --password secret

# Then configure your IDE to point at http://localhost:19283/v1
```

## Supported Clients

| Client | Integration | Config Tier |
|--------|-------------|-------------|
| **Roo Code** (VS Code) | Auth Proxy — zero code | `ConnectorProfile` |
| **Continue.dev** (VS Code) | Auth Proxy — zero code | `ConnectorProfile` |
| **Cursor** | Auth Proxy — zero code | `ConnectorProfile` |
| **OBot.ai** | Auth Proxy — zero code | `ConnectorProfile` |
| **Claude Desktop / Code** | FastMCP v2 server | `AdeptConnectorConfig` |
| **ChatGPT** (custom GPT) | REST + OpenAPI Actions | `AdeptConnectorConfig` |
| **AG-UI clients** | Direct endpoint | `AdeptConnectorConfig` |
| **OpenWebUI** | Direct API | `ConnectorProfile` |
| **JupyterLab** | Direct API | `ConnectorProfile` |

Ready-to-use config files are in [`configs/`](configs/) for each IDE tool.

## Package Structure

```
adept_connectors/
  core/               # Shared library
    config.py         #   ConnectorProfile, AdeptConnectorConfig
    auth.py           #   AuthManager (API key, JWT, Keycloak ROPC)
    session.py        #   SessionManager (multi-tier IDs, fork, persistence)
    facade.py         #   AdeptFacade (chat, agui, files, tools)
    rendering.py      #   ImageRenderer protocol + MarkdownRenderer
    clients/          #   HTTP client abstractions (SSE, JSONL, files, MCP)
    admin/            #   Keycloak user provisioning
  connectors/
    claude/           # Claude Desktop — FastMCP v2 bridge
    chatgpt/          # ChatGPT — FastAPI + OpenAPI Actions + OAuth2
    generic/          # Auth proxy for Roo Code, Continue.dev, Cursor, OBot.ai
```

## Development

```bash
git clone https://github.com/pnnl/adept-agentic.git
cd adept-agentic/examples/adept_connectors

# Install with dev dependencies
pip install -e ".[all,dev]"

# Run unit tests
make test-unit

# Run all tiers (unit -> integration -> e2e)
make test

# Run full suite including UAT
make test-all
```

See the [testing strategy](docs/CHATGPT_CONNECTOR_TESTING_STRATEGY.md) for details on the four-tier test architecture.

## Documentation

| Document | Description |
|----------|-------------|
| [Onboarding Guide](docs/ONBOARDING_GUIDE.md) | Step-by-step setup for each IDE tool |
| [Architecture Design](docs/ARCHITECTURE_DESIGN.md) | Core extraction plan and design rationale |
| [Testing Strategy](docs/CHATGPT_CONNECTOR_TESTING_STRATEGY.md) | Four-tier testing (unit, integration, E2E, UAT) |
| [Wiki: ADEPT Connectors](https://github.com/pnnl/adept-agentic/wiki/ADEPT-Connectors) | Full documentation |

## License

Copyright Battelle Memorial Institute 2026. Released under the [BSD-2-Clause](LICENSE) license.

See [LICENSE](LICENSE) for the full text including the U.S. Department of Energy disclaimer.
