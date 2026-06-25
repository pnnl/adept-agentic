# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-31

### Added

- **Core library** (`adept_connectors.core`)
  - `ConnectorProfile` — minimal config (URL + API key + model) for zero-code IDE tools
  - `AdeptConnectorConfig` — full config with Keycloak, sessions, workspace settings
  - `AuthManager` — token lifecycle management (API key, JWT, Keycloak ROPC with auto-refresh)
  - `SessionManager` — multi-tier session mapping with fork handling and optional persistence
  - `AdeptFacade` — high-level API wrapping Response API (SSE), AG-UI (JSONL), files, MCP proxy
  - `ImageRenderer` protocol with `MarkdownRenderer` default implementation
  - HTTP client abstractions: `BaseAdeptClient`, `ResponsesAPIClient`, `AGUIClient`, `FilesClient`, `MCPProxyClient`
  - Keycloak user provisioning (`admin/user_provisioning.py`)

- **ChatGPT Actions connector** (`adept_connectors.connectors.chatgpt`)
  - FastAPI application with OpenAI-compatible REST endpoints
  - OAuth2 authorization code flow proxy to Keycloak
  - Bearer token validation middleware
  - Routes: chat, files, tools, sessions, images, health
  - `ChatGPTImageRenderer` with in-memory image cache

- **Auth proxy for IDE tools** (`adept_connectors.connectors.generic`)
  - Transparent OpenAI-compatible proxy with JWT lifecycle management
  - CLI entry point: `adept-auth-proxy`
  - SSE and JSONL stream pass-through
  - Works with Roo Code, Continue.dev, Cursor, OBot.ai, and any OpenAI-compatible client

- **Test suite** (212 tests passing)
  - 187 unit tests (core + chatgpt + generic connectors)
  - 16 integration tests (live ADEPT stack, no LLM)
  - 9 E2E tests (live stack + LLM inference)
  - 9 UAT tests (macbook through nginx HTTPS)
  - Sequential Makefile runner for env var isolation between tiers

- **IDE configs** (`configs/`)
  - Ready-to-use config files for Roo Code, Continue.dev, Cursor, OBot.ai, AG-UI clients

- **Documentation**
  - Onboarding guide for domain scientists (multi-persona, all connectors)
  - Architecture design document
  - Testing strategy with issues, remediation, and rationale
  - Implementation tracker (Session 100)

[0.1.0]: https://github.com/pnnl/adept-agentic/releases/tag/adept-connectors-v0.1.0
