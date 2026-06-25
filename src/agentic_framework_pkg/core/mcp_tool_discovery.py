"""
Dynamic MCP Tool Discovery System

Replaces hardcoded tool configurations with runtime discovery via MCP server introspection.
This eliminates the "dual maintenance" problem where tool definitions existed in both
@mcp.tool() decorators and hardcoded JSON structures.

Architecture:
1. Introspect MCP servers via JSON-RPC tools/list calls
2. Cache results with fallback to static config for resilience  
3. Merge with external tools from tool_manager
4. Provide single source of truth for all tool configurations
"""
import os
import json
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import httpx

from ..logger_config import get_logger

logger = get_logger(__name__)

@dataclass
class MCPServer:
    """Represents an MCP server configuration"""
    name: str
    url: str
    description: str
    enabled: bool = True
    timeout: int = 10
    retry_count: int = 2

@dataclass 
class ToolConfig:
    """Unified tool configuration from MCP discovery"""
    name: str
    description: str
    server: str
    tool_type: str  # "mcp", "external"
    args_schema: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None

class MCPToolDiscovery:
    """
    Dynamically discovers tools from MCP servers, providing single source of truth
    for tool configurations without hardcoded JSON maintenance.
    """
    
    def __init__(self):
        self.mcp_servers: Dict[str, MCPServer] = {}
        self.tool_cache: Dict[str, List[ToolConfig]] = {}
        self.cache_ttl = 300  # 5 minutes
        self.last_discovery: Optional[float] = None
        self._initialize_mcp_servers()
    
    def _initialize_mcp_servers(self):
        """Initialize known MCP servers from environment configuration"""
        # Core MCP servers in the framework
        server_configs = [
            {
                "name": "mcp_server",
                "url": os.getenv("MCP_SERVER_URL", "http://mcp_server:8082"),
                "description": "General scientific tools server"
            },
            {
                "name": "sandbox_mcp_server", 
                "url": os.getenv("SANDBOX_MCP_SERVER_URL", "http://sandbox_mcp_server:8083"),
                "description": "Sandboxed code execution server"
            },
            {
                "name": "hpc_mcp_server",
                "url": os.getenv("HPC_MCP_SERVER_URL", "http://hpc_mcp_server:8084"), 
                "description": "HPC pipeline execution server"
            }
        ]
        
        for config in server_configs:
            server = MCPServer(
                name=config["name"],
                url=config["url"],
                description=config["description"]
            )
            self.mcp_servers[config["name"]] = server
            logger.info(f"Configured MCP server: {config['name']} at {config['url']}")
    
    async def discover_all_tools(self, force_refresh: bool = False) -> List[ToolConfig]:
        """
        Discover tools from all configured MCP servers.
        
        Args:
            force_refresh: Skip cache and force fresh discovery
            
        Returns:
            List of discovered tool configurations
        """
        import time
        current_time = time.time()
        
        # Check cache validity
        if (not force_refresh and 
            self.last_discovery and 
            current_time - self.last_discovery < self.cache_ttl and
            self.tool_cache):
            logger.debug("Using cached tool discovery results")
            return self._flatten_tool_cache()
        
        logger.info("Performing fresh MCP tool discovery...")
        all_tools = []
        
        # Discover from each MCP server
        for server_name, server in self.mcp_servers.items():
            if not server.enabled:
                logger.debug(f"Skipping disabled server: {server_name}")
                continue
                
            try:
                server_tools = await self._discover_server_tools(server)
                self.tool_cache[server_name] = server_tools
                all_tools.extend(server_tools)
                
                logger.info(f"Discovered {len(server_tools)} tools from {server_name}")
                
            except Exception as e:
                logger.warning(f"Failed to discover tools from {server_name}: {e} (expected if mesh not fully activated)")

                # Use fallback if available
                fallback_tools = self._get_fallback_tools(server_name)
                if fallback_tools:
                    logger.info(f"Using fallback configuration for {server_name}: {len(fallback_tools)} tools")
                    self.tool_cache[server_name] = fallback_tools
                    all_tools.extend(fallback_tools)
                else:
                    logger.warning(f"No fallback available for {server_name} (expected during startup)")
        
        self.last_discovery = current_time
        logger.info(f"Tool discovery completed: {len(all_tools)} total tools discovered")
        return all_tools
    
    async def _discover_server_tools(self, server: MCPServer) -> List[ToolConfig]:
        """Discover tools from a single MCP server via JSON-RPC"""
        tools = []
        
        for attempt in range(server.retry_count + 1):
            try:
                async with httpx.AsyncClient(timeout=server.timeout) as client:
                    # MCP JSON-RPC tools/list request
                    rpc_request = {
                        "jsonrpc": "2.0",
                        "id": f"discover_{server.name}_{attempt}",
                        "method": "tools/list",
                        "params": {}
                    }
                    
                    # Note: Perhaps check whether the server url already ends with /mcp to avoid double slashes
                    endpoint_url = server.url
                    if not endpoint_url.endswith("/mcp"):
                        endpoint_url += "/mcp"
                    
                    response = await client.post(
                        endpoint_url,  # Standard MCP endpoint should be /mcp
                        json=rpc_request,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream",  # Session 62: Match fastmcp.Client header pattern
                        }
                    )
                    
                    if response.status_code != 200:
                        http_error_message = f"HTTP {response.status_code} from {server.name} (expected if mesh not fully activated)"
                        logger.warning(http_error_message)
                        raise httpx.HTTPStatusError(
                            f"HTTP {response.status_code}",
                            request=response.request,
                            response=response
                        )
                    
                    rpc_response = response.json()
                    
                    if "error" in rpc_response:
                        raise Exception(f"MCP error: {rpc_response['error']}")
                    
                    if "result" not in rpc_response or "tools" not in rpc_response["result"]:
                        raise Exception("Invalid MCP response structure")
                    
                    # Convert MCP tools to ToolConfig objects
                    mcp_tools = rpc_response["result"]["tools"]
                    for tool_data in mcp_tools:
                        tool_config = ToolConfig(
                            name=tool_data["name"],
                            description=tool_data.get("description", "No description available"),
                            server=server.name,
                            tool_type="mcp",
                            args_schema=tool_data.get("inputSchema", {}),
                            metadata={
                                "server_url": server.url,
                                "discovery_method": "json_rpc",
                                "discovery_timestamp": self.last_discovery
                            }
                        )
                        tools.append(tool_config)
                    
                    logger.debug(f"Successfully discovered {len(tools)} tools from {server.name}")
                    break  # Success, exit retry loop
                    
            except Exception as e:
                if attempt < server.retry_count:
                    logger.warning(f"Attempt {attempt + 1} failed for {server.name}: {e}, retrying...")
                    await asyncio.sleep(1)  # Brief delay before retry
                else:
                    raise e  # Final attempt failed, re-raise
        
        return tools
    
    def _get_fallback_tools(self, server_name: str) -> List[ToolConfig]:
        """
        Get static fallback tool configuration when discovery fails.
        This maintains system resilience when MCP servers are unreachable.
        """
        fallback_configs = {
            "mcp_server": [
                {"name": "query_csv", "description": "Query CSV data"},
                {"name": "store_note", "description": "Store notes"},
                {"name": "retrieve_notes", "description": "Retrieve stored notes"}, 
                {"name": "uniprot_search", "description": "Search UniProt database"},
                {"name": "websearch", "description": "Search the web"},
                {"name": "web_scraping", "description": "Web scraping tool"},
                {"name": "blastp_biopython", "description": "BLASTP protein search"},
                {"name": "blastn_biopython", "description": "BLASTN nucleotide search"},
                {"name": "pubchem_search", "description": "Search PubChem database"},
                {"name": "pubchem_compound_properties", "description": "Get compound properties"},
                {"name": "list_uploaded_files", "description": "List uploaded files"},
                {"name": "alphafold_prediction", "description": "AlphaFold structure prediction"},
                {"name": "query_stored_alphafold", "description": "Query stored AlphaFold data"}
            ],
            "sandbox_mcp_server": [
                {"name": "perform_calculation", "description": "Perform calculations in sandbox"},
                {"name": "execute_code", "description": "Execute code in sandbox"}
            ],
            "hpc_mcp_server": [
                {"name": "run_nextflow_blast", "description": "Run Nextflow BLAST pipeline"},
                {"name": "run_video_transcription", "description": "Video transcription tool"},
                {"name": "gitxray_scan", "description": "GitXray repository analysis"}
            ]
        }
        
        if server_name not in fallback_configs:
            return []
            
        fallback_tools = []
        for tool_data in fallback_configs[server_name]:
            tool_config = ToolConfig(
                name=tool_data["name"],
                description=tool_data["description"],
                server=server_name,
                tool_type="mcp",
                args_schema={},  # No schema in fallback
                metadata={
                    "discovery_method": "fallback",
                    "fallback_reason": "mcp_server_unreachable"
                }
            )
            fallback_tools.append(tool_config)
            
        return fallback_tools
    
    def _flatten_tool_cache(self) -> List[ToolConfig]:
        """Flatten cached tools from all servers into single list"""
        all_tools = []
        for server_tools in self.tool_cache.values():
            all_tools.extend(server_tools)
        return all_tools
    
    async def get_server_health(self) -> Dict[str, Dict[str, Any]]:
        """Check health status of all MCP servers"""
        health_status = {}
        
        for server_name, server in self.mcp_servers.items():
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(f"{server.url}/health")
                    
                    if response.status_code == 200:
                        health_data = response.json()
                        status = "healthy"
                    else:
                        health_data = {"error": f"HTTP {response.status_code}"}
                        status = "unhealthy"
                        
            except Exception as e:
                health_data = {"error": str(e)}
                status = "unreachable"
            
            health_status[server_name] = {
                "status": status,
                "url": server.url,
                "enabled": server.enabled,
                "health_data": health_data,
                "cached_tools": len(self.tool_cache.get(server_name, []))
            }
        
        return health_status
    
    def get_tool_by_name(self, tool_name: str) -> Optional[ToolConfig]:
        """Find a tool configuration by name across all servers"""
        for server_tools in self.tool_cache.values():
            for tool in server_tools:
                if tool.name == tool_name:
                    return tool
        return None
    
    def get_tools_by_server(self, server_name: str) -> List[ToolConfig]:
        """Get all tools for a specific server"""
        tools = []
        try:
            tools = self.tool_cache.get(server_name, [])
        except Exception as e:
            logger.warning(f"Dynamic tool discovery via MCPToolDiscovery could not obtain the set of dynamically added MCP tools.")
            logger.warning(f"Dynamic tool discovery via MCPToolDiscovery error message: {e}")
        return tools
    

# Global instance
mcp_discovery = MCPToolDiscovery()
