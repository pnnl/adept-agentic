# Roadmap

This roadmap outlines the planned direction for ADEPT development. Priorities may shift based on community feedback and operational requirements.

## Overview

ADEPT follows a quarterly planning cadence with CalVer releases (MAJOR.MINOR.YYYYMMDD). Each quarter focuses on a theme that advances the platform toward production readiness across multiple cloud providers.

## Current Focus

- Multi-agent orchestration hardening and session isolation
- ASOPB (Agentic Security & Operations Performance Benchmark) maturity
- A2A (Agent-to-Agent) federation between ADEPT instances
- Context management with automatic compaction
- adept-connectors ecosystem (Claude Desktop, IDE integrations)

## Upcoming (Q4 2026)

- **Multi-cloud deployment**: Production Helm charts for EKS, AKS, and GKE
- **SPIFFE/SPIRE integration**: Cryptographic workload identity for A2A authentication
- **nsjail hardening**: Kernel-level sandbox isolation with seccomp profiles
- **Egress whitelist enforcement**: Network policy controls for tool server outbound traffic
- **Helm chart optimization**: Resource limits, HPA, and pod disruption budgets
- **Enhanced observability**: Full OpenTelemetry tracing across all three tiers

## Future (2027+)

- Public PyPI releases for `adept-connectors` package
- Pluggable LLM provider backends (beyond LiteLLM)
- Federated tool marketplace across ADEPT instances
- GPU-accelerated sandbox environments for ML workloads
- Declarative workflow definitions (YAML-based agent orchestration)
- Kubernetes Operator for zero-touch ADEPT deployments

## Contributing to Roadmap

Roadmap priorities are informed by:

1. **GitHub Issues** -- Feature requests labeled `enhancement`
2. **Community discussions** -- Architecture proposals and design documents
3. **Operational experience** -- Lessons from production deployments

To propose a roadmap item, open a GitHub issue with the `roadmap-proposal` label and include:

- Problem statement
- Proposed solution (high-level)
- Expected impact
- Any prototype or proof-of-concept work
