# ASOPB Test Suite

Comprehensive test suite for the Agentic Security & Operations Performance Benchmark (ASOPB) evaluation framework.

## Overview

- **3,462 lines of test code**
- **11 test modules** (conftest + 10 test files)
- **100+ test cases** covering all major components
- **Fixtures and mocks** for deterministic, isolated testing

## Test Structure

### Core Test Files

1. **test_models.py** (340 lines)
   - ControlScore composite calculation and floor enforcement
   - DomainResult aggregation (T1/T2/T3 averages, domain_score)
   - EvaluationReport ASPI calculation and gap ratios
   - FrameworkVersion version_key generation
   - ControlEvidence hash deduplication
   - Report integrity via report_hash
   - RedTeamScenario and RedTeamReport construction

2. **test_scoring.py** (400+ lines)
   - ASPI calculation against the paper's weighted mean formula
   - ASPI edge cases (all N/A domains, custom weights)
   - T1/T2 gap ratio (controls with design but no implementation)
   - Gap ratio edge cases (all zeros, all implemented, all gaps)
   - Stage classification (S1/S2/S3/S4 heuristics)
   - Domain profile output structure
   - Report delta comparison and control-level deltas

3. **test_scanners.py** (350+ lines)
   - AuthScanner JWT/OAuth/OIDC detection
   - Unsafe session parameter detection (Optional[str] = None)
   - Identity provider detection (Keycloak, Auth0, Okta, Cognito)
   - RBAC/ABAC pattern detection
   - Session validation and API key detection
   - Middleware and auth flag detection
   - Multiple finding aggregation and limiting

4. **test_analyzers.py** (280+ lines)
   - AnalyzerBase interface and initialization
   - Tool availability checking (mocked shutil.which)
   - Graceful degradation when tools missing
   - Result creation with metadata
   - JSON output parsing
   - Multiple analyzer execution

5. **test_domains.py** (350+ lines)
   - D4 Identity evaluator control definitions
   - D4 control scoring with JWT/auth evidence
   - Floor enforcement (LLM cannot lower below scanner floor)
   - Applicability checking
   - Domain metadata and severity levels
   - NIST/OWASP control mappings
   - T1/T2/T3 scoring criteria

6. **test_evidence_store.py** (350+ lines)
   - Save/load evaluation roundtrip
   - List evaluations with pagination
   - Version history retrieval (chronological order)
   - Evidence deduplication checking
   - Report integrity verification via hash
   - Version delta calculation

7. **test_redteam.py** (400+ lines)
   - RedTeamPluginBase execution
   - SimulatorPluginBase with lifecycle management
   - ReportIngesterBase JSON parsing
   - RedTeamRegistry plugin registration
   - Plugin discovery (empty cases, mocked entry points)
   - Report ingestion workflow
   - Scenario and report construction with evidence

8. **test_reports.py** (380+ lines)
   - Report JSON serialization/deserialization
   - Evidence bundle export (directory structure)
   - Report integrity across roundtrips
   - ASPI and gap ratio bounds (0-100, 0-1)
   - Control composite bounds
   - Report metadata (timestamp, version, stats)
   - Domain and control handling

## Fixtures

### conftest.py (shared pytest fixtures)

- `tmp_repo`: Minimal repo with pyproject.toml, src/agent.py, src/tools.py
- `tmp_repo_with_auth`: Extended with auth.py (JWT, Keycloak), docker-compose.yaml
- `tmp_repo_with_tools`: Extended with MCP tool registration patterns, ACL filtering
- `sample_config`: EvalConfig with skip_llm=True
- `evidence_store`: In-memory SQLite EvidenceStore
- `sample_scan_result`: Pre-built ScanResult with JWT/auth findings
- `sample_domain_result`: Pre-built DomainResult with D4 controls
- `sample_evaluation_report`: Complete EvaluationReport with multiple domains
- `minimal_agent_fixture_dir`: /tests/fixtures/minimal_agent/ (LangChain agent)
- `agent_with_auth_fixture_dir`: /tests/fixtures/agent_with_auth/ (Keycloak auth, ACLs)

### Test Fixture Directories

- `/tests/fixtures/minimal_agent/`
  - pyproject.toml (minimal deps)
  - src/agent.py (LangChain agent with flat tool list)
  - src/tools.py (register_tools pattern)

- `/tests/fixtures/agent_with_auth/`
  - pyproject.toml (with JWT/requests deps)
  - src/agent.py (auth-enabled)
  - src/auth.py (Keycloak JWT validation, JWKS fetching)
  - src/tools.py (register_tools with ACL filtering)
  - docker-compose.yaml (Keycloak service definition)

## Running the Tests

### All tests
```bash
pytest tests/
```

### Specific module
```bash
pytest tests/test_models.py
```

### With async support
```bash
pytest tests/ -v --asyncio-mode=auto
```

### Exclude LLM-dependent tests
```bash
pytest tests/ -m "not llm"
```

## Test Organization

### Deterministic Tests (No LLM)
- All core model tests
- All scoring tests
- Evidence store tests
- Report tests
- Domain tests (skip_llm=True)

### Async Tests (pytest-asyncio)
- Scanner tests (@pytest.mark.asyncio)
- Analyzer tests (@pytest.mark.asyncio)
- Domain evaluation tests (@pytest.mark.asyncio)
- Red-team plugin tests (@pytest.mark.asyncio)

### Mocked External Tools
- Analyzer is_available() checks use `@patch("shutil.which")`
- Red-team entry point discovery uses mock classes
- No actual external tools required

## Test Coverage

### Models
- 10 control score tests
- 7 domain result tests
- 7 evaluation report tests
- 4 framework version tests
- 4 control evidence tests
- 2 red-team scenario/report tests

### Scoring
- 5 ASPI calculation tests
- 5 T1/T2 gap ratio tests
- 4 stage classification tests
- 3 domain profile tests
- 3 report delta tests

### Scanners
- 13 AuthScanner pattern detection tests
- Covers JWT, OAuth, identity providers, RBAC, session validation, API keys, middleware

### Analyzers
- 6 AnalyzerBase tests
- 8 availability/tool checking tests
- 4 result creation tests
- 3 parsing tests

### Domains (D4 Identity)
- 4 control definition tests
- 4 scoring tests
- 3 detailed control tests
- 2 applicability tests
- 4 metadata tests

### Evidence Store
- 5 save/load tests
- 3 list/query tests
- 2 deduplication tests
- 2 integrity tests
- 2 delta tests

### Red-Team
- 4 plugin base tests
- 3 simulator tests
- 2 ingester tests
- 5 registry tests
- 2 integration tests
- 2 scenario construction tests

### Reports
- 3 serialization tests
- 4 export tests
- 5 validity/bounds tests
- 5 metadata tests
- 4 domain tests
- 4 control tests
- 3 warnings/skipped tests

## Key Testing Patterns

### 1. Fixture-Based Testing
All tests use pytest fixtures for consistent setup and isolation.

### 2. Deterministic Testing
LLM tests marked with `@pytest.mark.llm` can be excluded with `-m "not llm"`.

### 3. Mock External Tools
Analyzers mock `shutil.which` to avoid requiring actual tool installation.

### 4. Async Testing
Async scanner/analyzer/domain tests use `@pytest.mark.asyncio` with async/await.

### 5. Model Validation
All tests verify Pydantic model constraints (field ranges, required fields, etc.).

### 6. Edge Cases
Tests include boundary conditions (zeros, maximums, N/A values, empty collections).

## Dependencies

- pytest
- pytest-asyncio (for async tests)
- pydantic (for models)
- (No LLM provider required due to skip_llm=True in config)

## Notes

- Tests are independent and can run in any order
- Fixtures use tmp_path for file I/O isolation
- Evidence store uses in-memory SQLite by default
- Red-team tests use mock plugin classes, not entry points
- Scanner tests create minimal fixture files in tmp_path
