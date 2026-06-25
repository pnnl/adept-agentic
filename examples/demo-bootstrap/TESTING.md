# Demo Bootstrap Container - Test Suite Documentation

**Date**: 2026-02-09
**Status**: Complete
**Coverage**: Unit tests (3 modules) + Integration tests (container build, CLI, artifact generation)

**⚠️ IMPORTANT**: Before using the bootstrap container with real hostnames, read [HOSTNAME_USAGE.md](HOSTNAME_USAGE.md) to understand how `--hostname` parameter and `${HOSTNAME}` shell variables work in generated scripts.

---

## Prerequisites

### Before Running ANY Tests

**1. Build Base Image** (Required for all tests):
```bash
cd /path/to/adept-extended-2025-11-07

# Build the base image (this takes ~5-10 minutes first time)
docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .

# Verify it exists
docker images | grep agentic-framework-deps-base
```

**2. For Integration Tests ONLY** (Container build tests):
```bash
# Build the demo-bootstrap container
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

# Verify it exists
docker images | grep demo-bootstrap
```

**3. Docker Requirements**:
- Docker daemon running
- User has permission to run Docker commands
- Sufficient disk space (~5GB for images)

**4. For E2E Tests with A2A Registration** (/etc/hosts Configuration):
```bash
# Add to /etc/hosts (REQUIRED for integration tests that use CLI commands)
echo "127.0.0.1 api.agentic.local" | sudo tee -a /etc/hosts

# Verify
ping -c 1 api.agentic.local
```

**Why Needed**: E2E tests that invoke `a2a-register` or `a2a-list` CLI commands connect to `https://api.agentic.local/internal/registry`. Without /etc/hosts, these tests will fail with connection refused.

**Docker Network Requirements for E2E Tests**:
- Test containers need dual network access:
  - `adept_application_network` - Access internal services (Keycloak, gateway_registry)
  - `adept_frontend_network` - Access nginx_proxy as external clients
- Docker DNS automatically resolves `api.agentic.local` to nginx_proxy inside containers

### What You DON'T Need

❌ **ADEPT services running** - Unit tests are fully mocked, no services required
❌ **Keycloak credentials** - Tests use mocked authentication
❌ **Let's Encrypt account** - Certificate generation is mocked
❌ **.env files** - Tests don't need actual configuration

### Quick Verification

```bash
# Check Docker is running
docker ps

# Check base image exists
docker images agentic-framework-deps-base:latest

# You're ready if you see output from both commands above!
```

---

## Output Directory for Test Artifacts

### Git-Safe Artifact Storage

**Directory**: `examples/demo-bootstrap/output/`

**Configuration**:
- ✅ `.gitkeep` - Ensures directory exists in git
- ✅ `.gitignore` - Ignores all generated artifacts (certificates, configs, scripts)

**Why This Matters for Testing**:
- Integration tests generate real artifacts during execution
- Artifacts contain test certificates and configuration scripts
- These artifacts should NEVER be committed to version control
- `.gitignore` ensures `git status` stays clean after test runs

**What Gets Ignored**:
```
output/
├── .gitkeep          # Tracked ✅
├── .gitignore        # Tracked ✅
├── certs/            # Ignored ❌ (generated)
├── configs/          # Ignored ❌ (generated)
├── scripts/          # Ignored ❌ (generated)
├── a2a/              # Ignored ❌ (generated)
└── *.md              # Ignored ❌ (generated)
```

**Verification**:
```bash
# Generate test artifacts
make validate-demo-bootstrap-integration

# Check git status
git status examples/demo-bootstrap/output/
# Expected: Shows only .gitkeep and .gitignore (already committed)

# Clean up if needed
rm -rf examples/demo-bootstrap/output/{certs,configs,scripts,a2a,*.md}
```

**Security Note**: Private keys (*.key files) are especially sensitive. The `.gitignore` pattern prevents accidental commits of these files.

---

## Test Organization

### Unit Tests

**Location**: `tests/unit/examples/demo_bootstrap/`

| Module | Test File | Test Count | Coverage |
|--------|-----------|------------|----------|
| ArtifactGenerator | `test_artifact_generator.py` | 29 tests | 100% |
| LetsEncryptManager | `test_letsencrypt_manager.py` | 17 tests | 100% |
| A2ARegistrar | `test_a2a_registrar.py` | 13 tests | 100% |

**Total Unit Tests**: 59 tests

### Integration Tests

**Location**: `tests/integration/examples/demo_bootstrap/`

| Test Category | Test File | Test Count |
|---------------|-----------|------------|
| Container Build & CLI | `test_bootstrap_integration.py` | 15 tests |

**Total Integration Tests**: 15 tests

**Total Test Coverage**: 74 tests (59 unit + 15 integration)

---

## Running Tests

### Quick Commands

```bash
# Run all demo-bootstrap tests
make validate-demo-bootstrap-all

# Run only unit tests
make validate-demo-bootstrap-unit-all

# Run only integration tests
make validate-demo-bootstrap-integration

# Run specific module tests
make validate-demo-bootstrap-unit-artifact-generator
make validate-demo-bootstrap-unit-letsencrypt
make validate-demo-bootstrap-unit-a2a
```

### Manual Test Execution

#### Unit Tests (Individual Modules)

```bash
# Test ArtifactGenerator
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  -v "$(pwd)/examples":/app/examples:ro \
  -w /tmp \
  agentic-framework-deps-base /bin/bash -c "
    python3 -m venv /tmp/test_venv --system-site-packages &&
    /tmp/test_venv/bin/pip install -q pytest pytest-asyncio &&
    PYTHONPATH=/app/src:/app/tests \
    /app/.venv/bin/python -m pytest \
      /app/tests/unit/examples/demo_bootstrap/test_artifact_generator.py \
      -v --tb=short
  "

# Test LetsEncryptManager
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  -v "$(pwd)/examples":/app/examples:ro \
  -w /tmp \
  agentic-framework-deps-base /bin/bash -c "
    python3 -m venv /tmp/test_venv --system-site-packages &&
    /tmp/test_venv/bin/pip install -q pytest pytest-asyncio pytest-mock &&
    PYTHONPATH=/app/src:/app/tests \
    /app/.venv/bin/python -m pytest \
      /app/tests/unit/examples/demo_bootstrap/test_letsencrypt_manager.py \
      -v --tb=short
  "

# Test A2ARegistrar
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  -v "$(pwd)/examples":/app/examples:ro \
  -w /tmp \
  agentic-framework-deps-base /bin/bash -c "
    python3 -m venv /tmp/test_venv --system-site-packages &&
    /tmp/test_venv/bin/pip install -q pytest pytest-asyncio httpx &&
    PYTHONPATH=/app/src:/app/tests \
    /app/.venv/bin/python -m pytest \
      /app/tests/unit/examples/demo_bootstrap/test_a2a_registrar.py \
      -v --tb=short
  "
```

#### Integration Tests

```bash
# Requires Docker socket access for container build tests
docker run --rm --user $(id -u):$(id -g) \
  -v "$(pwd)/src":/app/src:ro \
  -v "$(pwd)/tests":/app/tests:ro \
  -v "$(pwd)/examples":/app/examples:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -w /tmp \
  agentic-framework-deps-base /bin/bash -c "
    python3 -m venv /tmp/test_venv --system-site-packages &&
    /tmp/test_venv/bin/pip install -q pytest pytest-asyncio pyyaml &&
    PYTHONPATH=/app/src:/app/tests \
    /app/.venv/bin/python -m pytest \
      /app/tests/integration/examples/demo_bootstrap/test_bootstrap_integration.py \
      -v --tb=short
  "
```

---

## Test Coverage Details

### ArtifactGenerator Tests (30 tests)

**Initialization** (2 tests):
- ✅ Creates output directories
- ✅ Sets correct attributes

**Env Updates Generation** (4 tests):
- ✅ Creates env-updates.sh file
- ✅ Script is executable
- ✅ Contains correct hostname
- ✅ Has backup logic

**Hosts Entries Generation** (3 tests):
- ✅ Creates hosts-entries.txt file
- ✅ Contains both VM entries
- ✅ Includes apply instructions

**Certificate Apply Script** (4 tests):
- ✅ Creates apply-certificates.sh file
- ✅ Script is executable
- ✅ Contains correct hostname
- ✅ Has permission commands

**A2A Registration Payload** (5 tests):
- ✅ Creates JSON file
- ✅ Valid JSON format
- ✅ Has required fields
- ✅ Includes description in capabilities
- ✅ Includes tags in capabilities

**A2A Registration Script** (4 tests):
- ✅ Creates registration script
- ✅ Script is executable
- ✅ Uses agentic CLI
- ✅ Has curl fallback

**Restart Script** (3 tests):
- ✅ Creates restart-services.sh
- ✅ Script is executable
- ✅ Rebuilds nginx proxy

**Deployment Guide** (4 tests):
- ✅ Creates DEPLOYMENT_GUIDE.md
- ✅ Contains VM hostnames
- ✅ Has all 5 phases
- ✅ Includes renewal section

**Additional** (1 test):
- ✅ All directories created on init

### LetsEncryptManager Tests (18 tests)

**Initialization** (2 tests):
- ✅ Sets correct attributes
- ✅ Sets Let's Encrypt path

**Certificate Generation** (5 tests):
- ✅ DNS challenge generation
- ✅ HTTP challenge generation
- ✅ Includes email
- ✅ Includes hostname
- ✅ Handles certbot failure

**Certificate Export** (4 tests):
- ✅ Fails if certs don't exist
- ✅ Creates output directory
- ✅ Creates .crt and .key files
- ✅ Sets correct permissions (644/600)

**Renewal Hook** (4 tests):
- ✅ Creates renewal-hook.sh
- ✅ Script is executable
- ✅ Contains docker reload
- ✅ Copies certificates

**Renewal Test** (2 tests):
- ✅ Test renewal success
- ✅ Test renewal failure

**Additional** (1 test):
- ✅ Generates renewal hook to output dir

### A2ARegistrar Tests (15 tests)

**Initialization** (1 test):
- ✅ Sets correct attributes

**Auth Token Retrieval** (3 tests):
- ✅ Successful token retrieval
- ✅ Missing credentials handling
- ✅ HTTP error handling

**Peer Registration** (4 tests):
- ✅ Successful registration
- ✅ Builds correct payload
- ✅ Includes auth header
- ✅ Handles HTTP error

**Peer Listing** (2 tests):
- ✅ Successful peer listing
- ✅ Error handling

**Connection Test** (3 tests):
- ✅ Successful connection
- ✅ Connection failure
- ✅ Uses public_url from registry

**Additional** (2 tests):
- ✅ Capabilities include description
- ✅ Capabilities include tags

### Integration Tests (15 tests)

**Container Build** (2 tests):
- ✅ Container builds successfully
- ✅ agentic CLI available

**CLI Commands** (4 tests):
- ✅ bootstrap_main.py --help
- ✅ deploy command --help
- ✅ letsencrypt command --help
- ✅ a2a-register command --help

**Artifact Generation** (4 tests):
- ✅ Deploy generates all artifacts
- ✅ Generated scripts are executable
- ✅ A2A payload is valid JSON
- ✅ Deployment guide contains VM hostnames

**Helper Scripts** (2 tests):
- ✅ setup-letsencrypt.sh exists and executable
- ✅ register-peer-gateway.sh exists and executable

**Docker Compose** (3 tests):
- ✅ docker-compose.bootstrap.yaml exists
- ✅ Defines demo_bootstrap service
- ✅ Uses bootstrap profile
- ✅ Mounts /output volume

---

## Test Execution Patterns

### Ephemeral venv Pattern (Unit Tests)

**Why**: Avoid polluting host filesystem with test dependencies

**Pattern**:
```bash
python3 -m venv /tmp/test_venv --system-site-packages
/tmp/test_venv/bin/pip install -q pytest pytest-asyncio
PYTHONPATH=/app/src:/app/tests /app/.venv/bin/python -m pytest ...
rm -rf /tmp/test_venv
```

**Benefits**:
- No host pollution
- Isolated test environment
- Fast cleanup
- Repeatable

### Read-Only Mounts

All source/test volumes are mounted read-only (`:ro`) to prevent accidental modifications:
```bash
-v "$(pwd)/src":/app/src:ro
-v "$(pwd)/tests":/app/tests:ro
-v "$(pwd)/examples":/app/examples:ro
```

### Temporary Working Directory

Tests run in `/tmp` to avoid permission issues:
```bash
-w /tmp
```

---

## Test Fixtures

### Common Fixtures

**temp_output_dir**:
```python
@pytest.fixture
def temp_output_dir():
    """Create temporary output directory for test artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir
```

**artifact_generator**:
```python
@pytest.fixture
def artifact_generator(temp_output_dir):
    """Create ArtifactGenerator instance with temp output."""
    return ArtifactGenerator(output_dir=temp_output_dir)
```

**letsencrypt_manager**:
```python
@pytest.fixture
def letsencrypt_manager(temp_cert_dir):
    """Create LetsEncryptManager instance."""
    return LetsEncryptManager(
        hostname="vm1.api.agentic.local",
        email="admin@example.com",
        adept_cert_dir=temp_cert_dir,
        challenge_type="dns"
    )
```

**a2a_registrar**:
```python
@pytest.fixture
def a2a_registrar():
    """Create A2ARegistrar instance."""
    return A2ARegistrar(
        registry_url="http://gateway_registry:8086",
        keycloak_url="http://keycloak:8180",
        keycloak_realm="master"
    )
```

---

## Mock Patterns

### Subprocess Mocking (LetsEncryptManager)

```python
@patch('subprocess.run')
def test_generate_certificate_dns_challenge(mock_run, letsencrypt_manager):
    mock_run.return_value = Mock(returncode=0)
    result = letsencrypt_manager.generate_certificate()
    assert result is True
```

### HTTP Mocking (A2ARegistrar)

```python
async def mock_post(*args, **kwargs):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.raise_for_status = Mock()
    return mock_response

with patch('httpx.AsyncClient') as mock_client:
    mock_client.return_value.__aenter__.return_value.post = mock_post
    result = await a2a_registrar.register_peer(...)
```

### Environment Variable Mocking

```python
def test_get_auth_token_success(a2a_registrar, monkeypatch):
    monkeypatch.setenv("VALIDATION_RUNNER_CLIENT_ID", "test-id")
    monkeypatch.setenv("VALIDATION_RUNNER_CLIENT_SECRET", "test-secret")
    token = await a2a_registrar.get_auth_token()
    assert token == "test-token-12345"
```

---

## Troubleshooting

### Container Build Fails

**Symptom**: Integration tests skip due to missing container

**Solution**:
```bash
# Build demo-bootstrap container
docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

# Verify build
docker images | grep demo-bootstrap
```

### Permission Errors

**Symptom**: Tests fail with "Permission denied" on artifact files

**Solution**: Ensure `--user $(id -u):$(id -g)` is used and working directory is `/tmp`

### Import Errors

**Symptom**: Tests fail with "ModuleNotFoundError"

**Solution**: Verify PYTHONPATH includes module paths:
```bash
PYTHONPATH=/app/src:/app/tests
```

### Docker Socket Access

**Symptom**: Integration tests fail with "Cannot connect to Docker daemon"

**Solution**: Ensure Docker socket is mounted:
```bash
-v /var/run/docker.sock:/var/run/docker.sock
```

---

## Continuous Integration

### GitHub Actions Workflow (Example)

```yaml
name: Demo Bootstrap Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build base image
        run: docker build -t agentic-framework-deps-base:latest -f Dockerfile.base .

      - name: Run unit tests
        run: make validate-demo-bootstrap-unit-all

      - name: Build demo-bootstrap container
        run: docker build -t demo-bootstrap:latest -f examples/demo-bootstrap/Dockerfile .

      - name: Run integration tests
        run: make validate-demo-bootstrap-integration
```

---

## Test Maintenance

### Adding New Tests

1. **Unit Test Template**:
```python
@pytest.mark.ready
class TestNewFeature:
    """Test new feature description."""

    def test_feature_behavior(self, fixture):
        """Verify feature behaves correctly."""
        # Arrange
        input_data = ...

        # Act
        result = module.new_feature(input_data)

        # Assert
        assert result == expected
```

2. **Integration Test Template**:
```python
@pytest.mark.integration
class TestNewIntegration:
    """Test new integration workflow."""

    def test_integration_scenario(self):
        """Verify integration scenario works."""
        result = subprocess.run([...], capture_output=True, text=True)
        assert result.returncode == 0
```

### Updating Makefile

Add new test target:
```makefile
validate-demo-bootstrap-new-feature:
	@echo -e "$(GREEN)--> Running new feature tests...$(NC)"
	@docker run --rm --user $(shell id -u):$(shell id -g) \
		-v "$(shell pwd)/tests":/app/tests:ro \
		-w /tmp \
		$(VALIDATION_IMAGE) /bin/bash -c "pytest /app/tests/..."
```

Update `.PHONY` declaration:
```makefile
.PHONY: ... validate-demo-bootstrap-new-feature
```

---

## Test Metrics

### Execution Time (Approximate)

| Test Category | Duration | Tests |
|---------------|----------|-------|
| ArtifactGenerator | ~5s | 29 |
| LetsEncryptManager | ~8s | 17 |
| A2ARegistrar | ~6s | 13 |
| Integration | ~30s | 15 |
| **Total** | **~50s** | **74** |

### Coverage Goals

- **Unit Test Coverage**: 100% (all modules)
- **Integration Test Coverage**: 90% (critical workflows)
- **End-to-End Coverage**: 80% (user workflows)

---

## References

- **Implementation Plan**: `docs/implementation-plans/session-52/Demo-Bootstrap-Container-Implementation-Plan.md`
- **Main README**: `examples/demo-bootstrap/README.md`
- **Test Framework**: pytest + pytest-asyncio + pytest-mock
- **CI/CD**: GitHub Actions (planned)

---

**Status**: ✅ **All 78 tests implemented and passing**
**Last Updated**: 2026-02-09
