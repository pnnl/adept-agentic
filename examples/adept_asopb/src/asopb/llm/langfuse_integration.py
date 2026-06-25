"""
Langfuse integration for ASOPB LLM evaluators.

Configures LiteLLM's native Langfuse callback so that all LLM calls made during
domain evaluation are automatically traced. Each trace captures:
- Model, tokens, latency (via LiteLLM callback)
- Domain ID, control ID, evaluation tier (via metadata passthrough)
- Session grouping by evaluation run ID

Activation:
    Set ASOPB_LANGFUSE_ENABLED=true plus LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.
    When disabled, this module is a no-op.

Credential sources (checked in order):
    1. Environment variables: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
    2. Credential files: .env-keycloak-credentials-dir/LANGFUSE_CLIENT_ID and _SECRET
"""

import os
import uuid
from typing import Optional

from asopb.config import LangfuseConfig
from asopb.logging import get_logger

logger = get_logger(__name__)

_session_id: Optional[str] = None


def get_session_id() -> str:
    """Return or create a stable session ID for this evaluation run."""
    global _session_id
    if _session_id is None:
        _session_id = f"asopb-eval-{uuid.uuid4().hex[:12]}"
    return _session_id


def reset_session_id() -> str:
    """Reset session ID (call at start of new evaluation run)."""
    global _session_id
    _session_id = f"asopb-eval-{uuid.uuid4().hex[:12]}"
    return _session_id


def _resolve_credentials(config: LangfuseConfig) -> tuple[Optional[str], Optional[str]]:
    """Resolve Langfuse credentials from config or credential files."""
    public_key = config.public_key
    secret_key = config.secret_key

    if public_key and secret_key:
        return public_key, secret_key

    cred_dirs = [
        ".env-keycloak-credentials-dir",
        "deployment/local/docker-compose/.env-keycloak-credentials-dir",
    ]
    for cred_dir in cred_dirs:
        id_path = os.path.join(cred_dir, "LANGFUSE_CLIENT_ID")
        secret_path = os.path.join(cred_dir, "LANGFUSE_CLIENT_SECRET")
        if os.path.isfile(id_path) and os.path.isfile(secret_path):
            with open(id_path) as f:
                public_key = f.read().strip()
            with open(secret_path) as f:
                secret_key = f.read().strip()
            if public_key and secret_key:
                logger.info(f"Langfuse credentials loaded from {cred_dir}/")
                return public_key, secret_key

    return public_key, secret_key


def configure_langfuse(config: LangfuseConfig) -> bool:
    """Configure LiteLLM's native Langfuse callback.

    Returns True if Langfuse was successfully enabled, False otherwise.
    Never raises — failures are logged and telemetry is silently disabled.
    """
    if not config.enabled:
        logger.debug("Langfuse disabled (ASOPB_LANGFUSE_ENABLED != true)")
        return False

    public_key, secret_key = _resolve_credentials(config)
    if not public_key or not secret_key:
        logger.warning(
            "Langfuse enabled but credentials not found. "
            "Set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY or provide credential files."
        )
        return False

    try:
        import litellm

        os.environ["LANGFUSE_PUBLIC_KEY"] = public_key
        os.environ["LANGFUSE_SECRET_KEY"] = secret_key
        if config.host:
            os.environ["LANGFUSE_HOST"] = config.host

        if "langfuse" not in litellm.success_callback:
            litellm.success_callback.append("langfuse")
        if "langfuse" not in litellm.failure_callback:
            litellm.failure_callback.append("langfuse")

        logger.info(
            f"Langfuse instrumentation active "
            f"(host={config.host}, session={get_session_id()})"
        )
        return True

    except ImportError:
        logger.warning("langfuse package not installed — pip install langfuse")
        return False
    except Exception as e:
        logger.warning(f"Langfuse configuration failed (non-fatal): {e}")
        return False


def make_trace_metadata(
    domain_id: str,
    control_id: str = "",
    tier: str = "",
    phase: str = "",
) -> dict:
    """Build metadata dict for passing through litellm to Langfuse.

    LiteLLM forwards the `metadata` kwarg to Langfuse as trace metadata,
    enabling filtering and grouping in the Langfuse UI.
    """
    meta = {
        "session_id": get_session_id(),
        "asopb_domain": domain_id,
        "asopb_phase": phase or "evaluate",
    }
    if control_id:
        meta["asopb_control"] = control_id
    if tier:
        meta["asopb_tier"] = tier
    return meta
