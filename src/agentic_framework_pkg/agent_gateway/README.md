# Agent Gateway

The Agent Gateway is a central component of the Agentic Framework, providing a unified, OpenAI-compatible API for interacting with various agent configurations. It manages tool registration, authentication, and stateful agent execution, making it a powerful and flexible entry point for any AI-powered application.

## Key Features

-   **OpenAI API Compatibility**: Exposes a wide range of standard OpenAI endpoints, allowing you to use official client libraries (`openai`, `langchain`, etc.) out of the box.
-   **Stateful Agent Execution**: Implements the full Assistants API (`Assistants`, `Threads`, `Runs`) for creating persistent agents that can maintain long-running conversations.
-   **Dynamic Tool Management**: Supports dynamic registration and authorization of tools, which are then provisioned to the agent at runtime.
-   **Multi-Modal Support**: Includes a Files API for uploading and managing documents and images, enabling agents to perform tasks like Retrieval-Augmented Generation (RAG) and vision-based queries.
-   **Extensible Authentication**: Integrated with Keycloak for robust, JWT-based authentication and authorization.

## Implemented OpenAI API Endpoints

The gateway currently supports the following OpenAI-compatible endpoints:

-   **Models**: `GET /v1/models`
-   **Chat Completions**: `POST /v1/chat/completions` (with tool call support)
-   **Embeddings**: `POST /v1/embeddings`
-   **Files**: `POST`, `GET`, `DELETE /v1/files`
-   **Assistants**: `POST`, `GET`, `DELETE /v1/assistants`
-   **Threads**: `POST /v1/threads`, `POST /v1/threads/{thread_id}/messages`, `GET /v1/threads/{thread_id}/messages`
-   **Runs**: `POST /v1/threads/{thread_id}/runs`, `GET /v1/threads/{thread_id}/runs/{run_id}`

## Getting Started

### Running with Docker Compose

The most reliable way to run the Agent Gateway is as part of the project's Docker Compose setup. The `start-chapter-resources.sh` script in the root of the chapter directory will build and orchestrate all the necessary services, including the gateway, Keycloak, and Redis.

```bash
# From the chapter's root directory
./start-chapter-resources.sh
```

The gateway will be available on the host at `http://localhost:8083`.

### Running Standalone (for Development)

After installing the package in editable mode (`uv pip install -e .`), you can run the agent gateway server directly. This is useful for local development and debugging.

```bash
run-agent-gateway
```

## Command-Line Client

A command-line client is provided for interacting with the gateway. It supports both interactive chat and file uploads.

### Interactive Chat

Start a chat session with a configured agent.

```bash
python -m agentic_framework_pkg.agent_gateway.cli.chat_client chat
```

Inside the chat, you can upload files at any time using the `/upload` command:

```
You: /upload /path/to/my_document.pdf /path/to/image.png
```

### File Upload

Upload one or more files directly from the command line. The client will automatically determine the correct purpose (`vision` or `assistants`) based on the file type.

```bash
python -m agentic_framework_pkg.agent_gateway.cli.chat_client upload /path/to/file.txt
```

## Integration with OpenWebUI

The Agent Gateway can also serve as a backend for frontends like OpenWebUI.

1.  **Run the Project**: Start all services using the `start-chapter-resources.sh` script.
2.  **Run OpenWebUI**:
    ```bash
    docker run -d -p 8902:8080 --add-host=host.docker.internal:host-gateway -v open-webui:/app/backend/data --name open-webui --restart always ghcr.io/open-webui/open-webui:main
    ```
3.  **Connect OpenWebUI to the Gateway**:
    -   Access OpenWebUI at `http://localhost:8902`.
    -   Navigate to Settings -> Connections.
    -   Set the "API Base URL" to `http://host.docker.internal:8083/v1`.
    -   Provide your JWT token for the `notebook-user` as the API Key.