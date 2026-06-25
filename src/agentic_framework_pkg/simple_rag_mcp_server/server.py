# src/agentic_framework_pkg/simple_rag_mcp_server/server.py
import os
from fastmcp import FastMCP

# Initialize FastMCP instance for the Simple RAG server
simple_rag_mcp = FastMCP(
    name=os.getenv("SIMPLE_RAG_MCP_SERVER_NAME", "AgenticFramework_SimpleRAG_MCP"),
    instructions="This MCP server provides tools for a simple, file-based RAG workflow.",
    # NOTE: stateless_http=True is passed to http_app() in main.py, not here.
    # FastMCP >=2.14 deprecated constructor kwargs; they must go in http_app().
)