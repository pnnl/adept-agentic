"""
This module provides a simple echo tool that runs inside a Docker container.

It is used for demonstrating and testing the `stdio` tool invocation protocol
where the command to be executed is a `docker run` command.
"""
import sys
import json

def main():
    """
    Reads a JSON object from stdin, extracts a 'message', and echoes it
    back to stdout in a JSON object.
    """
    input_data = json.loads(sys.stdin.read())
    message = input_data.get("message", "")
    response = {"status": "success", "echo": f"Docker tool received: {message}"}
    sys.stdout.write(json.dumps(response))

if __name__ == "__main__":
    main()
