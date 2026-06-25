"""
This module defines the agent "model" configurations for the framework.

It acts as a registry where different agent personalities or configurations
can be defined. The `AGENT_CONFIGURATIONS` dictionary maps a model ID
(e.g., "agentic-framework/scientific-agent-v1") to the specific settings
required to initialize the `ScientificWorkflowAgent` for that personality.

Architectural Role:
-   **Single Source of Truth:** This file is the definitive source for all
    available agent configurations.
-   **Decoupling:** It decouples the agent's core logic (`ScientificWorkflowAgent`)
    from its specific configurations, making it easy to add, remove, or modify
    agent personalities without changing the core agent code.
-   **Used by Orchestrator:** The `orchestration_service`'s `/v1/models` endpoint
    reads from this dictionary to advertise the available "models" to clients.
"""
from .scientific_workflow.langchain_agent import ScientificWorkflowAgent
from .stdio_tool_wrapper import EchoToolSchema

# This dictionary defines the different "models" or agent personalities that this gateway exposes.
# The key is the model ID that clients will use. The value contains the settings needed to
# initialize the ScientificWorkflowAgent for that specific personality.
AGENT_CONFIGURATIONS = {
    "agentic-framework:scientific-agent-v1": {
        "description": "Default scientific agent with all tools enabled, including a sample stdio echo tool.",
        "agent_class": ScientificWorkflowAgent,
        "system_prompt": None,  # Use the default system prompt from the agent class
        "stdio_tools": [
            {
                "name": "echo_message_tool",
                "description": "A simple tool that echoes back a message. Useful for testing the stdio tool integration.",
                "command": ["python3", "tools/echo_tool.py"],
                "working_directory": "/app/agentic_framework_pkg/agent_gateway", # Relative to container's /app
                "args_schema": EchoToolSchema
            }
        ]
    },
    "agentic-framework:n8n-summary-agent": {
        "description": "A specialized agent with a system prompt optimized for summarizing data and providing concise answers suitable for n8n workflows.",
        "agent_class": ScientificWorkflowAgent,
        "system_prompt": "You are an expert summarization agent. Your goal is to provide clear, concise summaries of the information you find. Do not provide long explanations or conversational filler. Your output will be used in automated workflows.",
        "stdio_tools": [] # No stdio tools for this agent
    },
}