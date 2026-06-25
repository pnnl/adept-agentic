# Session 100 (continued): adept_connectors Parity with claude_desktop_connector

**Date**: 2026-03-31
**Branch**: `feature-platform-optimizations-FY26Q2-validate-chatgpt-connector`
**Severity**: Enhancement + Bugfix
**Affected**: `examples/adept_connectors/`

---

## Summary

Bring `examples/adept_connectors/` to parity with `examples/claude_desktop_connector/` in terms of utility scripts, test suite quality, and validation coverage.

---

## Implementation Plan

| # | Task | Status | Details |
|---|------|--------|---------|
| 1 | Fix existing unit test failures (17->0) | DONE | conftest import path, proxy lifespan, CLI uvicorn mock, config env pollution |
| 2 | Add `scripts/bootstrap_demo_user.py` | DONE | Copied from claude_desktop_connector (bulk/delete/verify/multi-group) |
| 3 | Add `scripts/verify_deployment.py` | DONE | Copied from claude_desktop_connector (Keycloak, API, ROPC, issuer checks) |
| 4 | Add integration/e2e tests (`tests/integration/`) | DONE | 16 integration + 9 E2E tests, API key auto-discovery, all passing |
| 5 | Restructure tests to mirror source tree | DONE | `tests/core/`, `tests/connectors/chatgpt/`, `tests/connectors/generic/`, `tests/integration/` |
| 6 | UAT tests for macbook desktop validation | DONE (code) | 9 tests defined in `test_uat.py`, pending execution on macbook |
| 7 | Update docs and CHATGPT_CONNECTOR_TESTING_STRATEGY.md | DONE | Actual counts, issues/remediation/rationale, UAT section |
| 8 | Onboarding guide + architecture design doc | DONE | Multi-persona ONBOARDING_GUIDE.md, ARCHITECTURE_DESIGN.md reference copy |
| 9 | Fix stale API key format in ARCHITECTURE_REFERENCE.md | DONE | SERVICE_API_KEYS_CONFIG is flat dict, not `{"keys":[...]}` |
| 10 | PyPI release artifacts | DONE | LICENSE, CHANGELOG.md, py.typed, classifiers, urls, re-exports |
| 11 | Public release CI pipeline | DONE | `.publish-exclude` (rsync filter), `publish-to-public.sh`, GH Actions workflow |
| 12 | LLM-assisted scanning skills | DONE | `scripts/release/SKILLS.md` — 5 prompts for scan review, exclusion gen, audit, scrub, compare |
| 13 | Tighten `.publish-exclude` (ROADMAP, CHANGELOG, docs/*.md) | DONE | Replaced `+ /docs/*.md` wildcard with explicit whitelist; exclude sensitive top-level docs |
| 14 | ML model research for release scanning | DONE | BERT NER/PII/toxicity + detect-secrets + ASOPB integration docs in `scripts/release/docs/` |
| 15 | Prepare `adept_asopb` for PyPI release | DONE | LICENSE (BSD-2-Clause), CHANGELOG.md, py.typed, URLs to public repo, classifiers |
| 16 | ML-powered release scanning pipeline | DONE | Dockerfile + 4 scanners (regex, detect-secrets, BERT NER/PII, toxicity) + unified pipeline with ASOPB scoring |
| 17 | Release pipeline Makefile + tests | DONE | 84 tests (40 scanner + 19 publisher + 25 pipeline/ASOPB); lightweight (host) + container (Docker) modes |
| 18 | Rewrite project README.md | DONE | 879→180 lines; fix ADEPT title, remove session-specific bloat, add example stacks table, wiki link, license |
| 19 | Fix SIGPIPE bug in publish-to-public.sh | DONE | `diff | head -50` causes exit 141 under `set -e`; wrapped in `|| true` |
| 20 | Fix PEP 639 license classifier conflict in adept_asopb | DONE | Removed `License :: OSI Approved :: BSD License` classifier (conflicts with PEP 639 `license = "BSD-2-Clause"`) |
| 21 | Fix asopb subpackage discovery in pyproject.toml | DONE | Changed `packages = ["asopb"]` to `[tool.setuptools.packages.find] where = ["src"]` — 7 subpackages were missing |
| 22 | Fix Detoxify key mismatch in scan_toxicity.py | DONE | Model returns `toxicity`/`severe_toxicity`/`identity_attack`, not `toxic`/`severe_toxic`/`identity_hate` |
| 23 | Add `asopb[all]` extras and install in Dockerfile | DONE | Added `all` extra (analyzers + dev); Dockerfile installs `/tmp/asopb/[all]` |
| 24 | Docker smoke test target | DONE | `make docker-smoke` — verifies image, help, /scan mount, Python imports |
| 25 | Release pipeline README + user guide | DONE | `scripts/release/README.md` — architecture, quick start, file reference |
| 26 | Release pipeline testing strategy doc | DONE | `scripts/release/TESTING_STRATEGY.md` — test inventory, host vs container matrix, evidence logging |
| 27 | Docker container tests pass (68/68) | DONE | Scanner (40) + pipeline/ASOPB (28) including ML passes (NER, PII, toxicity, secrets) |
| 28 | Adapt `adept_connectors` docs for public release self-consistency | DONE | Rewrote 4 Claude Desktop docs + 3 cross-referencing docs; removed all `claude_desktop_connector` refs |
| 29 | Copy ASOPB research docs to `docs/research/` | DONE | 5 docs from `scripts/release/docs/` to top-level `docs/research/` (excluded from public release) |
| 30 | Report naming convention + archived scan report | DONE | `scripts/release/docs/reports/README.md` naming convention; archived ASPI scan report |
| 31 | Add `.claude/` to `.gitignore` | DONE | Lines 211-212 (already in `.publish-exclude` lines 105-106) |
| 32 | Fix scanner false positive on CI variable references | DONE | `scan_sensitive_content.py` credential regex: negative lookahead `(?!\$[\({])` excludes `$(VAR)`/`${VAR}` |
| 33 | Add `test-all-docker` Makefile target for zero-skip tests | DONE | Runs all 87 tests inside Docker container with ML deps; updated README + TESTING_STRATEGY |
| 34 | Commit and push | PENDING | |

---

## Bugfixes Applied

### 1. conftest Import Path (8 files)

**Problem**: 8 chatgpt test files used `from conftest import create_mock_facade` which pytest doesn't support as direct import.
**Fix**: Added root `tests/conftest.py` that inserts the chatgpt test directory into `sys.path`.
**Files**: `tests/conftest.py` (new)

### 2. Proxy App Lifespan Not Triggered (10 tests)

**Problem**: `httpx.ASGITransport` does NOT trigger FastAPI lifespan events. Proxy tests used `patch.object(app.state, "http_client")` but `http_client` only exists after lifespan runs.
**Fix**: Pre-initialize `app.state` in test helper `_create_test_app()` (auth, upstream_base, http_client) to bypass lifespan.
**Files**: `tests/connectors/generic/test_proxy.py`

### 3. CLI uvicorn Mock (6 tests)

**Problem**: `patch("adept_connectors.connectors.generic.cli.uvicorn")` fails because `uvicorn` is imported inside `main()` (local import), not at module level.
**Fix**: Use `patch.dict(sys.modules, {"uvicorn": mock_uvicorn})` to inject mock before the local import.
**Files**: `tests/connectors/generic/test_cli.py`

### 4. Config Env Var Pollution (1 test)

**Problem**: chatgpt conftest set `os.environ["ADEPT_API_KEY"] = "test-key-for-chatgpt-tests"` at module load, causing `TestConnectorProfile.test_defaults` to see a non-None api_key.
**Fix**: Changed to `os.environ.setdefault(...)` and added `monkeypatch.delenv("ADEPT_API_KEY")` to the affected test.
**Files**: `tests/connectors/chatgpt/conftest.py`, `tests/core/test_config.py`

### 5. MCP tools/call 404 for Internal Tools

**Problem**: Integration test called `PerformSimpleCalculation` via `/mcp` endpoint — got 404.
**Root Cause**: `/mcp` endpoint only exposes externally registered tools from Redis. Internal MCP server tools (PerformSimpleCalculation, websearch, etc.) are invoked directly by the orchestration service, not through the gateway `/mcp` proxy.
**Fix**: Replaced `test_call_tool_calculation` with `test_tool_names_include_known_tools` that validates `tools/list` returns known external tools. UAT V.7 validates tool schema structure.
**Rationale**: Tool execution is validated via E2E chat tests where the LLM triggers tool calls through the orchestration pipeline. The `/mcp` endpoint is for tool discovery, not direct invocation of internal tools.

### 6. Test-Key Env Var Cross-Conftest Pollution

**Problem**: Running `pytest tests/` (unit + integration together) caused integration tests to use fake `"test-key-for-chatgpt-tests"` instead of real API key, resulting in 401 Unauthorized.
**Root Cause**: pytest imports all conftest files during collection. Chatgpt conftest's `setdefault("ADEPT_API_KEY", "test-key...")` ran before integration conftest's `_discover_api_key()`, inserting a fake key that preempted credential file discovery.
**Fix**: (1) Inverted discovery order — integration conftest reads credential file first, falls back to `ADEPT_TEST_API_KEY` only (never reads `ADEPT_API_KEY`). (2) Makefile runs tiers as separate pytest invocations (`make test` = `test-unit` → `test-integration` → `test-e2e`).
**Files**: `tests/integration/conftest.py`, `Makefile`

### 7. SIGPIPE in publish-to-public.sh Dry-Run

**Problem**: `publish-to-public.sh --dry-run` exits with code 141 when the excluded file list exceeds 50 lines.
**Root Cause**: The pipeline `diff <(...) <(...) | grep | sed | head -50` causes `head` to close stdout after 50 lines. Under `set -euo pipefail`, `diff` receives SIGPIPE (128+13=141) and the script aborts before reaching step 4 (scanning).
**Fix**: Wrapped the diff pipeline in `(...) || true` to absorb the expected SIGPIPE.
**Files**: `scripts/release/publish-to-public.sh`

### 8. PEP 639 License Classifier Conflict in adept_asopb

**Problem**: Docker build of `adept-release-scanner` failed at `pip install /tmp/asopb/` with `InvalidConfigError: License classifiers have been superseded by license expressions`.
**Root Cause**: `examples/adept_asopb/pyproject.toml` had both PEP 639 `license = "BSD-2-Clause"` AND legacy `License :: OSI Approved :: BSD License` classifier. Newer setuptools (in python:3.11-slim) rejects the combination.
**Fix**: Removed the legacy classifier, keeping only PEP 639 expression.
**Files**: `examples/adept_asopb/pyproject.toml`

### 9. asopb Subpackage Discovery (7 subpackages missing)

**Problem**: `import asopb` succeeded but `asopb.domains` failed with `ModuleNotFoundError`.
**Root Cause**: `pyproject.toml` had `packages = ["asopb"]` which only includes the top-level package. The 7 subpackages (domains, analyzers, llm, redteam, reports, scanner, skills) were not included in the wheel.
**Fix**: Replaced `packages = ["asopb"]` + `[tool.setuptools.package-dir]` with `[tool.setuptools.packages.find] where = ["src"]` for auto-discovery.
**Files**: `examples/adept_asopb/pyproject.toml`

### 10. Detoxify Label Key Mismatch

**Problem**: `TestPipelineToxicity::test_toxicity_pass_runs` failed inside container with `KeyError: 'severe_toxic'`.
**Root Cause**: Detoxify `predict()` returns keys `toxicity`, `severe_toxicity`, `identity_attack` — not `toxic`, `severe_toxic`, `identity_hate` as documented in some older references.
**Fix**: Updated `THRESHOLDS` dict keys and severity classification in `scan_toxicity.py` to match actual model output.
**Files**: `scripts/release/scan_toxicity.py`

---

## Validation Results

### Unit Tests (187 passed, 4.98s)

| Category | Tests | Result |
|----------|-------|--------|
| Core (auth, config, session, clients, rendering, admin) | 111 | 111 passed |
| ChatGPT connector (app, routes, middleware, rendering) | 57 | 57 passed |
| Generic connector (proxy, CLI) | 19 | 19 passed |
| **Total** | **187** | **187 passed (4.98s)** |

### Integration Tests (16 passed, 0.48s)

| Test Class | Tests | Result |
|-----------|-------|--------|
| TestAuthIntegration | 2 | 2 passed |
| TestConnectivity | 2 | 2 passed |
| TestSessionManagerIntegration | 4 | 4 passed |
| TestFilesIntegration | 3 | 3 passed |
| TestMCPProxyIntegration | 3 | 3 passed |
| TestFacadeIntegration | 2 | 2 passed |
| **Total** | **16** | **16 passed (0.48s)** |

### E2E Tests (9 passed, 61.52s)

| Test Class | Tests | Result |
|-----------|-------|--------|
| TestResponseAPIChatE2E | 4 | 4 passed |
| TestAGUIProtocolE2E | 2 | 2 passed |
| TestFileUploadWorkflowE2E | 2 | 2 passed |
| TestLargeFileUploadE2E | 1 | 1 passed |
| **Total** | **9** | **9 passed (61.52s)** |

### UAT Tests (9 defined, pending execution)

| V# | Test | Status |
|----|------|--------|
| V.1 | ROPC auth through nginx HTTPS | Pending |
| V.2 | Response API SSE through nginx | Pending |
| V.3 | AG-UI JSONL through nginx | Pending |
| V.4 | Small file upload through nginx | Pending |
| V.5 | Large file upload (>1MB) through nginx | Pending |
| V.6 | MCP tools/list through nginx /mcp | Pending |
| V.7 | MCP tool schema validation through nginx /mcp | Pending |
| V.8 | Multi-turn session continuity | Pending |
| V.9 | File upload + chat workflow | Pending |

### Combined Run (unit + integration + e2e together)

```
pytest tests/ -v -k "not uat"
# 212 passed, 10 deselected in 194.74s (3:14)
```

### Totals

| Tier | Tests | Passed | Status |
|------|-------|--------|--------|
| Unit | 187 | 187 | COMPLETE |
| Integration | 16 | 16 | COMPLETE |
| E2E | 9 | 9 | COMPLETE |
| UAT | 9 | 0 | Pending macbook execution |
| **Grand Total** | **221** | **212** | **212/212 on RC + 9 UAT pending** |

### Release Pipeline Tests (87 passed)

| Test File | Host | Container | Total |
|-----------|------|-----------|-------|
| `test_scan_sensitive_content.py` | 40 passed | 40 passed | 40 |
| `test_publish_to_public.py` | 19 passed | N/A (host paths) | 19 |
| `test_scan_pipeline.py` | 22 passed, 3 skipped | 28 passed, 0 skipped | 28 |
| **Total** | **81 passed, 3 skipped** | **68 passed** | **87** |

Container tests include ML passes: detect-secrets (1), BERT NER (1), toxicity (1).

### Comparison: adept_connectors vs claude_desktop_connector

| Feature | claude_desktop_connector | adept_connectors |
|---------|--------------------------|-------------------|
| Unit tests | 184 passing | 187 passing |
| Integration tests | 10 passing | 16 passing |
| E2E tests | 6 passing | 9 passing |
| UAT tests | 6/6 passed (2026-03-29) | 9 defined, pending macbook |
| `scripts/bootstrap_demo_user.py` | Yes (bulk/delete/verify) | Yes (copied) |
| `scripts/verify_deployment.py` | Yes (5 checks) | Yes (copied) |
| Test structure mirrors source | Yes | Yes |
| API key auto-discovery | Yes | Yes |
| Pytest markers registered | Yes | Yes |

---

## Files Created

| File | Purpose |
|------|---------|
| `scripts/bootstrap_demo_user.py` | Bulk Keycloak user create/delete/verify |
| `scripts/verify_deployment.py` | Pre-flight deployment verification |
| `tests/conftest.py` | Root conftest for sys.path management |
| `tests/integration/__init__.py` | Integration test package |
| `tests/integration/conftest.py` | Shared fixtures (adept_config, adept_client, adept_facade, API key auto-discovery) |
| `tests/integration/test_core_integration.py` | 16 integration tests (auth, connectivity, sessions, files, MCP, facade) |
| `tests/integration/test_e2e.py` | 9 E2E tests (Response API SSE, AG-UI JSONL, file upload + chat, large file) |
| `tests/integration/test_uat.py` | 9 UAT tests (V.1-V.9 macbook desktop validation through nginx HTTPS) |
| `docs/ARCHITECTURE_DESIGN.md` | Architecture design doc (reference copy from GENERIC_CONNECTOR_CORE_EXTRACTION_PLAN) |
| `docs/ONBOARDING_GUIDE.md` | Multi-persona onboarding for all connectors (domain scientist audience) |
| `CHANGELOG.md` | Keep a Changelog format, 0.1.0 initial release |
| `LICENSE` | BSD-2-Clause + DOE disclaimer (from project root) |
| `src/adept_connectors/py.typed` | PEP 561 marker for type hint consumers |
| `.publish-exclude` (project root) | rsync filter rules for public release exclusions |
| `scripts/release/publish-to-public.sh` (project root) | Squash-merge publish script |
| `.github/workflows/publish-public-release.yml` (project root) | GitHub Actions workflow for public release |
| `docs/guides/RELEASING.md` (project root) | Release process documentation |
| `scripts/release/scan_sensitive_content.py` (project root) | Python keyword scanner for sensitive content (14 patterns, 3 severity levels, text/JSON output) |
| `scripts/release/SKILLS.md` (project root) | 5 LLM-assisted scanning skills for release pipeline review |
| `scripts/release/docs/ASOPB_FRAMEWORK_ANALYSIS.md` (project root) | ASOPB framework architecture analysis for release scanner integration |
| `scripts/release/docs/ASOPB_SCORING_AND_SUPPLY_CHAIN.md` (project root) | ASOPB scoring rubrics, supply chain hardening, AIVSS integration |
| `scripts/release/docs/ML_MODELS_FOR_RELEASE_SCANNING.md` (project root) | HuggingFace BERT model recommendations (NER, PII, toxicity, credentials) |
| `examples/adept_asopb/LICENSE` | BSD-2-Clause + DOE disclaimer (from project root) |
| `examples/adept_asopb/CHANGELOG.md` | Keep a Changelog format, 0.1.0 initial release |
| `examples/adept_asopb/src/asopb/py.typed` | PEP 561 marker for type hint consumers |
| `docs/SESSION_100_ADEPT_CONNECTORS_PARITY.md` | This document |
| `scripts/release/Dockerfile` (project root) | Container image with pre-downloaded BERT NER/PII + toxicity models for offline ML scanning |
| `scripts/release/scan_secrets.py` (project root) | Pass 1: detect-secrets (Yelp) credential scanner (28 detectors, regex + entropy) |
| `scripts/release/scan_ner_pii.py` (project root) | Pass 2: BERT NER (dslim/bert-base-NER) + PII (Isotonic/deberta-v3) entity detection |
| `scripts/release/scan_toxicity.py` (project root) | Pass 3: Toxicity detection via detoxify/toxic-bert (6 labels, batch inference) |
| `scripts/release/scan_pipeline.py` (project root) | Unified 4-pass pipeline orchestrator with ASOPB D5/D7/D8 scoring and ASPI composite |
| `scripts/release/Makefile` (project root) | Lightweight (host) + container (Docker) targets for scanning, staging, publishing, testing |
| `scripts/release/tests/test_scan_sensitive_content.py` (project root) | 40 unit tests for regex scanner (patterns, filtering, formatters, CLI) |
| `scripts/release/tests/test_publish_to_public.py` (project root) | 19 tests for publisher script (CLI, .publish-exclude validation, dry-run integration) |
| `scripts/release/tests/test_scan_pipeline.py` (project root) | 25 tests for pipeline + ASOPB scoring (14 ASOPB score tests, 6 pipeline, 5 formatter) |
| `scripts/release/README.md` (project root) | User guide: architecture, quick start, Docker image, file reference, testing |
| `scripts/release/TESTING_STRATEGY.md` (project root) | Testing strategy: test inventory, host vs container matrix, evidence logging |
| `scripts/release/.gitignore` (project root) | Ignore `asopb/` build context directory |

## Files Modified

| File | Change |
|------|--------|
| `tests/connectors/chatgpt/conftest.py` | `setdefault` instead of unconditional env var set |
| `tests/connectors/generic/test_proxy.py` | Pre-initialize app.state, remove patch.object lifespan dependency |
| `tests/connectors/generic/test_cli.py` | Use `patch.dict(sys.modules)` for uvicorn mock |
| `tests/core/test_config.py` | Add monkeypatch.delenv for env pollution isolation |
| `pyproject.toml` | Add pytest markers (integration, e2e, uat) |
| `docs/CHATGPT_CONNECTOR_TESTING_STRATEGY.md` | Full rewrite with actual counts, issues, remediation |
| `.publish-exclude` (project root) | Tightened docs whitelist: replaced `+ /docs/*.md` with explicit safe files; added `.claude/`, `**/logs/`, `config/stable-service-keys.json`, `**/certs/*.key` exclusions |
| `examples/adept_asopb/pyproject.toml` | BSD-2-Clause license, public repo URLs, Python 3.13, Typed classifier |
| `examples/adept_asopb/README.md` | Updated badges, license, and URLs to public repo |
| `README.md` (project root) | Complete rewrite: 879→180 lines, ADEPT title, example stacks, wiki link, license section |
| `scripts/release/publish-to-public.sh` (project root) | Fix SIGPIPE (exit 141) in dry-run diff pipeline |
| `examples/adept_asopb/pyproject.toml` | Fix PEP 639 classifier conflict + subpackage auto-discovery + add `all` extra |
| `scripts/release/scan_toxicity.py` (project root) | Fix Detoxify label key mismatch (severe_toxicity, identity_attack, toxicity) |
| `scripts/release/Dockerfile` (project root) | Install `asopb[all]` extras; build-time import validation |
| `scripts/release/Makefile` (project root) | Add `docker-smoke` target; fix `docker-test` to skip publisher tests in container |

## Related Documentation

**adept_connectors docs (adapted for public release):**
- `examples/adept_connectors/docs/ARCHITECTURE_DESIGN.md` (architecture design)
- `examples/adept_connectors/docs/ONBOARDING_GUIDE.md` (multi-persona onboarding for all connectors)
- `examples/adept_connectors/docs/CHATGPT_CONNECTOR_TESTING_STRATEGY.md`
- `examples/adept_connectors/docs/claude_desktop/ARCHITECTURE_REFERENCE.md` (auth flows, nginx routes)
- `examples/adept_connectors/docs/claude_desktop/KNOWN_ISSUES.md` (24 issues, categorized)
- `examples/adept_connectors/docs/claude_desktop/TESTING_STRATEGY.md` (four-tier test strategy)
- `examples/adept_connectors/docs/claude_desktop/WORKSHOP_DEMO_RUNBOOK.md` (server + client demo)

**Internal reference (not public):**
- `examples/claude_desktop_connector/docs/SESSION_100_BOOTSTRAP_SCRIPT_ENHANCEMENTS.md`
- `examples/claude_desktop_connector/docs/TESTING_STRATEGY.md`
- `examples/claude_desktop_connector/docs/ARCHITECTURE_REFERENCE.md` (API key format fix)

**Release pipeline:**
- `scripts/release/README.md` (release pipeline user guide)
- `scripts/release/TESTING_STRATEGY.md` (release pipeline testing methodology)
- `scripts/release/SKILLS.md` (LLM-assisted scanning skills)
- `scripts/release/Makefile` (`test-all-docker` for zero-skip container tests)
- `scripts/release/docs/reports/README.md` (report naming convention)

**Research (excluded from public release):**
- `docs/research/ASOPB_COMPREHENSIVE_ANALYSIS.md`
- `docs/research/ASOPB_FRAMEWORK_ANALYSIS.md`
- `docs/research/ASOPB_SCANNER_PATTERNS_REFERENCE.md`
- `docs/research/ASOPB_SCORING_AND_SUPPLY_CHAIN.md`
- `docs/research/ML_MODELS_FOR_RELEASE_SCANNING.md`

**Other:**
- `docs/implementation-plans/GENERIC_CONNECTOR_CORE_EXTRACTION_PLAN.md` (canonical source)

---

## Remaining Work

| # | Item | Priority | Status |
|---|------|----------|--------|
| 1 | Run UAT tests from macbook through nginx HTTPS | P1 | Pending |
| 2 | Roo Code proxy connector UAT validation | P1 | Pending |
| 3 | Configure PUBLIC_REPO_DEPLOY_KEY + PUBLIC_REPO_PAT secrets on internal repo | P1 | Pending |
| 4 | Dry-run publish to pnnl/adept-agentic | P1 | Pending |
| 5 | First public release (v0.1.0) | P1 | Pending |
| 6 | Commit and push | P1 | Pending |
