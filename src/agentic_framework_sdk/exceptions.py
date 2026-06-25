"""
Exception classes for Agentic Framework SDK

OpenAI-compatible exception hierarchy with additional UCS-specific exceptions.
"""

from typing import Optional, Any, Dict
import httpx


class APIError(Exception):
    """Base exception for all API errors."""
    
    def __init__(
        self,
        message: Optional[str] = None,
        request: Optional[httpx.Request] = None,
        response: Optional[httpx.Response] = None,
        body: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.request = request
        self.response = response
        self.body = body

    @property
    def status_code(self) -> Optional[int]:
        """HTTP status code of the response, if available."""
        if self.response is not None:
            return self.response.status_code
        return None

    @property
    def headers(self) -> Optional[httpx.Headers]:
        """HTTP headers of the response, if available."""
        if self.response is not None:
            return self.response.headers
        return None


class AuthenticationError(APIError):
    """Raised when authentication fails (401 Unauthorized)."""
    pass


class PermissionDeniedError(APIError):
    """Raised when permission is denied (403 Forbidden)."""
    pass


class NotFoundError(APIError):
    """Raised when a resource is not found (404 Not Found)."""
    pass


class ConflictError(APIError):
    """Raised when there's a conflict (409 Conflict).""" 
    pass


class UnprocessableEntityError(APIError):
    """Raised when request is unprocessable (422 Unprocessable Entity)."""
    pass


class RateLimitError(APIError):
    """Raised when rate limit is exceeded (429 Too Many Requests)."""
    pass


class InternalServerError(APIError):
    """Raised when server encounters an error (5xx status codes)."""
    pass


class APIConnectionError(APIError):
    """Raised when connection to API fails."""
    pass


class APITimeoutError(APIError):
    """Raised when request times out."""
    pass


class BadRequestError(APIError):
    """Raised when request is invalid (400 Bad Request)."""
    pass


class ValidationError(APIError):
    """Raised when input validation fails."""
    pass


# UCS-specific exceptions
class AgentError(APIError):
    """Base exception for agent-related errors."""
    pass


class SessionError(AgentError):
    """Raised when there's an issue with session management."""
    pass


class ToolExecutionError(AgentError):
    """Raised when tool execution fails."""
    
    def __init__(
        self,
        message: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_error: Optional[str] = None,
        **kwargs
    ) -> None:
        super().__init__(message, **kwargs)
        self.tool_name = tool_name
        self.tool_error = tool_error


class MCPError(AgentError):
    """Raised when MCP protocol communication fails."""
    pass


class AgentTimeoutError(AgentError):
    """Raised when agent execution times out."""
    pass


def create_api_error(response: httpx.Response) -> APIError:
    """Create appropriate API error based on HTTP status code."""
    status_code = response.status_code
    
    try:
        error_data = response.json()
        message = error_data.get("error", {}).get("message", response.text)
    except:
        message = response.text or f"HTTP {status_code} error"
    
    if status_code == 401:
        return AuthenticationError(message, response=response)
    elif status_code == 403:
        return PermissionDeniedError(message, response=response)
    elif status_code == 404:
        return NotFoundError(message, response=response)
    elif status_code == 409:
        return ConflictError(message, response=response)
    elif status_code == 422:
        return UnprocessableEntityError(message, response=response)
    elif status_code == 429:
        return RateLimitError(message, response=response)
    elif status_code >= 500:
        return InternalServerError(message, response=response)
    elif status_code >= 400:
        return BadRequestError(message, response=response)
    else:
        return APIError(message, response=response)