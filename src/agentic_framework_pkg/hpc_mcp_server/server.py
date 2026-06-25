import os
from fastmcp import FastMCP

# Initialize FastMCP instance for the HPC server
hpc_mcp = FastMCP(
    name=os.getenv("HPC_MCP_SERVER_NAME", "AgenticFramework_HPC_MCP"),
    instructions="This MCP server provides tools for High-Performance Computing tasks, including Nextflow pipeline execution.",
    # NOTE: stateless_http=True is passed to http_app() in main.py, not here.
    # FastMCP >=2.14 deprecated constructor kwargs; they must go in http_app().
)