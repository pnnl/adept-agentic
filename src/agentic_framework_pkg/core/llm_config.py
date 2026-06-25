"""
YAML-based LLM configuration system for ADEPT.

Loads provider, purpose, and credential configuration from a YAML file
specified by LLM_CONFIG_PATH. Falls back to env var resolution when
LLM_CONFIG_PATH is not set (backward-compatible).

Activation: YAML mode is strictly opt-in — activates ONLY when
  LLM_CONFIG_PATH is explicitly set. There is no default path.
  The file at that path MUST exist (fail-fast if missing).

Precedence when YAML is active:
  llm.yaml purposes > env vars (ignored for model selection)
  llm.yaml role_aliases > hardcoded aliases

Credential resolution within YAML:
  inline value (api_key: "sk-...") wins over env var reference (api_key_env: AZURE_API_KEY)
"""

import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

logger = logging.getLogger(__name__)

LLM_CONFIG_PATH_ENV = "LLM_CONFIG_PATH"


class ProviderType(str, Enum):
    bedrock = "bedrock"
    azure = "azure"
    openai = "openai"
    ollama = "ollama"
    anthropic = "anthropic"
    vertex_ai = "vertex_ai"


class RetryConfig(BaseModel):
    """Retry parameters for LLM calls. Parsed from YAML but not yet wired into LLMAgnosticClient (reserved for future use)."""

    model_config = ConfigDict(extra="forbid")

    max_retries: int = 10
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    backoff_multiplier: float = 2.0


class CredentialsConfig(BaseModel):
    """Dual-mode credentials: inline values or env var references.

    When both inline and env var ref are set for the same field,
    the inline value wins.
    """

    model_config = ConfigDict(extra="forbid")

    # Inline values
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_session_token: Optional[str] = None

    # Env var references (resolved at runtime)
    api_key_env: Optional[str] = None
    api_base_env: Optional[str] = None
    aws_access_key_id_env: Optional[str] = None
    aws_secret_access_key_env: Optional[str] = None
    aws_session_token_env: Optional[str] = None

    def resolve(self) -> Dict[str, str]:
        """Resolve credentials to actual values. Inline wins over env var ref."""
        resolved = {}

        api_key = self.api_key or (
            os.getenv(self.api_key_env, "") if self.api_key_env else None
        )
        if api_key:
            resolved["api_key"] = api_key

        api_base = self.api_base or (
            os.getenv(self.api_base_env, "") if self.api_base_env else None
        )
        if api_base:
            resolved["api_base"] = api_base

        access_key = self.aws_access_key_id or (
            os.getenv(self.aws_access_key_id_env, "")
            if self.aws_access_key_id_env
            else None
        )
        if access_key:
            resolved["aws_access_key_id"] = access_key

        secret_key = self.aws_secret_access_key or (
            os.getenv(self.aws_secret_access_key_env, "")
            if self.aws_secret_access_key_env
            else None
        )
        if secret_key:
            resolved["aws_secret_access_key"] = secret_key

        session_token = self.aws_session_token or (
            os.getenv(self.aws_session_token_env, "")
            if self.aws_session_token_env
            else None
        )
        if session_token:
            resolved["aws_session_token"] = session_token

        return resolved


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aws_region: Optional[str] = None
    api_base: Optional[str] = None
    api_version: Optional[str] = None
    credentials: Optional[CredentialsConfig] = None


class DefaultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderType = ProviderType.bedrock
    model: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    temperature: float = 0.0
    retry: RetryConfig = RetryConfig()


class PurposeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Optional[ProviderType] = None
    model: Optional[str] = None
    description: Optional[str] = None
    temperature: Optional[float] = None
    aws_region: Optional[str] = None
    api_version: Optional[str] = None
    credentials: Optional[CredentialsConfig] = None


class FallbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Optional[ProviderType] = None
    model: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


# Duplicated from LLMAgnosticClient.DEFAULT_MODEL_ENV_VARS to avoid circular
# import (llm_agnostic_layer imports litellm which may not be available in
# unit test environments). Kept in sync by integration tests.
_DEFAULT_MODEL_ENV_VARS = {
    "streamlit": "STREAMLIT_DEFAULT_MODEL",
    "embedding": "EMBEDDING_DEFAULT_MODEL",
    "rag": "RAG_DEFAULT_MODEL",
    "agent_main": "DEFAULT_LLM_MODEL",
    "agent_supervisor": "DEFAULT_LLM_MODEL",
    "agent_planner": "DEFAULT_LLM_MODEL",
    "coding_agent": "CODING_AGENT_DEFAULT_MODEL",
    "session_summary": "DEFAULT_LLM_MODEL",
    "generic": "DEFAULT_LLM_MODEL",
}


class LLMConfig(BaseModel):
    """Root configuration model for ADEPT LLM system.

    Loads from YAML when LLM_CONFIG_PATH is set (strictly opt-in).
    Falls back to env-var-based resolution otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    defaults: DefaultsConfig = DefaultsConfig()
    providers: Dict[str, ProviderConfig] = {}
    purposes: Dict[str, PurposeConfig] = {}
    fallback: Optional[FallbackConfig] = None
    role_aliases: Dict[str, str] = {}
    source: str = "env_vars"

    @model_validator(mode="after")
    def _resolve_inheritance(self) -> "LLMConfig":
        """Purposes inherit provider/model from defaults when not specified."""
        for name, purpose in self.purposes.items():
            if purpose.provider is None:
                purpose.provider = self.defaults.provider
            if purpose.model is None:
                purpose.model = self.defaults.model
            if purpose.temperature is None:
                purpose.temperature = self.defaults.temperature
        return self

    def get_model_for_purpose(self, purpose: str) -> Optional[str]:
        """Return the fully-qualified model string for a purpose.

        Format: "{provider_prefix}/{model}" for non-azure/openai providers,
        or just "{model}" for azure/openai (routed via env vars).
        """
        purpose_cfg = self.purposes.get(purpose)
        if not purpose_cfg:
            if self.fallback:
                return self._format_model(self.fallback.provider, self.fallback.model)
            return self._format_model(self.defaults.provider, self.defaults.model)

        return self._format_model(purpose_cfg.provider, purpose_cfg.model)

    def get_credentials_for_purpose(self, purpose: str) -> Dict[str, Any]:
        """Resolve credentials for a purpose.

        Priority: purpose-level credentials > provider-level credentials.
        Provider is determined by the same resolution chain as get_model_for_purpose():
          purpose config > fallback config > defaults.
        Returns dict suitable for passing to LiteLLM.
        """
        purpose_cfg = self.purposes.get(purpose)
        provider_name = self._resolve_provider_for_purpose(purpose_cfg)

        # Purpose-level credentials take priority
        if purpose_cfg and purpose_cfg.credentials:
            creds = purpose_cfg.credentials.resolve()
            if creds:
                return self._enrich_credentials(creds, provider_name, purpose_cfg)

        # Fall back to provider-level credentials
        provider_cfg = self.providers.get(provider_name)
        if provider_cfg and provider_cfg.credentials:
            creds = provider_cfg.credentials.resolve()
            if creds:
                return self._enrich_credentials(creds, provider_name, purpose_cfg)

        return {}

    def get_provider_config(self, purpose: str) -> Dict[str, Any]:
        """Get merged provider configuration for a purpose.

        Provider is determined by the same resolution chain as get_model_for_purpose():
          purpose config > fallback config > defaults.
        Includes aws_region, api_version, api_base from purpose or provider level.
        """
        purpose_cfg = self.purposes.get(purpose)
        provider_name = self._resolve_provider_for_purpose(purpose_cfg)
        provider_cfg = self.providers.get(provider_name, ProviderConfig())

        result: Dict[str, Any] = {}

        # Provider-level settings (lower priority)
        if provider_cfg.aws_region:
            result["aws_region"] = provider_cfg.aws_region
        if provider_cfg.api_base:
            result["api_base"] = provider_cfg.api_base
        if provider_cfg.api_version:
            result["api_version"] = provider_cfg.api_version

        # Purpose-level overrides (higher priority)
        if purpose_cfg:
            if purpose_cfg.aws_region:
                result["aws_region"] = purpose_cfg.aws_region
            if purpose_cfg.api_version:
                result["api_version"] = purpose_cfg.api_version

        return result

    def _resolve_provider_for_purpose(
        self, purpose_cfg: Optional[PurposeConfig]
    ) -> str:
        """Determine provider name using the same chain as get_model_for_purpose().

        Resolution: purpose config > fallback config > defaults.
        """
        if purpose_cfg and purpose_cfg.provider:
            return purpose_cfg.provider.value
        if self.fallback and self.fallback.provider:
            return self.fallback.provider.value
        return self.defaults.provider.value

    def _format_model(
        self, provider: Optional[ProviderType], model: Optional[str]
    ) -> Optional[str]:
        """Format model string with provider prefix for LiteLLM routing."""
        if not model:
            return None
        if not provider:
            return model

        # These providers need explicit prefix for LiteLLM routing
        prefix_providers = {
            ProviderType.bedrock: "bedrock/",
            ProviderType.ollama: "ollama/",
            ProviderType.anthropic: "anthropic/",
            ProviderType.vertex_ai: "vertex_ai/",
        }

        prefix = prefix_providers.get(provider, "")

        # Don't double-prefix
        if prefix and model.startswith(prefix):
            return model

        # Azure/OpenAI models don't need prefix (routed via env vars)
        if provider in (ProviderType.azure, ProviderType.openai):
            return model

        return f"{prefix}{model}"

    def _enrich_credentials(
        self,
        creds: Dict[str, str],
        provider_name: str,
        purpose_cfg: Optional[PurposeConfig],
    ) -> Dict[str, Any]:
        """Add provider-specific metadata (region, api_version) to credentials."""
        result = dict(creds)
        result["provider"] = provider_name

        provider_cfg = self.providers.get(provider_name, ProviderConfig())

        # Region: purpose > provider > None
        region = None
        if purpose_cfg and purpose_cfg.aws_region:
            region = purpose_cfg.aws_region
        elif provider_cfg.aws_region:
            region = provider_cfg.aws_region
        if region:
            result["aws_region"] = region

        # API version: purpose > provider > None
        api_version = None
        if purpose_cfg and purpose_cfg.api_version:
            api_version = purpose_cfg.api_version
        elif provider_cfg.api_version:
            api_version = provider_cfg.api_version
        if api_version:
            result["api_version"] = api_version

        # API base: provider > None
        if provider_cfg.api_base:
            result["api_base"] = provider_cfg.api_base

        return result

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "LLMConfig":
        """Load LLM configuration from YAML or fall back to env vars.

        Resolution order:
          1. Explicit config_path argument
          2. LLM_CONFIG_PATH env var
          3. Env var fallback (_from_env_vars)

        YAML mode is strictly opt-in: only activates when config_path is
        provided or LLM_CONFIG_PATH is set. Raises FileNotFoundError if the
        specified path does not exist (never silently falls back).
        """
        path = config_path or os.getenv(LLM_CONFIG_PATH_ENV)

        if path:
            source_desc = (
                "config_path argument"
                if config_path
                else f"{LLM_CONFIG_PATH_ENV} env var"
            )
            resolved = Path(path)
            if not resolved.is_absolute():
                resolved = Path.cwd() / resolved
            if resolved.is_file():
                return cls._from_yaml(resolved)
            if config_path:
                guidance = (
                    "Either fix the path or call load() without config_path "
                    "to fall back to env var configuration."
                )
            else:
                guidance = (
                    f"Either create the file or unset {LLM_CONFIG_PATH_ENV} "
                    f"to use env var configuration."
                )
            raise FileNotFoundError(
                f"{source_desc} is set to '{path}' but file does not exist at "
                f"'{resolved}'. {guidance}"
            )

        return cls._from_env_vars()

    @classmethod
    def _from_yaml(cls, path: Path) -> "LLMConfig":
        """Parse YAML file into LLMConfig.

        Raises ValueError if file is empty or not a mapping — opt-in YAML
        mode must never silently fall back to env vars.
        """
        logger.info(f"Loading LLM configuration from YAML: {path}")
        with open(path) as f:
            raw = yaml.safe_load(f)

        if not raw or not isinstance(raw, dict):
            raise ValueError(
                f"YAML file at '{path}' is empty or not a mapping. "
                f"Expected a YAML document with top-level keys like 'defaults', "
                f"'providers', 'purposes'. An explicitly specified config file "
                f"must contain valid configuration (will not silently fall back)."
            )

        known_keys = cls.model_fields.keys()
        unknown = set(raw.keys()) - set(known_keys) - {"source"}
        if unknown:
            raise ValueError(
                f"Unrecognized keys in {path}: {sorted(unknown)}. "
                f"Valid top-level keys: {sorted(known_keys)}. Check for typos."
            )

        # Validate provider keys against ProviderType enum
        if "providers" in raw and isinstance(raw["providers"], dict):
            valid_providers = {e.value for e in ProviderType}
            invalid_providers = set(raw["providers"].keys()) - valid_providers
            if invalid_providers:
                raise ValueError(
                    f"Invalid provider keys in {path}: {sorted(invalid_providers)}. "
                    f"Valid providers: {sorted(valid_providers)}. Check for typos."
                )

        config = cls.model_validate(raw)
        config.source = "yaml"
        return config

    @classmethod
    def _from_env_vars(cls) -> "LLMConfig":
        """Construct config from current env vars (backward-compatible).

        Reproduces exact current behavior: reads DEFAULT_MODEL_ENV_VARS mapping,
        detects provider from model prefix, resolves generic credentials.
        """
        env_var_map = dict(_DEFAULT_MODEL_ENV_VARS)

        purposes = {}
        for purpose_name, env_var in env_var_map.items():
            model = os.getenv(env_var)
            if not model:
                continue

            provider = cls._detect_provider_from_prefix(model)
            # Strip prefix for storage (YAML stores bare model names)
            bare_model = cls._strip_provider_prefix(model)

            purposes[purpose_name] = PurposeConfig(
                provider=provider,
                model=bare_model,
            )

        # Detect default provider/model
        default_model = os.getenv("DEFAULT_LLM_MODEL", "")
        default_provider = cls._detect_provider_from_prefix(default_model)
        default_bare = cls._strip_provider_prefix(default_model)

        # Build provider configs from env vars
        providers: Dict[str, ProviderConfig] = {}

        # Bedrock
        aws_region = os.getenv("AWS_REGION_NAME", "us-west-2")
        providers["bedrock"] = ProviderConfig(
            aws_region=aws_region,
            credentials=CredentialsConfig(
                aws_access_key_id_env="AWS_ACCESS_KEY_ID",
                aws_secret_access_key_env="AWS_SECRET_ACCESS_KEY",
            ),
        )

        # Azure
        azure_key_env = "AZURE_API_KEY"
        azure_base_env = "AZURE_API_BASE"
        azure_version = os.getenv("AZURE_API_VERSION", "2024-12-01-preview")
        if os.getenv(azure_key_env):
            providers["azure"] = ProviderConfig(
                api_version=azure_version,
                credentials=CredentialsConfig(
                    api_key_env=azure_key_env,
                    api_base_env=azure_base_env,
                ),
            )

        # Fallback
        fallback_model = os.getenv("DEFAULT_LLM_MODEL", default_bare)
        fallback_provider = cls._detect_provider_from_prefix(
            os.getenv("DEFAULT_LLM_MODEL", "")
        )

        config = cls(
            defaults=DefaultsConfig(
                provider=default_provider or ProviderType.bedrock,
                model=default_bare or "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                temperature=0.0,
            ),
            providers=providers,
            purposes=purposes,
            fallback=FallbackConfig(
                provider=fallback_provider,
                model=cls._strip_provider_prefix(fallback_model)
                or "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            ),
            role_aliases={},
            source="env_vars",
        )
        return config

    @staticmethod
    def _detect_provider_from_prefix(model: str) -> Optional[ProviderType]:
        """Detect provider type from model name prefix."""
        if not model:
            return None
        prefix_map = {
            "bedrock/": ProviderType.bedrock,
            "ollama/": ProviderType.ollama,
            "anthropic/": ProviderType.anthropic,
            "vertex_ai/": ProviderType.vertex_ai,
            "azure/": ProviderType.azure,
            "openai/": ProviderType.openai,
        }
        for prefix, provider in prefix_map.items():
            if model.startswith(prefix):
                return provider
        # Unprefixed models default to azure/openai routing
        return None

    @staticmethod
    def _strip_provider_prefix(model: str) -> str:
        """Remove provider prefix from model name."""
        if not model:
            return ""
        prefixes = (
            "bedrock/",
            "ollama/",
            "anthropic/",
            "vertex_ai/",
            "azure/",
            "openai/",
        )
        for prefix in prefixes:
            if model.startswith(prefix):
                return model[len(prefix) :]
        return model
