# Changelog

All notable changes to ADEPT are documented here. This project uses [CalVer](https://calver.org/) with the format `MAJOR.MINOR.YYYYMMDD`.

## Overview

Each release is gated by an ASOPB (Agentic Security & Operations Performance Benchmark) scan that must achieve an ASPI score of 90 or higher before publication.

## Latest Release

### v1.0.20260529

**Release Date**: 2026-05-29

#### Highlights

- **ASOPB Benchmark**: Full 7-pass security and quality scanning pipeline with ASPI scoring
- **Multi-agent orchestration**: Router and graph execution modes with RolePersona support
- **A2A federation**: Agent-to-Agent communication between ADEPT instances via Gateway Registry
- **adept-connectors**: Claude Desktop connector with MCP bridge and STDIO transport
- **28+ scientific tools**: BLAST, UniProt, PubChem, AlphaFold, ChromaDB RAG, sandbox execution
- **Response API**: Primary API with full SSE streaming (`/v1/responses/chat/completions`)
- **Context management**: Automatic compaction with token-aware truncation
- **YAML model catalog**: Declarative LLM purpose routing without code changes
- **Three-tier network architecture**: Frontend, application, and data network isolation
- **File-based secrets**: Production-ready credential management with fallback chain

#### Infrastructure

- Three-tier secure architecture (Gateway, Orchestration, MCP Servers)
- Keycloak IAM with JWT-based RBAC
- PostgreSQL state persistence with LangGraph checkpointing
- Redis-backed tool configuration and session management
- Docker Compose local development with Makefile lifecycle

#### Testing

- 100+ E2E test files covering authentication, multi-agent, MCP tools, and file operations
- Contract testing pattern for critical classes
- 4-tier MCP test strategy (unit, integration, registration, E2E)
- ASOPB 7-pass release scanning (regex, secrets, TruffleHog, NER/PII, toxicity)

## Previous Releases

!!! note "Release History"
    Prior releases were internal development milestones. The public changelog begins with v1.0.20260529.

## Version Scheme

ADEPT uses CalVer: `MAJOR.MINOR.YYYYMMDD`

- **MAJOR**: Breaking changes to public APIs or architecture
- **MINOR**: New features or significant enhancements
- **YYYYMMDD**: Release date stamp

Both the `agentic-framework-pkg` and `agentic-framework-sdk` packages share the same version number, bumped simultaneously during the release process.

## Release Process

1. Version bump in both packages
2. Squash-merge to main
3. Git tag `v<version>`
4. Stage release tree (`make stage`)
5. ASOPB scan (ASPI >= 90 gate)
6. Dry-run validation
7. Manual publish (never automated)
8. Tag `released-<version>`
9. GitHub Release with notes
