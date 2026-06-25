# How to Contribute

## Overview

ADEPT follows a structured 10-phase development lifecycle for all changes. This ensures consistency, traceability, and quality across the codebase regardless of whether you are adding a feature, fixing a bug, or refactoring infrastructure.

## Getting Started

1. Clone the repository and ensure Docker is available.
2. Run `make start` to bring up the local development stack.
3. Read `CLAUDE.md` for architecture context and port mappings.
4. Identify the appropriate work type (see decision tree below).

## Development Lifecycle

All work progresses through 10 phases:

| Phase | Name | Gate |
|-------|------|------|
| 0 | Planning | Implementation plan document exists |
| 1 | Discovery | 3+ analogous patterns identified |
| 2 | Design | Architecture decision documented |
| 3 | Branch | Branch created with correct naming |
| 4 | Implement | Code written, linted, formatted |
| 5 | Test | Required test tiers pass |
| 6 | Document | Tracking docs updated |
| 7 | Commit | Conventional Commit with doc references |
| 8 | Audit | Code hygiene checklist passes |
| 9 | Close | PR created, review requested |

## Decision Tree by Work Type

| Type | Branch Prefix | Test Requirement | Documentation |
|------|---------------|------------------|---------------|
| Feature | `feature-` | Unit + E2E | Implementation plan + report |
| Bugfix | `fix-` or `bugfix-` | Regression test | Bugfix document |
| Refactor | `refactor-` | Existing tests pass | Architecture note |
| Chore | `chore-` | Smoke test | Changelog entry |

## Branch Naming

Branches follow a hierarchical naming convention:

```
<type>-<scope>-<quarter>[-<detail>]
```

Examples:

- `feature-platform-optimizations-FY26Q3`
- `fix-credential-drift-session44`
- `chore-deps-update-20260501`

## Commit Format

All commits use [Conventional Commits](https://www.conventionalcommits.org/) with a Related Documentation footer:

```
<type>(<scope>): <description>

<body>

Related Documentation:
- docs/architecture/<RELEVANT_ARCHITECTURE_DOC>.md
- docs/testing/<RELEVANT_TEST_DOC>.md
```

Supported types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `perf`.

## Testing Requirements

Every change must satisfy the appropriate testing tier:

| Tier | Scope | Execution |
|------|-------|-----------|
| Unit | Single module, no external deps | `make validate-unit-all` |
| Integration | Multiple modules, mocked infra | Docker container with service stubs |
| E2E | Full stack, real services | `make validate` (services must be running) |

!!! warning "Zero-mock philosophy"
    ADEPT prefers real framework components over mocks. Integration and E2E tests use actual service containers rather than simulated responses.

## Claude Code Skills

The following skills automate lifecycle phases when working with Claude Code:

| Skill | Purpose |
|-------|---------|
| `/start-feature` | Walk through Phases 0-9 for new work |
| `/validate-tests` | Check required test tiers and evidence |
| `/write-session-report` | Draft implementation or bugfix report |
| `/update-tracking-docs` | Update CHANGELOG, ROADMAP, sprint tracker |
| `/prepare-commit` | Build Conventional Commit message |
| `/audit-hygiene` | Run full Code Hygiene checklist |
| `/pre-push-review` | Semantic self-review before push |
| `/prepare-pr` | Create PR and address review findings |
| `/close-task` | Run Phases 5-9 in sequence |
| `/mcp-plan` | Produce MCP server implementation plan |
| `/mcp-scaffold` | Create new MCP server from template |
| `/mcp-add-tool` | Add tool to existing MCP server |
| `/mcp-test` | Run 4-tier MCP test strategy |

## Code Review Process

After pushing your branch:

1. Create a PR using `gh pr create` with a structured summary.
2. Automated checks (lint, test, ASOPB) run in CI.
3. Copilot provides initial automated review.
4. A human reviewer approves or requests changes.
5. Address all findings before merge.

See [Code Review](code-review.md) for detailed review workflow documentation.
