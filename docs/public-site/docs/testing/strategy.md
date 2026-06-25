# Testing Strategy

## Overview

ADEPT employs a comprehensive testing strategy built on the principle of zero-mock testing -- preferring real framework components over simulated responses. All tests execute inside Docker containers to ensure environment consistency across development machines and CI.

## Testing Philosophy

!!! info "Zero-mock principle"
    Use real adapters with graceful fallback. Never mock framework dependencies. If a service is unavailable, the test should skip gracefully rather than assert against a fake response.

Core tenets:

- **Real services** -- tests interact with actual Keycloak, PostgreSQL, Redis, and MCP servers.
- **State isolation** -- unique thread IDs and session identifiers prevent cross-test contamination.
- **Container execution** -- all tests run inside the `agentic-framework-deps-base` image with pre-installed dependencies.
- **Deterministic fixtures** -- test data is created per-test and cleaned up after execution.

## Test Tiers

| Tier | Scope | Dependencies | Speed | When to Run |
|------|-------|-------------|-------|-------------|
| Unit | Single function or class | None (or stdlib only) | < 1s per test | Every commit |
| Integration | Module interactions | Service stubs or real containers | 1-10s per test | Before push |
| E2E | Full request lifecycle | All services running | 5-60s per test | Before PR |
| UAT | User acceptance flows | Full stack + external LLM | 30-120s per test | Before release |
| Performance | Load and latency | Full stack under stress | Minutes | Scheduled |

## Container Execution

All tests execute inside Docker containers using a dual-network pattern:

```bash
docker run --rm \
  --network=adept_application_network \
  --network=adept_frontend_network \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  agentic-framework-deps-base \
  /app/.venv/bin/pytest tests/e2e/test_example.py -v
```

Key conventions:

- Source and test mounts are always **read-only** (`:ro`).
- The container's pre-installed `/app/.venv` is used directly (no ephemeral venv creation).
- Dual networks provide access to both internal services and the reverse proxy.

## Contract Testing

Contract tests validate that class interfaces remain stable by checking:

1. **Attribute existence** -- all instance attributes referenced in methods exist after `__init__`.
2. **Method execution** -- public methods execute without `AttributeError` given typical inputs.
3. **Negative assertions** -- incorrect attributes (e.g., `self.logger` when a module-level logger is used) do not exist.

```python
class TestMyClassContract:
    def test_init_creates_required_attributes(self, instance):
        assert hasattr(instance, 'config')
        assert hasattr(instance, 'session_id')
        # Negative: ensure no incorrect attributes
        assert not hasattr(instance, 'logger')

    def test_method_executes_without_crash(self, instance):
        try:
            result = instance.process(sample_input)
            assert result is not None
        except AttributeError as e:
            pytest.fail(f"Contract violation: {e}")
```

Contract tests are added for any class exceeding 500 lines or after discovering an `AttributeError` bug.

## Test Organization

```
tests/
├── unit/                    # Component-level, no external deps
│   ├── agentic_framework_pkg/
│   └── agentic_framework_sdk/
├── e2e/                     # Full stack, real services
├── integration/             # Module interactions with stubs
└── performance/             # Load and stress tests
```

## Coverage Goals

| Scope | Target | Current |
|-------|--------|---------|
| Critical modules (auth, orchestration) | 90% | In progress |
| Standard modules (tools, utilities) | 70% | In progress |
| Overall | 80% | Actively growing |

Coverage is tracked via `pytest-cov` and reported in CI. The `make validate-unit-coverage` target generates HTML coverage reports for local inspection.
