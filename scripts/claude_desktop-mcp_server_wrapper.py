#!/usr/bin/env python3
"""
MCP Stdio Wrapper - Bridges stdio communication to HTTP MCP server
This script acts as a bridge between Claude Desktop (stdio) and your HTTP MCP server


    Sample configuration for Claude Desktop:
    {
        "mcpServers": {
            "playwright": {
            "command": "npx",
            "args": [
                "@playwright/mcp"
            ]
            },
        "sciencetools": {
            "command": "/path/to/adept-agentic/.venv/bin/python3",
            "args": ["/path/to/adept-agentic/scripts/claude_desktop-mcp_server_wrapper.py"],
            "env": {
                "MCP_SERVER_URL": "http://localhost:8080/mcp"
            }
            }
        }
    }

    Another configuration example for Claude Desktop:
    {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": [
                    "@playwright/mcp"
                ]
            },
            "puppeteer": {
                "command": "docker",
                "args": ["run", "-i", "--rm", "--init", "-e", "DOCKER_CONTAINER=true", "mcp/puppeteer"]
            },
            "sciencetools": {
                "command": "/path/to/adept-agentic/.venv/bin/python3",
                "args": ["/path/to/adept-agentic/scripts/claude_desktop-mcp_server_wrapper.py"],
                "env": {
                    "MCP_SERVER_URL": "http://localhost:8080/mcp/",
                    "PYTHONPATH": "/path/to/adept-agentic/src:/path/to/adept-agentic/.venv/lib/python3.11/site-packages/"
                }
            },
            "sciencetools-agentic_framework-mcp_server": {
                "command": "/opt/miniconda3/bin/uv",
                "args": [
                    "run",
                    "--directory",
                    "/path/to/adept-agentic",
                    "/path/to/adept-agentic/.venv/bin/python3", 
                    "-m", 
                    "agentic_framework_pkg.mcp_server.main"
                ],
                "env": {
                    "MCP_SERVER_URL": "http://localhost:8080/mcp/",
                    "PYTHONPATH": "/path/to/adept-agentic/src"
                }
            }
        }
    }
    
    Latest:
        {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": [
                    "@playwright/mcp"
                ]
                },
            "puppeteer": {
                "command": "docker",
                "args": ["run", "-i", "--rm", "--init", "-e", "DOCKER_CONTAINER=true", "mcp/puppeteer"]
                },
            "sciencetools": {
                "command": "/path/to/adept-agentic/.venv/bin/python3",
                "args": ["/path/to/adept-agentic/scripts/claude_desktop-mcp_server_wrapper.py"],
                "env": {
                    "MCP_SERVER_URL": "http://localhost:8080/mcp/",
                    "PYTHONPATH": "/path/to/adept-agentic/src:/path/to/adept-agentic/.venv/lib/python3.11/site-packages/"
                }
            }
        }
    }
    
    Sample if you have a Claude Pro subscription:
    {
        "mcpServers": {
            "agentic-framework-mcp": {
                "transport": "http",
                "url": "http://localhost:8080"
            },
            "agentic-framework-hpc-mcp": {
                "transport": "http",
                "url": "http://localhost:8081"
            }
        }
    }

"""

#!/usr/bin/env python3
"""
MCP Stdio Wrapper - Bridges stdio communication to HTTP MCP server
This script acts as a bridge between Claude Desktop (stdio) and your HTTP MCP server
"""

import sys
import json
import asyncio
import aiohttp
import logging, uuid # Added uuid
from typing import Dict, Any, Optional

# Configure logging to stderr so it doesn't interfere with stdio communication
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s: %(module)s.%(funcName)s:%(lineno)d - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

class MCPStdioWrapper:
    def __init__(self, server_url: str = "http://localhost:8080"):
        self.server_url = server_url.rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None
        self.mcp_session_id: Optional[str] = None # To store the session ID for this wrapper instance
        self.original_request_id: Optional[str] = None # To store the original request ID if needed
        logger.debug(f"Initialized MCPStdioWrapper with server URL: {self.server_url}")
        
    async def initialize(self):
        """Initialize the HTTP session"""
        self.session = aiohttp.ClientSession()
        # Only generate a new mcp_session_id if it's not already set, to maintain stability
        # This method might be called if self.session is None OR self.mcp_session_id is None
        if not self.mcp_session_id:
            self.mcp_session_id = str(uuid.uuid4()) # Generate a unique session ID for this wrapper instance
            logger.debug(f"Generated new MCP Session ID: {self.mcp_session_id}")
        logger.debug(f"Initialized wrapper with MCP Session ID: {self.mcp_session_id}")
    async def cleanup(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()
    
    async def _handle_sse_response(self, response: aiohttp.ClientResponse, request_id: Any, mcp_session_id: Any = None) -> Dict[str, Any]:
        """Handle Server-Sent Events response from MCP server"""
        try:
            # Read the SSE stream
            async for line in response.content:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                
                # SSE format: "data: <json>"
                if line.startswith('data: '):
                    data_part = line[6:]  # Remove "data: " prefix
                    if data_part.strip():
                        try:
                            return json.loads(data_part)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse SSE JSON: {e}")
                            continue
                            
            # If we get here, no valid JSON was found in the stream
            logger.error("No valid JSON found in SSE stream")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "No valid response in SSE stream"
                }
            }
            
        except Exception as e:
            logger.error(f"Error handling SSE response: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"SSE parsing error: {str(e)}"
                }
            }

    async def forward_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Forward a request to the HTTP MCP server"""
        try:
            # Ensure both session and mcp_session_id are initialized
            if not self.session or not self.mcp_session_id:
                logger.debug("Session or mcp_session_id missing/invalid, (re-)initializing...")
                await self.initialize()
            
            # Defensive check: if mcp_session_id is STILL None, something is very wrong.
            if not self.mcp_session_id:
                logger.error("CRITICAL: mcp_session_id is None even after initialization attempt. Generating emergency ID.")
                self.mcp_session_id = str(uuid.uuid4()) # Emergency fallback
                logger.debug(f"Emergency MCP Session ID generated: {self.mcp_session_id}")

            # Ensure 'params' key exists and is a dictionary
            current_params = request.get('params')
            if not isinstance(current_params, dict):
                logger.debug(f"Request 'params' was missing or not a dict (type: {type(current_params)}). Initializing as empty dict.")
                current_params = {}
            
            # Add or overwrite mcp_session_id in the request parameters
            current_params['mcp_session_id'] = self.mcp_session_id
            request['params'] = current_params # Assign back to the request

            logger.debug(f"Populated request params with mcp_session_id: {request['params']}")
            logger.debug(f"Full request payload to be sent: {json.dumps(request)}") # Changed to DEBUG

            # Forward the JSON-RPC request to your HTTP server
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "X-ID": self.mcp_session_id, # Add session ID as a header
                "X-Session-ID": self.mcp_session_id, # Add session ID as a header
                "X-MCP-Session-ID": self.mcp_session_id  # Add session ID as a header
            }
            
            # # Update the request to include params
            # request['params'] = {
            #     "id": request.get("id"),
            #     "session_id": self.mcp_session_id,
            #     "mcp_session_id": self.mcp_session_id
            # }
            if 'mcp_session_id' not in request:
                request['mcp_session_id'] = self.mcp_session_id
            
            if 'id' not in request and self.original_request_id is not None:
                # If the original request ID is set, use it for the response
                request['id'] = self.original_request_id
            elif 'id' not in request:
                # If no ID is set, generate a new one for this request
                request['id'] = str(uuid.uuid4())

            # Log the request before sending
            logger.debug(f"Forwarding request (post) to {self.server_url} ({request}) with headers: {headers}")
            async with self.session.post(
                self.server_url,  # Using the full URL since you included /mcp in the env var
                json=request,
                headers=headers
            ) as response:
                logger.debug(f"Received response with status {response.status}")
                
                if response.status == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    logger.debug(f"Response content-type: {content_type}")
                    
                    if 'application/json' in content_type:
                        # Standard JSON response
                        return await response.json()
                    elif 'text/event-stream' in content_type:
                        # Server-Sent Events response - read the stream
                        return await self._handle_sse_response(response, request.get("id"))
                    else:
                        # Try to parse as JSON anyway
                        try:
                            return await response.json()
                        except Exception:
                            # Fall back to text response
                            text_response = await response.text()
                            logger.error(f"Unexpected content type {content_type}, got text: {text_response}")
                            return {
                                "jsonrpc": "2.0",
                                "id": request.get("id"),
                                "error": {
                                    "code": -32603,
                                    "message": f"Unexpected response format"
                                }
                            }
                else:
                    # Handle non-200 responses
                    logger.error(f"HTTP error {response.status} for request {request.get('method', 'unknown')}: {response}")
                    error_text = await response.text()
                    logger.error(f"HTTP error {response.status}: {error_text}")
                    return {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": -32603,
                            "message": f"HTTP server error: {response.status}"
                        }
                    }
                    
        except aiohttp.ClientError as e:
            logger.error(f"Connection error: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Connection failed: {str(e)}"
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            }
    
    async def handle_stdio(self):
        """Handle stdio communication with Claude Desktop"""
        logger.debug("MCP Stdio Wrapper started")    
        try:
            while True:
                try:
                    # Read line from stdin
                    logger.debug("Waiting for input from stdin...")
                    line = await asyncio.get_event_loop().run_in_executor(
                        None, sys.stdin.readline
                    )
                    logger.debug(f"Received line: {line.strip()}")
                    if not line:
                        # EOF reached
                        break
                    logger.debug("Processing line from stdin...")
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Parse JSON-RPC request
                    try:
                        logger.debug("Parsing JSON request...")
                        request = json.loads(line)
                        logger.debug(f"Received request: {request.get('method', 'unknown')}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON: {e}")
                        continue
                    logger.debug(f"Parsed request: {request}")
                    
                    # Ensure the wrapper (session and session_id) is initialized.
                    # forward_request also has its own robust initialization checks.
                    if not self.session or not self.mcp_session_id:
                        logger.debug("Wrapper (MCPStdioWrapper) not fully initialized. Calling initialize().")
                        await self.initialize()
                    
                    # Forward the request. forward_request will handle mcp_session_id injection.
                    logger.debug(f"Forwarding request to HTTP server...: {request}")
                    response = await self.forward_request(request)
                    
                    # Send response back via stdout
                    logger.debug(f"Sending response back to stdout... :{response}")
                    
                    if self.original_request_id is None:
                        self.original_request_id = request.get("id")

                    if self.original_request_id is not None:
                        # This was a request, so Claude Desktop expects a response.
                        logger.debug(f"Original request ID: {self.original_request_id}")
                        response_to_send = {"jsonrpc": "2.0", "id": self.original_request_id, 
                                            # # Add params
                                            # "params": {
                                            #     "id": original_request_id,
                                            #     "request_id": original_request_id,
                                            #     "session_id": self.mcp_session_id,
                                            #     "mcp_session_id": self.mcp_session_id
                                            #     }
                        }

                        if isinstance(response, dict) and 'error' in response and response['error'] is not None:
                            # Populate error
                            logger.debug(f"Received error response from server: {response['error']}")
                            if isinstance(response['error'], dict):
                                response_to_send['error'] = {
                                    'code': response['error'].get('code', -32000), # Default JSON-RPC error code
                                    'message': str(response['error'].get('message', 'Unknown server error'))
                                }
                                if 'data' in response['error']: # Optional data field
                                    response_to_send['error']['data'] = response['error']['data']
                            else: # Malformed error from server/forward_request
                                response_to_send['error'] = {
                                    'code': -32603, # Internal error
                                    'message': f"Malformed error object received from forwarding: {response['error']}"
                                }
                        elif isinstance(response, dict) and 'result' in response:
                            # Handle success response
                            logger.debug(f"Received successful response from server: {response['result']} -- \n full response: {response}")
                            response_to_send['result'] = response['result']
                        else:
                            # Fallback error if response from forward_request is not well-formed or ambiguous
                            logger.error(f"Ambiguous or malformed response from forward_request for request ID {self.original_request_id}: {response}")
                            response_to_send['error'] = {
                                "code": -32603, # Internal error
                                "message": "Internal wrapper error: Ambiguous or malformed response from MCP server or forwarding."
                            }
                        
                        logger.debug(f"Final response to send to Claude Desktop: {response_to_send}")
                        response_line = json.dumps(response_to_send)
                        print(response_line, flush=True) # Ensure flush=True to send immediately
                        logger.debug(f"Sent response for: {request.get('method', 'unknown')} (ID: {self.original_request_id})")
                    else:
                        # Original message from Claude Desktop was a notification (no id).
                        # We typically don't send a response back for notifications.
                        # Log what happened with the forwarded notification.
                        logger.debug(f"Forwarded notification '{request.get('method', 'unknown')}' to server. Server's raw reaction (if any, via forward_request): {response}")
                        # If `response` (from `forward_request`) contains an error from the server about the notification,
                        # it's logged above by `forward_request` or here.
                        # Claude Desktop isn't expecting a JSON-RPC response for its own notification.
                        # If the server sends a notification back, that would be a separate message.
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.error(f"Error handling request: {e}")
                    
        finally:
            await self.cleanup()
            logger.debug("MCP Stdio Wrapper stopped")

async def main():
    """Main function"""
    # You can customize the server URL here or via environment variable
    import os
    server_url = os.getenv("MCP_SERVER_URL", "http://localhost:8080")
    
    wrapper = MCPStdioWrapper(server_url)
    await wrapper.handle_stdio()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.debug("Wrapper interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
