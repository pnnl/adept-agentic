"""
MCP Protocol Router for Agent Gateway

This router provides the HTTP endpoint for MCP JSON-RPC communication,
enabling MCP clients to interact with the agent gateway using the standard
Model Context Protocol.

Endpoints:
- POST /mcp - Main MCP JSON-RPC endpoint
- GET /mcp - MCP capabilities and server info  
- GET /mcp/health - MCP server health check
"""
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import JSONResponse
import json
from typing import Dict, Any

from ..mcp_bridge import mcp_request_handler, mcp_bridge
from ...logger_config import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.post("/mcp", 
             summary="MCP JSON-RPC Endpoint",
             description="Main endpoint for MCP (Model Context Protocol) JSON-RPC communication",
             tags=["MCP Protocol"])
async def mcp_jsonrpc_endpoint(request: Request):
    """
    Handle MCP JSON-RPC requests from MCP clients.
    
    Supports all standard MCP methods:
    - initialize: Protocol negotiation
    - tools/list: List available tools  
    - tools/call: Execute tools
    - resources/list: List resources (future)
    - prompts/list: List prompts (future)
    
    Authentication:
    - Requires JWT token in Authorization header or X-Auth-Token header
    - Token must be valid for the agent gateway's Keycloak realm
    
    Example MCP request:
    ```json
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }
    ```
    """
    try:
        # Handle the MCP JSON-RPC request
        response_data = await mcp_request_handler(request)
        
        # Return JSON-RPC response
        return JSONResponse(
            content=response_data,
            headers={
                "Content-Type": "application/json",
                "X-MCP-Server": "agentic-framework-gateway/1.0.0"
            }
        )
        
    except Exception as e:
        logger.error(f"[MCP_ROUTER] Unexpected error in MCP endpoint: {e}", exc_info=True)
        
        # Return JSON-RPC error response
        error_response = {
            "jsonrpc": "2.0",
            "error": {
                "code": -32603,
                "message": f"Internal server error: {e}"
            },
            "id": None
        }
        
        return JSONResponse(
            content=error_response,
            status_code=500,
            headers={"Content-Type": "application/json"}
        )

@router.get("/mcp",
           summary="MCP Server Information",
           description="Get MCP server capabilities and information",
           tags=["MCP Protocol"])
async def mcp_server_info():
    """
    Get MCP server information and capabilities.
    
    This endpoint provides information about the MCP server's capabilities
    without requiring a full JSON-RPC initialize call.
    
    Returns:
    - Server information (name, version)
    - Supported capabilities (tools, resources, prompts)
    - Protocol version
    - Authentication requirements
    """
    return JSONResponse(
        content={
            "server": mcp_bridge.server_info,
            "protocolVersion": mcp_bridge.protocol_version,
            "capabilities": mcp_bridge.capabilities,
            "authentication": {
                "required": True,
                "methods": ["bearer_token", "custom_header"],
                "headers": ["Authorization", "X-Auth-Token"]
            },
            "endpoints": {
                "jsonrpc": "/mcp",
                "health": "/mcp/health",
                "info": "/mcp"
            },
            "documentation": "https://spec.modelcontextprotocol.io/specification/"
        },
        headers={
            "Content-Type": "application/json",
            "X-MCP-Server": f"{mcp_bridge.server_info['name']}/{mcp_bridge.server_info['version']}"
        }
    )

@router.get("/mcp/health",
           summary="MCP Server Health Check",
           description="Health check endpoint for MCP server monitoring",
           tags=["MCP Protocol"])
async def mcp_health_check():
    """
    Health check endpoint for the MCP server.
    
    This endpoint can be used by monitoring systems to check if the
    MCP bridge is operational and can communicate with the orchestration service.
    """
    try:
        # Test connectivity to orchestration service
        orchestration_healthy = True
        try:
            import httpx
            import os
            orchestration_url = os.getenv("ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{orchestration_url}/health", timeout=5)
                orchestration_healthy = response.status_code == 200
        except:
            orchestration_healthy = False
        
        health_status = {
            "status": "healthy" if orchestration_healthy else "degraded",
            "mcp_bridge": "operational",
            "orchestration_service": "healthy" if orchestration_healthy else "unreachable",
            "protocol_version": mcp_bridge.protocol_version,
            "capabilities": list(mcp_bridge.capabilities.keys()),
            "timestamp": "2025-08-26T03:15:00Z"  # Will be replaced with actual timestamp
        }
        
        status_code = 200 if orchestration_healthy else 503
        
        return JSONResponse(
            content=health_status,
            status_code=status_code,
            headers={
                "Content-Type": "application/json",
                "X-MCP-Server": f"{mcp_bridge.server_info['name']}/{mcp_bridge.server_info['version']}"
            }
        )
        
    except Exception as e:
        logger.error(f"[MCP_ROUTER] Health check failed: {e}")
        
        return JSONResponse(
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": "2025-08-26T03:15:00Z"
            },
            status_code=503,
            headers={"Content-Type": "application/json"}
        )

@router.options("/mcp",
               summary="MCP CORS Preflight", 
               description="Handle CORS preflight requests for MCP endpoint",
               tags=["MCP Protocol"])
async def mcp_options():
    """Handle CORS preflight requests for MCP clients"""
    return Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Auth-Token",
            "Access-Control-Max-Age": "86400"
        }
    )