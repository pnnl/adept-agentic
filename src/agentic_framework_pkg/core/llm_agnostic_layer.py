import litellm
import os
import asyncio
from typing import List, Dict, Any, AsyncGenerator, Optional, Union, Tuple
import base64 # For NVIDIA image processing
import yaml
import openai # For NVIDIA vision API
from openai import (
    APIError as OpenAI_APIError,
    AuthenticationError as OpenAI_AuthenticationError,
    RateLimitError as OpenAI_RateLimitError,
    BadRequestError as OpenAI_BadRequestError,
    NotFoundError as OpenAI_NotFoundError,
    APIConnectionError as OpenAI_APIConnectionError,
    APITimeoutError as OpenAI_APITimeoutError)
from langchain_core.language_models.chat_models import BaseChatModel
from dotenv import load_dotenv # Import load_dotenv

# Use the centralized logger from logger_config.py
from ..logger_config import get_logger
from .observability_factory import ObservabilityFactory

logger = get_logger(__name__)
litellm.set_verbose = os.getenv("LITELLM_VERBOSE", "False").lower() == "true"

# Turn on LiteLLM's debug mode if the environment variable is set
litellm._turn_on_debug()

# NVIDIA Configuration Constants (using generic names for client setup)
NVIDIA_API_KEY_ENV_VAR = "NVIDIA_API_KEY" # Expects a general NVIDIA API key
NVIDIA_BASE_URL_ENV_VAR = "NVIDIA_API_BASE_URL"
NVIDIA_MULTI_MODAL_MODEL_ENV_VAR = "NVIDIA_MULTI_MODAL_MODEL_NAME" # Default vision model
DEFAULT_NVIDIA_VISION_MODEL = "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"

# Dictionary to specify parameters that should be omitted for certain model_name values
# when calling Langchain constructors. This helps prevent API errors for unsupported params.
# The key is the model_name (e.g., Azure deployment name, or the value of LANGCHAIN_LLM_MODEL),
# value is a list of param names (e.g., ["temperature"]).
MODEL_SPECIFIC_PARAMS_TO_OMIT: Dict[str, List[str]] = {
    # Example: "my-azure-deployment-name": ["temperature"],
    #"o3-mini": ["temperature", "top_p", "frequency_penalty", "presence_penalty"],
}

# --- Load environment variables from .env file at the very beginning ---
# Get the absolute path of the current script (langchain_agent.py)
current_script_path = os.path.abspath(__file__)

# Get the directory containing the current script
current_dir = os.path.dirname(current_script_path)
# should be src/agentic_framework_pkg/core

# Navigate up to the 'src' directory
src_dir = os.path.join(current_dir, '..', '..', '..')
# This assumes your structure is:
# agentic-framework/
# ├── .env
# ├── src/
# │   └── agentic_framework_pkg/
# │       └── core/
# │           └── llm_agnostic_layer.py
# So, from llm_agnostic_layer.py:
# .. (core)
# .. (agentic_framework_pkg)
# .. (src)
# This brings you to 'agentic-framework/'

# Construct the full path to the .env file
dotenv_path = os.path.abspath(os.path.join(src_dir, '.env'))
if not os.path.exists(dotenv_path):
    logger.warning(f".env file not found at {dotenv_path}. Make sure it exists in the root of the agentic-framework directory.")

# Load the .env file
load_dotenv(dotenv_path=dotenv_path)

# --- End of environment loading ---


def _resolve_catalog_path() -> str:
    """Resolve MODEL_CATALOG_PATH, falling back to package-relative lookup."""
    catalog_path = os.getenv("MODEL_CATALOG_PATH", "config/model_catalog.yaml")
    if os.path.isabs(catalog_path) or os.path.exists(catalog_path):
        return catalog_path
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(os.path.dirname(pkg_root))
    candidate = os.path.join(repo_root, catalog_path)
    return candidate if os.path.exists(candidate) else catalog_path


def _load_model_catalog_purposes() -> Dict[str, str]:
    """Load purpose-to-env-var mappings from the YAML model catalog."""
    catalog_path = _resolve_catalog_path()
    if not os.path.exists(catalog_path):
        return {}
    try:
        with open(catalog_path) as f:
            catalog = yaml.safe_load(f) or {}
        purposes = {}
        for purpose, config in catalog.get("purposes", {}).items():
            env_var = config.get("env_var")
            if env_var:
                purposes[purpose] = env_var
        if purposes:
            logger.info(f"Model catalog loaded {len(purposes)} purposes from {catalog_path}")
        return purposes
    except Exception as e:
        logger.warning(f"Failed to load model catalog from {catalog_path}: {e}")
        return {}


class LLMServiceError(Exception):
    """Custom exception for LLM service errors."""
    pass

class LLMAgnosticClient:
    """
    A client for interacting with various LLMs in an agnostic manner using LiteLLM.
    """

    # Retry configuration for rate limiting and transient errors
    MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "10"))
    INITIAL_RETRY_DELAY = float(os.getenv("LLM_INITIAL_RETRY_DELAY", "1.0"))  # seconds
    MAX_RETRY_DELAY = float(os.getenv("LLM_MAX_RETRY_DELAY", "60.0"))  # seconds
    BACKOFF_MULTIPLIER = float(os.getenv("LLM_BACKOFF_MULTIPLIER", "2.0"))

    OPENAI_COMPLETION_PARAMS = {
        "temperature", "max_tokens", "max_completion_tokens", "top_p", "frequency_penalty",
        "presence_penalty", "stop", "tools", "tool_choice",
        "response_format", "seed", "logprobs", "top_logprobs", "user"
    }
    OPENAI_EMBEDDING_PARAMS = {"dimensions", "encoding_format", "user"}

    # Internal parameters used for tracking/observability, not passed to LLM API
    INTERNAL_PARAMS = {"thread_id", "session_context", "session_id", "mcp_session_id",
                       "multi_agent_session_id", "gateway_session_id"}

    AZURE_DEPLOYMENT_URL_PART = "/openai/deployments/"

    # Model name prefixes that indicate a non-Azure/non-OpenAI provider.
    # When a model name starts with one of these, it must be routed through
    # ChatLiteLLM (LangChain path) or LiteLLM native (async path) — NOT
    # through AzureChatOpenAI or ChatOpenAI, even if generic Azure/OpenAI
    # env vars are present. See: SESSION_60_LLM_PURPOSE_ROUTING_AZURE_FIRST_PRIORITY_BUG.md
    NON_AZURE_OPENAI_PREFIXES = (
        "bedrock/",
        "ollama/",
        "anthropic/",
        "cohere/",
        "replicate/",
        "huggingface/",
        "sagemaker/",
        "vertex_ai/",
    )

    DEFAULT_MODEL_ENV_VARS = {
        "streamlit": "STREAMLIT_DEFAULT_MODEL",
        "embedding": "EMBEDDING_DEFAULT_MODEL",
        "rag": "RAG_DEFAULT_MODEL",
        "agent_main": "DEFAULT_LLM_MODEL",  # Main langchain agent model
        "agent_supervisor": "DEFAULT_LLM_MODEL",  # Multi-agent supervisor model
        "agent_planner": "DEFAULT_LLM_MODEL",  # Multi-agent planner model
        "coding_agent": "CODING_AGENT_DEFAULT_MODEL",  # Coding agent LLM purpose
        "session_summary": "DEFAULT_LLM_MODEL",  # Session summary generation (Streamlit UI)
        "generic": "DEFAULT_LLM_MODEL",  # A general fallback, same as agent_main
    }

    def __init__(self, config=None):
        from .llm_config import LLMConfig
        self.config = config or LLMConfig.load()

        self._model_env_vars = dict(self.DEFAULT_MODEL_ENV_VARS)
        catalog_purposes = _load_model_catalog_purposes()
        for purpose, env_var in catalog_purposes.items():
            if purpose not in self._model_env_vars:
                self._model_env_vars[purpose] = env_var

        if self.config.source == "yaml":
            self.default_models = {
                purpose: self.config.get_model_for_purpose(purpose)
                for purpose in self.config.purposes
            }
            if "generic" not in self.default_models:
                self.default_models["generic"] = self.config.get_model_for_purpose("generic")
            logger.info(f"[LLM_CONFIG] YAML mode active — {len(self.config.purposes)} purposes loaded from config")
        else:
            self.default_models = {
                purpose: os.getenv(env_var_name)
                for purpose, env_var_name in self._model_env_vars.items()
            }
            logger.info(f"Default models initialized from {dotenv_path}: {self.default_models}")

        # Log the provider routing that each purpose will take at startup
        for purpose, model in self.default_models.items():
            if model:
                has_prefix = any(model.startswith(p) for p in self.NON_AZURE_OPENAI_PREFIXES)
                provider = "litellm_prefix" if has_prefix else "azure_or_openai_env"
                logger.info(
                    f"[LLM_ROUTING] Startup: purpose={purpose}, model={model}, "
                    f"expected_provider={provider}"
                )
        # NVIDIA Client Initialization
        self._nvidia_api_key = os.getenv(NVIDIA_API_KEY_ENV_VAR)
        self._nvidia_base_url = os.getenv(NVIDIA_BASE_URL_ENV_VAR, "https://integrate.api.nvidia.com/v1")
        self._nvidia_default_vision_model = os.getenv(NVIDIA_MULTI_MODAL_MODEL_ENV_VAR, DEFAULT_NVIDIA_VISION_MODEL)
        self.is_nvidia_client_available = bool(self._nvidia_api_key)
        if self.is_nvidia_client_available:
            logger.info(f"NVIDIA API key is configured. Vision model '{self._nvidia_default_vision_model}' is available.")
        else:
            logger.info(f"'{NVIDIA_API_KEY_ENV_VAR}' not set. NVIDIA multi-modal capabilities will be unavailable.")

    def _extract_thread_id_from_kwargs(self, kwargs: Dict[str, Any]) -> str:
        """Extract thread_id from kwargs if available (LangGraph context).

        Phase 4: Helper method to extract thread_id for token tracking correlation.
        """
        # Check for thread_id in various possible locations
        if "thread_id" in kwargs:
            return kwargs["thread_id"]
        if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
            if "thread_id" in kwargs["metadata"]:
                return kwargs["metadata"]["thread_id"]
        if "extra_body" in kwargs and isinstance(kwargs["extra_body"], dict):
            if "thread_id" in kwargs["extra_body"]:
                return kwargs["extra_body"]["thread_id"]
        return "unknown"

    def _extract_session_context_from_kwargs(self, kwargs: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
        """Extract session_context from kwargs for multi-tier session tracking.

        Phase 4: Helper method to extract complete session hierarchy (all 4 tiers).

        Returns:
            Dictionary with session context or None if not available:
            - session_id (Tier 1)
            - mcp_session_id (Tier 2)
            - multi_agent_session_id (Tier 3)
            - gateway_session_id (Tier 4)
            - user_id
            - username
            - interaction_type
        """
        # Check for session_context in various possible locations
        if "session_context" in kwargs:
            return kwargs["session_context"]
        if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
            if "session_context" in kwargs["metadata"]:
                return kwargs["metadata"]["session_context"]
        if "extra_body" in kwargs and isinstance(kwargs["extra_body"], dict):
            if "session_context" in kwargs["extra_body"]:
                return kwargs["extra_body"]["session_context"]
        return None

    def _parse_azure_root_endpoint(self, api_base: str) -> str:
        """Extracts the root Azure endpoint from a potentially deployment-specific URL."""
        if self.AZURE_DEPLOYMENT_URL_PART in api_base:
            return api_base.split(self.AZURE_DEPLOYMENT_URL_PART)[0]
        return api_base # Assume it's already the root endpoint

    async def _call_litellm(
        self,
        method_name: str,
        model: str,
        llm_purpose: str,
        **kwargs: Any
    ) -> Any:
        """
        Private helper to make calls to LiteLLM, centralizing credential and endpoint logic.
        """
        # Pop explicit credentials from kwargs first
        # These will take precedence if provided by the caller directly.
        explicit_api_key = kwargs.pop("api_key", None)
        explicit_api_base = kwargs.pop("api_base", None)
        explicit_api_version = kwargs.pop("api_version", None) # For Azure

        # Helper to get env vars: tries PURPOSE_SPECIFIC_VAR, then GENERIC_VAR
        def get_env_config(base_var_name: str, purpose: str) -> str | None:
            val = os.getenv(f"{purpose.upper()}_{base_var_name}")
            if val:
                return val
            return os.getenv(base_var_name)

        # Fetch purpose-aware environment variables
        azure_env_api_key = get_env_config("AZURE_API_KEY", llm_purpose)
        azure_env_api_base = get_env_config("AZURE_API_BASE", llm_purpose) # Should be like https://YOUR_RESOURCE_NAME.openai.azure.com/
        azure_env_api_version = get_env_config("AZURE_API_VERSION", llm_purpose)

        openai_env_api_key = get_env_config("OPENAI_API_KEY", llm_purpose)
        # openai_env_api_base = get_env_config("OPENAI_API_BASE", llm_purpose) # If needed for OpenAI proxies

        ollama_env_api_base = get_env_config("OLLAMA_API_BASE", llm_purpose)

        # AWS Bedrock environment variable handling
        aws_access_key_id = get_env_config("AWS_ACCESS_KEY_ID", llm_purpose)
        aws_secret_access_key = get_env_config("AWS_SECRET_ACCESS_KEY", llm_purpose)
        aws_region_name = get_env_config("AWS_REGION_NAME", llm_purpose)

        # Determine final credentials and endpoint
        final_api_key = explicit_api_key
        final_api_base = explicit_api_base
        final_api_version = explicit_api_version

        config_source_log = f"explicit_kwargs (purpose: {llm_purpose})" # Base assumption

        # ──────────────────────────────────────────────────────────
        # Model-prefix-aware provider detection (Session 60 fix)
        # If the model name explicitly indicates a non-Azure/non-OpenAI provider,
        # skip Azure/OpenAI env var priority and let LiteLLM handle routing natively.
        # This prevents bedrock/ models from being misrouted through Azure when
        # generic AZURE_API_* env vars are set for other purposes (e.g., agent_main).
        # ──────────────────────────────────────────────────────────
        model_has_provider_prefix = any(
            model.startswith(prefix) for prefix in self.NON_AZURE_OPENAI_PREFIXES
        )

        if model_has_provider_prefix:
            logger.info(
                f"[LLM_ROUTING] Model '{model}' has provider prefix — "
                f"skipping Azure/OpenAI env var priority for purpose '{llm_purpose}'"
            )
            config_source_log = f"model_prefix (purpose: {llm_purpose})"
            # Don't set final_api_key/base/version from Azure env vars.
            # LiteLLM handles provider-native credential resolution for prefixed models.

        elif azure_env_api_key and azure_env_api_base and azure_env_api_version:
            logger.debug(f"Using Azure environment variables for purpose '{llm_purpose}': api_key, api_base, api_version.")
            all_explicit_were_none_for_azure = (explicit_api_key is None and explicit_api_base is None and explicit_api_version is None)
            if final_api_key is None:
                final_api_key = azure_env_api_key
            if final_api_base is None:
                final_api_base = azure_env_api_base
            if final_api_version is None:
                final_api_version = azure_env_api_version
            if all_explicit_were_none_for_azure:
                config_source_log = f"azure_env (purpose: {llm_purpose})"

        elif openai_env_api_key and final_api_key is None and final_api_base is None:
            logger.debug(f"Using OpenAI environment variables for purpose '{llm_purpose}': api_key.")
            final_api_key = openai_env_api_key
            config_source_log = f"openai_env (purpose: {llm_purpose})"

        # Handle Ollama if model indicates it and no other base is set
        if model.startswith("ollama/") and final_api_base is None:
            logger.debug(f"Using Ollama environment variables for purpose '{llm_purpose}': api_base.")
            final_api_base = ollama_env_api_base or "http://localhost:11434"
            if config_source_log == f"explicit_kwargs (purpose: {llm_purpose})" and explicit_api_base is None and \
               not (azure_env_api_key and azure_env_api_base and azure_env_api_version and explicit_api_key is None and explicit_api_base is None and explicit_api_version is None) and \
               not (openai_env_api_key and explicit_api_key is None and explicit_api_base is None):
                 config_source_log = f"ollama_default (purpose: {llm_purpose})"

        # Construct parameters for LiteLLM call (unified path for all providers)

        # Azure provider detection: only true for non-prefixed models routed via Azure env vars
        is_azure_provider = (not model_has_provider_prefix and
                             (config_source_log.startswith("azure_env") or
                              (final_api_base and "azure" in final_api_base.lower())))

        # Ensure Azure models have correct prefix for LiteLLM routing
        if is_azure_provider and not model.startswith("ollama/"):
            litellm_model = f"azure/{model}" if not model.startswith("azure/") else model
            logger.debug(f"Using LiteLLM for Azure provider with model '{litellm_model}' (purpose: {llm_purpose}, config source: {config_source_log})")
        else:
            litellm_model = model
            logger.debug(f"Using LiteLLM for purpose '{llm_purpose}' with model '{litellm_model}' (config source: {config_source_log})")

        # Single unified path through LiteLLM for all providers
        litellm_params = {
            "model": litellm_model,
            "api_key": final_api_key,
            "api_base": final_api_base,
        }

        # Add api_version for Azure OpenAI
        if final_api_version and is_azure_provider:
            if not (final_api_base and "api-version=" in final_api_base.lower()):
                litellm_params["api_version"] = final_api_version
            else:
                logger.debug(f"api-version found in api_base ('{final_api_base}'), not adding separate api_version from env var '{final_api_version}'.")

        # Filter out internal tracking parameters before passing to LiteLLM
        # Internal params (thread_id, session_context, etc.) are used for observability,
        # not for LLM API calls - they cause errors with some providers (e.g., Azure o4-mini)
        filtered_kwargs = {k: v for k, v in kwargs.items() if k not in self.INTERNAL_PARAMS}
        litellm_params.update(filtered_kwargs)

        # Pass AWS credentials for Bedrock models.
        # LiteLLM's Bedrock auth has two paths (base_aws_llm.py):
        #   1. Bearer token: If AWS_BEARER_TOKEN_BEDROCK env var is set, LiteLLM
        #      reads it automatically and uses Authorization: Bearer {token} header.
        #   2. SigV4/IAM: If no bearer token, uses aws_access_key_id + aws_secret_access_key
        #      for SigV4 signing (from params → env → boto3 credential chain).
        # We pass all resolved credentials explicitly for defense-in-depth and to
        # support per-purpose credential isolation (e.g., CODING_AGENT_AWS_ACCESS_KEY_ID).
        if model.startswith("bedrock/"):
            if aws_region_name:
                litellm_params["aws_region_name"] = aws_region_name
            if aws_access_key_id:
                litellm_params["aws_access_key_id"] = aws_access_key_id
            if aws_secret_access_key:
                litellm_params["aws_secret_access_key"] = aws_secret_access_key
            logger.debug(
                f"Using AWS Bedrock for model '{model}' in region {aws_region_name}, "
                f"bearer_token_env={'SET' if os.getenv('AWS_BEARER_TOKEN_BEDROCK') else 'UNSET'}, "
                f"iam_creds={'explicit' if aws_access_key_id else 'env_fallback'}"
            )

        log_params = {k: v for k, v in litellm_params.items()
                      if k not in ("api_key", "aws_secret_access_key", "aws_access_key_id")}
        provider_label = "bedrock" if model.startswith("bedrock/") else \
                         "ollama" if model.startswith("ollama/") else \
                         "azure" if is_azure_provider else \
                         "openai" if config_source_log.startswith("openai_env") else "litellm"
        logger.info(
            f"[LLM_ROUTING] Resolution: purpose={llm_purpose}, model={model}, "
            f"litellm_model={litellm_model}, provider={provider_label}, "
            f"config_source={config_source_log}, prefix_detected={model_has_provider_prefix}"
        )
        logger.debug(f"LiteLLM call params (key excluded): {log_params}")

        # Implement exponential backoff retry for rate limiting (HTTP 429) and transient errors
        retry_count = 0
        last_exception = None

        while retry_count <= self.MAX_RETRIES:
            try:
                if method_name == "acompletion":
                    # Pass all relevant kwargs (including messages, stream) via litellm_params
                    response = await litellm.acompletion(**litellm_params)

                    # Phase 4: Track token usage for cost analysis
                    if response and hasattr(response, 'usage') and response.usage:
                        usage = response.usage
                        thread_id = self._extract_thread_id_from_kwargs(kwargs)
                        session_context = self._extract_session_context_from_kwargs(kwargs)

                        # Backward-compatible structured logging
                        logger.info(
                            f"[COST_TRACKING] "
                            f"Purpose={llm_purpose}, "
                            f"Model={model}, "
                            f"Input={usage.prompt_tokens}, "
                            f"Output={usage.completion_tokens}, "
                            f"Total={usage.total_tokens}, "
                            f"Method={method_name}"
                        )

                        # Phase 4: Send token usage to observability backend (non-blocking, error-safe)
                        try:
                            obs_factory = ObservabilityFactory()
                            await obs_factory.track_token_usage(
                                thread_id=thread_id,
                                model=model,
                                input_tokens=usage.prompt_tokens,
                                output_tokens=usage.completion_tokens,
                                total_tokens=usage.total_tokens,
                                metadata={
                                    "purpose": llm_purpose,
                                    "method": method_name,
                                    "config_source": config_source_log
                                },
                                session_context=session_context
                            )
                            logger.debug(
                                f"[TOKEN_TRACKING] Tracked token usage: {usage.total_tokens} "
                                f"tokens for model {model} (thread_id: {thread_id})"
                            )
                        except Exception as e:
                            # Don't fail LLM call if observability tracking fails
                            logger.warning(f"[TOKEN_TRACKING] Failed to track token usage: {e}")
                    else:
                        logger.debug(f"No usage data available for model {model}")

                    return response
                elif method_name == "aembedding":
                    # LiteLLM's aembedding response needs to be parsed
                    embedding_response = await litellm.aembedding(**litellm_params)

                    # Phase 4: Track token usage for embeddings (if available)
                    if embedding_response and hasattr(embedding_response, 'usage') and embedding_response.usage:
                        usage = embedding_response.usage
                        thread_id = self._extract_thread_id_from_kwargs(kwargs)
                        session_context = self._extract_session_context_from_kwargs(kwargs)

                        # Backward-compatible structured logging
                        logger.info(
                            f"[COST_TRACKING] "
                            f"Purpose={llm_purpose}, "
                            f"Model={model}, "
                            f"Input={usage.prompt_tokens}, "
                            f"Total={usage.total_tokens}, "
                            f"Method={method_name}"
                        )

                        # Phase 4: Send token usage to observability backend (non-blocking, error-safe)
                        try:
                            obs_factory = ObservabilityFactory()
                            await obs_factory.track_token_usage(
                                thread_id=thread_id,
                                model=model,
                                input_tokens=usage.prompt_tokens,
                                output_tokens=0,  # Embeddings don't have output tokens
                                total_tokens=usage.total_tokens,
                                metadata={
                                    "purpose": llm_purpose,
                                    "method": method_name,
                                    "config_source": config_source_log,
                                    "input_text_count": len(kwargs.get("input", []))
                                },
                                session_context=session_context
                            )
                            logger.debug(
                                f"[TOKEN_TRACKING] Tracked embedding token usage: {usage.total_tokens} "
                                f"tokens for model {model} (thread_id: {thread_id})"
                            )
                        except Exception as e:
                            # Don't fail embedding call if observability tracking fails
                            logger.warning(f"[TOKEN_TRACKING] Failed to track embedding token usage: {e}")

                    return [item['embedding'] for item in embedding_response.data]
                else:
                    raise ValueError(f"Unsupported LiteLLM method: {method_name}")

            except litellm.exceptions.AuthenticationError as e:
                # Authentication errors should not be retried
                logger.error(f"LiteLLM AuthenticationError for model {model} (purpose: {llm_purpose}, api_base: {final_api_base}, source: {config_source_log}): {e}", exc_info=True)
                raise LLMServiceError(f"Authentication error for model {model} (purpose: {llm_purpose}): {e}") from e

            except litellm.exceptions.RateLimitError as e:
                # Rate limit errors - implement exponential backoff
                last_exception = e
                if retry_count < self.MAX_RETRIES:
                    # Calculate exponential backoff delay
                    delay = min(
                        self.INITIAL_RETRY_DELAY * (self.BACKOFF_MULTIPLIER ** retry_count),
                        self.MAX_RETRY_DELAY
                    )
                    logger.warning(
                        f"Rate limit error for model {model} (purpose: {llm_purpose}). "
                        f"Retry {retry_count + 1}/{self.MAX_RETRIES} after {delay:.1f}s delay. "
                        f"Error: {e}"
                    )
                    await asyncio.sleep(delay)
                    retry_count += 1
                    continue  # Retry the request
                else:
                    # Max retries exceeded
                    logger.error(
                        f"Max retries ({self.MAX_RETRIES}) exceeded for rate limit error on model {model} "
                        f"(purpose: {llm_purpose}, api_base: {final_api_base}): {e}",
                        exc_info=True
                    )
                    raise LLMServiceError(
                        f"Rate limit error for model {model} (purpose: {llm_purpose}) after {self.MAX_RETRIES} retries: {e}"
                    ) from e

            except litellm.exceptions.APIError as e:
                # Other API errors - log and raise without retry
                logger.error(f"LiteLLM API error for model {model} (purpose: {llm_purpose}, api_base: {final_api_base}, source: {config_source_log}): {e}", exc_info=True)
                raise LLMServiceError(f"LLM API error for model {model} (purpose: {llm_purpose}): {e}") from e

            except Exception as e:
                # Unexpected errors - log and raise
                logger.error(f"Unexpected error during LiteLLM call for model {model} (purpose: {llm_purpose}, api_base: {final_api_base}, source: {config_source_log}): {e}", exc_info=True)
                raise LLMServiceError(f"Unexpected error for model {model} (purpose: {llm_purpose}): {e}") from e

        # This should not be reached, but handle it just in case
        if last_exception:
            raise LLMServiceError(
                f"Failed after {self.MAX_RETRIES} retries for model {model} (purpose: {llm_purpose}): {last_exception}"
            ) from last_exception

    async def agenerate_response(
        self,
        messages: List[Dict[str, str]],
        llm_purpose: str, # e.g., "streamlit", "rag"
        model: str | None = None,
        stream: bool = False,
        **kwargs: Any
    ) -> Any | AsyncGenerator[Any, None]:
        """
        Generates a response from the specified LLM.

        Args:
            messages (list): A list of message objects, typically {"role": "user/assistant/system", "content": "..."}.
            llm_purpose (str): The purpose of the LLM call (e.g., "streamlit", "rag"). Used for config and default model selection.
            model (str, optional): The model identifier. If None, uses default for llm_purpose.
            stream (bool): Whether to stream the response. Defaults to False.
            **kwargs: Additional parameters to pass to the LiteLLM completion call (e.g., temperature, max_tokens).

        Returns:
            The response from the LLM. If streaming, this will be an async iterator.
        Raises:
            LLMServiceError: If an API error occurs.
            ValueError: If no model is specified and no default model can be found.
        """
        final_model = model
        if final_model is None:
            final_model = self.default_models.get(llm_purpose) or self.default_models.get("generic")
        if final_model is None:
            raise ValueError(f"No model specified and no default model found for purpose '{llm_purpose}' or generic default.")

        return await self._call_litellm(
            "acompletion",
            model=final_model,
            llm_purpose=llm_purpose,
            messages=messages,
            stream=stream,
            **kwargs
        )

    async def acreate_embedding(self, input_texts: List[str], model: str | None = None, **kwargs: Any) -> List[List[float]]:
        """
        Generates embeddings for a list of input texts using LiteLLM.
        """
        llm_purpose = "embedding"
        final_model = model
        if final_model is None:
            final_model = self.default_models.get(llm_purpose) or self.default_models.get("generic")
        if final_model is None:
            raise ValueError(f"No model specified and no default model found for purpose '{llm_purpose}' or generic default.")

        embedding_response = await self._call_litellm(
            "aembedding",
            model=final_model,
            llm_purpose=llm_purpose,
            input=input_texts,
            **kwargs
        )
        return embedding_response # Already in List[List[float]] format from dispatcher

    def _initialize_nvidia_client(self):
        """Initializes the NVIDIA AsyncOpenAI client if API key is available."""
        if self._nvidia_api_key:
            try:
                self._nvidia_async_client = openai.AsyncOpenAI(
                    base_url=self._nvidia_base_url,
                    api_key=self._nvidia_api_key,
                )
                self.is_nvidia_client_available = True
                logger.info(f"NVIDIA AsyncOpenAI client initialized for vision model '{self._nvidia_default_vision_model}' at base URL '{self._nvidia_base_url}'.")
            except Exception as e:
                logger.error(f"Failed to initialize NVIDIA AsyncOpenAI client: {e}", exc_info=True)
                self._nvidia_async_client = None
                self.is_nvidia_client_available = False
        else:
            logger.info(f"'{NVIDIA_API_KEY_ENV_VAR}' not set. NVIDIA multi-modal capabilities will be unavailable.")

    async def aextract_text_from_image_content(
        self,
        image_bytes: bytes,
        image_mime_type: str, # e.g., "image/png", "image/jpeg"
        prompt_text: str,
        model: Optional[str] = None # Specific NVIDIA vision model to use
    ) -> str:
        """
        Sends image data and a prompt to the configured NVIDIA multi-modal model
        and returns the extracted text.
        """
        if not self.is_nvidia_client_available or not self._nvidia_async_client:
            logger.error("NVIDIA client not initialized. Cannot process image content.")
            raise LLMServiceError("NVIDIA client not initialized for image processing.")

        target_model = model or self._nvidia_default_vision_model
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:{image_mime_type};base64,{base64_image}"}},
                ],
            }
        ]

        try:
            logger.debug(f"Sending request to NVIDIA model {target_model} for image analysis. Prompt: {prompt_text[:50]}...")
            completion = await self._nvidia_async_client.chat.completions.create(
                model=target_model, messages=messages, temperature=0.2, top_p=0.7, max_tokens=2048, stream=False
            )
            if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
                return completion.choices[0].message.content
            logger.warning(f"NVIDIA model '{target_model}' returned no content for prompt '{prompt_text[:50]}...'.")
            return ""
        except Exception as e:
            logger.error(f"NVIDIA API call to model '{target_model}' failed for prompt '{prompt_text[:50]}...': {e}", exc_info=True)
            raise LLMServiceError(f"NVIDIA API call to model '{target_model}' failed: {e}")

    def get_langchain_chat_model(
        self,
        llm_purpose: str,
        model_name: Optional[str] = None,
        temperature: Optional[float] = 0.0,
        return_name: bool = False,
        **kwargs: Any
    ) -> Union[BaseChatModel, Tuple[BaseChatModel, str]]:
        """
        Returns a Langchain-compatible chat model instance (ChatOpenAI or AzureChatOpenAI)
        based on environment configuration and specified purpose/model.

        Args:
            llm_purpose (str): The purpose of the LLM call (e.g., "agent_main", "rag").
            model_name (str, optional): Specific model/deployment name. If None, uses default for llm_purpose.
            **kwargs: Additional parameters for the Langchain model constructor (e.g., temperature).

        Returns:
            A Langchain BaseChatModel instance.
        Raises:
            ValueError: If LLM configuration is incomplete or no suitable model can be determined.
        """
        final_model_name = model_name
        if final_model_name is None:
            final_model_name = self.default_models.get(llm_purpose) or self.default_models.get("generic")

        if not final_model_name:
            raise ValueError(f"No model name specified and no default model found for purpose '{llm_purpose}' or generic default: {self.default_models}")

        # Prepare constructor_kwargs by copying incoming kwargs.
        # These will be passed to the Langchain model constructors.
        constructor_kwargs = kwargs.copy()

        # Filter out known unsupported parameters for the specific final_model_name
        if final_model_name in MODEL_SPECIFIC_PARAMS_TO_OMIT:
            for param_to_omit in MODEL_SPECIFIC_PARAMS_TO_OMIT[final_model_name]:
                if param_to_omit in constructor_kwargs:
                    logger.warning(f"Omitting parameter '{param_to_omit}' for model '{final_model_name}' as it's listed for omission from Langchain constructor.")
                    del constructor_kwargs[param_to_omit]

        # ──────────────────────────────────────────────────────────
        # Model-prefix-aware provider detection (Session 60 fix)
        # If the model name explicitly indicates a non-Azure/non-OpenAI provider,
        # route directly to ChatLiteLLM which handles all providers natively.
        # This MUST run before the Azure/OpenAI env var priority block to prevent
        # bedrock/ models from being misrouted to AzureChatOpenAI.
        # ──────────────────────────────────────────────────────────
        model_has_provider_prefix = any(
            final_model_name.startswith(prefix) for prefix in self.NON_AZURE_OPENAI_PREFIXES
        )

        if model_has_provider_prefix:
            logger.info(
                f"[LLM_ROUTING] Model '{final_model_name}' has provider prefix — "
                f"routing to ChatLiteLLM for purpose '{llm_purpose}' "
                f"(bypassing Azure/OpenAI env var priority)"
            )
            try:
                from langchain_community.chat_models import ChatLiteLLM
            except ImportError:
                raise ValueError(
                    f"Model '{final_model_name}' requires ChatLiteLLM (langchain-community) "
                    f"but it is not installed."
                )

            litellm_kwargs = constructor_kwargs.copy()
            litellm_kwargs["model"] = final_model_name

            # For Bedrock models: resolve and pass purpose-specific AWS credentials.
            # LiteLLM's Bedrock auth (base_aws_llm.py) checks two paths:
            #   1. Bearer token: AWS_BEARER_TOKEN_BEDROCK env var (read automatically)
            #   2. SigV4/IAM: aws_access_key_id + aws_secret_access_key (from params → env)
            # We pass IAM credentials explicitly for per-purpose isolation (e.g.,
            # CODING_AGENT_AWS_ACCESS_KEY_ID) and defense-in-depth if bearer token unset.
            if final_model_name.startswith("bedrock/"):
                def _get_purpose_env(base_var: str) -> str | None:
                    val = os.getenv(f"{llm_purpose.upper()}_{base_var}")
                    return val if val else os.getenv(base_var)

                aws_region = _get_purpose_env("AWS_REGION_NAME")
                aws_key_id = _get_purpose_env("AWS_ACCESS_KEY_ID")
                aws_secret = _get_purpose_env("AWS_SECRET_ACCESS_KEY")
                if aws_region:
                    litellm_kwargs["aws_region_name"] = aws_region
                if aws_key_id:
                    litellm_kwargs["aws_access_key_id"] = aws_key_id
                if aws_secret:
                    litellm_kwargs["aws_secret_access_key"] = aws_secret
                logger.info(
                    f"[LLM_ROUTING] Bedrock credentials: region={aws_region}, "
                    f"bearer_token_env={'SET' if os.getenv('AWS_BEARER_TOKEN_BEDROCK') else 'UNSET'}, "
                    f"iam_creds={'explicit' if aws_key_id else 'env_fallback'}"
                )

            log_display = {k: v for k, v in litellm_kwargs.items() if 'key' not in k.lower()}
            logger.info(
                f"[LLM_ROUTING] Resolution: purpose={llm_purpose}, model={final_model_name}, "
                f"provider=litellm_prefix, params={log_display}"
            )
            model_instance = ChatLiteLLM(**litellm_kwargs)
            return (model_instance, final_model_name) if return_name else model_instance

        # ──────────────────────────────────────────────────────────
        # Azure/OpenAI priority (only for non-prefixed models like "o4-mini", "gpt-4o")
        # ──────────────────────────────────────────────────────────

        # Helper to get env vars: tries PURPOSE_SPECIFIC_VAR, then GENERIC_VAR
        def get_env_config(base_var_name: str, purpose: str) -> str | None:
            val = os.getenv(f"{purpose.upper()}_{base_var_name}")
            if val:
                return val
            return os.getenv(base_var_name)

        azure_api_key = get_env_config("AZURE_API_KEY", llm_purpose)
        azure_api_base = get_env_config("AZURE_API_BASE", llm_purpose)
        azure_api_version = get_env_config("AZURE_API_VERSION", llm_purpose)

        openai_api_key = get_env_config("OPENAI_API_KEY", llm_purpose)

        if azure_api_base and azure_api_key and azure_api_version:
            # Strip "azure/" prefix — it's a LiteLLM routing convention, not an Azure
            # deployment name. AzureChatOpenAI uses the deployment name in the URL path
            # (/openai/deployments/{name}/...) so "azure/gpt-4o" would 404.
            azure_deployment_name = final_model_name
            if azure_deployment_name.startswith("azure/"):
                azure_deployment_name = azure_deployment_name[len("azure/"):]
            logger.info(
                f"[LLM_ROUTING] Resolution: purpose={llm_purpose}, model={final_model_name}, "
                f"deployment={azure_deployment_name}, provider=azure"
            )
            from langchain_openai import AzureChatOpenAI # Local import
            azure_root_endpoint = self._parse_azure_root_endpoint(azure_api_base)
            model_instance = AzureChatOpenAI(
                azure_deployment=azure_deployment_name,
                openai_api_version=azure_api_version,
                azure_endpoint=azure_root_endpoint,
                api_key=azure_api_key,
                **constructor_kwargs
            )
            return (model_instance, final_model_name) if return_name else model_instance
        elif openai_api_key:
            logger.info(
                f"[LLM_ROUTING] Resolution: purpose={llm_purpose}, model={final_model_name}, "
                f"provider=openai"
            )
            from langchain_openai import ChatOpenAI # Local import
            model_instance = ChatOpenAI(
                model=final_model_name,
                openai_api_key=openai_api_key,
                **constructor_kwargs
            )
            return (model_instance, final_model_name) if return_name else model_instance
        else:
            error_msg = (
                f"LLM configuration for Langchain model (purpose: {llm_purpose}, model: {final_model_name}) is missing or incomplete. "
                "Please set environment variables for either Azure OpenAI "
                "(e.g., AZURE_API_BASE, AZURE_API_KEY, AZURE_API_VERSION) "
                "or standard OpenAI (e.g., OPENAI_API_KEY)."
            )
            logger.error(error_msg)
            # Fallback to ChatLiteLLM if direct Azure/OpenAI config is missing
            logger.info(
                f"[LLM_ROUTING] Resolution: purpose={llm_purpose}, model={final_model_name}, "
                f"provider=litellm_fallback"
            )
            try:
                from langchain_community.chat_models import ChatLiteLLM # Local import
            except ImportError:
                logger.error("langchain_community.chat_models.ChatLiteLLM not found. Please install langchain-community.")
                raise ValueError(f"{error_msg} Also, ChatLiteLLM (langchain-community) is not available for fallback.")

            chat_litellm_final_kwargs = constructor_kwargs.copy()
            chat_litellm_final_kwargs["model"] = final_model_name

            log_display_params = {
                k: v for k, v in chat_litellm_final_kwargs.items() if 'key' not in k.lower()
            }
            logger.debug(f"Instantiating ChatLiteLLM with params: {log_display_params}")
            model_instance = ChatLiteLLM(**chat_litellm_final_kwargs)
            return (model_instance, final_model_name) if return_name else model_instance
