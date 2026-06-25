"""
This module provides a universal adapter for executing MCP (Multi-Component
Protocol) tools via the `docker mcp gateway run` command.

It acts as a bridge, allowing the Agent Gateway to invoke any tool available
to the MCP CLI as if it were a standard `stdio` tool. This is a powerful
mechanism for testing and debugging, but it is not recommended for production
use due to the overhead of spawning a subprocess for each tool call.
"""
import sys
import json
import subprocess

def main():
    """
    Reads a JSON object from stdin containing the target tool's name and
    arguments, executes it using `docker mcp gateway run`, and passes the
    result back to stdout.
    """
    try:
        # 1. Read the input from the Agent Gateway
        input_data_str = sys.stdin.read()
        input_data = json.loads(input_data_str)

        tool_name = input_data.get("mcp_tool_name")
        tool_args = input_data.get("mcp_tool_args", {})

        if not tool_name:
            raise ValueError("mcp_tool_name must be provided.")

        # 2. Construct and execute the `docker mcp gateway run` command
        command = ["docker", "mcp", "gateway", "run", tool_name]
        
        # The arguments for the target tool must be passed as a JSON string to the subprocess's stdin
        process = subprocess.run(
            command,
            input=json.dumps(tool_args).encode('utf-8'),
            capture_output=True,
            check=True, # Raise an exception if the command fails
            timeout=120 # 2-minute timeout
        )

        # 3. Pass the result from the subprocess back to the Agent Gateway
        sys.stdout.write(process.stdout.decode('utf-8'))

    except subprocess.CalledProcessError as e:
        # If the subprocess fails, return its stderr as the error message
        error_response = {
            "status": "error",
            "message": f"The underlying tool '{tool_name}' failed.",
            "details": e.stderr.decode('utf-8')
        }
        sys.stdout.write(json.dumps(error_response))
    except Exception as e:
        error_response = {
            "status": "error",
            "message": str(e)
        }
        sys.stdout.write(json.dumps(error_response))

if __name__ == "__main__":
    main()