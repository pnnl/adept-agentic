"""
Resource implementations for OpenAI-compatible SDK

This module provides the resource classes that implement OpenAI's API structure
while adding UCS (Universal Client Support) extensions for the Agentic Framework.
"""

import dataclasses
import json
import uuid
from typing import Dict, Any, List, Optional, Union, AsyncIterator, Iterator
from datetime import datetime

from .exceptions import APIError, ValidationError, ToolExecutionError
from .models.responses import (
    ChatCompletionResponse,
    CompletionResponse,
    ModelResponse,
    FileResponse,
    ResponseCompletionResponse,
    ResponseStreamChunk,
    ResponseStreamChoice,
    ResponseStreamDelta
)


def _filter_dataclass_fields(cls, data: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a dict to only keys that are valid fields on *cls* (a dataclass).

    Prevents ``TypeError: __init__() got an unexpected keyword argument``
    when the server returns new fields that the SDK model hasn't been
    updated to accept yet.
    """
    valid_keys = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in valid_keys}


class Resources:
    """Container for all resource classes."""

    class Responses:
        """Response API resource matching actual implementation."""

        def __init__(self, client):
            self.client = client
            self.completions = self.ResponseCompletions(client)

        class ResponseCompletions:
            """Response completions endpoint - matches agent_gateway implementation."""

            def __init__(self, client):
                self.client = client

            def create(
                self,
                model: str,
                messages: List[Dict[str, Any]],
                # OpenAI parameters
                max_tokens: Optional[int] = None,
                temperature: Optional[float] = None,
                top_p: Optional[float] = None,
                stream: Optional[bool] = False,
                functions: Optional[List[Dict[str, Any]]] = None,
                function_call: Optional[Union[str, Dict[str, Any]]] = None,
                user: Optional[str] = None,
                # OpenAI API Parity parameters
                logprobs: Optional[bool] = None,
                top_logprobs: Optional[int] = None,
                logit_bias: Optional[Dict[str, int]] = None,
                n: Optional[int] = None,
                response_format: Optional[Dict[str, Any]] = None,
                seed: Optional[int] = None,
                stop: Optional[Union[str, List[str]]] = None,
                frequency_penalty: Optional[float] = None,
                presence_penalty: Optional[float] = None,
                # Multi-tier session management (CRITICAL)
                session_id: Optional[str] = None,
                mcp_session_id: Optional[str] = None,
                multi_agent_session_id: Optional[str] = None,
                gateway_session_id: Optional[str] = None,
                # API type identifier
                api_type: str = "response",
                **kwargs
            ) -> Union[Dict[str, Any], Iterator[Dict[str, Any]]]:
                """
                Create a response completion.

                This matches the actual implementation in agent_gateway/routers/v1/responses.py
                """

                payload = {
                    "model": model,
                    "messages": messages,
                    "api_type": api_type,
                    **kwargs
                }

                # Add optional OpenAI parameters
                if max_tokens is not None:
                    payload["max_tokens"] = max_tokens
                if temperature is not None:
                    payload["temperature"] = temperature
                if top_p is not None:
                    payload["top_p"] = top_p
                if functions is not None:
                    payload["functions"] = functions
                if function_call is not None:
                    payload["function_call"] = function_call
                if user is not None:
                    payload["user"] = user

                # Add OpenAI parity parameters
                if logprobs is not None:
                    payload["logprobs"] = logprobs
                if top_logprobs is not None:
                    payload["top_logprobs"] = top_logprobs
                if logit_bias is not None:
                    payload["logit_bias"] = logit_bias
                if n is not None:
                    payload["n"] = n
                if response_format is not None:
                    payload["response_format"] = response_format
                if seed is not None:
                    payload["seed"] = seed
                if stop is not None:
                    payload["stop"] = stop
                if frequency_penalty is not None:
                    payload["frequency_penalty"] = frequency_penalty
                if presence_penalty is not None:
                    payload["presence_penalty"] = presence_penalty

                # Add multi-tier session management
                if session_id is not None:
                    payload["session_id"] = session_id
                if mcp_session_id is not None:
                    payload["mcp_session_id"] = mcp_session_id
                if multi_agent_session_id is not None:
                    payload["multi_agent_session_id"] = multi_agent_session_id
                if gateway_session_id is not None:
                    payload["gateway_session_id"] = gateway_session_id

                # Handle streaming
                if stream:
                    payload["stream"] = True
                    return self.client._make_request(
                        "POST",
                        "/responses/completions",
                        json_data=payload,
                        stream=True
                    )
                else:
                    response = self.client._make_request(
                        "POST",
                        "/responses/completions",
                        json_data=payload
                    )
                    # Return ResponseCompletionResponse model
                    return ResponseCompletionResponse.from_dict(response)

    class AsyncResponses:
        """Async Response API resource."""

        def __init__(self, client):
            self.client = client
            self.completions = self.AsyncResponseCompletions(client)

        class AsyncResponseCompletions:
            """Async response completions endpoint."""

            def __init__(self, client):
                self.client = client

            async def create(
                self,
                model: str,
                messages: List[Dict[str, Any]],
                # OpenAI parameters
                max_tokens: Optional[int] = None,
                temperature: Optional[float] = None,
                top_p: Optional[float] = None,
                stream: Optional[bool] = False,
                functions: Optional[List[Dict[str, Any]]] = None,
                function_call: Optional[Union[str, Dict[str, Any]]] = None,
                user: Optional[str] = None,
                # OpenAI API Parity parameters
                logprobs: Optional[bool] = None,
                top_logprobs: Optional[int] = None,
                logit_bias: Optional[Dict[str, int]] = None,
                n: Optional[int] = None,
                response_format: Optional[Dict[str, Any]] = None,
                seed: Optional[int] = None,
                stop: Optional[Union[str, List[str]]] = None,
                frequency_penalty: Optional[float] = None,
                presence_penalty: Optional[float] = None,
                # Multi-tier session management
                session_id: Optional[str] = None,
                mcp_session_id: Optional[str] = None,
                multi_agent_session_id: Optional[str] = None,
                gateway_session_id: Optional[str] = None,
                # API type identifier
                api_type: str = "response",
                **kwargs
            ) -> Union[Dict[str, Any], AsyncIterator[Dict[str, Any]]]:
                """Async version of create response completion."""

                payload = {
                    "model": model,
                    "messages": messages,
                    "api_type": api_type,
                    **kwargs
                }

                # Add optional OpenAI parameters
                if max_tokens is not None:
                    payload["max_tokens"] = max_tokens
                if temperature is not None:
                    payload["temperature"] = temperature
                if top_p is not None:
                    payload["top_p"] = top_p
                if functions is not None:
                    payload["functions"] = functions
                if function_call is not None:
                    payload["function_call"] = function_call
                if user is not None:
                    payload["user"] = user

                # Add OpenAI parity parameters
                if logprobs is not None:
                    payload["logprobs"] = logprobs
                if top_logprobs is not None:
                    payload["top_logprobs"] = top_logprobs
                if logit_bias is not None:
                    payload["logit_bias"] = logit_bias
                if n is not None:
                    payload["n"] = n
                if response_format is not None:
                    payload["response_format"] = response_format
                if seed is not None:
                    payload["seed"] = seed
                if stop is not None:
                    payload["stop"] = stop
                if frequency_penalty is not None:
                    payload["frequency_penalty"] = frequency_penalty
                if presence_penalty is not None:
                    payload["presence_penalty"] = presence_penalty

                # Add multi-tier session management
                if session_id is not None:
                    payload["session_id"] = session_id
                if mcp_session_id is not None:
                    payload["mcp_session_id"] = mcp_session_id
                if multi_agent_session_id is not None:
                    payload["multi_agent_session_id"] = multi_agent_session_id
                if gateway_session_id is not None:
                    payload["gateway_session_id"] = gateway_session_id

                # Handle streaming
                if stream:
                    payload["stream"] = True
                    return await self.client._make_request(
                        "POST",
                        "/responses/completions",
                        json_data=payload,
                        stream=True
                    )
                else:
                    response = await self.client._make_request(
                        "POST",
                        "/responses/completions",
                        json_data=payload
                    )
                    # Return ResponseCompletionResponse model
                    return ResponseCompletionResponse.from_dict(response)
    
    class Chat:
        """Chat resource with completions sub-resource to match OpenAI API structure."""
        
        def __init__(self, client):
            self.client = client
            self.completions = Resources.ChatCompletions(client)
    
    class AsyncChat:
        """Async Chat resource with completions sub-resource."""
        
        def __init__(self, client):
            self.client = client
            self.completions = Resources.AsyncChatCompletions(client)

    class ChatCompletions:
        """OpenAI-compatible chat completions resource."""
        
        def __init__(self, client):
            self.client = client
        
        def create(
            self,
            model: str,
            messages: List[Dict[str, Any]],
            max_tokens: Optional[int] = None,
            temperature: Optional[float] = None,
            stream: bool = False,
            tools: Optional[List[Dict[str, Any]]] = None,
            session_id: Optional[str] = None,
            **kwargs
        ) -> Union[ChatCompletionResponse, Iterator[Dict[str, Any]]]:
            """Create a chat completion."""
            
            payload = {
                "model": model,
                "messages": messages,
                "stream": stream,
                **kwargs
            }
            
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            if tools is not None:
                payload["tools"] = tools
            if session_id is not None:
                payload["session_id"] = session_id
            
            if stream:
                return self.client._make_request("POST", "/chat/completions", json_data=payload, stream=True)
            else:
                response = self.client._make_request("POST", "/chat/completions", json_data=payload)
                return ChatCompletionResponse(**_filter_dataclass_fields(ChatCompletionResponse, response))

    class AsyncChatCompletions:
        """Async version of chat completions resource."""
        
        def __init__(self, client):
            self.client = client
        
        async def create(
            self,
            model: str,
            messages: List[Dict[str, Any]],
            max_tokens: Optional[int] = None,
            temperature: Optional[float] = None,
            stream: bool = False,
            tools: Optional[List[Dict[str, Any]]] = None,
            session_id: Optional[str] = None,
            **kwargs
        ) -> Union[ChatCompletionResponse, AsyncIterator[Dict[str, Any]]]:
            """Create a chat completion."""
            
            payload = {
                "model": model,
                "messages": messages,
                "stream": stream,
                **kwargs
            }
            
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            if tools is not None:
                payload["tools"] = tools
            if session_id is not None:
                payload["session_id"] = session_id
            
            if stream:
                return self.client._make_request("POST", "/chat/completions", json_data=payload, stream=True)
            else:
                response = await self.client._make_request("POST", "/chat/completions", json_data=payload)
                return ChatCompletionResponse(**_filter_dataclass_fields(ChatCompletionResponse, response))

    class Completions:
        """OpenAI-compatible completions resource."""
        
        def __init__(self, client):
            self.client = client
        
        def create(
            self,
            model: str,
            prompt: Union[str, List[str]],
            max_tokens: Optional[int] = None,
            temperature: Optional[float] = None,
            stream: bool = False,
            **kwargs
        ) -> Union[CompletionResponse, Iterator[Dict[str, Any]]]:
            """Create a completion."""
            
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": stream,
                **kwargs
            }
            
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            
            if stream:
                return self.client._make_request("POST", "/completions", json_data=payload, stream=True)
            else:
                response = self.client._make_request("POST", "/completions", json_data=payload)
                return CompletionResponse(**_filter_dataclass_fields(CompletionResponse, response))

    class AsyncCompletions:
        """Async version of completions resource."""
        
        def __init__(self, client):
            self.client = client
        
        async def create(
            self,
            model: str,
            prompt: Union[str, List[str]],
            max_tokens: Optional[int] = None,
            temperature: Optional[float] = None,
            stream: bool = False,
            **kwargs
        ) -> Union[CompletionResponse, AsyncIterator[Dict[str, Any]]]:
            """Create a completion."""
            
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": stream,
                **kwargs
            }
            
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            
            if stream:
                return self.client._make_request("POST", "/completions", json_data=payload, stream=True)
            else:
                response = await self.client._make_request("POST", "/completions", json_data=payload)
                return CompletionResponse(**_filter_dataclass_fields(CompletionResponse, response))

    class Models:
        """OpenAI-compatible models resource."""
        
        def __init__(self, client):
            self.client = client
        
        def list(self) -> Dict[str, Any]:
            """List available models."""
            return self.client._make_request("GET", "/models")
        
        def retrieve(self, model: str) -> Dict[str, Any]:
            """Retrieve a specific model."""
            return self.client._make_request("GET", f"/models/{model}")

    class AsyncModels:
        """Async version of models resource."""
        
        def __init__(self, client):
            self.client = client
        
        async def list(self) -> Dict[str, Any]:
            """List available models."""
            return await self.client._make_request("GET", "/models")
        
        async def retrieve(self, model: str) -> Dict[str, Any]:
            """Retrieve a specific model."""
            return await self.client._make_request("GET", f"/models/{model}")

    class Files:
        """OpenAI-compatible files resource with Agentic Framework extensions."""

        def __init__(self, client):
            self.client = client

        def create(
            self,
            file: Any,  # File-like object
            purpose: str = "assistants",
            **kwargs
        ) -> Dict[str, Any]:
            """Upload a file."""
            # If file is a file-like object, extract name and content
            if hasattr(file, 'read'):
                # Get filename from file object if available
                filename = getattr(file, 'name', 'uploaded_file')
                if isinstance(filename, str) and '/' in filename:
                    filename = filename.split('/')[-1]  # Get just the filename

                # Read the content
                content = file.read()
                # Reset file position if possible
                if hasattr(file, 'seek'):
                    file.seek(0)

                # Determine content type
                content_type = "application/octet-stream"
                if filename.endswith('.txt'):
                    content_type = "text/plain"
                elif filename.endswith('.pdf'):
                    content_type = "application/pdf"
                elif filename.endswith('.py'):
                    content_type = "text/x-python"
                elif filename.endswith('.xml'):
                    content_type = "application/xml"
                elif filename.endswith(('.md', '.markdown')):
                    content_type = "text/markdown"
                elif filename.endswith(('.json')):
                    content_type = "application/json"
                elif filename.endswith(('.csv')):
                    content_type = "text/csv"

                # Format as tuple for httpx
                # Include purpose as text field in files dict for proper multipart encoding
                files = {
                    "file": (filename, content, content_type),
                    "purpose": (None, purpose)  # Text field in multipart
                }
            else:
                # Assume it's already properly formatted
                files = {
                    "file": file,
                    "purpose": (None, purpose)
                }

            # Add any additional fields to files dict for multipart encoding
            for key, value in kwargs.items():
                files[key] = (None, str(value))

            return self.client._make_request("POST", "/files", files=files)
        
        def list(self) -> Dict[str, Any]:
            """List files."""
            return self.client._make_request("GET", "/files")
        
        def retrieve(self, file_id: str) -> Dict[str, Any]:
            """Retrieve a file."""
            return self.client._make_request("GET", f"/files/{file_id}")
        
        def delete(self, file_id: str) -> Dict[str, Any]:
            """Delete a file."""
            return self.client._make_request("DELETE", f"/files/{file_id}")

        def register_local(
            self,
            file_path: str,
            session_id: Optional[str] = None,
            alias: Optional[str] = None,
            copy_to_session: bool = True
        ) -> Dict[str, Any]:
            """
            Register an existing file from the filesystem with the current session.

            This allows accessing files that were uploaded in different sessions
            or exist on the filesystem through other means.

            Args:
                file_path: Full path to the file on the filesystem
                session_id: Session to register the file with (uses current if None)
                alias: Optional friendly name/alias for the file
                copy_to_session: If True, copies file to session directory; if False, just registers reference

            Returns:
                Registration response with file_id and details

            Example:
                client.files.register_local(
                    "/app/data/uploaded_files/sessions/old_session/file-abc.pdf",
                    alias="report.pdf"
                )
            """
            payload = {
                "file_path": file_path,
                "copy_to_session": copy_to_session
            }
            if session_id:
                payload["session_id"] = session_id
            if alias:
                payload["alias"] = alias

            return self.client._make_request("POST", "/files/register-local", json_data=payload)

    class AsyncFiles:
        """Async version of files resource."""
        
        def __init__(self, client):
            self.client = client
        
        async def create(
            self,
            file: Any,
            purpose: str = "assistants",
            **kwargs
        ) -> Dict[str, Any]:
            """Upload a file."""
            # If file is a file-like object, extract name and content
            if hasattr(file, 'read'):
                # Get filename from file object if available
                filename = getattr(file, 'name', 'uploaded_file')
                if isinstance(filename, str) and '/' in filename:
                    filename = filename.split('/')[-1]  # Get just the filename

                # Read the content
                content = file.read()
                # Reset file position if possible
                if hasattr(file, 'seek'):
                    file.seek(0)

                # Determine content type
                content_type = "application/octet-stream"
                if filename.endswith('.txt'):
                    content_type = "text/plain"
                elif filename.endswith('.pdf'):
                    content_type = "application/pdf"
                elif filename.endswith('.py'):
                    content_type = "text/x-python"
                elif filename.endswith('.xml'):
                    content_type = "application/xml"
                elif filename.endswith(('.md', '.markdown')):
                    content_type = "text/markdown"
                elif filename.endswith(('.json')):
                    content_type = "application/json"
                elif filename.endswith(('.csv')):
                    content_type = "text/csv"

                # Format as tuple for httpx
                # Include purpose as text field in files dict for proper multipart encoding
                files = {
                    "file": (filename, content, content_type),
                    "purpose": (None, purpose)  # Text field in multipart
                }
            else:
                # Assume it's already properly formatted
                files = {
                    "file": file,
                    "purpose": (None, purpose)
                }

            # Add any additional fields to files dict for multipart encoding
            for key, value in kwargs.items():
                files[key] = (None, str(value))

            return await self.client._make_request("POST", "/files", files=files)
        
        async def list(self) -> Dict[str, Any]:
            """List files."""
            return await self.client._make_request("GET", "/files")
        
        async def retrieve(self, file_id: str) -> Dict[str, Any]:
            """Retrieve a file."""
            return await self.client._make_request("GET", f"/files/{file_id}")
        
        async def delete(self, file_id: str) -> Dict[str, Any]:
            """Delete a file."""
            return await self.client._make_request("DELETE", f"/files/{file_id}")

        async def register_local(
            self,
            file_path: str,
            session_id: Optional[str] = None,
            alias: Optional[str] = None,
            copy_to_session: bool = True
        ) -> Dict[str, Any]:
            """
            Register an existing file from the filesystem with the current session.

            This allows accessing files that were uploaded in different sessions
            or exist on the filesystem through other means.

            Args:
                file_path: Full path to the file on the filesystem
                session_id: Session to register the file with (uses current if None)
                alias: Optional friendly name/alias for the file
                copy_to_session: If True, copies file to session directory; if False, just registers reference

            Returns:
                Registration response with file_id and details

            Example:
                await client.files.register_local(
                    "/app/data/uploaded_files/sessions/old_session/file-abc.pdf",
                    alias="report.pdf"
                )
            """
            payload = {
                "file_path": file_path,
                "copy_to_session": copy_to_session
            }
            if session_id:
                payload["session_id"] = session_id
            if alias:
                payload["alias"] = alias

            return await self.client._make_request("POST", "/files/register-local", json_data=payload)

    class Beta:
        """
        OpenAI beta features (assistants, threads, etc).

        .. deprecated:: 1.1.0
            The Assistant API is deprecated. Use the Response API instead.
            Will be removed in v2.0.0.
        """

        def __init__(self, client):
            import warnings
            warnings.warn(
                "The Assistant API (client.beta.*) is deprecated and will be removed in v2.0.0. "
                "Use the Response API (client.responses.*) instead.",
                DeprecationWarning,
                stacklevel=3
            )
            self.client = client
            self.assistants = self.Assistants(client)
            self.threads = self.Threads(client)
            
        class Assistants:
            """Assistants API resource."""
            
            def __init__(self, client):
                self.client = client
            
            def create(self, **kwargs) -> Dict[str, Any]:
                """Create an assistant."""
                return self.client._make_request("POST", "/assistants", json_data=kwargs)
            
            def list(self, **kwargs) -> Dict[str, Any]:
                """List assistants."""
                return self.client._make_request("GET", "/assistants", params=kwargs)
            
            def retrieve(self, assistant_id: str) -> Dict[str, Any]:
                """Retrieve an assistant."""
                return self.client._make_request("GET", f"/assistants/{assistant_id}")
            
            def update(self, assistant_id: str, **kwargs) -> Dict[str, Any]:
                """Update an assistant."""
                return self.client._make_request("POST", f"/assistants/{assistant_id}", json_data=kwargs)
            
            def delete(self, assistant_id: str) -> Dict[str, Any]:
                """Delete an assistant."""
                return self.client._make_request("DELETE", f"/assistants/{assistant_id}")
        
        class Threads:
            """Threads API resource."""
            
            def __init__(self, client):
                self.client = client
                self.messages = self.Messages(client)
                self.runs = self.Runs(client)
            
            def create(self, **kwargs) -> Dict[str, Any]:
                """Create a thread."""
                return self.client._make_request("POST", "/threads", json_data=kwargs)
            
            def retrieve(self, thread_id: str) -> Dict[str, Any]:
                """Retrieve a thread."""
                return self.client._make_request("GET", f"/threads/{thread_id}")
            
            def update(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                """Update a thread."""
                return self.client._make_request("POST", f"/threads/{thread_id}", json_data=kwargs)
            
            def delete(self, thread_id: str) -> Dict[str, Any]:
                """Delete a thread."""
                return self.client._make_request("DELETE", f"/threads/{thread_id}")
            
            class Messages:
                """Thread messages resource."""
                
                def __init__(self, client):
                    self.client = client
                
                def create(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                    """Create a message."""
                    return self.client._make_request("POST", f"/threads/{thread_id}/messages", json_data=kwargs)
                
                def list(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                    """List messages in a thread."""
                    return self.client._make_request("GET", f"/threads/{thread_id}/messages", params=kwargs)
                
                def retrieve(self, thread_id: str, message_id: str) -> Dict[str, Any]:
                    """Retrieve a message."""
                    return self.client._make_request("GET", f"/threads/{thread_id}/messages/{message_id}")
            
            class Runs:
                """Thread runs resource."""
                
                def __init__(self, client):
                    self.client = client
                
                def create(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                    """Create a run."""
                    return self.client._make_request("POST", f"/threads/{thread_id}/runs", json_data=kwargs)
                
                def list(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                    """List runs in a thread."""
                    return self.client._make_request("GET", f"/threads/{thread_id}/runs", params=kwargs)
                
                def retrieve(self, thread_id: str, run_id: str) -> Dict[str, Any]:
                    """Retrieve a run."""
                    return self.client._make_request("GET", f"/threads/{thread_id}/runs/{run_id}")
                
                def cancel(self, thread_id: str, run_id: str) -> Dict[str, Any]:
                    """Cancel a run."""
                    return self.client._make_request("POST", f"/threads/{thread_id}/runs/{run_id}/cancel")

    class AsyncBeta:
        """
        Async version of beta features.

        .. deprecated:: 1.1.0
            The Assistant API is deprecated. Use the Response API instead.
            Will be removed in v2.0.0.
        """

        def __init__(self, client):
            import warnings
            warnings.warn(
                "The Assistant API (client.beta.*) is deprecated and will be removed in v2.0.0. "
                "Use the Response API (client.responses.*) instead.",
                DeprecationWarning,
                stacklevel=3
            )
            self.client = client
            self.assistants = self.AsyncAssistants(client)
            self.threads = self.AsyncThreads(client)
            
        class AsyncAssistants:
            """Async assistants API resource."""
            
            def __init__(self, client):
                self.client = client
            
            async def create(self, **kwargs) -> Dict[str, Any]:
                """Create an assistant."""
                return await self.client._make_request("POST", "/assistants", json_data=kwargs)
            
            async def list(self, **kwargs) -> Dict[str, Any]:
                """List assistants."""
                return await self.client._make_request("GET", "/assistants", params=kwargs)
            
            async def retrieve(self, assistant_id: str) -> Dict[str, Any]:
                """Retrieve an assistant."""
                return await self.client._make_request("GET", f"/assistants/{assistant_id}")
            
            async def update(self, assistant_id: str, **kwargs) -> Dict[str, Any]:
                """Update an assistant."""
                return await self.client._make_request("POST", f"/assistants/{assistant_id}", json_data=kwargs)
            
            async def delete(self, assistant_id: str) -> Dict[str, Any]:
                """Delete an assistant."""
                return await self.client._make_request("DELETE", f"/assistants/{assistant_id}")
        
        class AsyncThreads:
            """Async threads API resource."""
            
            def __init__(self, client):
                self.client = client
                self.messages = self.AsyncMessages(client)
                self.runs = self.AsyncRuns(client)
            
            async def create(self, **kwargs) -> Dict[str, Any]:
                """Create a thread."""
                return await self.client._make_request("POST", "/threads", json_data=kwargs)
            
            async def retrieve(self, thread_id: str) -> Dict[str, Any]:
                """Retrieve a thread."""
                return await self.client._make_request("GET", f"/threads/{thread_id}")
            
            async def update(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                """Update a thread."""
                return await self.client._make_request("POST", f"/threads/{thread_id}", json_data=kwargs)
            
            async def delete(self, thread_id: str) -> Dict[str, Any]:
                """Delete a thread."""
                return await self.client._make_request("DELETE", f"/threads/{thread_id}")
            
            class AsyncMessages:
                """Async thread messages resource."""
                
                def __init__(self, client):
                    self.client = client
                
                async def create(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                    """Create a message."""
                    return await self.client._make_request("POST", f"/threads/{thread_id}/messages", json_data=kwargs)
                
                async def list(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                    """List messages in a thread."""
                    return await self.client._make_request("GET", f"/threads/{thread_id}/messages", params=kwargs)
                
                async def retrieve(self, thread_id: str, message_id: str) -> Dict[str, Any]:
                    """Retrieve a message."""
                    return await self.client._make_request("GET", f"/threads/{thread_id}/messages/{message_id}")
            
            class AsyncRuns:
                """Async thread runs resource."""
                
                def __init__(self, client):
                    self.client = client
                
                async def create(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                    """Create a run."""
                    return await self.client._make_request("POST", f"/threads/{thread_id}/runs", json_data=kwargs)
                
                async def list(self, thread_id: str, **kwargs) -> Dict[str, Any]:
                    """List runs in a thread."""
                    return await self.client._make_request("GET", f"/threads/{thread_id}/runs", params=kwargs)
                
                async def retrieve(self, thread_id: str, run_id: str) -> Dict[str, Any]:
                    """Retrieve a run."""
                    return await self.client._make_request("GET", f"/threads/{thread_id}/runs/{run_id}")
                
                async def cancel(self, thread_id: str, run_id: str) -> Dict[str, Any]:
                    """Cancel a run."""
                    return await self.client._make_request("POST", f"/threads/{thread_id}/runs/{run_id}/cancel")

    class Agentic:
        """UCS extensions specific to Agentic Framework."""
        
        def __init__(self, client):
            self.client = client
            self.tools = self.Tools(client)
            self.sessions = self.Sessions(client)
            self.agents = self.Agents(client)
        
        class Tools:
            """Tool management resource."""
            
            def __init__(self, client):
                self.client = client
            
            def register(self, tool_config: Dict[str, Any]) -> Dict[str, Any]:
                """Register a new tool."""
                return self.client._make_request("POST", "/tools/register", json_data=tool_config)
            
            def list(self) -> Dict[str, Any]:
                """List all registered tools."""
                return self.client._make_request("GET", "/tools/list")
            
            def retrieve(self, tool_name: str) -> Dict[str, Any]:
                """Retrieve a specific tool."""
                return self.client._make_request("GET", f"/tools/{tool_name}")
            
            def delete(self, tool_name: str) -> Dict[str, Any]:
                """Delete a tool."""
                return self.client._make_request("DELETE", f"/tools/{tool_name}")
            
            def update_acl(self, tool_name: str, acl: Dict[str, Any]) -> Dict[str, Any]:
                """Update tool access control list."""
                return self.client._make_request("PUT", f"/tools/{tool_name}/acl", json_data=acl)
        
        class Sessions:
            """Session management resource."""
            
            def __init__(self, client):
                self.client = client
            
            def create(self, **kwargs) -> Dict[str, Any]:
                """Create a new session."""
                return self.client._make_request("POST", "/sessions", json_data=kwargs)
            
            def list(self) -> Dict[str, Any]:
                """List user sessions."""
                return self.client._make_request("GET", "/sessions")
            
            def retrieve(self, session_id: str) -> Dict[str, Any]:
                """Retrieve a session."""
                return self.client._make_request("GET", f"/sessions/{session_id}")
            
            def delete(self, session_id: str) -> Dict[str, Any]:
                """Delete a session."""
                return self.client._make_request("DELETE", f"/sessions/{session_id}")
        
        class Agents:
            """Agent workflow resource."""
            
            def __init__(self, client):
                self.client = client
            
            def invoke(
                self,
                input: str,
                session_id: Optional[str] = None,
                agent_id: Optional[str] = None,
                context: Optional[Dict[str, Any]] = None,
                **kwargs
            ) -> Dict[str, Any]:
                """Invoke an agent directly."""
                payload = {
                    "input": input,
                    **kwargs
                }
                
                if session_id is not None:
                    payload["session_id"] = session_id
                if agent_id is not None:
                    payload["agent_id"] = agent_id
                if context is not None:
                    payload["context"] = context
                
                return self.client._make_request("POST", "/invoke", json_data=payload)

    class AsyncAgentic:
        """Async version of UCS extensions."""
        
        def __init__(self, client):
            self.client = client
            self.tools = self.AsyncTools(client)
            self.sessions = self.AsyncSessions(client)
            self.agents = self.AsyncAgents(client)
        
        class AsyncTools:
            """Async tool management resource."""
            
            def __init__(self, client):
                self.client = client
            
            async def register(self, tool_config: Dict[str, Any]) -> Dict[str, Any]:
                """Register a new tool."""
                return await self.client._make_request("POST", "/tools/register", json_data=tool_config)
            
            async def list(self) -> Dict[str, Any]:
                """List all registered tools."""
                return await self.client._make_request("GET", "/tools/list")
            
            async def retrieve(self, tool_name: str) -> Dict[str, Any]:
                """Retrieve a specific tool."""
                return await self.client._make_request("GET", f"/tools/{tool_name}")
            
            async def delete(self, tool_name: str) -> Dict[str, Any]:
                """Delete a tool."""
                return await self.client._make_request("DELETE", f"/tools/{tool_name}")
            
            async def update_acl(self, tool_name: str, acl: Dict[str, Any]) -> Dict[str, Any]:
                """Update tool access control list."""
                return await self.client._make_request("PUT", f"/tools/{tool_name}/acl", json_data=acl)
        
        class AsyncSessions:
            """Async session management resource."""
            
            def __init__(self, client):
                self.client = client
            
            async def create(self, **kwargs) -> Dict[str, Any]:
                """Create a new session."""
                return await self.client._make_request("POST", "/sessions", json_data=kwargs)
            
            async def list(self) -> Dict[str, Any]:
                """List user sessions."""
                return await self.client._make_request("GET", "/sessions")
            
            async def retrieve(self, session_id: str) -> Dict[str, Any]:
                """Retrieve a session."""
                return await self.client._make_request("GET", f"/sessions/{session_id}")
            
            async def delete(self, session_id: str) -> Dict[str, Any]:
                """Delete a session."""
                return await self.client._make_request("DELETE", f"/sessions/{session_id}")
        
        class AsyncAgents:
            """Async agent workflow resource."""
            
            def __init__(self, client):
                self.client = client
            
            async def invoke(
                self,
                input: str,
                session_id: Optional[str] = None,
                agent_id: Optional[str] = None,
                context: Optional[Dict[str, Any]] = None,
                **kwargs
            ) -> Dict[str, Any]:
                """Invoke an agent directly."""
                payload = {
                    "input": input,
                    **kwargs
                }
                
                if session_id is not None:
                    payload["session_id"] = session_id
                if agent_id is not None:
                    payload["agent_id"] = agent_id
                if context is not None:
                    payload["context"] = context
                
                return await self.client._make_request("POST", "/invoke", json_data=payload)