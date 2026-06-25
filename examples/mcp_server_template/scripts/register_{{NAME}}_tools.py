#!/usr/bin/env python3
"""
{{DISPLAY_NAME}} MCP Tool Registration Script

Discovers tools via MockMCP introspection (tools/list) and registers them with
the ADEPT orchestration service's external tool catalog.

Usage:
    # Register all tools
    python register_{{NAME}}_tools.py --register

    # Deregister all tools
    python register_{{NAME}}_tools.py --deregister

    # Show tool schemas (no registration)
    python register_{{NAME}}_tools.py --show-schemas

    # Verify registration status
    python register_{{NAME}}_tools.py --verify

Environment Variables:
    {{NAME_UPPER}}_MCP_HOST: MCP server hostname (default: {{NAME}}_mcp_server)
    {{NAME_UPPER}}_MCP_PORT: MCP server port (default: {{MCP_PORT}})
    ORCHESTRATION_SERVICE_URL: ADEPT orchestration service URL
    KEYCLOAK_URL: Keycloak auth endpoint
    KEYCLOAK_REALM: Keycloak realm (default: agentic-framework)
    GATEWAY_CLIENT_ID: Service client ID for authentication
    GATEWAY_CLIENT_SECRET: Service client secret
"""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field


# =============================================================================
# Configuration
# =============================================================================

TOOL_MODULES = [
    "{{NAME}}_mcp.tools.example_tool",
    "{{NAME}}_mcp.tools.get_job_status",
]

MCP_HOST = os.getenv("{{NAME_UPPER}}_MCP_HOST", "{{NAME}}_mcp_server")
MCP_PORT = int(os.getenv("{{NAME_UPPER}}_MCP_PORT", "{{MCP_PORT}}"))
ORCHESTRATION_SERVICE_URL = os.getenv(
    "ORCHESTRATION_SERVICE_URL", "http://orchestration_service:8084"
)
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8180")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "agentic-framework")
GATEWAY_CLIENT_ID = os.getenv("GATEWAY_CLIENT_ID", "")
GATEWAY_CLIENT_SECRET = os.getenv("GATEWAY_CLIENT_SECRET", "")


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class ToolDefinition:
    """Parsed tool definition from MCP tools/list response."""

    name: str
    description: str
    input_schema: Dict[str, Any]


class ToolRegistrationRequest(BaseModel):
    """Request payload for /admin/tools/register endpoint."""

    name: str = Field(..., description="Unique tool name")
    description: str = Field(..., description="Human-readable description")
    tool_type: str = Field(default="mcp", description="Tool type (mcp, http, stdio)")
    config: Dict[str, Any] = Field(..., description="Tool-specific configuration")
    input_schema: Dict[str, Any] = Field(..., description="JSON Schema for tool inputs")
    acl: Optional[Dict[str, Any]] = Field(
        default=None, description="Access control list (groups, users)"
    )


# =============================================================================
# Helper Functions
# =============================================================================

def _extract_tool(tool_data: Dict[str, Any]) -> Optional[ToolDefinition]:
    """Extract tool definition from MCP tools/list response item."""
    try:
        return ToolDefinition(
            name=tool_data["name"],
            description=tool_data.get("description", ""),
            input_schema=tool_data.get("inputSchema", {}),
        )
    except KeyError as e:
        print(f"Warning: Skipping malformed tool definition (missing {e})")
        return None


async def _get_service_token() -> Optional[str]:
    """Obtain service client access token from Keycloak."""
    if not GATEWAY_CLIENT_ID or not GATEWAY_CLIENT_SECRET:
        print("Error: GATEWAY_CLIENT_ID and GATEWAY_CLIENT_SECRET must be set")
        return None

    token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": GATEWAY_CLIENT_ID,
        "client_secret": GATEWAY_CLIENT_SECRET,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(token_url, data=payload)
            response.raise_for_status()
            return response.json()["access_token"]
    except Exception as e:
        print(f"Error obtaining service token: {e}")
        return None


async def _check_mcp_health() -> bool:
    """Check if {{DISPLAY_NAME}} MCP server is reachable."""
    health_url = f"http://{MCP_HOST}:{MCP_PORT}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(health_url)
            response.raise_for_status()
            data = response.json()
            print(f"✓ {{DISPLAY_NAME}} MCP server healthy: {data.get('status', 'unknown')}")
            return True
    except Exception as e:
        print(f"✗ {{DISPLAY_NAME}} MCP server unreachable at {health_url}: {e}")
        return False


# =============================================================================
# Core Operations
# =============================================================================

async def discover_tools(mcp_url: str) -> List[ToolDefinition]:
    """Discover tools via MCP JSON-RPC tools/list call."""
    print(f"\n=== Discovering {{DISPLAY_NAME}} MCP Tools ===")
    print(f"MCP URL: {mcp_url}")

    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(mcp_url, json=request_payload)
            response.raise_for_status()
            rpc_response = response.json()

            if "error" in rpc_response:
                print(f"Error from MCP server: {rpc_response['error']}")
                return []

            tools_data = rpc_response.get("result", {}).get("tools", [])
            tools = [_extract_tool(t) for t in tools_data if _extract_tool(t)]
            print(f"✓ Discovered {len(tools)} tools")
            return tools

    except Exception as e:
        print(f"✗ Failed to discover tools: {e}")
        return []


async def register_tools(
    tools: List[ToolDefinition], mcp_url: str, auth_token: str
) -> None:
    """Register discovered tools with orchestration service."""
    print(f"\n=== Registering {{DISPLAY_NAME}} Tools ===")

    register_url = f"{ORCHESTRATION_SERVICE_URL}/admin/tools/register"
    headers = {"Authorization": f"Bearer {auth_token}"}

    success_count = 0
    for tool in tools:
        payload = ToolRegistrationRequest(
            name=tool.name,
            description=tool.description,
            tool_type="mcp",
            config={"mcp_url": mcp_url},
            input_schema=tool.input_schema,
            acl={"allowed_groups": ["scientists", "admin"]},
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    register_url, json=payload.model_dump(), headers=headers
                )
                response.raise_for_status()
                print(f"  ✓ Registered: {tool.name}")
                success_count += 1
        except httpx.HTTPStatusError as e:
            print(f"  ✗ Failed to register {tool.name}: {e.response.status_code}")
            print(f"    Response: {e.response.text}")
        except Exception as e:
            print(f"  ✗ Failed to register {tool.name}: {e}")

    print(f"\n✓ Registered {success_count}/{len(tools)} tools")


async def deregister_tools(tools: List[ToolDefinition], auth_token: str) -> None:
    """Deregister tools from orchestration service."""
    print(f"\n=== Deregistering {{DISPLAY_NAME}} Tools ===")

    deregister_url = f"{ORCHESTRATION_SERVICE_URL}/admin/tools/deregister"
    headers = {"Authorization": f"Bearer {auth_token}"}

    success_count = 0
    for tool in tools:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(
                    f"{deregister_url}/{tool.name}", headers=headers
                )
                response.raise_for_status()
                print(f"  ✓ Deregistered: {tool.name}")
                success_count += 1
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                print(f"  - Not found (already removed): {tool.name}")
            else:
                print(f"  ✗ Failed to deregister {tool.name}: {e.response.status_code}")
        except Exception as e:
            print(f"  ✗ Failed to deregister {tool.name}: {e}")

    print(f"\n✓ Deregistered {success_count}/{len(tools)} tools")


async def verify_tools(tools: List[ToolDefinition], auth_token: str) -> None:
    """Verify tool registration status."""
    print(f"\n=== Verifying {{DISPLAY_NAME}} Tool Registration ===")

    list_url = f"{ORCHESTRATION_SERVICE_URL}/admin/tools/list"
    headers = {"Authorization": f"Bearer {auth_token}"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(list_url, headers=headers)
            response.raise_for_status()
            registered_tools = response.json().get("tools", [])
            registered_names = {t["name"] for t in registered_tools}

            for tool in tools:
                status = "✓ Registered" if tool.name in registered_names else "✗ Not registered"
                print(f"  {status}: {tool.name}")

    except Exception as e:
        print(f"✗ Failed to verify tools: {e}")


def show_schemas(tools: List[ToolDefinition]) -> None:
    """Display tool schemas in human-readable format."""
    print(f"\n=== {{DISPLAY_NAME}} Tool Schemas ===\n")

    for tool in tools:
        print(f"Tool: {tool.name}")
        print(f"Description: {tool.description}")
        print(f"Input Schema:")
        print(json.dumps(tool.input_schema, indent=2))
        print("-" * 80)


# =============================================================================
# Main Entry Point
# =============================================================================

async def main() -> int:
    """Main entry point for tool registration workflow."""
    parser = argparse.ArgumentParser(
        description="{{DISPLAY_NAME}} MCP Tool Registration Script"
    )
    parser.add_argument(
        "--register", action="store_true", help="Register tools with orchestration service"
    )
    parser.add_argument(
        "--deregister", action="store_true", help="Deregister tools from orchestration service"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Verify tool registration status"
    )
    parser.add_argument(
        "--show-schemas", action="store_true", help="Display tool schemas (no registration)"
    )
    parser.add_argument(
        "--mcp-url",
        default=f"http://{MCP_HOST}:{MCP_PORT}/mcp",
        help=f"MCP server URL (default: http://{MCP_HOST}:{MCP_PORT}/mcp)",
    )

    args = parser.parse_args()

    # Require at least one action
    if not any([args.register, args.deregister, args.verify, args.show_schemas]):
        parser.print_help()
        return 1

    # Health check
    if not await _check_mcp_health():
        print("\n✗ {{DISPLAY_NAME}} MCP server is not reachable. Exiting.")
        return 1

    # Discover tools
    tools = await discover_tools(args.mcp_url)
    if not tools:
        print("\n✗ No tools discovered. Exiting.")
        return 1

    # Show schemas only (no auth needed)
    if args.show_schemas:
        show_schemas(tools)
        return 0

    # Get auth token for orchestration service operations
    auth_token = await _get_service_token()
    if not auth_token:
        print("\n✗ Failed to obtain service authentication token. Exiting.")
        return 1

    # Execute requested operations
    if args.register:
        await register_tools(tools, args.mcp_url, auth_token)

    if args.deregister:
        await deregister_tools(tools, auth_token)

    if args.verify:
        await verify_tools(tools, auth_token)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
