#!/usr/bin/env python3
"""
Debug script to test MCP client connection and tool calling directly.
"""

import asyncio
import json
import os
from fastmcp import Client as MCPClient
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_mcp_client():
    """Test MCP client connection and tool calling"""
    mcp_server_url = "http://mcp_server:8080/mcp"
    
    print(f"Testing MCP client connection to: {mcp_server_url}")
    
    try:
        # Test connection and tool calling
        async with MCPClient(mcp_server_url) as client:
            print("✅ MCP Client connected successfully")
            
            # Try to list available tools
            print("\n🔍 Testing client.list_tools()...")
            try:
                tools = await client.list_tools()
                print(f"✅ Available tools: {tools}")
            except Exception as e:
                print(f"❌ Failed to list tools: {e}")
            
            # Try to call a simple tool
            print("\n🛠️ Testing client.call_tool('perform_calculation', {'expression': '2+2'})...")
            try:
                result = await client.call_tool("perform_calculation", {"expression": "2+2"})
                print(f"✅ Tool call result: {result}")
            except Exception as e:
                print(f"❌ Failed to call tool: {e}")
                
    except ConnectionRefusedError as e:
        print(f"❌ Connection refused: {e}")
    except Exception as e:
        print(f"❌ Client error: {e}")

if __name__ == "__main__":
    asyncio.run(test_mcp_client())