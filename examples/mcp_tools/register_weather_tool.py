#!/usr/bin/env python3
"""
Register Weather MCP Tool with ADEPT
=====================================

This script demonstrates how to programmatically register an external MCP tool
using the ADEPT SDK.

🔐 SECURITY NOTE - Authentication Pattern
==========================================

This example uses service tokens for DEMONSTRATION purposes only.

**Production Recommendations**:

For Human Users (CLI):
  ✅ Use: agentic auth login (JWT tokens with MFA support)
  ❌ Don't: Read service tokens from credentials directory

For Services (CI/CD, Automation):
  ✅ Use: Service tokens from secrets manager (Vault, AWS SM, Azure KV)
  ❌ Don't: Share service tokens across users/teams

Zero-Trust Architecture:
  ✅ Every request validates JWT or service token
  ✅ Group-based authorization (ACLs)
  ✅ User attribution for audit logs
  ✅ MFA support (enable in Keycloak)

See: docs/security/MCP_TOOL_REGISTRATION_AUTHENTICATION.md

Usage:
    # Development/Testing (service token from credentials)
    export ADEPT_API_KEY="sk-service-..."
    python examples/mcp_tools/register_weather_tool.py

    # Production (user JWT token)
    agentic auth login  # Authenticate via Keycloak (supports MFA)
    export ADEPT_JWT_TOKEN=$(cat ~/.agentic/auth_token)
    python examples/mcp_tools/register_weather_tool.py

Requirements:
    pip install agentic-framework-sdk
"""

import argparse
import os
import sys
from typing import Optional

# Try to import ADEPT SDK
try:
    from agentic_framework_sdk import OpenAI
except ImportError:
    print("ERROR: agentic-framework-sdk not installed")
    print("Install with: pip install -e .")
    sys.exit(1)


def register_stdio_tool(client: OpenAI) -> dict:
    """
    Register the stdio-based weather MCP tool.

    Args:
        client: ADEPT SDK client

    Returns:
        Registration response dictionary
    """
    tool_config = {
        "name": "weather_service",
        "type": "mcp",
        "url": "stdio:python examples/mcp_tools/example_weather_mcp_server.py",
        "description": "Get weather data for any city using stdio transport",
        "acl_groups": ["notebook-users", "scientists", "admin"],
        "metadata": {
            "transport": "stdio",
            "tools": ["get_weather", "get_forecast"],
            "example": "stdio-based MCP server"
        }
    }

    print("📋 Tool Configuration:")
    print(f"  Name: {tool_config['name']}")
    print(f"  Type: {tool_config['type']}")
    print(f"  URL: {tool_config['url']}")
    print(f"  Description: {tool_config['description']}")
    print(f"  ACL Groups: {', '.join(tool_config['acl_groups'])}")
    print()

    print("🚀 Registering tool with ADEPT...")
    response = client.agentic.tools.register(tool_config)

    return response


def register_http_tool(client: OpenAI, port: int = 8090) -> dict:
    """
    Register the HTTP-based weather MCP tool.

    Args:
        client: ADEPT SDK client
        port: HTTP server port (default: 8090)

    Returns:
        Registration response dictionary
    """
    tool_config = {
        "name": "weather_http",
        "type": "mcp",
        "url": f"http://localhost:{port}",
        "description": "HTTP-based weather service with MCP protocol",
        "acl_groups": ["notebook-users", "scientists", "admin"],
        "metadata": {
            "transport": "http",
            "tools": ["get_weather", "get_forecast"],
            "endpoints": {
                "list": "/tools/list",
                "call": "/tools/call"
            },
            "example": "HTTP-based MCP server with FastAPI"
        }
    }

    print("📋 Tool Configuration:")
    print(f"  Name: {tool_config['name']}")
    print(f"  Type: {tool_config['type']}")
    print(f"  URL: {tool_config['url']}")
    print(f"  Description: {tool_config['description']}")
    print(f"  ACL Groups: {', '.join(tool_config['acl_groups'])}")
    print()

    print("⚠️  Note: Ensure HTTP server is running before registration:")
    print(f"   python examples/mcp_tools/example_weather_http_server.py")
    print()

    print("🚀 Registering tool with ADEPT...")
    response = client.agentic.tools.register(tool_config)

    return response


def list_tools(client: OpenAI) -> dict:
    """
    List all registered tools.

    Args:
        client: ADEPT SDK client

    Returns:
        Tools list response
    """
    print("📋 Fetching registered tools...")
    response = client.agentic.tools.list()

    if isinstance(response, dict) and "tools" in response:
        tools = response["tools"]
    elif isinstance(response, list):
        tools = response
    else:
        tools = []

    print(f"\n✅ Found {len(tools)} registered tools:")
    for tool in tools:
        print(f"\n  • {tool.get('name', 'Unknown')}")
        print(f"    Type: {tool.get('type', 'N/A')}")
        print(f"    Description: {tool.get('description', 'No description')[:80]}")
        if "url" in tool:
            print(f"    URL: {tool['url']}")

    return response


def main():
    """Main registration script."""
    parser = argparse.ArgumentParser(
        description="Register weather MCP tool with ADEPT framework"
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Register HTTP-based tool instead of stdio"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8090,
        help="HTTP server port (default: 8090)"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.getenv("ADEPT_BASE_URL", "https://api.agentic.local"),
        help="ADEPT API base URL"
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only list registered tools, don't register new ones"
    )

    args = parser.parse_args()

    # Get authentication credentials
    api_key = os.getenv("ADEPT_API_KEY")
    jwt_token = os.getenv("ADEPT_JWT_TOKEN")

    if not api_key and not jwt_token:
        print("❌ ERROR: No authentication credentials found")
        print("\nSet one of:")
        print("  export ADEPT_API_KEY='sk-service-...'")
        print("  export ADEPT_JWT_TOKEN='eyJhbGci...'")
        print("\nGet service token with:")
        print("  cat deployment/local/docker-compose/.env-keycloak-credentials-dir/.env-keycloak-credentials | grep OPENWEBUI_SERVICE_API_KEY")
        sys.exit(1)

    print("=" * 80)
    print("ADEPT MCP Tool Registration")
    print("=" * 80)
    print()

    # Initialize SDK client
    try:
        client = OpenAI(
            base_url=args.base_url,
            api_key=jwt_token if jwt_token else api_key
        )
        print(f"✅ Connected to ADEPT at {args.base_url}")
        print()
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize SDK client: {e}")
        sys.exit(1)

    # List tools if --list-only flag is set
    if args.list_only:
        try:
            list_tools(client)
            print()
            print("=" * 80)
            return
        except Exception as e:
            print(f"\n❌ ERROR: Failed to list tools: {e}")
            sys.exit(1)

    # Register tool
    try:
        if args.http:
            response = register_http_tool(client, port=args.port)
        else:
            response = register_stdio_tool(client)

        print("\n✅ Tool registered successfully!")
        print(f"\nResponse: {response}")
        print()

        # List all tools to confirm
        print("-" * 80)
        list_tools(client)

    except Exception as e:
        print(f"\n❌ ERROR: Failed to register tool: {e}")
        print("\nTroubleshooting:")
        print("  1. Ensure ADEPT services are running (make start)")
        print("  2. Check authentication credentials")
        print("  3. Verify network connectivity to", args.base_url)
        sys.exit(1)

    print()
    print("=" * 80)
    print("✅ Registration Complete!")
    print()
    print("Next steps:")
    print("  1. Test the tool:")
    print("     agentic tools list")
    print("  2. Use in agent workflows:")
    print("     The agent will automatically discover and use the weather tools")
    print("=" * 80)


if __name__ == "__main__":
    main()
