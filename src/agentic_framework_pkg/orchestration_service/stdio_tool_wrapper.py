"""
This module provides the core functionality for creating and executing tools that
communicate over standard I/O (stdio).

It defines a generic wrapper that can turn any command-line executable that
reads JSON from stdin and writes JSON to stdout into a LangChain-compatible `Tool`.

Architectural Role:
-   **Tool Abstraction:** This wrapper is a key component for tool abstraction.
    It decouples the agent framework from the specific implementation language
    or environment of a tool.
-   **Used by ExternalToolManager:** The `ExternalToolManager` uses the
    `create_stdio_tool` factory to create tool instances for any registered
    tool that specifies `"protocol": "stdio"`.
"""
import asyncio
import json
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from typing import Type, Dict, Any, List, Optional

async def _run_stdio_tool(command: List[str], input_data: Dict[str, Any], working_directory: Optional[str] = None) -> str:
    """
    Asynchronously runs a command-line tool, passing JSON data via stdin
    and capturing JSON data from stdout.

    Args:
        command: The command and its arguments to execute.
        input_data: A dictionary of arguments to be serialized to JSON and
                    sent to the tool's stdin.
        working_directory: The directory in which to run the command.

    Returns:
        The JSON string captured from the tool's stdout.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_directory
        )

        input_json = json.dumps(input_data)
        stdout, stderr = await proc.communicate(input=input_json.encode())

        if proc.returncode != 0:
            error_message = stderr.decode().strip()
            return f"Error executing command '{command}': {error_message}"

        result_json = stdout.decode().strip()
        return result_json

    except FileNotFoundError:
        return f"Error: The command '{command[0]}' was not found."
    except Exception as e:
        return f"Failed to run stdio tool with command '{command}': {e}"

def create_stdio_tool(
    name: str,
    description: str,
    command: List[str],
    args_schema: Type[BaseModel],
    working_directory: Optional[str] = None
) -> StructuredTool:
    """
    Factory function to create a LangChain StructuredTool that executes a local command via stdio.

    Uses StructuredTool (not Tool) to support multi-parameter tool schemas.
    Tool() is single-input only and raises 'Too many arguments' for tools
    with 2+ parameters.

    Args:
        name: The name of the tool.
        description: The description of the tool.
        command: The command and arguments to execute.
        args_schema: The Pydantic model defining the tool's input arguments.
        working_directory: The directory in which to run the command.

    Returns:
        A LangChain `StructuredTool` instance supporting multi-argument inputs.
    """
    async def tool_func(**kwargs) -> str:
        return await _run_stdio_tool(command, kwargs, working_directory)

    return StructuredTool.from_function(
        name=name,
        description=description,
        func=None,
        coroutine=tool_func,
        args_schema=args_schema,
    )

# Example of a Pydantic model for the echo tool
class EchoToolSchema(BaseModel):
    """Input schema for the echo tool."""
    message: str = Field(..., description="The message to be echoed back.")