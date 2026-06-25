"""
OpenAI-compatible client for Agentic Framework

Drop-in replacement for openai library with UCS extensions.
"""

import os
import asyncio
from typing import Optional, Dict, Any, Union, List, AsyncIterator, Iterator
from urllib.parse import urljoin
import httpx
import json
from datetime import datetime

from .exceptions import (
    APIError,
    AuthenticationError,
    create_api_error,
)
from .models.requests import ChatCompletionRequest, CompletionRequest
from .models.responses import ChatCompletionResponse, CompletionResponse
from ._resources import Resources


class OpenAI:
    """
    OpenAI-compatible client for Agentic Framework.
    
    Drop-in replacement for openai.OpenAI with scientific AI capabilities.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Union[float, httpx.Timeout] = 300.0,
        max_retries: int = 2,
        default_headers: Optional[Dict[str, str]] = None,
        default_query: Optional[Dict[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
        **kwargs
    ):
        """
        Initialize Agentic Framework client.

        Args:
            api_key: Service API key or JWT token
            base_url: Base URL for API (defaults to http://localhost:8083/v1)
            timeout: Request timeout in seconds (default 300s for streaming agent operations)
            max_retries: Number of retries on failure
            default_headers: Default headers for all requests
            default_query: Default query parameters
            http_client: Custom HTTP client
        """
        
        # Try to get API key from multiple sources
        self.api_key = api_key or os.getenv("AGENTIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        
        # If no API key provided, try to get from stored authentication token
        if not self.api_key:
            self.api_key = self._get_stored_token()
        
        # Set default base URL - prefer NGINX proxy endpoint
        self.base_url = (base_url or 
                        os.getenv("AGENTIC_BASE_URL") or 
                        os.getenv("OPENAI_BASE_URL") or 
                        "https://api.agentic.local/v1").rstrip('/')
        
        # Validate required parameters
        if not self.api_key:
            raise AuthenticationError(
                "API key is required. Either:\n"
                "1. Set AGENTIC_API_KEY environment variable, or\n"
                "2. Run 'agentic auth login' to authenticate, or\n"
                "3. Pass api_key parameter"
            )
        
        # Set up timeout
        if isinstance(timeout, (int, float)):
            timeout = httpx.Timeout(timeout)
        
        # Prepare headers
        # NOTE: Do NOT set Content-Type here. httpx sets it automatically:
        #   - "application/json" when json= is passed
        #   - "multipart/form-data; boundary=..." when files= is passed
        # A hardcoded Content-Type: application/json breaks file uploads
        # because the server receives multipart body with JSON content type.
        headers = {
            "User-Agent": "agentic-framework-sdk/1.0.0",
            "Accept": "application/json",
        }

        # Add authentication header
        if self.api_key.startswith("sk-service-"):
            headers["X-API-Key"] = self.api_key
        else:
            # Assume JWT token
            headers["Authorization"] = f"Bearer {self.api_key}"

        if default_headers:
            headers.update(default_headers)

        # Initialize HTTP client
        if http_client is None:
            # Configure SSL verification for development
            verify_ssl = kwargs.pop('verify', True)

            # For development with self-signed certificates, disable SSL verification
            # if using api.agentic.local (development endpoint)
            if "api.agentic.local" in self.base_url and verify_ssl is True:
                verify_ssl = False  # Allow self-signed certs in development
                import warnings
                warnings.warn(
                    "Using self-signed certificate for api.agentic.local. "
                    "SSL verification disabled for development.",
                    UserWarning,
                    stacklevel=2,
                )

            self.http_client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=timeout,
                params=default_query,
                verify=verify_ssl,
                **kwargs
            )
        else:
            # If a custom http_client is provided, we need to ensure it has the correct base_url
            # Always create a new client with our settings to ensure compatibility
            # Try to detect SSL verification setting
            verify_setting = False  # Default for development with NGINX proxy

            # Merge headers
            merged_headers = {**dict(getattr(http_client, 'headers', {})), **headers}

            # Create new client with our base_url and merged settings
            self.http_client = httpx.Client(
                base_url=self.base_url,
                headers=merged_headers,
                timeout=getattr(http_client, 'timeout', timeout),
                params=default_query,
                verify=verify_setting,  # Always disable for dev
                **kwargs
            )

        # Initialize resource handlers with proper OpenAI API hierarchy
        self.chat = Resources.Chat(self)
        self.completions = Resources.Completions(self)
        self.models = Resources.Models(self)
        self.files = Resources.Files(self)

        # Response API as primary interface
        self.responses = Resources.Responses(self)

        # Beta resources for OpenAI compatibility (DEPRECATED)
        self._beta_warned = False
        self._original_beta = Resources.Beta(self)

        # UCS extensions
        self.agentic = Resources.Agentic(self)

    @property
    def beta(self):
        """Deprecated beta API access."""
        if not self._beta_warned:
            import warnings
            warnings.warn(
                "The Assistant API (client.beta.*) is deprecated and will be removed in v2.0.0. "
                "Use the Response API (client.responses.*) instead. "
                "See migration guide: https://docs.agentic.ai/migration/assistant-to-response",
                DeprecationWarning,
                stacklevel=2
            )
            self._beta_warned = True
        return self._original_beta
    
    def _make_request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        **kwargs
    ) -> Union[Dict[str, Any], Iterator[Dict[str, Any]]]:
        """Make HTTP request to API."""

        try:
            if stream:
                return self._make_streaming_request(method, path, json_data, params, **kwargs)
            else:
                # httpx expects relative path when base_url is set
                # Remove leading slash if present to avoid double slashes
                if path.startswith('/'):
                    path = path[1:]

                response = self.http_client.request(
                    method=method,
                    url=path,
                    json=json_data,
                    params=params,
                    files=files,
                    data=data,
                    **kwargs
                )
                
                if response.status_code >= 400:
                    raise create_api_error(response)
                
                return response.json()
                
        except httpx.RequestError as e:
            raise APIError(f"Request failed: {e}")
        except httpx.TimeoutException as e:
            raise APIError(f"Request timed out: {e}")
    
    def _make_streaming_request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Iterator[Dict[str, Any]]:
        """Make streaming HTTP request."""

        headers = kwargs.pop("headers", {})
        headers["Accept"] = "text/event-stream"

        # httpx expects relative path when base_url is set
        # Remove leading slash if present to avoid double slashes
        if path.startswith('/'):
            path = path[1:]

        # Streaming requests need a longer timeout than regular API calls
        # because agent processing involves LLM reasoning + tool execution
        # which can take 30-120+ seconds. Enforce a minimum of 300s.
        stream_timeout = max(self.http_client.timeout.read or 300, 300)

        try:
            with self.http_client.stream(
                method=method,
                url=path,
                json=json_data,
                params=params,
                headers=headers,
                timeout=stream_timeout,
                **kwargs
            ) as response:
                
                if response.status_code >= 400:
                    raise create_api_error(response)
                
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            yield json.loads(data)
                        except json.JSONDecodeError:
                            continue
                            
        except httpx.RequestError as e:
            raise APIError(f"Streaming request failed: {e}")
        except httpx.TimeoutException as e:
            raise APIError(f"Streaming request timed out: {e}")
    
    def _get_stored_token(self) -> Optional[str]:
        """
        Try to get a stored authentication token.
        
        Returns:
            Access token if available, None otherwise
        """
        try:
            # Try to import and use token storage
            from .auth import TokenStorage, AuthenticationError
            
            token_storage = TokenStorage()
            if token_storage.is_token_valid():
                token_info = token_storage.get_token()
                return token_info.get("access_token")
                
        except ImportError:
            # Auth module not available
            pass
        except Exception:
            # Token storage failed, ignore silently
            pass
        
        return None
    
    def close(self):
        """Close the HTTP client."""
        self.http_client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class AsyncOpenAI:
    """
    Async OpenAI-compatible client for Agentic Framework.
    
    Async drop-in replacement for openai.AsyncOpenAI.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Union[float, httpx.Timeout] = 300.0,
        max_retries: int = 2,
        default_headers: Optional[Dict[str, str]] = None,
        default_query: Optional[Dict[str, str]] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        **kwargs
    ):
        """Initialize async Agentic Framework client."""
        
        # Set defaults (same logic as sync client)
        self.api_key = api_key or os.getenv("AGENTIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or
                        os.getenv("AGENTIC_BASE_URL") or
                        os.getenv("OPENAI_BASE_URL") or
                        "https://api.agentic.local/v1").rstrip('/')
        
        if not self.api_key:
            raise AuthenticationError(
                "API key is required. Set AGENTIC_API_KEY environment variable or pass api_key parameter."
            )
        
        # Set up timeout
        if isinstance(timeout, (int, float)):
            timeout = httpx.Timeout(timeout)
        
        # Prepare headers
        # NOTE: Do NOT set Content-Type here — see sync client comment.
        headers = {
            "User-Agent": "agentic-framework-sdk/1.0.0",
            "Accept": "application/json",
        }

        # Add authentication
        if self.api_key.startswith("sk-service-"):
            headers["X-API-Key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if default_headers:
            headers.update(default_headers)

        # Initialize async HTTP client
        if http_client is None:
            # Configure SSL verification for development
            verify_ssl = kwargs.pop('verify', True)

            # For development with self-signed certificates
            if "api.agentic.local" in self.base_url and verify_ssl is True:
                verify_ssl = False

            self.http_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=timeout,
                params=default_query,
                verify=verify_ssl,
                **kwargs
            )
        else:
            # If a custom http_client is provided, ensure it has the correct base_url
            # Always create a new client with our settings to ensure compatibility
            verify_setting = False  # Default for development with NGINX proxy

            # Merge headers
            merged_headers = {**dict(getattr(http_client, 'headers', {})), **headers}

            # Create new client with our base_url and merged settings
            self.http_client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=merged_headers,
                timeout=getattr(http_client, 'timeout', timeout),
                params=default_query,
                verify=verify_setting,  # Always disable for dev
                **kwargs
            )

        # Initialize async resource handlers with proper OpenAI API hierarchy
        self.chat = Resources.AsyncChat(self)
        self.completions = Resources.AsyncCompletions(self)
        self.models = Resources.AsyncModels(self)
        self.files = Resources.AsyncFiles(self)

        # Response API as primary interface
        self.responses = Resources.AsyncResponses(self)

        # Beta resources (DEPRECATED)
        self._beta_warned = False
        self._original_beta = Resources.AsyncBeta(self)

        # UCS extensions
        self.agentic = Resources.AsyncAgentic(self)

    @property
    def beta(self):
        """Deprecated beta API access."""
        if not self._beta_warned:
            import warnings
            warnings.warn(
                "The Assistant API (client.beta.*) is deprecated and will be removed in v2.0.0. "
                "Use the Response API (client.responses.*) instead. "
                "See migration guide: https://docs.agentic.ai/migration/assistant-to-response",
                DeprecationWarning,
                stacklevel=2
            )
            self._beta_warned = True
        return self._original_beta
    
    async def _make_request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        **kwargs
    ) -> Union[Dict[str, Any], AsyncIterator[Dict[str, Any]]]:
        """Make async HTTP request to API."""

        try:
            if stream:
                return self._make_streaming_request(method, path, json_data, params, **kwargs)
            else:
                # httpx expects relative path when base_url is set
                # Remove leading slash if present to avoid double slashes
                if path.startswith('/'):
                    path = path[1:]

                response = await self.http_client.request(
                    method=method,
                    url=path,
                    json=json_data,
                    params=params,
                    files=files,
                    data=data,
                    **kwargs
                )
                
                if response.status_code >= 400:
                    raise create_api_error(response)
                
                return response.json()
                
        except httpx.RequestError as e:
            raise APIError(f"Request failed: {e}")
        except httpx.TimeoutException as e:
            raise APIError(f"Request timed out: {e}")
    
    async def _make_streaming_request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """Make async streaming HTTP request."""

        headers = kwargs.pop("headers", {})
        headers["Accept"] = "text/event-stream"

        # httpx expects relative path when base_url is set
        # Remove leading slash if present to avoid double slashes
        if path.startswith('/'):
            path = path[1:]

        # Streaming requests need a longer timeout than regular API calls
        # because agent processing involves LLM reasoning + tool execution
        # which can take 30-120+ seconds. Enforce a minimum of 300s.
        stream_timeout = max(self.http_client.timeout.read or 300, 300)

        try:
            async with self.http_client.stream(
                method=method,
                url=path,
                json=json_data,
                params=params,
                headers=headers,
                timeout=stream_timeout,
                **kwargs
            ) as response:
                
                if response.status_code >= 400:
                    raise create_api_error(response)
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            yield json.loads(data)
                        except json.JSONDecodeError:
                            continue
                            
        except httpx.RequestError as e:
            raise APIError(f"Streaming request failed: {e}")
        except httpx.TimeoutException as e:
            raise APIError(f"Streaming request timed out: {e}")
    
    def _get_stored_token(self) -> Optional[str]:
        """
        Try to get a stored authentication token.
        
        Returns:
            Access token if available, None otherwise
        """
        try:
            # Try to import and use token storage
            from .auth import TokenStorage, AuthenticationError
            
            token_storage = TokenStorage()
            if token_storage.is_token_valid():
                token_info = token_storage.get_token()
                return token_info.get("access_token")
                
        except ImportError:
            # Auth module not available
            pass
        except Exception:
            # Token storage failed, ignore silently
            pass
        
        return None
    
    async def close(self):
        """Close the async HTTP client."""
        await self.http_client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()