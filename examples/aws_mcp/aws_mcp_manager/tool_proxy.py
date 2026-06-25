"""Tool proxy — dispatch tool calls to loaded AWS MCP server subprocesses."""

from typing import Any

from loguru import logger

from .server_registry import ServerRegistry


def register_tool_proxy(app, registry: ServerRegistry) -> None:
    """Register tool dispatch and listing tools on the FastMCP app."""

    @app.tool()
    async def aws_tool_call(tool_name: str, arguments: dict[str, Any] | None = None) -> dict:
        """Dispatch a tool call to the correct loaded AWS MCP server subprocess.

        The tool_name must be qualified with the server's namespace prefix,
        e.g. 's3_tables.create_table_bucket' or 'dynamodb.put_item'.

        Use list_loaded_tools to see all available qualified tool names.

        Args:
            tool_name: Qualified tool name in 'prefix.tool_name' format.
            arguments: Tool arguments as a JSON object.

        Returns:
            Tool execution result from the AWS MCP server.
        """
        arguments = arguments or {}
        try:
            result = await registry.call_tool(tool_name, arguments)
            # Extract content from MCP CallToolResult
            if hasattr(result, "content"):
                content_items = []
                for item in result.content:
                    if hasattr(item, "text"):
                        content_items.append(item.text)
                    elif hasattr(item, "data"):
                        content_items.append(item.data)
                    else:
                        content_items.append(str(item))
                return {
                    "success": True,
                    "tool_name": tool_name,
                    "result": content_items if len(content_items) > 1 else content_items[0] if content_items else None,
                    "is_error": getattr(result, "isError", False),
                }
            return {"success": True, "tool_name": tool_name, "result": str(result)}
        except (RuntimeError, ValueError) as exc:
            return {"success": False, "tool_name": tool_name, "error": str(exc)}
        except Exception as exc:
            logger.exception("Unexpected error calling tool {}", tool_name)
            return {"success": False, "tool_name": tool_name, "error": str(exc)}

    @app.tool()
    async def list_loaded_tools() -> dict:
        """List all tools from all currently loaded AWS MCP servers.

        Returns:
            Aggregated list of available tools with their qualified names.
        """
        tools = registry.list_all_tools()
        grouped: dict[str, list] = {}
        for tool in tools:
            grouped.setdefault(tool.server_name, []).append({
                "qualified_name": tool.qualified_name,
                "name": tool.name,
                "description": tool.description,
            })

        return {
            "total_tools": len(tools),
            "servers": {
                name: {"tool_count": len(items), "tools": items}
                for name, items in grouped.items()
            },
        }

    logger.info("Registered 2 tool-proxy tools: aws_tool_call, list_loaded_tools")
