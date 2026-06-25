"""
LLMClient: Async LiteLLM wrapper with caching, rate limiting, and fallback support.

Provides a unified interface for LLM-assisted domain evaluation with:
- Response caching keyed on (system, user, model) hash
- Token bucket rate limiting
- Token usage tracking
- Automatic fallback to secondary model on failure
- JSON output enforcement via structured completions
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from asopb.config import LLMConfig
from asopb.logging import get_logger

logger = get_logger(__name__)


class LLMClient:
    """
    Async client for LLM completions with caching, rate limiting, and fallback.

    Wraps LiteLLM to provide:
    - Async completion with system + user prompts
    - JSON schema enforcement
    - Response caching (SHA256 of system+user+model)
    - Token bucket rate limiting
    - Token usage tracking
    - Fallback to secondary model on failure
    """

    def __init__(self, config: LLMConfig, langfuse_config=None):
        """
        Initialize LLMClient.

        Args:
            config: LLMConfig with model, fallback_model, rate_limit_rpm, cache settings
            langfuse_config: Optional LangfuseConfig for observability instrumentation

        Raises:
            ImportError: if litellm is not installed
        """
        try:
            import litellm
            self.litellm = litellm
        except ImportError:
            raise ImportError(
                "litellm not installed. Install with: pip install litellm\n"
                "LiteLLM provides unified async API across Claude, GPT, Gemini, and 100+ models.\n"
                "See: https://docs.litellm.ai/"
            )

        self.langfuse_enabled = False
        if langfuse_config:
            from asopb.llm.langfuse_integration import configure_langfuse
            self.langfuse_enabled = configure_langfuse(langfuse_config)

        self.config = config
        self.model = config.model
        self.fallback_model = config.fallback_model

        # Rate limiting: token bucket
        self.rate_limit_rpm = config.rate_limit_rpm
        self.min_interval = 60.0 / max(1, config.rate_limit_rpm)  # seconds between requests
        self._last_request_time: Optional[datetime] = None
        self._rate_limit_lock = asyncio.Lock()

        # Token tracking
        self.input_tokens = 0
        self.output_tokens = 0
        self._token_lock = asyncio.Lock()

        # Response caching
        self.cache_enabled = config.cache_enabled
        if config.cache_dir:
            self.cache_dir = Path(config.cache_dir)
        else:
            # Default: ~/.asopb/cache
            self.cache_dir = Path.home() / ".asopb" / "cache"

        if self.cache_enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Response caching enabled: {self.cache_dir}")

    def _cache_key(self, system: str, user: str, model: str) -> str:
        """Generate cache key from system + user + model."""
        content = f"{system}|{user}|{model}".encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def _get_cached(self, cache_key: str) -> Optional[dict]:
        """Load cached response if it exists."""
        if not self.cache_enabled:
            return None

        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache {cache_key}: {e}")

        return None

    def _set_cached(self, cache_key: str, response: dict) -> None:
        """Store response in cache."""
        if not self.cache_enabled:
            return

        cache_path = self.cache_dir / f"{cache_key}.json"
        try:
            with open(cache_path, "w") as f:
                json.dump(response, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write cache {cache_key}: {e}")

    async def _wait_rate_limit(self) -> None:
        """Enforce rate limiting via token bucket."""
        async with self._rate_limit_lock:
            if self._last_request_time is None:
                self._last_request_time = datetime.now(timezone.utc)
                return

            elapsed = (datetime.now(timezone.utc) - self._last_request_time).total_seconds()
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)

            self._last_request_time = datetime.now(timezone.utc)

    async def _track_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Accumulate token usage."""
        async with self._token_lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens

    async def complete(
        self,
        system: str,
        user: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        metadata: Optional[dict] = None,
        **kwargs
    ) -> str:
        """
        Get LLM completion with system + user prompts.

        Args:
            system: System prompt defining role/context
            user: User message/query
            temperature: Override config temperature
            max_tokens: Override config max_tokens
            metadata: Optional dict forwarded to Langfuse via LiteLLM callback
            **kwargs: Additional litellm.acompletion() arguments

        Returns:
            Response text from LLM

        Raises:
            RuntimeError: if both primary and fallback models fail
        """
        if metadata:
            kwargs["metadata"] = metadata
        # Check cache
        cache_key = self._cache_key(system, user, self.model)
        cached = self._get_cached(cache_key)
        if cached:
            logger.debug(f"Cache hit: {cache_key}")
            return cached.get("content", "")

        # Apply rate limiting
        await self._wait_rate_limit()

        # Prepare parameters
        temp = temperature if temperature is not None else self.config.temperature
        max_tk = max_tokens if max_tokens is not None else self.config.max_tokens

        # Try primary model
        try:
            response = await self.litellm.acompletion(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temp,
                max_tokens=max_tk,
                timeout=self.config.timeout_seconds,
                **kwargs
            )

            content = response.choices[0].message.content

            # Track tokens
            input_tk = response.usage.prompt_tokens
            output_tk = response.usage.completion_tokens
            await self._track_tokens(input_tk, output_tk)

            # Cache result
            cache_data = {
                "content": content,
                "model": self.model,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "input_tokens": input_tk,
                "output_tokens": output_tk,
            }
            self._set_cached(cache_key, cache_data)

            return content

        except Exception as e:
            logger.warning(f"Primary model {self.model} failed: {e}")

            # Try fallback
            if self.fallback_model:
                logger.info(f"Attempting fallback model: {self.fallback_model}")
                try:
                    response = await self.litellm.acompletion(
                        model=self.fallback_model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=temp,
                        max_tokens=max_tk,
                        timeout=self.config.timeout_seconds,
                        **kwargs
                    )

                    content = response.choices[0].message.content

                    # Track tokens from fallback
                    input_tk = response.usage.prompt_tokens
                    output_tk = response.usage.completion_tokens
                    await self._track_tokens(input_tk, output_tk)

                    # Cache with fallback model tag
                    fallback_key = self._cache_key(system, user, self.fallback_model)
                    cache_data = {
                        "content": content,
                        "model": self.fallback_model,
                        "fallback": True,
                        "cached_at": datetime.now(timezone.utc).isoformat(),
                        "input_tokens": input_tk,
                        "output_tokens": output_tk,
                    }
                    self._set_cached(fallback_key, cache_data)

                    return content

                except Exception as fb_e:
                    logger.error(f"Fallback model {self.fallback_model} also failed: {fb_e}")
                    raise RuntimeError(
                        f"Both primary ({self.model}) and fallback ({self.fallback_model}) "
                        f"models failed. Primary: {e}. Fallback: {fb_e}"
                    ) from fb_e
            else:
                raise RuntimeError(f"LLM completion failed and no fallback model configured: {e}") from e

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: dict,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> dict:
        """
        Get LLM completion with JSON output enforcement.

        Uses response_format to force structured JSON output matching schema.

        Args:
            system: System prompt
            user: User message
            schema: JSON schema dict (OpenAI format)
            temperature: Override config temperature
            max_tokens: Override config max_tokens
            **kwargs: Additional litellm.acompletion() arguments

        Returns:
            Parsed JSON dict from response

        Raises:
            ValueError: if response is not valid JSON
            RuntimeError: if completion fails
        """
        # Add schema enforcement via response_format
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "structured_output",
                "schema": schema,
                "strict": True,
            }
        }

        content = await self.complete(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            **kwargs
        )

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {content}")
            raise ValueError(f"LLM response was not valid JSON: {e}") from e

    def get_token_usage(self) -> dict[str, int]:
        """Return accumulated token usage."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
        }

    def reset_token_usage(self) -> None:
        """Reset token counters."""
        self.input_tokens = 0
        self.output_tokens = 0
