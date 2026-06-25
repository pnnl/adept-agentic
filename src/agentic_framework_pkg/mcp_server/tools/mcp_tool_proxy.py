
"""
**DEPRECATED:** This module is deprecated in favor of the centralized
`ExternalToolManager` in the `agent-gateway`. The functionality for dynamic
tool registration is now handled by the gateway's `/v1/tools/register` endpoint,
which provides a more robust and unified approach to tool integration.

This file is retained for posterity but should not be used in new development.
---
This module implements the MCP Tool Proxy, a set of tools that allows the main
LangChain agent to dynamically manage and invoke tools from other MCP servers.
This provides a flexible, runtime-managed tool system instead of a static,
compile-time one.

The configuration of registered MCP servers is persisted in a ChromaDB collection,
ensuring that the agent's knowledge of external tools survives container restarts.

As a "meta-tool," the MCP Tool Proxy gives the agent the powerful capability
to dynamically expand its own toolset at runtime. Instead of being limited to a
statically compiled list of tools, the agent can use this proxy to discover,
register, and invoke tools from other MCP servers on the network, all without
requiring a restart or redeployment.
"""
import os
import json
from typing import Dict, Any, Optional, List

import chromadb
from chromadb.utils import embedding_functions
try:
    # Try new FastMCP API
    from fastmcp import FastMCP, TextContent, MCPClient
    from fastmcp.tools import Tool
except ImportError:
    try:
        # Fallback to older API
        from fastmcp import FastMCP, Tool, TextContent, MCPClient
    except ImportError:
        # Final fallback for MCP
        from mcp import FastMCP, TextContent, MCPClient
        from mcp.tools import Tool
from ...core.llm_agnostic_layer import LLMAgnosticClient

from ...logger_config import get_logger

logger = get_logger(__name__)

# --- ChromaDB Configuration ---
VECTOR_DB_URL = os.getenv("VECTOR_DB_URL", "http://vector_db_server:8001")
COLLECTION_NAME = "mcp_registered_servers"

class ChromaDBProxyConfigManager:
    """
    Manages the persistence of MCP server configurations in ChromaDB.
    """
    def __init__(self, db_url: str, collection_name: str):
        try:
            self.client = chromadb.HttpClient(url=db_url)
            # A simple embedding function is sufficient as we are not doing semantic search on the content.
            self.embedding_function = embedding_functions.DefaultEmbeddingFunction()
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"ChromaDBProxyConfigManager connected to {db_url} and got collection '{collection_name}'.")
        except Exception as e:
            logger.error(f"Failed to connect to ChromaDB at {db_url}: {e}", exc_info=True)
            self.client = None
            self.collection = None

    def add_server(self, alias: str, url: str, headers: Optional[Dict[str, str]] = None):
        if not self.collection:
            raise ConnectionError("ChromaDB collection is not available.")
        
        # Use the alias as the ID for easy retrieval
        self.collection.add(
            ids=[alias],
            documents=[f"Configuration for MCP server with alias '{alias}' at URL '{url}'."],
            metadatas=[{"url": url, "headers": json.dumps(headers or {})}]
        )
        logger.info(f"Added/updated MCP server '{alias}' in ChromaDB.")

    def get_server(self, alias: str) -> Optional[Dict[str, Any]]:
        if not self.collection:
            raise ConnectionError("ChromaDB collection is not available.")
            
        result = self.collection.get(ids=[alias])
        if not result or not result.get('ids'):
            return None
            
        metadata = result['metadatas'][0]
        return {
            "alias": alias,
            "url": metadata.get("url"),
            "headers": json.loads(metadata.get("headers", '{}'))
        }

    def get_all_servers(self) -> List[Dict[str, Any]]:
        if not self.collection:
            raise ConnectionError("ChromaDB collection is not available.")
        
        results = self.collection.get()
        servers = []
        for i, server_id in enumerate(results['ids']):
            metadata = results['metadatas'][i]
            servers.append({
                "alias": server_id,
                "url": metadata.get("url"),
                "headers": json.loads(metadata.get("headers", '{}'))
            })
        return servers

# --- MCP Tool Proxy Tools ---

class AddMCPServerTool(Tool):
    name = "add_mcp_server"
    description = "Registers a new MCP server URL with a unique alias and optional authentication headers for easy reference."
    
    def __init__(self):
        self.config_manager = ChromaDBProxyConfigManager(VECTOR_DB_URL, COLLECTION_NAME)

    async def __call__(self, url: str, alias: str, headers: Optional[Dict[str, str]] = None) -> List[TextContent]:
        try:
            # Ping the server's /tools endpoint to verify it's a valid MCP server
            async with MCPClient(url, headers=headers) as client:
                await client.list_tools()
            
            self.config_manager.add_server(alias=alias, url=url, headers=headers)
            return [TextContent(text=f"Successfully registered and verified MCP server with alias '{alias}'.")]
        except Exception as e:
            logger.error(f"Failed to add MCP server '{alias}' at {url}: {e}", exc_info=True)
            return [TextContent(text=f"Error: Could not add MCP server '{alias}'. Failed to verify server or save configuration. Reason: {e}")]

class ListMCPToolsTool(Tool):
    name = "list_mcp_tools"
    description = "Lists all available tools from all registered MCP servers, or from a specific list of server aliases."

    def __init__(self):
        self.config_manager = ChromaDBProxyConfigManager(VECTOR_DB_URL, COLLECTION_NAME)

    async def __call__(self, aliases: Optional[List[str]] = None) -> List[TextContent]:
        servers_to_check = []
        if aliases:
            for alias in aliases:
                server = self.config_manager.get_server(alias)
                if server:
                    servers_to_check.append(server)
                else:
                    return [TextContent(text=f"Error: No server found with alias '{alias}'.")]
        else:
            servers_to_check = self.config_manager.get_all_servers()

        if not servers_to_check:
            return [TextContent(text="No MCP servers are registered yet. Use 'add_mcp_server' to add one.")]

        full_report = ""
        for server in servers_to_check:
            try:
                async with MCPClient(server['url'], headers=server['headers']) as client:
                    tools = await client.list_tools()
                    full_report += f"--- Tools from server '{server['alias']}' ---\n"
                    for tool in tools:
                        full_report += f"- {tool.name}: {tool.description}\n"
            except Exception as e:
                full_report += f"--- Could not fetch tools from server '{server['alias']}' ---\n"
                full_report += f"Error: {e}\n"
        
        return [TextContent(text=full_report)]

class InvokeMCPToolTool(Tool):
    name = "invoke_mcp_tool"
    description = "Invokes a specific tool on a registered MCP server identified by its alias."

    def __init__(self):
        self.config_manager = ChromaDBProxyConfigManager(VECTOR_DB_URL, COLLECTION_NAME)

    async def __call__(self, alias: str, tool_name: str, parameters: Dict[str, Any]) -> List[TextContent]:
        server = self.config_manager.get_server(alias)
        if not server:
            return [TextContent(text=f"Error: No MCP server found with alias '{alias}'.")]

        try:
            async with MCPClient(server['url'], headers=server['headers']) as client:
                result = await client.call_tool(tool_name, parameters)
                # Assuming the result is a list of ContentPart, extract text from the first one for simplicity
                if result and isinstance(result, list) and hasattr(result[0], 'text'):
                    return [TextContent(text=result[0].text)]
                return [TextContent(text=str(result))] # Fallback
        except Exception as e:
            logger.error(f"Error invoking tool '{tool_name}' on server '{alias}': {e}", exc_info=True)
            return [TextContent(text=f"Error invoking tool '{tool_name}' on '{alias}': {e}")]

class ExportMCPServersToJSONTool(Tool):
    name = "export_mcp_servers_to_json"
    description = "Exports the current list of registered MCP servers and their configurations to a JSON string."

    def __init__(self):
        self.config_manager = ChromaDBProxyConfigManager(VECTOR_DB_URL, COLLECTION_NAME)

    async def __call__(self) -> List[TextContent]:
        try:
            servers = self.config_manager.get_all_servers()
            json_output = json.dumps(servers, indent=2)
            return [TextContent(text=json_output)]
        except Exception as e:
            logger.error(f"Failed to export MCP server configurations: {e}", exc_info=True)
            return [TextContent(text=f"Error exporting configurations: {e}")]

# This list is imported by the MCP server to expose the tools.
tools = [AddMCPServerTool(), ListMCPToolsTool(), InvokeMCPToolTool(), ExportMCPServersToJSONTool()]

def register_tools(mcp: FastMCP, llm_client: Optional[LLMAgnosticClient] = None):
    """Registers the MCP Tool Proxy tools with the FastMCP instance."""
    # The llm_client is not used here but is included for signature consistency.
    for tool in tools:
        mcp.add_tool(tool)
    logger.info(f"Registered {len(tools)} MCP tool proxy tools.")

