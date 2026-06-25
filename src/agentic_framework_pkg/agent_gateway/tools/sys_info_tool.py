"""
This module provides a simple `stdio` tool that retrieves basic system
information from the container where it is executed.

It is used for testing the `stdio` tool invocation protocol.
"""
import sys
import json
import platform
import os

def main():
    """
    Gathers system information and writes it to stdout as a JSON object.
    """
    # This tool doesn't require any input, but it's good practice to handle it.
    try:
        json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # No input, which is fine for this tool.
        pass

    response = {
        "status": "success",
        "os_type": platform.system(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "container_hostname": os.getenv("HOSTNAME", "N/A")
    }
    
    # Write the JSON response to standard output
    sys.stdout.write(json.dumps(response))

if __name__ == "__main__":
    main()