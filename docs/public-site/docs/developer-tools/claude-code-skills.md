# Claude Code Skills

ADEPT ships 22 Claude Code skills that automate the 10-phase development lifecycle. Skills are invoked with `/<skill-name>` inside a Claude Code session and provide guided workflows for feature development, MCP server creation, and release management.

## Overview

Skills are **tool-agnostic accelerators** -- the same workflow they encode can be followed manually by reading `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md`. Skills simply reduce friction by prompting for required inputs, running validation gates, and generating artifacts in the correct format.

## Skill Categories

Skills fall into three categories aligned with the development lifecycle:

- **Feature Lifecycle** -- Planning through commit and push
- **MCP Server** -- Building and registering new tool servers
- **Release** -- Scanning, scoring, and publishing

## Feature Lifecycle Skills

| Skill | Phase | Description |
|-------|-------|-------------|
| `/start-feature` | 0-9 | Walk through all phases for a new feature, bugfix, or enhancement |
| `/validate-tests` | 5 | Check required test tiers and verify timestamped evidence |
| `/write-session-report` | 6 | Draft implementation report or bugfix documentation |
| `/update-tracking-docs` | 7 | Update CHANGELOG, ROADMAP, KNOWN_ISSUES, and sprint tracker |
| `/prepare-commit` | 8 | Build Conventional Commit message with documentation references |
| `/audit-hygiene` | 8 | Walk the full Code Hygiene checklist (PASS/FAIL per item) |
| `/pre-push-review` | 8 | Semantic self-review: pattern consistency, dead code, doc-code divergence |
| `/prepare-pr` | 9 | Create PR, check reviews, address findings, resolve conversations |
| `/review-pr` | 9 | Assess and address PR review findings from Copilot/CodeRabbit/humans — classify, fix, reply |
| `/close-task` | 5-9 | Run Phases 5-9 in sequence (test, document, commit, audit, push) |

## MCP Server Skills

| Skill | Phase | Description |
|-------|-------|-------------|
| `/mcp-plan` | 1-2 | Analyze a Python library and produce an MCP server plan: API audit, parameter mapping, dependencies |
| `/mcp-scaffold` | 4 | Create a new external MCP server from the canonical template |
| `/mcp-add-tool` | 4 | Add a new tool to an existing MCP server following `register(mcp)` + Pydantic pattern |
| `/mcp-test` | 5 | Run the 4-tier MCP test strategy: unit, integration, registration, E2E |
| `/mcp-register` | 9 | Register MCP server tools with the ADEPT gateway, including pre-flight validation |

## Release Skills

| Skill | Phase | Description |
|-------|-------|-------------|
| `/prepare-release` | 10 | Walk steps 4-6 of the release pipeline (stage, scan, dry-run). Never executes publish. |
| `/scan-release` | 10 | Run full ASOPB scan on staged release tree (air-gapped, 7-pass) |
| `/scan-path` | -- | Run ASOPB scan on an arbitrary host directory with ASPI scoring |
| `/triage-cve` | -- | Investigate and triage CVE findings: lookup, reachability analysis, remediation |

!!! note "Release Safety"
    The `/prepare-release` skill deliberately stops before the publish step. Publishing requires a manual `make publish` invocation to prevent accidental releases.

## Using Skills Manually

Every skill encodes a workflow documented in the repository. If you prefer to work without Claude Code skills:

1. **Feature work** -- Follow `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md` phases 0-9
2. **MCP servers** -- Use the template in `docs/development/MCP_SERVER_DEVELOPMENT_SKILLS_PLAN.md`
3. **Releases** -- Follow `docs/development/VERSIONING_AND_RELEASE_CONVENTIONS.md`
4. **Code hygiene** -- Use the Quick Reference Card in `docs/development/CODE_HYGIENE.md`

Skills reduce manual effort but do not replace understanding of the underlying processes.

## Additional Skills

| Skill | Description |
|-------|-------------|
| `/start-sprint` | Create GitHub issues and plans for a multi-day coordinated sprint |
| `/token-utilization` | Aggregate LLM token consumption from observability backends |
| `/connect-adept` | Connect Claude Code to an ADEPT instance and run a doctor check |
| `/slurm-job-submit` | Submit Slurm HPC jobs via ADEPT agent -- single-agent (v1) or multi-agent with LLM-as-judge (v2) |

## Extending Skills

Skills are defined as Claude Code skill configurations. To add a new skill:

1. Define the skill name, trigger conditions, and description
2. Implement the guided workflow with validation gates
3. Document the skill in this reference and in `CLAUDE.md`
4. Test the skill end-to-end in a fresh session

Refer to `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md` for the complete phase definitions that skills automate.
