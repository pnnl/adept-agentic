"""FastMCP application — AWS MCP Server Manager entry point."""

import argparse
import signal

from dotenv import load_dotenv
from fastmcp import FastMCP
from loguru import logger

from .catalog import Catalog
from .config import AWSMCPManagerConfig
from .meta_tools import register_meta_tools
from .server_registry import ServerRegistry
from .sts_broker import STSBroker
from .tool_proxy import register_tool_proxy

# FastMCP application singleton
app = FastMCP(
    name="AWS MCP Server Manager",
    instructions=(
        "Meta-MCP server that manages 65+ AWS MCP servers on demand. "
        "Use load_aws_server to hot-load a server, then aws_tool_call to "
        "invoke its tools. Tools are namespaced as 'prefix.tool_name' "
        "(e.g. 's3_tables.create_table_bucket'). "
        "Use list_available_servers to see the catalog and "
        "list_loaded_tools to see currently available tools."
    ),
)

# Module-level references for shutdown
_registry = None


def main() -> None:
    """Entry point: initialize components, register tools, start server."""
    global _registry

    load_dotenv()

    parser = argparse.ArgumentParser(description="AWS MCP Server Manager")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="streamable-http",
        help="MCP transport (default: streamable-http)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Listen port (default: from config or 8003)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Listen host (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    # Initialize components
    config = AWSMCPManagerConfig()
    port = args.port or config.port

    logger.info("AWS MCP Server Manager starting on {}:{}", args.host, port)
    logger.info("STS config: role_arn={}, region={}", config.sts_role_arn or "(none)", config.aws_region)
    logger.info("Limits: max_loaded={}, subprocess_timeout={}s", config.max_loaded_servers, config.subprocess_timeout)

    sts_broker = STSBroker(config)
    catalog = Catalog()
    catalog.load_from_file()

    _registry = ServerRegistry(config, sts_broker)

    # Register tools on the app
    register_meta_tools(app, catalog, _registry)
    register_tool_proxy(app, _registry)

    logger.info("Registered 6 MCP tools, catalog has {} servers", len(catalog))

    # Run the server
    app.run(transport=args.transport, port=port, host=args.host)


if __name__ == "__main__":
    main()
