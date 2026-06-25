#!/bin/bash

# Create the main directory
mkdir -p docs/tutorial-branches

# --- Chapter 00: Introduction ---
CHAPTER_DIR="docs/tutorial-branches/chapter-00-introduction"
mkdir -p "$CHAPTER_DIR"
# This chapter is based on docs/agentic-framework-tutorial.md, which I don't have.
# I will create a description based on the README.md and the presentation.
# I will copy the README.md and the presentation to this folder.
cp README.md "$CHAPTER_DIR/"
cp "docs/Agentic_Framework_Presentation - 2025-07-01 - BioEconomy COIN with Notes.pdf" "$CHAPTER_DIR/"
# Create chapter-description.md
cat > "$CHAPTER_DIR/chapter-description.md" <<'EOL'
# Chapter 00: Introduction

This chapter introduces the Agentic Framework, a teaching tool and blueprint for integrating Large Language Models (LLMs) with scientific computing workflows. The framework is designed to be a hands-on guide for researchers, students, and developers looking to understand the intersection of AI and scientific computing.

## Key Concepts

- **Agentic Framework**: A modular framework for building agentic applications.
- **Model Context Protocol (MCP)**: A protocol for hosting tools and managing state.
- **Streamlit**: A Python library for creating web applications, used here as a user interface harness.
- **Langchain**: A framework for developing applications powered by language models.
- **RAG (Retrieval-Augmented Generation)**: A technique for providing LLMs with external knowledge.

## Core Components

The framework consists of several core components:

- **User Interface (Streamlit App)**: The primary frontend for user interaction.
- **Agent Orchestration (Langchain Agent)**: The central "brain" of the application.
- **Tool Execution Layer (MCP Servers)**: Dedicated servers for hosting and exposing tools.
- **LLM Interaction (LLM Agnostic Layer)**: A unified interface for interacting with different LLMs.
- **Data Persistence & State Management (ChromaDB)**: Manages the storage and retrieval of persistent data.

For more details, please refer to the `README.md` and the presentation PDF included in this folder.
EOL

# --- Chapter 01: Main ---
BRANCH="main"
CHAPTER_DIR="docs/tutorial-branches/chapter-01-main"
mkdir -p "$CHAPTER_DIR"
git archive "$BRANCH" | tar -x -C "$CHAPTER_DIR"
# Create chapter-description.md
cat > "$CHAPTER_DIR/chapter-description.md" <<'EOL'
# Chapter 01: Main - Basic Architecture

This chapter presents the foundational architecture of the Agentic Framework. At this stage, the framework is simple and demonstrates the core concepts of an agentic system.

## Architecture

- **Langchain Agent**: A basic Langchain agent is used for orchestration. It can understand user queries and use tools to fulfill requests.
- **No Chain-of-Thought (CoT)**: The agent in this version is a simple ReAct agent, which is a form of CoT, but for the purpose of this tutorial, we consider it a baseline before introducing more complex reasoning patterns with LangGraph.
- **MCP Session ID**: The `mcp_session_id` is introduced to manage state and context across tool calls.
- **Core Components**: The main components are the Streamlit UI, the Langchain agent, and a single MCP server hosting a basic set of tools.

This chapter serves as the starting point for the tutorial, upon which more advanced features will be added in subsequent chapters.
EOL

# --- Chapter 02: HPC MCP Server with CoT ---
BRANCH="feature-hpc-mcp-server-with-CoT"
CHAPTER_DIR="docs/tutorial-branches/chapter-02-hpc-mcp-server-with-cot"
mkdir -p "$CHAPTER_DIR"
git archive "$BRANCH" | tar -x -C "$CHAPTER_DIR"
# Create chapter-description.md
cat > "$CHAPTER_DIR/chapter-description.md" <<'EOL'
# Chapter 02: HPC MCP Server and Chain-of-Thought

This chapter enhances the framework by introducing a dedicated MCP server for High-Performance Computing (HPC) tasks and upgrading the agent to use LangGraph for more sophisticated Chain-of-Thought (CoT) reasoning.

## Key Additions

- **HPC MCP Server**: A new, separate `fastmcp` server is added to host computationally intensive tools like Nextflow pipelines for BLAST searches, video processing with Whisper, and code repository security scanning with GitXRay. This separation of concerns prevents long-running tasks from blocking the main MCP server.
- **LangGraph Integration**: The agent is upgraded from a simple agent to a more complex reasoning engine built with LangGraph. This allows for more explicit and controllable multi-step reasoning, which is a more advanced form of Chain-of-Thought. The agent can now create more complex plans and execute them.
- **Stateful Interactions**: The use of `mcp_session_id` is continued and becomes more important for tracking the state of these more complex, multi-step workflows.
EOL

# --- Chapter 03: LLM Sandbox and Multi-Agent MCP ---
BRANCH="feature-add-llm-sandbox-mcp-with-cot"
CHAPTER_DIR="docs/tutorial-branches/chapter-03-llm-sandbox-and-multi-agent"
mkdir -p "$CHAPTER_DIR"
git archive "$BRANCH" | tar -x -C "$CHAPTER_DIR"
# Create chapter-description.md
cat > "$CHAPTER_DIR/chapter-description.md" <<'EOL'
# Chapter 03: LLM Sandbox and Multi-Agent Capabilities

This chapter introduces two major features: a sandboxed environment for secure code execution and a multi-agent system for tackling complex tasks.

## Key Additions

- **Sandbox MCP Server**: A new, highly specialized MCP server is added to execute arbitrary Python, JavaScript, and shell code in a secure, isolated environment using the `llm-sandbox` library. This allows the agent to perform dynamic calculations, data manipulation, and other tasks that can be solved with code, without compromising the host system.
- **Multi-Agent Tool**: The main MCP server is updated with a `multi_agent_tool`. This tool allows for the creation and management of teams of AI agents. A "Planner" agent can generate a plan, which is then executed by a "Supervisor" agent that delegates tasks to worker agents with specific roles (e.g., "chemist", "bioinformatician"). This enables the framework to handle much more complex, multi-step workflows that require different areas of expertise.
- **Multi-Agent ID**: A `multi_agent_id` is introduced for context tracking within these complex, multi-agent sessions.
EOL

# --- Chapter 04: Kubernetes Deployment with Helm ---
BRANCH="feature-emsl-use-pnnl-proxy"
CHAPTER_DIR="docs/tutorial-branches/chapter-04-kubernetes-deployment"
mkdir -p "$CHAPTER_DIR"
git archive "$BRANCH" | tar -x -C "$CHAPTER_DIR"
# Create chapter-description.md
cat > "$CHAPTER_DIR/chapter-description.md" <<'EOL'
# Chapter 04: Kubernetes Deployment with Helm

This chapter focuses on the deployment of the Agentic Framework to a Kubernetes cluster using Helm charts. This represents a significant step towards a production-ready setup.

## Infrastructure as Code (IaC)

- **Helm Charts**: The framework now includes Helm charts to manage the deployment of its various components (MCP servers, Streamlit app, etc.) as Kubernetes resources. This allows for repeatable, configurable deployments.
- **Kubernetes Deployment**: The `infra/helm/README` provides detailed instructions on how to deploy the framework to a Kubernetes cluster, including:
    - Creating Kubernetes secrets for credentials.
    - Configuring `values.yaml` for the Helm chart.
    - Installing and upgrading Helm releases.
    - Port-forwarding to access the Streamlit UI.
- **On-Prem Deployment**: The work in this chapter is geared towards deploying the stack in an on-premise Kubernetes cluster, demonstrating how the framework can be adapted to different environments.
EOL

# --- Chapter 05: OpenWebUI Integration ---
BRANCH="feature-add-openwebui"
CHAPTER_DIR="docs/tutorial-branches/chapter-05-openwebui-integration"
mkdir -p "$CHAPTER_DIR"
git archive "$BRANCH" | tar -x -C "$CHAPTER_DIR"
# Create chapter-description.md
cat > "$CHAPTER_DIR/chapter-description.md" <<'EOL'
# Chapter 05: OpenWebUI Integration

This chapter introduces a new backend service that makes the Agentic Framework compatible with the OpenWebUI frontend.

## Key Features

- **OpenWebUI Backend**: A new service, `agent_gateway`, is added. It provides an OpenAI-compatible API endpoint (`/v1/chat/completions`).
- **Agent as a Model**: This new backend allows the `Scientific Workflow Agent` to be used as a backend model within OpenWebUI. This means you can interact with the agent through the rich chat interface of OpenWebUI.
- **Separation of Frontend and Backend**: The architecture is updated to demonstrate a clear separation between the frontend (OpenWebUI) and the backend (the agentic framework). This is managed through the `docker-compose-openwebui.yaml` file.
EOL

# --- Chapter 06: Advanced Multi-Agent Orchestration ---
BRANCH="feature-add-tutorial-for-manuscript"
CHAPTER_DIR="docs/tutorial-branches/chapter-06-advanced-multi-agent-orchestration"
mkdir -p "$CHAPTER_DIR"
git archive "$BRANCH" | tar -x -C "$CHAPTER_DIR"
# Create chapter-description.md
cat > "$CHAPTER_DIR/chapter-description.md" <<'EOL'
# Chapter 06: Advanced Multi-Agent Orchestration with Dual Execution Modes

This chapter introduces a significant enhancement to the multi-agent system, providing two distinct modes for orchestrating agent workflows.

## Key Features

- **Dual Execution Modes**: The `multi_agent_tool` now supports two supervisor patterns, selectable at session creation:
    - **Router Mode**: This mode uses a traditional supervisor agent that follows a static, pre-generated plan. A "Planner" agent creates the plan, and the "Supervisor" executes it by delegating tasks to worker agents. This is useful for well-defined, linear workflows.
    - **Graph Mode**: This mode uses a dynamic, `langgraph`-based supervisor that functions as a state machine. It decides the next best action at each step based on the current state, allowing for more flexible and adaptive problem-solving without a rigid upfront plan. This aligns closely with modern, state-driven agentic architectures.
- **Flexible Orchestration**: This dual-mode capability allows developers to choose the best orchestration strategy for their specific use case, whether it requires the predictability of a static plan or the adaptability of a dynamic graph.
EOL

echo "Tutorial branches have been checked out to docs/tutorial-branches/"
