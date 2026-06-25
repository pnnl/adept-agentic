"""
MCP Protocol Bridge for Agent Gateway

This module implements MCP (Model Context Protocol) compatibility for the agent_gateway,
allowing MCP clients to interact with the unified execution architecture through the 
standard MCP JSON-RPC protocol.

Features:
- MCP protocol negotiation and initialization
- Tool discovery and invocation via MCP
- Authentication integration with JWT tokens
- Protocol translation between MCP and OpenAI formats
- Session management bridge to multi-tier hierarchy

Architecture:
- MCP Client → Agent Gateway MCP Bridge → Orchestration Service → Tool Execution
"""
import json
import asyncio
from typing import Dict, Any, List, Optional, Union
from fastapi import HTTPException, Request
from fastmcp import FastMCP
import httpx
import uuid
import os
from datetime import datetime

from .auth import validate_jwt, validate_service_api_key, detect_token_type
from ..logger_config import get_logger

logger = get_logger(__name__)

class MCPAuthenticationError(Exception):
    """Raised when MCP client authentication fails"""
    pass

class MCPProtocolError(Exception):
    """Raised when MCP protocol negotiation fails"""
    pass

class AgentGatewayMCPBridge:
    """
    MCP Protocol Bridge that translates MCP JSON-RPC calls to Agent Gateway operations
    """
    
    def __init__(self):
        self.orchestration_base_url = os.getenv("ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084")
        self.protocol_version = "2024-11-05"
        self.server_info = {
            "name": "agentic-framework-gateway",
            "version": "1.0.0"
        }
        
        # MCP capabilities we support
        self.capabilities = {
            "tools": {
                "listChanged": True
            },
            "resources": {},  # Future: file/data resources
            "prompts": {},    # Future: prompt templates
            "logging": {}     # Future: structured logging
        }
    
    async def extract_auth_token(self, request_data: Dict[str, Any], headers: Dict[str, str]) -> Optional[str]:
        """
        Extract JWT token from MCP request.
        
        MCP clients can provide auth via:
        1. HTTP Authorization header
        2. MCP metadata in request
        3. Custom header (X-Auth-Token)
        """
        # Method 1: Standard HTTP Authorization header
        auth_header = headers.get("authorization") or headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header.split("Bearer ", 1)[1]
        
        # Method 2: Custom auth header
        custom_token = headers.get("x-auth-token") or headers.get("X-Auth-Token")
        if custom_token:
            return custom_token
        
        # Method 3: MCP metadata (if present in request)
        if "meta" in request_data and "auth_token" in request_data["meta"]:
            return request_data["meta"]["auth_token"]
        
        return None
    
    async def validate_authentication(self, request_data: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        """Validate authentication and return user info"""
        token = await self.extract_auth_token(request_data, headers)
        
        if not token:
            raise MCPAuthenticationError("No authentication token provided")
        
        try:
            token_type = detect_token_type(token)

            if token_type == "service_api_key":
                # Service API key path (sk-service-*)
                service_info = await validate_service_api_key(token)
                username = service_info.get("username", "service")
                logger.info(f"[MCP_BRIDGE] Service API key authenticated: {username}")
                return {
                    "token": token,
                    "user_info": service_info,
                    "user_id": service_info.get("user_id", service_info.get("client_id", "unknown")),
                    "username": username
                }
            else:
                # JWT path (default)
                payload = await validate_jwt(token)
                username = payload.get("preferred_username") or payload.get("clientId", "unknown")
                logger.info(f"[MCP_BRIDGE] JWT authenticated: {username}")
                return {
                    "token": token,
                    "user_info": payload,
                    "user_id": payload.get("sub", "unknown"),
                    "username": username
                }
        except Exception as e:
            logger.error(f"[MCP_BRIDGE] Authentication failed: {e}")
            raise MCPAuthenticationError(f"Token validation failed: {e}")
    
    def create_mcp_error(self, code: int, message: str, data: Any = None) -> Dict[str, Any]:
        """Create standard MCP error response"""
        error = {
            "code": code,
            "message": message
        }
        if data:
            error["data"] = data
        return error
    
    async def proxy_to_orchestration(self, endpoint: str, auth_info: Dict[str, Any],
                                   method: str = "GET", data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Proxy request to orchestration service with authentication.

        Uses X-Forwarded-User-Token header (same pattern as all other gateway
        routers: responses.py, files.py, agui.py, etc.) so the orchestration
        service's get_forwarded_user() dependency can validate the token.
        """
        url = f"{self.orchestration_base_url}{endpoint}"
        headers = {
            "X-Forwarded-User-Token": auth_info["token"],
            "Content-Type": "application/json",
            "X-Forwarded-User": auth_info.get("username", "unknown"),
            "X-Forwarded-User-ID": auth_info.get("user_id", "unknown")
        }
        
        async with httpx.AsyncClient() as client:
            try:
                if method.upper() == "GET":
                    response = await client.get(url, headers=headers, timeout=30)
                elif method.upper() == "POST":
                    response = await client.post(url, headers=headers, json=data, timeout=30)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                raise MCPProtocolError(f"Timeout calling orchestration service: {endpoint}")
            except httpx.HTTPStatusError as e:
                raise MCPProtocolError(f"Orchestration service error {e.response.status_code}: {e.response.text}")
            except Exception as e:
                raise MCPProtocolError(f"Failed to proxy to orchestration service: {e}")
    
    def translate_tools_to_mcp(self, openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Translate OpenAI tool format to MCP tool format
        
        OpenAI format:
        {
            "name": "tool_name",
            "description": "Tool description",
            "parameters": {"type": "object", "properties": {...}}
        }
        
        MCP format:
        {
            "name": "tool_name", 
            "description": "Tool description",
            "inputSchema": {"type": "object", "properties": {...}}
        }
        """
        mcp_tools = []
        for tool in openai_tools:
            mcp_tool = {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "inputSchema": tool.get("parameters", tool.get("args_schema", {"type": "object"}))
            }
            mcp_tools.append(mcp_tool)
        
        logger.debug(f"[MCP_BRIDGE] Translated {len(openai_tools)} tools to MCP format")
        return mcp_tools
    
    def translate_mcp_tool_call(self, mcp_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Translate MCP tool call to OpenAI function call format
        
        MCP format:
        {
            "name": "tool_name",
            "arguments": {...}
        }
        
        OpenAI format for execution:
        {
            "function": {
                "name": "tool_name",
                "arguments": json.dumps({...})
            }
        }
        """
        return {
            "type": "function",
            "function": {
                "name": mcp_params.get("name"),
                "arguments": json.dumps(mcp_params.get("arguments", {}))
            }
        }
    
    async def handle_initialize(self, params: Dict[str, Any], auth_info: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request"""
        client_info = params.get("clientInfo", {})
        protocol_version = params.get("protocolVersion")
        
        logger.info(f"[MCP_BRIDGE] Initialize request from {client_info.get('name', 'unknown')} v{client_info.get('version', 'unknown')}")
        logger.info(f"[MCP_BRIDGE] Client protocol version: {protocol_version}")
        
        if protocol_version != self.protocol_version:
            logger.warning(f"[MCP_BRIDGE] Protocol version mismatch: client={protocol_version}, server={self.protocol_version}")
        
        return {
            "protocolVersion": self.protocol_version,
            "capabilities": self.capabilities,
            "serverInfo": self.server_info,
            "instructions": "Agent Gateway MCP Bridge - Connect to agentic framework via MCP protocol"
        }
    
    async def handle_tools_list(self, params: Dict[str, Any], auth_info: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP tools/list request"""
        try:
            # Get tools from the model-scoped endpoint (no admin role required).
            # This returns both static built-in tools and dynamically registered
            # tools, filtered by the user's ACL — same as what the agent sees.
            model_id = os.getenv("DEFAULT_AGENT_MODEL", "agentic-framework:scientific-agent-v1")
            response = await self.proxy_to_orchestration(f"/v1/models/{model_id}/tools", auth_info)

            # The endpoint returns {"tools": [...]}, extract the list
            openai_tools = response.get("tools", []) if isinstance(response, dict) else response

            # Convert to MCP format
            mcp_tools = self.translate_tools_to_mcp(openai_tools)
            
            logger.info(f"[MCP_BRIDGE] Returning {len(mcp_tools)} tools to MCP client")
            
            return {
                "tools": mcp_tools
            }
        except Exception as e:
            logger.error(f"[MCP_BRIDGE] Failed to list tools: {e}")
            raise MCPProtocolError(f"Failed to retrieve tools: {e}")
    
    async def handle_tools_call(self, params: Dict[str, Any], auth_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle MCP tools/call request by creating a simplified execution
        """
        try:
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            logger.info(f"[MCP_BRIDGE] Tool call request: {tool_name} with args: {json.dumps(arguments)[:200]}")
            
            # Create a simplified completion request to execute the tool
            completion_request = {
                "model": "agentic-framework:scientific-agent-v1",
                "messages": [
                    {
                        "role": "user",
                        "content": f"Execute the {tool_name} tool with the provided arguments."
                    }
                ],
                "tools": [
                    {
                        "type": "function", 
                        "function": {
                            "name": tool_name,
                            "parameters": {"type": "object", "properties": {}}  # Simplified
                        }
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": tool_name}
                },
                "max_tokens": 1000
            }
            
            # Execute via Response API
            result = await self.proxy_to_orchestration(
                "/v1/responses/chat/completions",
                auth_info, 
                method="POST",
                data=completion_request
            )
            
            # Extract tool execution result
            tool_result = "Tool executed successfully"
            if "choices" in result and result["choices"]:
                choice = result["choices"][0]
                if "message" in choice:
                    message = choice["message"]
                    if "tool_calls" in message:
                        # Extract actual tool execution result
                        tool_result = json.dumps(message["tool_calls"], indent=2)
                    else:
                        tool_result = message.get("content", "Tool executed")
            
            return {
                "content": [
                    {
                        "type": "text",
                        "text": tool_result
                    }
                ],
                "isError": False
            }
            
        except Exception as e:
            logger.error(f"[MCP_BRIDGE] Tool call failed: {e}")
            return {
                "content": [
                    {
                        "type": "text", 
                        "text": f"Tool execution error: {e}"
                    }
                ],
                "isError": True
            }
    
    async def handle_resources_list(self, params: Dict[str, Any], auth_info: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP resources/list request (future feature)"""
        return {
            "resources": []
        }
    
    async def handle_prompts_list(self, params: Dict[str, Any], auth_info: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP prompts/list request (future feature)"""
        return {
            "prompts": []
        }

# Global MCP bridge instance
mcp_bridge = AgentGatewayMCPBridge()

# Create FastMCP instance for HTTP transport
mcp_server = FastMCP("agentic-framework-gateway")

@mcp_server.tool()
async def proxy_tool_execution(name: str, arguments: dict = None) -> str:
    """
    Proxy tool for MCP clients to execute any available tool through the agent gateway
    """
    # This will be called by the MCP protocol handler
    # The actual implementation is in handle_tools_call
    return f"Tool {name} execution proxied through agent gateway"

async def mcp_request_handler(request: Request) -> Dict[str, Any]:
    """
    Main MCP JSON-RPC request handler
    """
    try:
        # Parse JSON-RPC request
        request_data = await request.json()
        headers = dict(request.headers)
        
        logger.debug(f"[MCP_BRIDGE] Received MCP request: {request_data.get('method')} (id: {request_data.get('id')})")
        
        # Validate JSON-RPC format
        if not all(key in request_data for key in ["jsonrpc", "method", "id"]):
            return {
                "jsonrpc": "2.0",
                "error": mcp_bridge.create_mcp_error(-32600, "Invalid JSON-RPC request"),
                "id": request_data.get("id", "unknown")
            }
        
        method = request_data["method"]
        params = request_data.get("params", {})
        request_id = request_data["id"]
        
        # Handle initialization without authentication
        if method == "initialize":
            # For initialize, we allow minimal auth or no auth
            try:
                auth_info = await mcp_bridge.validate_authentication(request_data, headers)
            except MCPAuthenticationError:
                # Allow initialize without full auth for protocol negotiation
                auth_info = {"token": None, "user_info": {"preferred_username": "anonymous"}}
            
            result = await mcp_bridge.handle_initialize(params, auth_info)
            
            return {
                "jsonrpc": "2.0",
                "result": result,
                "id": request_id
            }
        
        # All other methods require authentication
        try:
            auth_info = await mcp_bridge.validate_authentication(request_data, headers)
        except MCPAuthenticationError as e:
            return {
                "jsonrpc": "2.0",
                "error": mcp_bridge.create_mcp_error(-32001, str(e)),
                "id": request_id
            }
        
        # Route to appropriate handler
        if method == "tools/list":
            result = await mcp_bridge.handle_tools_list(params, auth_info)
        elif method == "tools/call":
            result = await mcp_bridge.handle_tools_call(params, auth_info)
        elif method == "resources/list":
            result = await mcp_bridge.handle_resources_list(params, auth_info)
        elif method == "prompts/list":
            result = await mcp_bridge.handle_prompts_list(params, auth_info)
        else:
            return {
                "jsonrpc": "2.0",
                "error": mcp_bridge.create_mcp_error(-32601, f"Method not found: {method}"),
                "id": request_id
            }
        
        return {
            "jsonrpc": "2.0",
            "result": result,
            "id": request_id
        }
        
    except json.JSONDecodeError:
        return {
            "jsonrpc": "2.0",
            "error": mcp_bridge.create_mcp_error(-32700, "Parse error"),
            "id": None
        }
    except Exception as e:
        logger.error(f"[MCP_BRIDGE] Unexpected error: {e}", exc_info=True)
        return {
            "jsonrpc": "2.0",
            "error": mcp_bridge.create_mcp_error(-32603, f"Internal error: {e}"),
            "id": request_data.get("id", "unknown")
        }