# Vibe Coding with Claude Code Skills

**Date**: 2026-04-30
**Context**: Real session demonstrating the `/start-feature` skill workflow for #48 (Parallel ML Scan Architecture)
**Branch**: `feature-platform-optimizations-FY26Q2-optimize-github-actions-asopb`

---

## What This Document Covers

A walkthrough of how Claude Code skills orchestrate the feature development lifecycle
in ADEPT. This is captured from a live session (not a synthetic example), showing
the actual decisions, gates, and artifacts produced at each phase.

---

## The Problem That Triggered This Work

The ASOPB pre-release scan (GitHub Actions CI) was timing out. NER (BERT inference)
takes 7.9 seconds per file on GitHub-hosted runners (4 vCPU, 16 GB RAM) -- 5.1x
slower than the local dev host. With 1,005 staged files, the sequential ML pipeline
projects to 305+ minutes. The 45-minute job timeout killed it at 300/1005 files.

**Goal**: Redesign the workflow to complete ML scanning in under 60 minutes using
GitHub Actions native parallelism.

---

## Skill Lifecycle: Phase-by-Phase

### Phase 0: Orient

The `/start-feature` skill begins by reading three mandatory documents:
1. `CLAUDE.md` -- architecture, port mappings, critical rules
2. `docs/development/FEATURE_DEVELOPMENT_WORKFLOW.md` -- the 10-phase lifecycle
3. `docs/development/CODE_HYGIENE.md` -- branch naming, commit format, testing tiers

Then it gathers situational awareness:
```bash
git branch --show-current
git status
git log --oneline -5
```

**Gate**: Must know work type (feature/bugfix/refactor/chore) and which phases apply.

**In this session**: Work type = feature, full Phase 0-9 applies.

---

### Phase 1: Plan

The skill checks if an implementation plan exists:
```bash
find docs/implementation-plans/ -name "*.md" | xargs grep -l "ASOPB.*parallel\|parallel.*ML"
```

If no plan exists, the skill blocks: "Write the plan BEFORE writing code."

**In this session**: The implementation plan was written FIRST as
`docs/implementation-plans/ASOPB_PARALLEL_ML_SCAN_PLAN.md` before any implementation
began. This was explicitly demanded -- the developer stopped the AI mid-stream with
"where are the intermediate outputs and why are you executing installations
without a proper plan?"

**Key artifacts from planning**:
- SDK evaluation (6 orchestration frameworks compared)
- Measured performance data (per-pass timing on both local and GHA runners)
- Architecture diagram (3-tier parallel job graph)
- 6 implementation tasks (T1-T6)
- Risk assessment and acceptance criteria

**Gate**: Implementation plan file must exist with tasks and acceptance criteria.

---

### Phase 2: Discover

Before implementing, find 3+ analogous patterns in the codebase:

**Found**:
1. `build-and-push.yml:69-79` -- matrix strategy over Docker services
2. `lint-and-test.yml:72-79` -- matrix strategy for parallel Docker build validation
3. `asopb-pre-release-scan.yml:188-194` -- artifact upload pattern (already in use)

These confirm that the project already uses GHA matrix strategy and artifact
upload/download patterns. The parallel scan architecture follows the same conventions.

**Gate**: At least 3 analogous implementations documented in the plan.

---

### Phase 3: Branch

Branch naming follows CODE_HYGIENE.md convention:
```
<category>-<workstream>-<FY-quarter>-<scope>
```

Result: `feature-platform-optimizations-FY26Q2-optimize-github-actions-asopb`

This is a child branch of `feature-platform-optimizations-FY26Q2-add-devtools-skypilot`.

**GitHub issue created**: #48 ("perf(ci): Parallel ML scan architecture for ASOPB GitHub Action") as a child of #32.

**Gate**: Branch exists on remote, issue linked.

---

### Phase 4: Implement

The plan specifies 6 tasks:

| Task | Scope | Description |
|------|-------|-------------|
| T1 | `scripts/release/aggregate_ml_results.py` | Merge per-pass/per-chunk JSON into combined report |
| T2 | `.github/workflows/asopb-pre-release-scan.yml` | Refactor to parallel matrix architecture |
| T3 | `scripts/release/Dockerfile` | Review for per-pass invocation compatibility |
| T4 | `scripts/release/Makefile` | Add per-pass and parallel local targets |
| T5 | Documentation | Update DevOps guide, onboarding, README |
| T6 | Validation | Verify parallel vs sequential ASOPB score parity |

Implementation follows the plan strictly. No scope drift -- extensions go to backlog.

---

### Phase 5: Test

Test tier determination based on what changed:
- `scripts/release/` changes -> unit tests for aggregation script
- `.github/workflows/` changes -> CI validation (push and observe)
- No `src/` changes -> no framework unit/integration tests needed

Required evidence:
```bash
mkdir -p logs && nohup make test-pipeline-full \
  > logs/test_pipeline_full_$(date +%Y%m%d_%H%M%S).log 2>&1 &
```

---

### Phase 6-9: Document, Commit, Validate, Close

These phases are orchestrated by `/close-task` which runs:
- Session report drafting (`/write-session-report`)
- Tracking doc updates (`/update-tracking-docs`)
- Commit message preparation (`/prepare-commit`)
- Hygiene audit (`/audit-hygiene`)
- PR creation (`/prepare-pr`)

---

## Key Decisions Made During This Session

### 1. SDK Evaluation: Why Not Use an Orchestration Framework?

| SDK | Verdict | One-Line Rationale |
|-----|---------|-------------------|
| mystic-ai/pipeline | Eliminated | ML model deployment, not workflow orchestration |
| Prefect | Overkill | 80+ deps for 5 Docker invocations |
| Metaflow | Wrong context | Cloud ML lifecycle, local mode is single-threaded |
| Ray | Eliminated | 70 MB wheel, requires cluster initialization |
| Parsl (DOE/ANL) | Closest fit | But duplicates what GHA matrix already does |
| Dask | Eliminated | Data parallelism, not subprocess orchestration |

**Decision**: GHA matrix strategy IS the orchestration layer. Adding an SDK creates
a second orchestration layer inside the first. The bottleneck is CPU (BERT on 4 vCPU),
not orchestration logic.

### 2. Chunk Count: Why 4?

| Chunks | Time/Chunk (NER) | Total Runners | Wall-Clock |
|--------|-----------------|---------------|------------|
| 2 | 66 min | 2 | 66 min |
| **4** | **33 min** | **4** | **~35 min** |
| 8 | 17 min | 8 | ~19 min |

4 chunks keep NER under 35 min per chunk, stay within GitHub's 20-concurrent-job
limit (13 total runners), and the artifact overhead (~30s/job) is negligible.

### 3. No Scanner Code Changes

All parallelism is external (directory-based file chunking). The scanner already
accepts any directory via `rglob("*")` and supports `--passes ner` / `--passes pii`
individually. Zero changes to Python scanning code.

---

## Anti-Patterns Avoided

These were explicitly called out by the developer during this session:

1. **Implementing before planning**: "where are the intermediate outputs
   and why are you executing installations without a proper plan?" -- Always
   write the plan doc to `docs/implementation-plans/` FIRST.

2. **Ad-hoc installations in CI**: Installing dependencies on the fly instead of
   using the pre-built Docker image. The scanner image
   (`scripts/release/Dockerfile`) has all ML models cached at build time.

3. **Inventing orchestration**: "We don't need to re-invent workflow orchestration."
   Use the platform's native capabilities (GHA matrix) before adding external tools.

4. **No intermediate output tracking**: Every pass writes crash-safe per-pass JSON
   via `--output-dir`. Every chunk uploads its results as a named artifact. Even if
   one chunk times out, the others are preserved.

---

## Skill Reference Quick Card

| Skill | Phase | What It Does |
|-------|-------|--------------|
| `/start-feature` | 0-9 | Master conductor -- walks through entire lifecycle |
| `/mcp-plan` | 1-2 | API audit + parameter mapping for MCP servers |
| `/validate-tests` | 5 | Checks required test tiers and timestamped evidence |
| `/write-session-report` | 6 | Drafts implementation report from git diff + logs |
| `/update-tracking-docs` | 6 | Syncs CHANGELOG, ROADMAP, KNOWN_ISSUES, sprint tracker |
| `/prepare-commit` | 7 | Builds Conventional Commit message with doc references |
| `/audit-hygiene` | 8 | Full Code Hygiene checklist (PASS/FAIL per item) |
| `/prepare-pr` | 9 | Create PR, check review, address findings, resolve conversations |
| `/close-task` | 5-9 | Runs Phases 5-9 in sequence (test, document, commit, audit, push) |
| `/prepare-release` | Pre-publish | ASOPB scan, staging, dry-run, publish gate |

---

## How This Workflow Prevents the Top 5 AI Pair-Programming Failures

(From `docs/development/VIBE_CODING_FRICTION_ANALYSIS.md`)

| Failure Mode | How Skills Prevent It |
|-------------|----------------------|
| Implementing without understanding context | Phase 0 forces reading 3 docs before any work |
| Reinventing existing patterns | Phase 2 requires finding 3+ analogous implementations |
| Scope drift during implementation | Phase 4 references the plan doc; extensions go to backlog |
| Claiming success without validation | Phase 5 requires timestamped test logs newer than code |
| Lost context across sessions | Phase 6 writes session report; Phase 7 commits doc references |

---

## Reproducing This Workflow

To use the same workflow on your next feature:

```
/start-feature #<issue> <description>. Branch: <branch-name>
```

The skill will walk you through each phase, pausing at gates for confirmation.
If any gate fails, it tells you exactly what to fix before proceeding.
