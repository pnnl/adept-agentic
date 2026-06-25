"""
This module provides the ExternalToolManager, a central registry and factory
for all dynamically registered tools within the framework.

Architectural Role (in Three-Tier Model):
-   **Centralized Tool Registry:** This class, living in the `orchestration_service`,
    is the single source of truth for all dynamically registered tools.
-   **Persistence:** It uses Redis to persist tool configurations, ensuring that
    registered tools are not lost on service restart.
-   **Protocol-Agnostic Factory:** It uses a dictionary of factory functions to
    create LangChain-compatible `Tool` objects from their stored configurations,
    supporting multiple invocation protocols (e.g., `http`, `stdio`).
-   **Authorization and Scoping:** Its `get_authorized_tools` method is the
    critical link between the tool registry and the agent. It takes a user's
    credentials (forwarded from the gateway) and filters the master list of
    tools based on their stored Access Control Lists (ACLs). This ensures that
    the `ScientificWorkflowAgent` is only ever provisioned with the tools a
    user is permitted to use.
"""
import aiohttp
import json
from typing import Dict, List, Any, Type, Optional
from langchain_core.tools import StructuredTool, Tool
from pydantic import BaseModel, create_model
import os
import redis.asyncio as redis
import httpx
from ..logger_config import get_logger
from .stdio_tool_wrapper import create_stdio_tool
from .redis_client import get_tools_redis_client

try:
    from fastmcp import Client
except ImportError:
    Client = None  # type: ignore[assignment,misc]

logger = get_logger(__name__)

# Infrastructure fields auto-injected by the framework at runtime.
# These must NOT be required in the LLM-facing schema — the LLM
# doesn't know these values.  _mcp_tool_func / MCPToolWrapper
# handles them transparently (filtering or injecting as needed).
_FRAMEWORK_INJECTED_FIELDS = frozenset({
    "mcp_session_id",
    "session_id",
    "multi_agent_session_id",
    "gateway_session_id",
    "execution_timeout",
    "user_context",
    "session_hierarchy",
    "execution_context",
    "user_id",
    "username",
})


def _create_args_schema(schema_definition: Dict[str, Any]) -> Type[BaseModel]:
    """Dynamically creates a Pydantic model from a JSON schema definition."""
    field_definitions = {}
    if schema_definition:
        for prop_name, prop_details in schema_definition.items():
            field_type = str
            if prop_details.get("type") == "integer":
                field_type = int
            elif prop_details.get("type") == "number":
                field_type = float
            elif prop_details.get("type") == "boolean":
                field_type = bool
            elif prop_details.get("type") == "object":
                field_type = dict
            elif prop_details.get("type") == "array":
                field_type = list

            # Support optional fields with defaults
            default = prop_details.get("default", ...)
            # Framework-injected fields should never be required in
            # the LLM-facing schema, even if the tool's JSON schema
            # declares them without a default.
            if default is ... and prop_name in _FRAMEWORK_INJECTED_FIELDS:
                default = None
                field_type = Optional[field_type]
            description = prop_details.get("description", "")
            from pydantic import Field
            field_definitions[prop_name] = (field_type, Field(default=default, description=description))

    return create_model('DynamicToolArgs', **field_definitions)

async def _track_external_tool(
    tool_name: str,
    tool_class: str,
    server_url: str,
    kwargs: Dict[str, Any],
    output: str,
    duration: float,
    is_error: bool,
) -> None:
    """Non-blocking observability tracking for external tool calls."""
    try:
        from ..core.observability_factory import (
            ObservabilityFactory,
            truncate_for_observability,
        )
        obs_factory = ObservabilityFactory()
        mcp_session_id = kwargs.get("mcp_session_id") or "unknown"
        metadata = {
            "tool_name": tool_name,
            "tool_class": tool_class,
            "execution_duration_seconds": round(duration, 3),
            "mcp_session_id": mcp_session_id,
            "server_url": server_url,
            "parameter_keys": list(kwargs.keys()),
        }
        if is_error:
            metadata["status"] = "error"
        full, trunc = truncate_for_observability(output)
        await obs_factory.track_tool_output(
            thread_id=mcp_session_id,
            checkpoint_id=f"ext_tool_{tool_name}_{int(duration * 1000)}",
            tool_name=tool_name,
            full_output=full,
            truncated_output=trunc,
            output_size=len(output),
            metadata=metadata,
        )
    except Exception:
        pass  # Non-blocking — never disrupt tool execution


def _create_http_tool(config: Dict[str, Any]) -> StructuredTool:
    """Factory for creating a tool that communicates over HTTP.

    Uses StructuredTool (not Tool) to support multi-parameter tool schemas.
    Tool() is single-input only and raises 'Too many arguments' for tools
    with 2+ parameters.
    """
    connection_info = config["invocation"]["connection"]
    url = connection_info["url"]
    method = connection_info.get("method", "POST")
    headers = connection_info.get("headers", {})

    async def _http_tool_func(**kwargs) -> str:
        import time
        start_time = time.time()
        result = None
        error_output = None
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.request(method, url, json=kwargs) as response:
                    response.raise_for_status()
                    if "application/json" in response.content_type:
                        result = json.dumps(await response.json())
                    else:
                        result = await response.text()
                    return result
        except aiohttp.ClientError as e:
            logger.error(f"HTTP tool '{config['name']}' failed: {e}")
            error_output = f"Error: Could not connect to the tool service at {url}. {e}"
            return error_output
        except Exception as e:
            logger.error(f"An unexpected error occurred in HTTP tool '{config['name']}': {e}")
            error_output = f"An unexpected error occurred: {e}"
            return error_output
        finally:
            duration = time.time() - start_time
            output = result or error_output or ""
            await _track_external_tool(
                tool_name=config["name"],
                tool_class="ExternalHTTPTool",
                server_url=url,
                kwargs=kwargs,
                output=output,
                duration=duration,
                is_error=error_output is not None,
            )

    args_schema = _create_args_schema(config.get("args_schema", {}))

    return StructuredTool.from_function(
        name=config["name"],
        description=config["description"],
        func=None,
        coroutine=_http_tool_func,
        args_schema=args_schema,
    )

def _create_mcp_tool(config: Dict[str, Any]) -> StructuredTool:
    """Factory for creating a tool that communicates via MCP JSON-RPC protocol.

    Uses FastMCP Client to connect to a remote MCP server (Streamable HTTP transport).
    The client handles the MCP initialize handshake and tools/call JSON-RPC requests.

    Connection config shape:
        {
            "invocation": {
                "protocol": "mcp",
                "connection": {
                    "url": "http://opentrons_mcp_server:9003",  # Base URL
                    "tool_name": "execute_opentrons_protocol_tool"  # MCP tool name
                }
            }
        }
    """
    connection_info = config["invocation"]["connection"]
    url = connection_info["url"]
    tool_name = connection_info.get("tool_name", config["name"])

    async def _mcp_tool_func(**kwargs) -> str:
        import time
        start_time = time.time()
        # Filter out framework-injected args the MCP server doesn't expect.
        # Keep mcp_session_id — MCP servers use it for session isolation.
        filtered = {
            k: v
            for k, v in kwargs.items()
            if k not in ("user_id", "username")
        }
        result = None
        error_output = None
        try:
            if Client is None:
                error_output = "Error: fastmcp package is not installed. Install with: pip install fastmcp"
                return error_output

            async with Client(url) as client:
                mcp_result = await client.call_tool(tool_name, filtered, raise_on_error=False)
                if mcp_result.is_error:
                    error_text = " ".join(
                        c.text for c in mcp_result.content if hasattr(c, "text")
                    )
                    error_output = f"MCP tool error: {error_text}"
                    return error_output
                # Extract text from content list
                parts = []
                for content in mcp_result.content:
                    if hasattr(content, "text"):
                        parts.append(content.text)
                    elif hasattr(content, "data"):
                        parts.append(json.dumps(content.data))
                result = "\n".join(parts) if parts else json.dumps({"status": "completed"})
                return result
        except Exception as e:
            logger.error(f"MCP tool '{config['name']}' failed: {e}")
            error_output = f"Error: Could not connect to MCP server at {url}. {e}"
            return error_output
        finally:
            duration = time.time() - start_time
            output = result or error_output or ""
            await _track_external_tool(
                tool_name=config["name"],
                tool_class="ExternalMCPTool",
                server_url=url,
                kwargs=kwargs,
                output=output,
                duration=duration,
                is_error=error_output is not None,
            )

    args_schema = _create_args_schema(config.get("args_schema", {}))

    return StructuredTool.from_function(
        name=config["name"],
        description=config["description"],
        func=None,
        coroutine=_mcp_tool_func,
        args_schema=args_schema,
    )


def _create_stdio_tool_from_config(config: Dict[str, Any]) -> Tool:
    """Factory for creating a tool that communicates over stdio."""
    connection_info = config["invocation"]["connection"]
    command = connection_info.get("command")
    if not command or not isinstance(command, list):
        raise ValueError("Stdio tool configuration must include a 'command' list.")

    working_directory = connection_info.get("working_directory")
    
    return create_stdio_tool(
        name=config["name"],
        description=config["description"],
        command=command,
        args_schema=_create_args_schema(config.get("args_schema", {})),
        working_directory=working_directory
    )

class ExternalToolManager:
    """
    Manages the registration, persistence, and authorized retrieval of dynamic tools.
    """
    def __init__(self):
        """Initializes the tool manager."""
        self.redis_client = None
        self.registered_tools: Dict[str, Tool] = {}
        self.protocol_factories = {
            "http": _create_http_tool,
            "stdio": _create_stdio_tool_from_config,
            "mcp": _create_mcp_tool,
        }
        self._initialized = False  # Track initialization state to skip redundant retries
        self._load_tools_from_file()

    async def initialize(self):
        """Initializes the Redis client and loads all tool configurations from it."""
        self.redis_client = await get_tools_redis_client()
        logger.info(f"ExternalToolManager using shared Redis pool for database /0 (tools)")
        await self._load_tools_from_redis()
        self._initialized = True  # Mark as initialized to skip redundant retries

    def _load_tools_from_file(self):
        """Loads initial tool configurations from a local JSON file."""
        config_path = os.getenv("MCP_SERVERS_CONFIG_PATH", os.path.join(os.path.dirname(__file__), "config", "mcp_servers.json"))
        try:
            with open(config_path) as f:
                config_data = json.load(f)
                mcp_servers = config_data.get("mcpServers", {})
                for tool_name, server_config in mcp_servers.items():
                    server_config["name"] = tool_name # Add the name to the config dict
                    try:
                        self._register_tool_from_config(server_config)
                    except ValueError as e:
                        logger.error(f"Failed to load tool '{tool_name}' from file: {e}")
        except FileNotFoundError:
            logger.warning(f"{config_path} not found, skipping file-based tool loading.")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding {config_path}: {e}")

    async def _load_tools_from_redis(self):
        """
        Loads all tool configurations from Redis and populates the in-memory cache.
        Performance optimization: Uses MGET for batch retrieval.
        """
        try:
            # Optimization: Collect all keys first, then batch fetch with mget()
            keys = [key async for key in self.redis_client.scan_iter("external_tool:*")]

            if not keys:
                logger.info("No external tools found in Redis")
                return

            # Batch fetch all tool configs with single mget() call
            config_jsons = await self.redis_client.mget(keys)

            for key, config_json in zip(keys, config_jsons):
                if config_json:
                    config = json.loads(config_json)
                    try:
                        self._register_tool_from_config(config)
                    except ValueError as e:
                        logger.error(f"Failed to load tool '{config.get('name')}' from Redis: {e}")
        except Exception as e:
            logger.error(f"Error loading tools from Redis: {e}", exc_info=True)

    def _register_tool_from_config(self, config: Dict[str, Any]):
        """
        Creates a LangChain Tool from a configuration and caches it in memory.
        """
        tool_name = config.get("name")
        if not tool_name:
            raise ValueError("Tool configuration must include a 'name'.")

        invocation = config.get("invocation")
        if not invocation or "protocol" not in invocation:
            raise ValueError("Tool configuration must include an 'invocation' block with a 'protocol'.")
            
        protocol = invocation["protocol"]
        if protocol not in self.protocol_factories:
            raise ValueError(f"Unsupported tool protocol: '{protocol}'. Supported protocols are: {list(self.protocol_factories.keys())}")

        if tool_name in self.registered_tools:
            logger.warning(f"Tool '{tool_name}' is already registered. Overwriting.")

        # Create the tool using the appropriate factory
        factory = self.protocol_factories[protocol]
        tool = factory(config)
        
        self.registered_tools[tool_name] = tool
        logger.info(f"Successfully registered '{protocol}' tool: '{tool_name}'")

    def get_all_tools(self) -> List[Tool]:
        """Returns a list of all currently registered tool instances."""
        return list(self.registered_tools.values())

    async def get_tool_config(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves the raw configuration dictionary for a tool from Redis."""
        if not self.redis_client:
            logger.error("Redis client not initialized. Cannot fetch tool config.")
            return None
        try:
            config_json = await self.redis_client.get(f"external_tool:{tool_name}")
            if config_json:
                return json.loads(config_json)
            logger.warning(f"Tool config for '{tool_name}' not found in Redis.")
            return None
        except Exception as e:
            logger.error(f"Error fetching tool config for '{tool_name}' from Redis: {e}", exc_info=True)
            return None

    async def _introspect_http_tool(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Attempts to introspect an HTTP tool by fetching its OpenAPI schema.
        """
        url = config["invocation"]["connection"]["url"]
        try:
            openapi_url = f"{url.rstrip('/')}/openapi.json"
            async with httpx.AsyncClient() as client:
                response = await client.get(openapi_url, timeout=5)
                response.raise_for_status()
                openapi_spec = response.json()
                logger.info(f"Successfully introspected OpenAPI spec for {config['name']}")
                config["introspected_metadata"] = {"openapi_spec": openapi_spec}
        except httpx.RequestError as e:
            logger.warning(f"Could not fetch OpenAPI spec for {config['name']} at {openapi_url}: {e}")
            config["introspected_metadata"] = {"error": f"Could not fetch OpenAPI spec: {e}"}
        except json.JSONDecodeError:
            logger.warning(f"Could not decode OpenAPI spec for {config['name']} at {openapi_url}: Invalid JSON response.")
            config["introspected_metadata"] = {"error": "Invalid JSON response for OpenAPI spec."}
        except Exception as e:
            logger.error(f"Unexpected error during introspection for {config['name']}: {e}", exc_info=True)
            config["introspected_metadata"] = {"error": f"Unexpected introspection error: {e}"}
        return config

    async def register_tool(self, config: Dict[str, Any]):
        """
        Validates, registers, introspects (if applicable), and persists a tool.
        """
        tool_name = config.get("name")
        if not tool_name:
            raise ValueError("Tool configuration must include a 'name'.")

        if config.get("invocation", {}).get("protocol") == "http":
            config = await self._introspect_http_tool(config)

        self._register_tool_from_config(config)
        
        try:
            await self.redis_client.set(f"external_tool:{tool_name}", json.dumps(config))
            logger.info(f"Tool '{tool_name}' persisted to Redis.")
        except Exception as e:
            logger.error(f"Failed to persist tool '{tool_name}' to Redis: {e}", exc_info=True)
            raise

    async def get_authorized_tools(self, user_id: Optional[str], user_groups: List[str]) -> List[Tool]:
        """
        Returns a list of tools the user is authorized to use based on their ACLs.
        Performance optimization: Uses MGET for batch retrieval (10x faster than N individual gets).
        """
        authorized_tools = []
        try:
            # Optimization: Collect all keys first, then batch fetch with mget()
            keys = [key async for key in self.redis_client.scan_iter("external_tool:*")]

            if not keys:
                return authorized_tools

            # Batch fetch all tool configs with single mget() call (50ms → 5ms for 50 tools)
            config_jsons = await self.redis_client.mget(keys)

            for key, config_json in zip(keys, config_jsons):
                if config_json:
                    config = json.loads(config_json)
                    tool_id = config.get("name")
                    acl = config.get("acl", {})

                    # Auto-register tools found in Redis but not yet in memory
                    # (handles tools registered after service startup or session resume)
                    if tool_id and tool_id not in self.registered_tools:
                        try:
                            self._register_tool_from_config(config)
                        except (ValueError, Exception) as e:
                            logger.warning(f"Skipping tool '{tool_id}' (auto-register failed): {e}")
                            continue

                    if tool_id not in self.registered_tools:
                        continue

                    if acl.get("global"):
                        authorized_tools.append(self.registered_tools[tool_id])
                        continue

                    if user_id and user_id in acl.get("users", []):
                        authorized_tools.append(self.registered_tools[tool_id])
                        continue

                    if user_groups and any(group in acl.get("groups", []) for group in user_groups):
                        authorized_tools.append(self.registered_tools[tool_id])
                        continue
        except Exception as e:
            logger.error(f"Error retrieving authorized tools from Redis: {e}", exc_info=True)
            raise
        
        return authorized_tools

    async def delete_tool(self, tool_name: str):
        """Deletes a tool from Redis and the in-memory cache."""
        if tool_name not in self.registered_tools:
            raise ValueError(f"Tool '{tool_name}' not found.")
        
        try:
            await self.redis_client.delete(f"external_tool:{tool_name}")
            del self.registered_tools[tool_name]
            logger.info(f"Tool '{tool_name}' deleted successfully from Redis and cache.")
        except Exception as e:
            logger.error(f"Failed to delete tool '{tool_name}' from Redis: {e}", exc_info=True)
            raise

    async def update_tool_acl(self, tool_name: str, new_acl: Dict[str, Any]):
        """Updates the Access Control List (ACL) for a specific tool."""
        if tool_name not in self.registered_tools:
            raise ValueError(f"Tool '{tool_name}' not found.")

        # Use Lua script for atomic ACL update (prevents race conditions with 4 workers)
        lua_script = """
        local key = KEYS[1]
        local new_acl_json = ARGV[1]

        -- Get current tool configuration
        local config_json = redis.call('GET', key)
        if not config_json then
            return redis.error_reply("Tool configuration not found in Redis")
        end

        -- Parse JSON, update ACL field, and save back atomically
        local cjson = require('cjson')
        local config = cjson.decode(config_json)
        config.acl = cjson.decode(new_acl_json)
        redis.call('SET', key, cjson.encode(config))

        return cjson.encode(config)
        """

        try:
            # Execute Lua script atomically
            result = await self.redis_client.eval(
                lua_script,
                1,  # Number of keys
                f"external_tool:{tool_name}",  # KEYS[1]
                json.dumps(new_acl)  # ARGV[1]
            )

            # Reload tool configuration from Redis result
            config = json.loads(result)
            self._register_tool_from_config(config)
            logger.info(f"ACL for tool '{tool_name}' updated atomically via Lua script.")
        except Exception as e:
            logger.error(f"Failed to update ACL for tool '{tool_name}': {e}", exc_info=True)
            raise

# Global instance of the tool manager
tool_manager = ExternalToolManager()