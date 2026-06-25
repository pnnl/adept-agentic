# Agent Gateway Tools: Reference & Testing

## 1. Purpose of This Directory

The Python scripts and Dockerfiles in this directory are **reference implementations and testing harnesses** for the `stdio` tool protocol. They are **not** the primary, production-level tools of the framework. Those live in the dedicated executor services (`mcp_server`, `hpc_mcp_server`, etc.).

The purpose of these files is to:

*   **Demonstrate the `stdio` Protocol:** Provide simple, clear examples of how to create a command-line tool that can be integrated with the agentic framework.
*   **Test the `StdioToolWrapper`:** Serve as invaluable, simple targets for testing the core `ExternalToolManager` and its ability to run and communicate with `stdio` processes.
*   **Provide a Developer Starting Point:** Act as a template for developers who want to create their own `stdio`-based tools.

---

## 2. The `stdio` Protocol Contract

The contract for a tool to be compatible with the `stdio` wrapper is extremely simple:

1.  The tool **MUST** read a single, complete JSON object from its standard input (`stdin`). This JSON will contain the arguments for the tool call.
2.  The tool **MUST** write a single, complete JSON object to its standard output (`stdout`). This JSON represents the result of the tool's execution.
3.  If the tool encounters an error, it should still write a JSON object to `stdout` containing an "error" key with a descriptive message. Any output to `stderr` will be captured and logged but is primarily for debugging.

---

## 3. How to Register These Tools

A tool script only becomes available to the agent after it has been **registered** with the orchestration service. Registration involves sending a JSON configuration that tells the framework the tool's name, description, and how to run it.

You can register a tool using the Management UI or programmatically via the API.

### Example: Registering the `echo_tool.py`

**Step 1: Create a JSON Configuration File**

Create a file named `register_echo_tool.json` with the following content. This file defines the tool's metadata and tells the `ExternalToolManager` to run it using the Python interpreter.

```json
{
  "name": "echo_message_tool",
  "description": "A simple tool that echoes back a message. Useful for testing the stdio tool integration.",
  "args_schema": {
    "message": {
      "type": "string",
      "description": "The message to be echoed back."
    }
  },
  "invocation": {
    "protocol": "stdio",
    "connection": {
      "command": [
        "python",
        "/app/src/agentic_framework_pkg/agent_gateway/tools/echo_tool.py"
      ],
      "working_directory": "/app/src"
    }
  },
  "acl": {
    "global": true
  }
}
```
*Note: The paths in the `"command"` array are the absolute paths *inside the orchestration service container* where the tool script is located.*

**Step 2: Register via the API**

Use a tool like `curl` to POST this configuration to the orchestration service's registration endpoint. This requires a valid admin JWT token.

```bash
# First, get an admin token from Keycloak
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8180/realms/master/protocol/openid-connect/token" \
-H "Content-Type: application/x-www-form-urlencoded" \
-d "client_id=admin-cli" \
-d "username=admin" \
-d "password=admin" \
-d "grant_type=password" | jq -r .access_token)

# Now, register the tool
curl -X POST http://localhost:8084/admin/tools/register \
-H "Content-Type: application/json" \
-H "Authorization: Bearer $ADMIN_TOKEN" \
-d @register_echo_tool.json
```

Once registered, the `echo_message_tool` will immediately become available to the `ScientificWorkflowAgent`.

---

## 4. Invocation Patterns Demonstrated

This directory contains examples of the different ways `stdio` tools can be invoked:

1.  **Direct Script Execution:** `echo_tool.py` and `sys_info_tool.py` are designed to be run directly by an interpreter like Python.
2.  **Containerized Execution:** `Dockerfile.sys_info_tool` shows how a script can be packaged into a Docker image. The registration `command` would then be `["docker", "run", "--rm", "-i", "your-image-name:latest"]`.
3.  **Adapter/Proxy Pattern:** `gateway_run_adapter.py` is a `stdio` tool that, when run, turns around and calls another tool via a different mechanism (`docker mcp gateway run`). This shows how the `stdio` protocol can be used to create bridges to other subsystems.
