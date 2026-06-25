---
name: start-sprint
description: Initialize a new sprint with GitHub issue parity, local tracker updates, and a testing/deployment strategy. Creates umbrella + sub-task issues, updates all local tracking docs, and defines validation requirements per sub-task and for the umbrella. Use at the START of a new sprint or workstream.
disable-model-invocation: true
allowed-tools: Bash(gh *) Bash(git *) Bash(grep *) Bash(ls *) Read Write Edit Glob Grep
argument-hint: <sprint-title> (e.g., "SkyPilot AWS Deployment")
---

You are assisting an ADEPT developer with initializing a new sprint (or multi-workstream feature). This skill ensures full parity between GitHub issues and local implementation tracking BEFORE any implementation begins.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in issues or documents.

---

## Phase 1: Gather Context

Read the active sprint status tracker:
```bash
ls -t docs/implementation-sprints/SPRINT_*_STATUS.md | head -1
```

Read the umbrella plan doc (if it exists) and identify:
- The overarching GitHub issue (#16 for FY26Q2)
- Existing workstreams and their issue numbers
- The sprint week and priority

Ask the developer:
1. Sprint/workstream title (use `$ARGUMENTS` if provided)
2. Number of sub-tasks/workstreams
3. Owner assignments (if known)
4. Priority and sprint week

---

## Phase 2: Create GitHub Issues

### 2a. Umbrella Issue

Create an umbrella issue following the #25 or #33 pattern:

```bash
gh issue create \
  --title "<Sprint Title> -- <Subtitle>" \
  --body "$(cat <<'EOF'
## Overview
<1-2 sentence problem statement>

## Workstreams
- [ ] WS1: <title> (effort: X days)
- [ ] WS2: <title> (effort: X days)
- [ ] WSN: <title> (effort: X days)

## Dependency Graph
```
WS1 --> WS4
WS2 --> WS5
WS3 --> WS5
```

## Testing & Deployment Strategy
<How the umbrella will be validated end-to-end>

## Plan Documentation
- `docs/implementation-plans/<UMBRELLA_DOC>.md`
- `docs/implementation-plans/<subdir>/WS1_*.md`

## Sprint
- **Parent**: #16 (FY26Q2 Platform Optimizations)
- **Priority**: P1
- **Sprint**: W<N>+
EOF
)" \
  --label enhancement,infrastructure
```

Record the returned issue number.

### 2b. Per-Workstream Child Issues

For each workstream, create a child issue:

```bash
gh issue create \
  --title "WS<N>: <Workstream Title>" \
  --body "$(cat <<'EOF'
**Parent**: #<umbrella_number>
**Plan**: `docs/implementation-plans/<subdir>/WS<N>_*.md`
**Effort**: X days
**Dependencies**: <list or None>

## Scope
<Brief scope from plan doc>

## Testing Strategy
- **Offline validation**: <what can be validated without cloud resources>
- **Online validation**: <what requires credentials but no live resources>
- **Live deployment**: <what requires actual resource creation>
- **IaC parity**: <what infrastructure-as-code must be validated (CDK/Terraform/Pulumi)>

## Acceptance Criteria
- [ ] <criterion 1>
- [ ] <criterion 2>
EOF
)" \
  --label enhancement
```

Record each returned issue number.

---

## Phase 3: Update Local Tracking

### 3a. Sprint Status Tracker

Add rows to the issue status table:

```markdown
| #<umbrella> | <Sprint Title> | @<owner> | P1 | W<N>+ | Open (planning) | -- |
| #<ws1> | WS1: <title> | @<owner> | P1 | W<N> | In progress | -- |
| #<ws2> | WS2: <title> | -- | P1 | W<N>+ | Open | -- |
```

Update the issue hierarchy section and the summary count line.

### 3b. Umbrella Plan Doc

Add `**GitHub Issue**: [#N](url)` to the plan doc header.
Add an issue-to-workstream mapping table in the Sprint Tracking section.

### 3c. Per-Workstream Plan Docs

Add to each WS doc header:
```markdown
**GitHub Issue**: [#N](https://github.com/<org>/<repo>/issues/N)
**Parent**: [UMBRELLA_DOC.md](../UMBRELLA_DOC.md) ([#<umbrella>](url))
```

---

## Phase 4: Define Testing & Deployment Strategy

**CRITICAL**: No sub-task is ready for commit without a validated testing strategy. The umbrella must define end-to-end deployment validation.

### 4a. Per-Workstream Testing Strategy

For each workstream, define and document in the plan doc:

| Tier | What | How | Blocks Commit? |
|------|------|-----|----------------|
| Offline | YAML/schema/lint validation | Containerized (no credentials) | YES |
| Online | Cloud connectivity, dry-run | With credentials, no resources | YES |
| Live | Actual deployment + health checks | Creates real resources | YES (first time) |
| IaC Parity | CDK/Terraform matches task YAML specs | Compare resource configs | YES |

Each workstream MUST have:
- A `Makefile` validation target (e.g., `make sky-validate-offline`)
- A containerized test approach (never install tools directly on host)
- A CSP-specific validation path (AWS first, Azure/GCP later)
- Documented acceptance criteria that map to testable assertions

### 4b. Umbrella End-to-End Validation

The umbrella issue/doc must define:
1. **Integration test**: How workstreams interact (e.g., WS1 output feeds WS4)
2. **CSP coverage**: Which CSPs are validated (AWS primary, Azure/GCP planned)
3. **IaC validation**: CDK synth/diff, Terraform plan, Pulumi preview
4. **Deployment pipeline**: Full lifecycle test (provision -> deploy -> health check -> teardown)
5. **Cost controls**: Budget limits for live testing

### 4c. CSP Support Matrix

Document in umbrella plan doc:

| CSP | IaC Tool | Status | Validation Target |
|-----|----------|--------|-------------------|
| AWS | CDK | Primary (first supported) | `make sky-validate-aws` |
| Azure | Pulumi | Planned | `make sky-validate-azure` (future) |
| GCP | Terraform | Planned | `make sky-validate-gcp` (future) |

Note: Cloud-based servers use Ubuntu; on-premises VMs use Rocky Linux. Both OS families MUST be supported for parity with on-premises K8s clusters.

---

## Phase 5: Update Tracking Docs

Update `docs/CHANGELOG.md` and `docs/ROADMAP.md` with the sprint initialization entry:

```markdown
## Session <N>: <Sprint Title> Initialization (<Month Year>)
**Type**: Sprint planning
**GitHub Issues**: #<umbrella> (OPEN), #<ws1> (OPEN), ...
```

---

## Phase 6: Verification Checklist

Before declaring sprint initialization complete, verify:

```bash
# All issues created
gh issue list --label enhancement --state open | grep "<sprint keyword>"

# Local tracker has all issue numbers
grep -c '#<umbrella>' docs/implementation-sprints/SPRINT_*_STATUS.md

# All plan docs have GitHub Issue headers
for ws in docs/implementation-plans/<subdir>/WS*.md; do
  grep -l "GitHub Issue" "$ws" || echo "MISSING: $ws"
done

# Testing strategy documented
grep -l "Testing Strategy\|Validation\|Acceptance Criteria" docs/implementation-plans/<subdir>/WS*.md
```

Present the checklist results. If any items fail, provide remediation steps.

---

## Anti-Patterns (Avoid These)

- Starting implementation before GitHub issues exist
- Committing code without validation targets passing
- Creating a monolithic plan doc instead of per-workstream docs
- Skipping the testing strategy definition
- Not defining CSP parity requirements upfront
- Using host-installed tools instead of containerized validation
- Deploying to cloud without offline validation passing first
- Inspecting or mounting user home directories for credentials (`~/.aws`, `~/.ssh`) — inject creds via env vars sourced from operational scripts (e.g., `setup-claude-bedrock.sh`)
