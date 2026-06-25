"""
This module provides a simple echo tool that runs as a local Python script.

It is used for demonstrating and testing the `stdio` tool invocation protocol
for executing local scripts. It reads a JSON object from stdin, extracts a
'message', and echoes it back to stdout in a JSON object. It also includes
basic logging to a file for debugging purposes.
"""
import sys
import json
import os

# Add a simple log to a file for debugging purposes
log_file_path = os.path.join(os.path.dirname(__file__), 'echo_tool.log')

def log(message):
    """Appends a message to the tool's log file."""
    with open(log_file_path, 'a') as f:
        f.write(f"{message}\n")

if __name__ == "__main__":
    # Clear log file for new run
    if os.path.exists(log_file_path):
        os.remove(log_file_path)

    log("Echo tool started.")
    
    try:
        input_json = sys.stdin.read()
        log(f"Received from stdin: {input_json}")

        if not input_json:
            log("Stdin was empty.")
            raise ValueError("Input JSON cannot be empty.")

        data = json.loads(input_json)
        log(f"Parsed JSON data: {data}")
        
        message = data.get("message", "")
        
        response = {
            "status": "success",
            "echo": f"The echo tool says: '{message}'"
        }
        log(f"Sending to stdout: {json.dumps(response)}")
        
        sys.stdout.write(json.dumps(response))
        
    except json.JSONDecodeError as e:
        error_message = f"Failed to decode JSON: {e}. Input was: '{input_json[:100]}...'"
        log(f"ERROR: {error_message}")
        error_response = {
            "status": "error",
            "message": error_message
        }
        # Writing error to stdout as per the wrapper's expectation for a return value
        sys.stdout.write(json.dumps(error_response))
        sys.exit(0) # Exit gracefully so stdout is captured
    except Exception as e:
        error_message = str(e)
        log(f"ERROR: {error_message}")
        error_response = {
            "status": "error",
            "message": error_message
        }
        sys.stdout.write(json.dumps(error_response))
        sys.exit(0) # Exit gracefully so stdout is captured