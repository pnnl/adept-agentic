# Langfuse Bootstrap Scripts

This directory contains scripts for bootstrapping Langfuse credentials for the ADEPT framework.

## Overview

The bootstrap process ensures that ADEPT services can send telemetry to Langfuse without manual configuration. The process is:
- **Idempotent**: Safe to run multiple times
- **Automatic**: Can be triggered by services on startup
- **Resilient**: Services continue without observability if bootstrap fails

## Files

- `bootstrap_langfuse_credentials.py` - Main bootstrap script
- `requirements.txt` - Optional dependencies (script works without them)
- `README.md` - This file

## Usage

### Manual Bootstrap

Run directly:
```bash
python scripts/langfuse/bootstrap_langfuse_credentials.py
```

Via Makefile:
```bash
make langfuse-bootstrap
```

### Automatic Bootstrap

The orchestration service checks for credentials on startup and attempts bootstrap if missing:
```python
# In orchestration_service/app.py
if not credentials_exist():
    run_bootstrap()  # Attempt bootstrap
    # Continue regardless of success
```

## How It Works

1. **Check Existing Credentials**: Reads `.env` to check if `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` exist
2. **Generate If Missing**: Creates cryptographically secure API keys
3. **Update Environment**: Atomically updates `.env` file with new credentials
4. **Create Backup**: Saves credentials to `.env.langfuse` for reference

## Environment Variables

### Input Variables

- `ENV_FILE` - Path to .env file (default: `.env`)
- `WAIT_FOR_SERVICES` - Wait for Langfuse to be healthy (default: `false`)
- `INITIALIZE_LANGFUSE` - Initialize Langfuse database (default: `false`)
- `LANGFUSE_HOST` - Langfuse API endpoint (default: `http://langfuse-web:3001`)

### Generated Variables

The script generates and saves:
- `LANGFUSE_PUBLIC_KEY` - Public API key (format: `pk-lf-{32-hex-chars}`)
- `LANGFUSE_SECRET_KEY` - Secret API key (format: `sk-lf-{32-hex-chars}`)
- `LANGFUSE_HOST` - API endpoint for ADEPT services
- `OBSERVABILITY_BACKEND` - Set to `langfuse` if not present

## Security

- Credentials are generated using Python's `secrets` module (cryptographically secure)
- Atomic file updates prevent partial writes
- No credentials are logged (secret keys are truncated in logs)
- Backup file has same permissions as main .env

## Graceful Degradation

If bootstrap fails:
- Services log warnings but continue
- Observability is disabled for that session
- No hard failures or blocked services

## Integration with Docker Compose

The bootstrap is **NOT** a hard dependency. Services start independently:

```yaml
# No depends_on for bootstrap
orchestration_service:
  environment:
    - OBSERVABILITY_BACKEND=${OBSERVABILITY_BACKEND:-langfuse}
  # Service checks for credentials on startup
```

## Integration with Kubernetes

For Kubernetes deployments:
1. Use a Job to run the bootstrap script
2. Store credentials in a Secret
3. Mount the Secret in pods
4. Services check for credentials and handle missing ones gracefully

## Troubleshooting

### Credentials Not Found
- Check `.env` file exists and is readable
- Verify `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are present
- Run `make langfuse-bootstrap` to generate

### Bootstrap Fails
- Check Python 3 is available
- Ensure write permissions for `.env` file
- Review logs for specific errors

### Services Can't Connect to Langfuse
- Verify `LANGFUSE_HOST` is correct
- Check network connectivity between services
- Ensure Langfuse stack is running (`make langfuse-start`)

## Future Enhancements

- Direct PostgreSQL initialization
- API-based project creation
- Credential rotation support
- Integration with external secret managers