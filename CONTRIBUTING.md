# Contributing to ADEPT

**ADEPT**: Agentic Discovery and Exploration Platform for Tools

This guide covers the software development lifecycle, code hygiene conventions, and onboarding path for all ADEPT contributors -- developers, domain scientists, and AI pair-programming sessions.

For detailed architecture, port mappings, API strategy, and validation commands, see `CLAUDE.md`.

---

## Onboarding Path

Read these documents in order. Each step builds on the previous.

### Step 1: Understand the Codebase and Conventions

| Read | What You Learn |
|------|---------------|
| `CLAUDE.md` | Project identity, three-tier architecture, port mappings, API strategy (Response API primary), validation commands, critical safety rules. Every Claude Code session loads this automatically. |
| `docs/development/CODE_HYGIENE.md` | Branch naming, Conventional Commit format, session documentation templates, 5-tier testing strategy, Related Documentation footer chains, Quick Reference Card checklist. |

### Step 2: Learn the Feature Development Lifecycle

| Read | What You Learn |
|------|---------------|
| `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md` | 10-phase canonical lifecycle (orient, plan, discover, branch, implement, test, document, commit, validate, close). Mandatory gates at each phase. Decision tree for bugfix vs feature vs refactor vs chore. Test tier selection matrix. Anti-patterns section (8 categories with empirical data). |
| `docs/development/VIBE_CODING_FRICTION_ANALYSIS.md` | Why the gates exist. Analysis of 2,187 developer-AI interactions across 100+ sessions. 8 friction categories with incident counts, root causes, and mitigations. |

### Step 3: Use Claude Code Skills (Optional)

14 skills automate the lifecycle phases. Skills are tool-agnostic accelerators -- developers using any editor can follow the same workflow manually.

**Feature Lifecycle Skills:**

| Skill | Phase | What It Does |
|-------|-------|-------------|
| `/start-feature` | 0-9 | Master conductor -- walks the full lifecycle interactively |
| `/start-sprint` | 0-3 | Creates GitHub issues + umbrella plan + testing strategy |
| `/validate-tests` | 5 | Checks required test tiers, verifies timestamped evidence |
| `/write-session-report` | 6 | Drafts implementation report or bugfix doc |
| `/update-tracking-docs` | 6 | Updates CHANGELOG, ROADMAP, KNOWN_ISSUES, sprint tracker |
| `/prepare-commit` | 7 | Builds Conventional Commit message with doc reference chains |
| `/audit-hygiene` | 8 | Walks full Code Hygiene Quick Reference Card checklist |
| `/prepare-pr` | 9 | Creates PR, checks Copilot/peer review, addresses findings, resolves review conversations |
| `/close-task` | 5-9 | End-of-session workflow (phases 5-9 in sequence) |

**MCP Server Development Skills:**

| Skill | Phase | What It Does |
|-------|-------|-------------|
| `/mcp-plan` | 1-2 | API audit, parameter mapping, dependencies, session boundaries for a target Python library |
| `/mcp-scaffold` | 4 | Creates MCP server from canonical template with 8-check collision detection gate |
| `/mcp-add-tool` | 4 | Adds tool following `register(mcp)` + Pydantic pattern with session isolation |
| `/mcp-test` | 5 | Runs 4-tier MCP test strategy (unit, integration, registration, E2E) |
| `/mcp-register` | 9 | Registers server tools with ADEPT gateway, pre-flight validation, Redis verification |

Start any new work with: `/start-feature`
Close any session with: `/close-task`

### Step 4: Set Up Your Development Environment

**Local (Docker):** See `docs/PLATFORM_AI_ENGINEER_ONBOARDING.md` for the full platform setup with Docker Compose.

**Local (Docker-free):** See `docs/development/DOCKER_FREE_DEVELOPMENT.md` for host-mode workflows using `make setup-host-dev`, `make lint-host`, `make test-host-unit`.

**AWS EC2 (PNNL):** See `devtools/skypilot/ONBOARDING.md` for the CDK + Ansible two-step provisioning pipeline. All infrastructure targets live in `devtools/Makefile.internal`, conditionally included into the root Makefile via `-include` (silently skipped in public releases). Run `make help-internal` from the project root to list them.

---

## Software Development Lifecycle

### 10-Phase Feature Development Lifecycle

Derived from friction analysis of 2,187 developer-AI prompts across 100+ sessions. The top three friction sources -- implementing before planning (13.4%), not cross-referencing existing patterns (11.2%), and documentation/commit hygiene drift (16.4%) -- are addressed by mandatory gates.

```
Phase 0: Orient    -- Read CLAUDE.md, CODE_HYGIENE.md, target area skills
Phase 1: Plan      -- Create GitHub issue + implementation plan doc
Phase 2: Discover  -- Find 3+ analogous implementations in the codebase
Phase 3: Branch    -- Create child branch from correct parent, push to remotes
Phase 4: Implement -- Code changes mapped to planned tasks, no scope drift
Phase 5: Test      -- Run required tiers with nohup + timestamped logs
Phase 6: Document  -- Session report, tracking docs (CHANGELOG, ROADMAP)
Phase 7: Commit    -- Conventional Commits with Related Documentation chains
Phase 8: Validate  -- Full hygiene audit (branch, tests, docs, commit)
Phase 9: Close     -- Push, update GitHub issues, update sprint tracker
```

### Decision Tree

The phase sequence adapts by work type:

| Type | Phases |
|------|--------|
| Feature | Full Phase 0-9 |
| Bugfix | Phase 0, skip 1 (use existing issue), 2-9 |
| Refactor | Phase 0, 1 (lightweight), 3-9 |
| Chore | Phase 3, 4, 5 (if testable), 7, 9 |
| MCP Server | Full Phase 0-9 with `/mcp-*` skills at Phases 1-2, 4, 5, 9 |

### Gate Requirements

Each phase has a mandatory gate that must pass before advancing:

| Phase | Gate |
|-------|------|
| 0 | Can name the branch convention, commit format, and applicable test tiers |
| 1 | Implementation plan doc exists in `docs/implementation-plans/` |
| 2 | 3+ analogous implementations reviewed and documented |
| 3 | Branch exists on remote |
| 4 | All changes map to planned tasks |
| 5 | Timestamped test logs exist in `logs/` and are newer than code changes |
| 6 | Session report exists; CHANGELOG has this session's entry |
| 7 | Commit has both Related Documentation sections; no AI agent attribution |
| 8 | All Code Hygiene Quick Reference Card items pass |
| 9 | Branch pushed; GitHub issues updated; sprint tracker current |

---

## Code Hygiene

### Branch Naming

```
<category>-<workstream>-<FY-quarter>-<scope-description>
```

Categories: `feature-`, `fix-`, `proposals/`

Branches use a cascading model -- work streams branch from a parent feature branch, not directly from `main`.

### Commit Format

Conventional Commits with Related Documentation footer chains:

```
<type>(<scope>): <imperative summary, max 72 chars>

<what changed, why, test evidence with counts>

Related documentation (this commit):
- docs/implementation-reports/SESSION_<N>_<TITLE>.md
- docs/CHANGELOG.md

Related documentation (past 5 commits):
- <paths from git log -5 cross-referenced with modified docs>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`

No AI agent references in commit messages, trailers, or document metadata.

### Testing Tiers

| Change Scope | Unit | Integration | E2E | UAT | Contract |
|-------------|------|-------------|-----|-----|----------|
| Single module | REQ | -- | -- | -- | -- |
| Cross-component | REQ | REQ | -- | -- | -- |
| API route / gateway | REQ | REQ | REQ | -- | -- |
| New/modified class >500L | REQ | -- | -- | -- | REQ |
| Connector / UI | REQ | REQ | REQ | REQ | -- |
| `examples/adept_connectors/` | REQ | REQ | REQ | REQ | -- |
| Docs only | -- | -- | -- | -- | -- |
| IaC (CDK/Ansible/Helm) | -- | -- | DRY | -- | -- |

All test invocations must use `nohup` with timestamped logs:

```bash
mkdir -p logs && nohup make validate-<target> \
  > logs/<scope>_<tier>_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

### Session Documentation

Every development session produces a report:
- Features: `docs/implementation-reports/SESSION_<N>_<TITLE>.md`
- Bugfixes: `docs/bugfixes/SESSION_<N>_<TITLE>.md`

Tracking docs updated at each session:
- `docs/CHANGELOG.md` -- session entry with GitHub Issues line
- `docs/ROADMAP.md` -- progress tracking section
- `docs/KNOWN_ISSUES.md` -- new issues discovered or existing issues resolved
- Active sprint tracker in `docs/implementation-sprints/`

---

## Anti-Patterns

These are the 8 most common friction sources from empirical analysis. Each maps to a gate in the lifecycle.

1. **Implementing before planning** -- Write the implementation plan doc before writing code
2. **Not cross-referencing existing patterns** -- Find 3+ analogous implementations before proposing new solutions
3. **Ad-hoc shell commands** -- Use Makefile targets for all lifecycle operations; if you run it twice, it becomes a target
4. **Guessing before investigating** -- Read logs, trace errors, check configs before proposing fixes
5. **Not persisting findings** -- Write investigation results to `docs/`, not just conversation
6. **Scope drift** -- Implement only what was planned; extensions go to backlog as separate issues
7. **Missing doc references in commits** -- Include both Related Documentation sections in every commit
8. **Wrong tone for audience** -- No emojis in professional docs; proposals read like proposals; code reads like code

---

## AWS EC2 Developer VM (PNNL)

For developers deploying to PNNL's SCP-restricted `adept_VPC`:

```bash
make cdk-deploy-bg              # CDK provisions EC2 + IAM + SG + CloudWatch (~3 min)
# Wait for PNNL Nessus agent hooks (~5-20 min)
make cdk-retrieve-key           # Download SSH key from Secrets Manager
make ec2-sync EC2_HOST=<ip>     # rsync codebase to EC2 (~5 sec incremental)
make ansible-prepare-vm-bg \    # Docker, Python, workspace (~10 min)
  ANSIBLE_TARGET_HOST=<ip> \
  ANSIBLE_SSH_KEY=<key>.pem
make ec2-exec EC2_HOST=<ip> EC2_CMD="make start"  # Bootstrap ADEPT stack (~5 min)
```

Day-to-day operations use host-local `ec2-*` targets (SSH-based, no container): `ec2-ping`, `ec2-sync`, `ec2-ssh`, `ec2-exec`, `ec2-stats`, `ec2-validate`.

Full guide: `devtools/skypilot/ONBOARDING.md`

---

## Key References

| Document | Purpose |
|----------|---------|
| `CLAUDE.md` | Architecture, API strategy, port mappings, validation commands |
| `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md` | 10-phase lifecycle with gates |
| `docs/development/CODE_HYGIENE.md` | Branch, commit, test, doc conventions |
| `docs/development/VIBE_CODING_FRICTION_ANALYSIS.md` | Empirical basis for lifecycle gates |
| `docs/PLATFORM_AI_ENGINEER_ONBOARDING.md` | Platform setup with Docker |
| `docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md` | Ansible, EC2, credential management |
| `docs/development/DOCKER_FREE_DEVELOPMENT.md` | Host-mode development without Docker |
| `devtools/skypilot/ONBOARDING.md` | AWS EC2 deployment (CDK + Ansible) |
| `config/model_catalog.yaml` | LLM purposes and role aliases (YAML, no Python changes) |
