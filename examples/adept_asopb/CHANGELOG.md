# Changelog

All notable changes to the ASOPB framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-31

### Added

- 8 security domains (D1-D8) with 47 built-in controls
- Three-layer evaluation pipeline: Scanners -> Analyzers -> Domain Evaluators
- ASPI (Agentic Security Posture Index) weighted scoring engine (0-100)
- Stage classification: S1 (Minimal) through S4 (Hardened)
- OWASP AIVSS v0.8 integration with 10 Agentic Risk Amplification Factors
- 8 built-in scanners: auth, codebase, tools, sandbox, itot, federation, observability, supply_chain
- 7 built-in analyzers: gitxray, semgrep, bandit, pip-audit, dockerfile, tls, ioc_scanner
- LLM-driven domain evaluation with skill markdown guidance (LiteLLM)
- Deterministic floor + LLM ceiling scoring pattern
- SQLite evidence store with CRC hashing and version delta tracking
- Red-team plugin architecture (setuptools entry points)
- Custom controls via YAML (STIG-style, merge with built-ins)
- JSON, Markdown, and HTML report renderers
- Evidence bundle export for compliance and audit
- Click-based CLI: evaluate, scan, tools, compare, validate, init
- Python async API for programmatic use
- Supply chain hardening controls (D8.6-D8.8) post-LiteLLM incident
- IOC scanner for known-compromised package versions
- 9 test modules with 2 fixture frameworks
