"""Meta-tools — MCP tools for managing AWS MCP server lifecycle."""

from loguru import logger

from .catalog import Catalog
from .models import ServerState
from .server_registry import ServerRegistry


def register_meta_tools(app, catalog: Catalog, registry: ServerRegistry) -> None:
    """Register lifecycle management tools on the FastMCP app."""

    @app.tool()
    async def load_aws_server(server_name: str) -> dict:
        """Hot-load an AWS MCP server subprocess with STS temporary credentials.

        This spawns the server as a stdio subprocess, performs MCP initialization,
        and discovers all available tools. The server's tools become available
        via the aws_tool_call tool with the server's namespace prefix.

        Args:
            server_name: Name of the server from the catalog,
                e.g. 's3-tables-mcp-server'.

        Returns:
            Server status including discovered tools.
        """
        catalog_entry = catalog.get(server_name)
        if not catalog_entry:
            return {
                "success": False,
                "error": f"Server '{server_name}' not found in catalog. "
                f"Use list_available_servers to see available servers.",
            }

        try:
            entry = await registry.load_server(catalog_entry)
            return {
                "success": True,
                "server_name": entry.catalog.name,
                "state": entry.state.value,
                "tool_prefix": entry.catalog.tool_prefix,
                "tools": [
                    {"name": t.qualified_name, "description": t.description}
                    for t in entry.tools
                ],
                "tool_count": len(entry.tools),
            }
        except RuntimeError as exc:
            return {"success": False, "error": str(exc)}

    @app.tool()
    async def unload_aws_server(server_name: str) -> dict:
        """Stop an AWS MCP server subprocess and remove its tools.

        Args:
            server_name: Name of the server to unload.

        Returns:
            Confirmation of unload.
        """
        entry = registry.get_entry(server_name)
        if not entry or entry.state != ServerState.running:
            return {
                "success": False,
                "error": f"Server '{server_name}' is not currently loaded.",
            }

        try:
            await registry.unload_server(server_name)
            return {"success": True, "server_name": server_name, "state": "stopped"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @app.tool()
    async def list_available_servers() -> dict:
        """List all AWS MCP servers in the catalog with their current load state.

        Returns:
            Catalog of available servers with state information.
        """
        servers = []
        for cat_entry in catalog.list_all():
            entry = registry.get_entry(cat_entry.name)
            state = entry.state.value if entry else "stopped"
            tool_count = len(entry.tools) if entry and entry.state == ServerState.running else 0
            servers.append({
                "name": cat_entry.name,
                "tool_prefix": cat_entry.tool_prefix,
                "description": cat_entry.description,
                "state": state,
                "tool_count": tool_count,
            })

        running = sum(1 for s in servers if s["state"] == "running")
        return {
            "total": len(servers),
            "running": running,
            "max_loaded": registry.max_loaded_servers,
            "servers": servers,
        }

    @app.tool()
    async def server_status(server_name: str) -> dict:
        """Get detailed status of a specific AWS MCP server.

        Args:
            server_name: Name of the server to query.

        Returns:
            Detailed server status including tools, load time, and errors.
        """
        cat_entry = catalog.get(server_name)
        if not cat_entry:
            return {"success": False, "error": f"Server '{server_name}' not in catalog."}

        entry = registry.get_entry(server_name)
        if not entry:
            return {
                "success": True,
                "server_name": server_name,
                "state": "stopped",
                "description": cat_entry.description,
                "tool_prefix": cat_entry.tool_prefix,
                "tools": [],
            }

        return {
            "success": True,
            "server_name": server_name,
            "state": entry.state.value,
            "description": cat_entry.description,
            "tool_prefix": cat_entry.tool_prefix,
            "tools": [
                {"name": t.qualified_name, "description": t.description}
                for t in entry.tools
            ],
            "tool_count": len(entry.tools),
            "loaded_at": entry.loaded_at.isoformat() if entry.loaded_at else None,
            "pid": entry.pid,
            "error": entry.error,
        }

    logger.info("Registered 4 meta-tools: load, unload, list, status")
