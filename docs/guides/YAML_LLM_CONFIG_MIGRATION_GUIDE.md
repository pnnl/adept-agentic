# Migrating from .env to YAML LLM Configuration

**Status**: Production-ready (Session 120, 2026-05-16)
**Issue**: #74
**Related**: #41 (original YAML config implementation), #69 (fallback-chain hardening)

## Overview

ADEPT supports two LLM configuration modes:

| Mode | Activation | Model Selection | Credential Source |
|------|-----------|-----------------|-------------------|
| **Env var mode** (default) | `LLM_CONFIG_PATH` unset | `DEFAULT_LLM_MODEL`, `CODING_AGENT_DEFAULT_MODEL`, etc. | Same env vars |
| **YAML mode** (opt-in) | `LLM_CONFIG_PATH=/app/config/llm.yaml` | `config/llm.yaml` purposes section | Env var _references_ in YAML |

YAML mode is strictly opt-in. When active, env vars like `DEFAULT_LLM_MODEL` are **ignored** for model selection (credentials still resolve via `*_env` references in the YAML).

## Quick Start: Migration in 3 Steps

### Step 1: Generate YAML from your current .env

```bash
# Preview (stdout)
python scripts/config/migrate_env_to_yaml.py --env-file .env --validate

# Write to config/llm.yaml
python scripts/config/migrate_env_to_yaml.py --env-file .env --validate --write
```

The script:
- Reads all model/provider env vars from your `.env`
- Detects provider from model prefix (`bedrock/`, `azure/`, `ollama/`, etc.)
- Infers provider from credentials when no prefix is present
- Generates YAML with env var _references_ (never inline secrets)
- Validates the output through `LLMConfig.load()`

### Step 2: Enable YAML mode

Add to your `.env`:
```bash
# YAML LLM Configuration (opt-in)
LLM_CONFIG_PATH=/app/config/llm.yaml
```

### Step 3: Rebuild services

```bash
make rebuild-orchestrator
# Or for all services:
make rebuild-core
```

### Verify

```bash
docker exec orchestration_service /app/.venv/bin/python -c "
from agentic_framework_pkg.core.llm_config import LLMConfig
config = LLMConfig.load()
print(f'Source: {config.source}')
print(f'Provider: {config.defaults.provider.value}')
print(f'Model: {config.defaults.model}')
print(f'Purposes: {len(config.purposes)}')
"
```

Expected output:
```
Source: yaml
Provider: azure
Model: o4-mini
Purposes: 13
```

## What Changes in YAML Mode

| Aspect | Env Mode | YAML Mode |
|--------|----------|-----------|
| Model selection | `DEFAULT_LLM_MODEL` env var | `purposes.agent_main.model` in YAML |
| Provider routing | Prefix detection (`bedrock/`, `azure/`) | Explicit `provider:` field |
| Credentials | Direct env vars (`AZURE_API_KEY`) | Env var _references_ (`api_key_env: AZURE_API_KEY`) |
| Purpose routing | Hardcoded in `_DEFAULT_MODEL_ENV_VARS` | Declarative in YAML `purposes:` section |
| Role aliases | `model_catalog.yaml` + hardcoded | YAML `role_aliases:` section (highest priority) |
| Fallback | `DEFAULT_LLM_MODEL` | `fallback:` section |
| Unknown purposes | Falls back to default model | Falls through to `fallback:` then `defaults:` |

## What Stays the Same

- **Credential storage**: Still in `.env` (YAML references them, never stores them)
- **LANGCHAIN_LLM_MODEL override**: Still takes precedence for ScientificWorkflowAgent
- **model_catalog.yaml**: Still loaded independently (YAML role_aliases win on conflict)
- **Service architecture**: No changes to Tier 1/2/3 communication
- **API behavior**: Responses API, Assistants API unchanged

## File Layout

```
config/
  llm.yaml.example    # Template (git-tracked, no secrets)
  llm.yaml            # Your deployment config (gitignored, may have credentials)

scripts/config/
  migrate_env_to_yaml.py       # Migration script
  validate_config_parity.py    # Parity validation
```

## Validation Targets

```bash
# Check llm.yaml.example stays in sync with code
make validate-config-parity

# Unit tests for migration scripts (29 tests)
make validate-unit-config-migration

# Integration tests for YAML mode (11 tests)
make validate-integration-yaml-mode

# E2E tests (requires running stack with YAML mode)
make validate-e2e-yaml-mode

# All YAML config tests combined
make validate-yaml-config-all
```

## Reverting to Env Mode

Remove or comment out `LLM_CONFIG_PATH` in `.env`:
```bash
# LLM_CONFIG_PATH=/app/config/llm.yaml
```

Rebuild:
```bash
make rebuild-orchestrator
```

No other changes needed — env var mode resumes automatically.

## Design Decisions

1. **Opt-in only**: YAML mode never activates without explicit `LLM_CONFIG_PATH`
2. **Fail-fast**: If `LLM_CONFIG_PATH` is set but file is missing/empty, startup fails immediately (no silent fallback)
3. **No credentials in YAML**: Only env var references (`*_env` fields) — secrets stay in `.env`
4. **Provider key validation**: Typos in provider names raise `ValueError` at load time
5. **Consistent fallback chain**: `get_model_for_purpose()`, `get_credentials_for_purpose()`, and `get_provider_config()` all resolve provider via the same chain: purpose > fallback > defaults

## Troubleshooting

### "ValueError: YAML file at '...' is empty or not a mapping"

The YAML file exists but is empty or contains only comments. Regenerate:
```bash
python scripts/config/migrate_env_to_yaml.py --env-file .env --write
```

### "ValueError: Invalid provider keys in ..."

A typo in the `providers:` section. Valid values: `bedrock`, `azure`, `openai`, `ollama`, `anthropic`, `vertex_ai`.

### "FileNotFoundError: YAML config file not found"

`LLM_CONFIG_PATH` points to a file that doesn't exist in the container. Check the volume mount:
```bash
docker exec orchestration_service ls -la /app/config/llm.yaml
```

### Model not routing correctly

Check which model resolves for a purpose:
```bash
docker exec orchestration_service /app/.venv/bin/python -c "
from agentic_framework_pkg.core.llm_config import LLMConfig
config = LLMConfig.load()
for purpose in ['agent_main', 'coding_agent', 'rag', 'embedding']:
    print(f'{purpose}: {config.get_model_for_purpose(purpose)}')
"
```
