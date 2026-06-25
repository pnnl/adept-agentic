"""
OpenAI-compatible error response formatter.

Ensures all error responses match the exact format expected by OpenAI client libraries.
"""
import traceback
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Union, Dict, Any
from ..logger_config import get_logger

logger = get_logger(__name__)

class OpenAIError(Exception):
    """Base class for OpenAI-compatible errors."""
    
    def __init__(self, message: str, type: str, param: str = None, code: str = None):
        self.message = message
        self.type = type
        self.param = param
        self.code = code
        super().__init__(self.message)

class OpenAIErrorFormatter:
    """Formats errors to match OpenAI API response structure."""
    
    @staticmethod
    def format_error(
        message: str,
        type: str,
        param: str = None,
        code: str = None,
        status_code: int = 400
    ) -> Dict[str, Any]:
        """
        Format error response to match OpenAI API structure.
        
        OpenAI error format:
        {
            "error": {
                "message": "...",
                "type": "invalid_request_error",
                "param": "model",
                "code": "model_not_found"
            }
        }
        """
        error_obj = {
            "message": message,
            "type": type
        }
        
        if param is not None:
            error_obj["param"] = param
            
        if code is not None:
            error_obj["code"] = code
            
        return {"error": error_obj}

    @staticmethod
    def validation_error_response(exc: RequestValidationError) -> JSONResponse:
        """Convert FastAPI validation errors to OpenAI format."""
        # Extract first validation error for simplicity
        if exc.errors():
            error = exc.errors()[0]
            param = ".".join(str(loc) for loc in error["loc"] if loc != "body")
            message = f"Invalid parameter: {param}. {error['msg']}"
        else:
            param = None
            message = "Invalid request parameters"
            
        formatted_error = OpenAIErrorFormatter.format_error(
            message=message,
            type="invalid_request_error",
            param=param,
            code="invalid_parameter"
        )
        
        return JSONResponse(
            status_code=400,
            content=formatted_error
        )

    @staticmethod
    def http_exception_response(exc: Union[HTTPException, StarletteHTTPException]) -> JSONResponse:
        """Convert HTTP exceptions to OpenAI format."""
        
        # Map HTTP status codes to OpenAI error types
        error_type_mapping = {
            400: "invalid_request_error",
            401: "authentication_error", 
            403: "permission_error",
            404: "not_found_error",
            409: "conflict_error",
            422: "invalid_request_error",
            429: "rate_limit_exceeded_error",
            500: "api_error",
            502: "api_error",
            503: "api_error"
        }
        
        error_type = error_type_mapping.get(exc.status_code, "api_error")
        
        # Extract code from detail if present
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            # If the detail is already a formatted OpenAI error, return it directly
            return JSONResponse(status_code=exc.status_code, content=detail)
            
        if isinstance(detail, dict):
            message = detail.get("message", "An error occurred.")
            error_type = detail.get("type", error_type)
            param = detail.get("param")
            code = detail.get("code")
        else:
            message = str(detail) if detail else "An error occurred"
            param = None
            code = None
        
        formatted_error = OpenAIErrorFormatter.format_error(
            message=message,
            type=error_type,
            param=param,
            code=code
        )
        
        return JSONResponse(
            status_code=exc.status_code,
            content=formatted_error
        )

    @staticmethod
    def generic_exception_response(exc: Exception) -> JSONResponse:
        """Convert generic exceptions to OpenAI format."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        
        formatted_error = OpenAIErrorFormatter.format_error(
            message="An unexpected error occurred",
            type="api_error",
            code="internal_error"
        )
        
        return JSONResponse(
            status_code=500,
            content=formatted_error
        )

# Exception handlers for FastAPI app
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle FastAPI validation errors."""
    return OpenAIErrorFormatter.validation_error_response(exc)

async def http_exception_handler(request: Request, exc: Union[HTTPException, StarletteHTTPException]):
    """Handle HTTP exceptions.""" 
    return OpenAIErrorFormatter.http_exception_response(exc)

async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other exceptions."""
    return OpenAIErrorFormatter.generic_exception_response(exc)

# Common OpenAI error creators
def create_invalid_model_error(model: str) -> OpenAIError:
    """Create a model not found error."""
    return OpenAIError(
        message=f"The model '{model}' does not exist",
        type="invalid_request_error",
        param="model",
        code="model_not_found"
    )

def create_authentication_error(message: str = "Incorrect API key provided") -> OpenAIError:
    """Create an authentication error.""" 
    return OpenAIError(
        message=message,
        type="authentication_error",
        code="invalid_api_key"
    )

def create_permission_error(message: str = "Insufficient permissions") -> OpenAIError:
    """Create a permission error."""
    return OpenAIError(
        message=message,
        type="permission_error", 
        code="insufficient_permissions"
    )

def create_not_found_error(resource: str, id: str) -> OpenAIError:
    """Create a resource not found error."""
    return OpenAIError(
        message=f"No {resource} with id '{id}' was found",
        type="not_found_error",
        param="id",
        code="resource_not_found"
    )