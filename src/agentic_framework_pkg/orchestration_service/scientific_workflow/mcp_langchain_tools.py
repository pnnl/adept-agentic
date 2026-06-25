"""
This module serves as the crucial bridge between the LangChain agent ecosystem and the
distributed MCP (Multi-Component Protocol) tool servers. It implements a "Static Factory"
pattern for exposing MCP tools to the LangChain agent.

High-Level Design: The Static Factory Pattern
---------------------------------------------
Instead of having the LangChain agent dynamically discover tools at runtime by calling
an MCP server's `list-tools` endpoint, this module provides a series of explicit
factory functions (e.g., `get_mcp_execute_code_tool_langchain`).

Each factory function is responsible for creating a `MCPToolWrapper` instance, which
is a LangChain-compatible `BaseTool`. The factory hardcodes the specific MCP server URL
(e.g., `HPC_MCP_SERVER_URL`, `SANDBOX_MCP_SERVER_URL`) and the exact name of the tool
on that server (e.g., `execute_code`).

The main `ScientificWorkflowAgent` then calls these factories during its initialization
to build a static list of all the tools it knows how to use.

Developer-Facing Details: Advantages and Disadvantages
------------------------------------------------------

### Advantage: Explicit, Transparent, and Secure

1.  **Clarity and Control:** The agent's total set of capabilities is explicitly defined
    in one place: the `self.tools` list within `ScientificWorkflowAgent`. There is no
    ambiguity about which tools the agent can access.
2.  **Compile-Time Safety:** This approach allows for better static analysis and debugging.
    You can see the entire tool chain at a glance, and it's easier to catch errors
    or misconfigurations before the application even runs.
3.  **Security and Scoping:** It provides a robust security boundary. The agent can *only*
    access the tools that are explicitly wrapped in this file. It cannot discover and
    call a potentially sensitive or unintended tool that might be exposed on an MCP server.
    This prevents the agent from gaining capabilities that were not explicitly granted to it.
4.  **Simplified Agent Logic:** The agent's system prompt can be more detailed and accurate
    because the full list of tools is known beforehand. This improves the reliability of
    the LLM's reasoning process for tool selection.

### Disadvantage: Less Dynamic

1.  **Manual Updates Required:** The primary trade-off is a lack of dynamism. If a new
    tool is added to an MCP server, a developer must manually add a corresponding
    factory function to this file and then add that factory to the
    `self.tools` list in `ScientificWorkflowAgent`. The agent will not discover the new tool automatically.
2.  **Potential for Configuration Drift:** It is possible for the tool definitions in this
    file (e.g., the `args_schema`) to become out of sync with the actual tool's
    signature on the MCP server if the server is updated independently. This requires
    disciplined development to keep the wrapper and the tool in sync.

### Conclusion

This static factory approach was chosen because it prioritizes **security, clarity, and
reliability** over dynamic flexibility. For a complex system with multiple specialized
tool servers (HPC, Sandbox, etc.), having an explicit, auditable "allowlist" of tools
in the agent's core logic is a significant architectural advantage that outweighs the
inconvenience of manual updates.

This static approach is complemented by the **MCP Tool Proxy**, which is also
exposed to the agent via a factory in this module. The proxy acts as a controlled
gateway for dynamic tool usage, allowing the agent to discover and invoke tools
from other MCP servers at runtime. This hybrid model provides a secure foundation
of core tools while still offering a powerful, controlled mechanism for runtime
extensibility.

Developer Guide: Adding a New MCP Tool
---------------------------------------

To add a new MCP tool to the ScientificWorkflowAgent, follow these steps:

### Step 1: Create the MCP Tool Function
Create your tool in the appropriate MCP server directory:

```python
# In src/agentic_framework_pkg/[server]_mcp_server/tools/my_new_tool.py

from fastmcp import mcp
from fastmcp.mcp.context import Context
from typing import Dict, Any, Optional

@mcp.tool()
async def my_new_tool(
    param1: str,
    param2: int,
    ctx: Context,
    mcp_session_id: Optional[str] = None
) -> Dict[str, Any]:
    \"\"\"
    Description of what this tool does.

    Args:
        param1: Description of parameter 1
        param2: Description of parameter 2
        ctx: MCP context (automatically provided)
        mcp_session_id: Session ID for session-aware operations

    Returns:
        Dict containing the tool's results
    \"\"\"
    # Your tool implementation here
    return {"result": "success", "data": "your_data"}
```

### Step 2: Register Tool in MCP Server
Add your tool to the MCP server's main.py file:

```python
# In src/agentic_framework_pkg/[server]_mcp_server/main.py

from tools.my_new_tool import my_new_tool

# Add to the tools list
mcp_tools = [
    my_new_tool,
    # ... existing tools
]
```

### Step 3: Create LangChain Factory Function
Add a factory function in this file (mcp_langchain_tools.py):

```python
def get_mcp_my_new_tool_langchain(mcp_session_id: Optional[str] = None) -> BaseTool:
    \"\"\"
    Factory function to create a LangChain-compatible wrapper for my_new_tool.

    Args:
        mcp_session_id: Session ID for session-aware tool execution

    Returns:
        LangChain BaseTool instance
    \"\"\"

    # Define Pydantic model for input validation
    class MyNewToolInput(BaseModel):
        param1: str = Field(description="Description of parameter 1")
        param2: int = Field(description="Description of parameter 2")

    return MCPToolWrapper(
        name="my_new_tool",
        description="Description of what this tool does",
        server_url=DEFAULT_MCP_SERVER_URL,  # or HPC_MCP_SERVER_URL, SANDBOX_MCP_SERVER_URL
        args_schema=MyNewToolInput,
        mcp_session_id=mcp_session_id
    )
```

### Step 4: Add to ScientificWorkflowAgent Tools List
Update the tools list in langchain_agent.py:

```python
# In src/agentic_framework_pkg/orchestration_service/scientific_workflow/langchain_agent.py

# Import your new factory function
from .mcp_langchain_tools import get_mcp_my_new_tool_langchain

# In the async_init method, add to self.tools list:
self.tools = [
    get_mcp_my_new_tool_langchain(mcp_session_id=tool_session_context.get("mcp_session_id")),
    # ... existing tools
]
```

### Step 5: Test Your Integration
Create a simple test to verify the tool works:

```python
# Test in a development environment
agent = await ScientificWorkflowAgent.create(mcp_session_id="test_session")
result = await agent.arun("Please use my_new_tool with param1='test' and param2=42")
```

### Important Notes:

1. **Session Context**: All MCP tools should accept `mcp_session_id` for session-aware operations
2. **Error Handling**: Implement proper error handling in your tool function
3. **Documentation**: Always provide clear docstrings for both the MCP tool and factory function
4. **Pydantic Models**: Use Pydantic models for input validation to ensure type safety
5. **Server Selection**: Choose the appropriate MCP server URL based on your tool's purpose:
   - `DEFAULT_MCP_SERVER_URL`: General scientific tools (BLAST, UniProt, etc.)
   - `HPC_MCP_SERVER_URL`: High-performance computing tasks (Nextflow, video processing)
   - `SANDBOX_MCP_SERVER_URL`: Code execution and file operations

### Hybrid Architecture Considerations:

With the new hybrid orchestration architecture, tools automatically receive session
hierarchy context. Your tool will have access to:
- `session_id`: Basic user session
- `mcp_session_id`: Tool persistence context
- `multi_agent_session_id`: Team coordination (if applicable)
- `gateway_session_id`: A2A delegation (if applicable)

This enables sophisticated session-aware behavior and state persistence across
agent invocations.
"""

from langchain_core.tools import BaseTool, Tool, StructuredTool
from pydantic import (
    Field,
    BaseModel,
    ConfigDict,
    validator,
)  # For describing tool inputs if not using default string
from typing import Type, Optional, Any, Dict, TypeVar, List, Union, TYPE_CHECKING
import asyncio
from fastmcp import Client as MCPClient

# Import observability decorator
try:
    from agentic_framework_pkg.core.observability import observable_tool

    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False

    # Create a no-op decorator if observability is not available
    def observable_tool(name=None):
        def decorator(func):
            return func

        return decorator


import os
import json
from dotenv import load_dotenv
from pathlib import Path

from ...logger_config import get_logger  # Use centralized logger

logger = get_logger(__name__)

# Load environment variables from .env file at the root of the codebase
root_dir = Path(
    __file__
).parent.parent.parent.parent  # Navigate to root from current file
dotenv_path = root_dir / ".env"
load_dotenv(dotenv_path)

# --- MCP Server URL Configuration ---
# These URLs are used by tools to connect to the correct MCP server.
# They are set by the deployment environment (Helm for K8s, .env/docker-compose for local).

DEFAULT_MCP_SERVER_URL = os.getenv("DEFAULT_MCP_SERVER_URL", "http://mcp_server:8080/")
logger.info(f"Langchain Tools: Default MCP Server URL set to: {DEFAULT_MCP_SERVER_URL}")

HPC_MCP_SERVER_URL = os.getenv("HPC_MCP_SERVER_URL", "http://hpc_mcp_server:8081/")
logger.info(f"Langchain Tools: HPC MCP Server URL set to: {HPC_MCP_SERVER_URL}")

SANDBOX_MCP_SERVER_URL = os.getenv(
    "SANDBOX_MCP_SERVER_URL", "http://sandbox_mcp_server:8082/"
)
logger.info(f"Langchain Tools: Sandbox MCP Server URL set to: {SANDBOX_MCP_SERVER_URL}")


T = TypeVar("T", bound=BaseModel)


class MCPToolWrapper(BaseTool):
    """
    A Langchain BaseTool wrapper for calling tools on a remote MCP server.
    Enhanced with observability metadata tracking.
    """

    mcp_client_url: str  # Explicitly set by factory functions
    actual_tool_name: str
    mcp_session_id: Optional[str] = None  # The session ID for stateful tool calls
    # 'name' and 'description' for Langchain are set at instantiation. # This comment is outdated
    # args_schema: Optional] = None # For structured input using Pydantic
    args_schema: Optional[Type[T]] = (
        None  # Pydantic model for structured input, if needed
    )

    # Enhanced context support
    user_context: Optional[Dict[str, Any]] = (
        None  # Full user context for enhanced tools
    )
    session_hierarchy: Optional[Dict[str, Any]] = None  # Session hierarchy context
    execution_context: Optional[Dict[str, Any]] = None  # Execution preferences

    # Observability tracking (initialized at runtime, not in factory)
    _execution_start: Optional[float] = None
    _execution_end: Optional[float] = None
    _retry_count: int = 0
    _error_context: Optional[str] = None

    def _create_observability_metadata(
        self,
        args: Dict[str, Any],
        result: Any,
        error: Optional[Exception] = None
    ) -> Dict[str, Any]:
        """
        Create observability metadata for tool execution.

        This metadata augments what the MCP decorator provides with runtime context
        that's only available during execution.

        IMPORTANT: Dynamically checks for attribute existence to support:
        - MCPToolFactory pattern (has actual_tool_name)
        - Dynamic MCP tool registration (may not have actual_tool_name)
        - Custom BaseTool implementations (varying attributes)

        Args:
            args: Tool arguments
            result: Tool execution result
            error: Exception if execution failed

        Returns:
            Dict with metadata fields for logging/tracking
        """
        duration = None
        if hasattr(self, "_execution_start") and hasattr(self, "_execution_end"):
            if self._execution_start and self._execution_end:
                duration = self._execution_end - self._execution_start

        metadata = {
            # Defensive: Check for actual_tool_name (MCPToolFactory), fallback to name (BaseTool)
            "tool_name": getattr(self, "actual_tool_name", None) or getattr(self, "name", "unknown"),
            "tool_class": self.__class__.__name__,  # Always available
            "execution_duration_seconds": duration,
            # Defensive: Check for MCP-specific attributes
            "mcp_session_id": getattr(self, "mcp_session_id", None),
            "retry_count": getattr(self, "_retry_count", 0),
            "parameter_summary": self._summarize_parameters(args),
            "result_summary": self._summarize_result(result) if result else None,
            # Defensive: Check for error tracking attributes
            "error_context": getattr(self, "_error_context", None) if error else None,
            "resource_hints": self._extract_resource_hints(args),
        }

        # Filter out None values for cleaner logs
        return {k: v for k, v in metadata.items() if v is not None}

    def _summarize_parameters(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create human-readable parameter summary.

        For large parameters (file contents, JSON blobs), provide size/type info
        instead of full content.

        Args:
            args: Tool arguments

        Returns:
            Summarized parameters
        """
        summary = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 200:
                summary[key] = f"<string: {len(value)} chars>"
            elif isinstance(value, (list, dict)) and len(str(value)) > 200:
                summary[key] = f"<{type(value).__name__}: {len(value)} items>"
            else:
                summary[key] = value
        return summary

    def _summarize_result(self, result: Any) -> str:
        """
        Create human-readable result summary.

        Args:
            result: Tool execution result

        Returns:
            Summarized result
        """
        if result is None:
            return "<None>"

        result_str = str(result)
        if len(result_str) > 500:
            return f"<result: {len(result_str)} chars, type: {type(result).__name__}>"
        return result_str

    def _extract_resource_hints(self, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extract resource usage hints from parameters.

        Helps observability systems understand tool behavior:
        - File operations (size, path)
        - Large downloads (URL, expected size)
        - Database queries (complexity hints)

        Args:
            args: Tool arguments

        Returns:
            Resource hints dictionary or None
        """
        hints = {}

        if "file_path" in args or "file_id" in args or "folder_path" in args:
            hints["resource_type"] = "file_operation"

        if "url" in args:
            hints["resource_type"] = "network_request"
            hints["url_domain"] = self._extract_domain(args["url"])

        if "query" in args and isinstance(args["query"], str):
            hints["query_length"] = len(args["query"])

        return hints if hints else None

    def _extract_domain(self, url: str) -> str:
        """
        Extract domain from URL.

        Args:
            url: URL string

        Returns:
            Domain name
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc or "unknown"
        except Exception:
            return "unknown"

    def _get_timeout_for_tool(self, kwargs: Any) -> int:
        """
        Determine appropriate timeout based on tool type and parameters.

        Returns timeout in seconds.
        """
        # Check if user explicitly provided a timeout
        if "execution_timeout" in kwargs:
            return min(kwargs["execution_timeout"], 300)  # Cap at 5 minutes

        # Respect timeout_seconds parameter from tool input (e.g., CreateRAGIndexFromFolder,
        # ProcessFilesBatch). This ensures the MCP client httpx timeout matches the
        # user-specified server-side timeout.
        if "timeout_seconds" in kwargs:
            return int(kwargs["timeout_seconds"])

        # Tool-specific timeout configurations
        timeout_config = {
            # File processing tools need more time for large files
            "process_uploaded_file": 120,  # 2 minutes for PDF processing
            "process_file_advanced": 120,
            "register_local_file": 60,
            "register_local_folder": 180,  # 3 minutes for recursive folder ops
            # RAG operations can be slow with large documents
            "create_rag_index": 180,  # 3 minutes for indexing
            "query_rag_index": 60,
            "query_file_content": 90,  # 1.5 minutes for RAG queries
            # Batch file operations
            "process_files_batch": 180,  # 3 minutes for batch processing (5-50 files)
            "create_rag_index_from_folder": 300,  # 5 minutes for complete folder→RAG workflow
            # Code execution
            "execute_code": 60,  # Usually specified in ExecuteCodeInput
            # External API calls
            "web_search": 30,
            "query_uniprot_by_accession": 30,
            "query_uniprot_by_gene": 30,
            "query_uniprot": 30,  # legacy alias
            "search_pubchem_by_name": 30,
            "search_pubchem_by_query": 30,
            "get_pubchem_compound_properties": 30,
            "query_pubchem": 30,  # legacy alias
            # Bioinformatics (NCBI BLAST can take 1-2 min)
            "perform_blastp_search": 120,
            "perform_blastn_search": 120,
            "perform_blastp_search_biopython": 120,
            "perform_blastn_search_biopython": 120,
            # AlphaFold (PDB downloads can be large)
            "get_alphafold_prediction_and_store": 60,
            "query_stored_alphafold_predictions": 60,
            # Database operations
            "file_to_sql": 120,
            "query_file_sql": 60,
            # Default for unknown tools
            "default": 60,
        }

        # Get timeout for this specific tool
        timeout = timeout_config.get(self.actual_tool_name, timeout_config["default"])

        # Check for large file indicators in parameters
        if "file_path" in kwargs or "file_id" in kwargs or "folder_path" in kwargs:
            # Increase timeout for file operations
            timeout = int(timeout * 1.5)

        logger.debug(
            f"Determined timeout of {timeout}s for tool {self.actual_tool_name}"
        )
        return timeout

    # D3.2 hardening: Parameter boundary validation
    _NUMERIC_BOUNDS = {
        "size": (0, 10_000_000_000),
        "limit": (0, 100_000),
        "count": (0, 100_000),
        "max_results": (0, 10_000),
        "timeout_seconds": (1, 3600),
        "execution_timeout": (1, 600),
        "max_tokens": (1, 1_000_000),
        "width": (1, 100_000),
        "height": (1, 100_000),
    }

    _INJECTION_PATTERNS = (
        "$(", "`", "&&", "||", ";", "|", "\n", "\r",
        "<script", "javascript:", "data:text/html",
        "' OR ", "\" OR ", "DROP TABLE", "DELETE FROM",
    )

    def _validate_tool_params(self, params: dict) -> Optional[str]:
        """Validate tool parameters for adversarial values.

        Returns an error message string if validation fails, None if params are valid.
        """
        for key, value in params.items():
            if key in ("mcp_session_id", "user_context", "session_hierarchy", "execution_context"):
                continue

            if isinstance(value, (int, float)):
                bounds = self._NUMERIC_BOUNDS.get(key)
                if bounds:
                    low, high = bounds
                    if value < low or value > high:
                        return f"Invalid parameter value for '{key}'"
                elif value < -1_000_000_000:
                    return f"Invalid parameter value for '{key}'"

            elif isinstance(value, str):
                value_lower = value[:50_000].lower()
                for pattern in self._INJECTION_PATTERNS:
                    if pattern.lower() in value_lower:
                        if key in ("code", "query", "prompt", "content", "text", "message", "body"):
                            continue
                        return f"Invalid parameter value for '{key}'"

        return None

    # This method is called by Langchain if the tool is synchronous
    def _run(self, **kwargs: Any) -> str:
        """
        Synchronous entry point for tool execution.

        NOTE: @observable_tool decorator removed to fix Pydantic schema generation
        warnings. Manual instrumentation added for proper observability.
        See: docs/fixes/.../INVESTIGATION_MCP_TOOL_AWAITED_WARNING.md
        """
        import time

        start_time = time.time()

        try:
            # This is the synchronous entry point. We need to call the async _arun method.
            # The challenge is that Langchain might call this from a context where an
            # asyncio event loop is already running.
            logger.info(
                f"[MCP_TOOL_SYNC_START] tool={self.actual_tool_name}, "
                f"session={self.mcp_session_id}, args={list(kwargs.keys())}"
            )

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # If a loop is already running, we cannot use asyncio.run() directly.
                # nest_asyncio patches the loop to allow re-entrant calls to run().
                logger.warning(
                    f"Event loop is running. Applying nest_asyncio for tool '{self.actual_tool_name}'."
                )
                import nest_asyncio

                nest_asyncio.apply()

            # Now it's safe to call asyncio.run()
            result = asyncio.run(self._arun(**kwargs))

            duration = time.time() - start_time
            logger.info(
                f"[MCP_TOOL_SYNC_SUCCESS] tool={self.actual_tool_name}, "
                f"duration={duration:.2f}s, result_len={len(result)}"
            )

            return result

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"[MCP_TOOL_SYNC_ERROR] tool={self.actual_tool_name}, "
                f"duration={duration:.2f}s, error={str(e)}",
                exc_info=True,
            )
            return f"Error executing tool {self.actual_tool_name}: {e}"

    # This method is called by Langchain if the tool is asynchronous
    async def _arun(self, **kwargs: Any) -> str:
        """
        Asynchronous entry point for tool execution.

        NOTE: @observable_tool decorator removed to fix Pydantic schema generation
        warnings. Manual instrumentation added for proper observability.
        See: docs/fixes/.../INVESTIGATION_MCP_TOOL_AWAITED_WARNING.md
        """
        import time

        # Initialize observability tracking
        self._execution_start = time.time()
        self._retry_count = 0
        self._error_context = None

        start_time = time.time()

        # When args_schema is used, Langchain passes parsed arguments as kwargs.
        logger.info(
            f"[MCP_TOOL_START] tool={self.actual_tool_name}, "
            f"session={self.mcp_session_id}, args={list(kwargs.keys())}"
        )

        # The mcp_session_id is now managed by the wrapper, not the LLM.
        # We inject it directly into the parameters for the tool call.
        params_for_tool_call = kwargs.copy()
        if self.mcp_session_id:
            params_for_tool_call["mcp_session_id"] = self.mcp_session_id
        else:
            logger.warning(
                f"No mcp_session_id was provided to the MCPToolWrapper for '{self.actual_tool_name}'. "
                f"The tool will be called without a session context, which may cause issues for stateful tools."
            )

        # Inject enhanced context for context-aware tools (like ExecuteCode)
        if self.user_context:
            params_for_tool_call["user_context"] = self.user_context
        if self.session_hierarchy:
            params_for_tool_call["session_hierarchy"] = self.session_hierarchy
        if self.execution_context:
            params_for_tool_call["execution_context"] = self.execution_context

        logger.debug(
            f"MCPToolWrapper _arun for {self.actual_tool_name}: "
            f"raw_kwargs_from_langchain={kwargs}, "
            f"final_params_for_tool_call={params_for_tool_call}"
        )

        # Configure timeout based on tool type and parameters
        timeout_seconds = self._get_timeout_for_tool(kwargs)
        logger.info(
            f"[MCP_TOOL_TIMEOUT] tool={self.actual_tool_name}, "
            f"timeout={timeout_seconds}s"
        )

        # D3.2 hardening: Validate tool parameters before MCP call
        validation_error = self._validate_tool_params(params_for_tool_call)
        if validation_error:
            logger.warning(
                f"[MCP_PARAM_VALIDATION] Rejected {self.actual_tool_name}: {validation_error}"
            )
            return f"Invalid parameter value for tool '{self.actual_tool_name}'"

        try:
            logger.debug(
                f"[MCP_CONNECT] tool={self.actual_tool_name}, url={self.mcp_client_url}"
            )
            # Initialize MCPClient WITHOUT session_id in constructor
            # Pass timeout to MCPClient so httpx read_timeout >= asyncio.wait_for timeout.
            # Without this, httpx default read timeout fires before asyncio.wait_for,
            # causing httpx.ReadTimeout for long-running tools (e.g., RAG embedding).
            async with MCPClient(self.mcp_client_url, timeout=timeout_seconds) as client:
                logger.debug(
                    f"[MCP_INVOKE] tool={self.actual_tool_name}, "
                    f"actual_name={self.actual_tool_name}, "
                    f"params_keys={list(params_for_tool_call.keys())}"
                )

                # Wrap the tool call with timeout
                try:
                    result_content_list = await asyncio.wait_for(
                        client.call_tool(self.actual_tool_name, params_for_tool_call),
                        timeout=timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    duration = time.time() - start_time
                    timeout_msg = f"Tool '{self.actual_tool_name}' timed out after {timeout_seconds} seconds."
                    logger.error(
                        f"[MCP_TOOL_TIMEOUT_ERROR] tool={self.actual_tool_name}, "
                        f"timeout={timeout_seconds}s, duration={duration:.2f}s"
                    )
                    return f"TIMEOUT ERROR: {timeout_msg}"

                # Process result: Handle both CallToolResult objects and list responses
                logger.debug(
                    f"[MCP_RESULT] tool={self.actual_tool_name}, "
                    f"result_type={type(result_content_list).__name__}"
                )

                result = None

                # Check if result is a CallToolResult object (FastMCP protocol)
                if hasattr(result_content_list, "__class__") and result_content_list.__class__.__name__ == "CallToolResult":
                    # Extract actual data from CallToolResult.content[0].text
                    if hasattr(result_content_list, "content") and isinstance(result_content_list.content, list):
                        if len(result_content_list.content) > 0:
                            first_content = result_content_list.content[0]
                            if hasattr(first_content, "text"):
                                result = first_content.text
                                logger.debug(
                                    f"[MCP_UNWRAP] {self.actual_tool_name}: Unwrapped CallToolResult - "
                                    f"extracted {len(result)} chars from .content[0].text"
                                )
                            else:
                                result = str(result_content_list.content)
                                logger.warning(
                                    f"[MCP_UNWRAP] {self.actual_tool_name}: CallToolResult.content[0] has no .text attribute - "
                                    f"stringifying content: {result[:200]}"
                                )
                        else:
                            result = ""
                            logger.warning(f"[MCP_UNWRAP] {self.actual_tool_name}: CallToolResult.content is empty list")
                    else:
                        result = str(result_content_list)
                        logger.warning(
                            f"[MCP_UNWRAP] {self.actual_tool_name}: CallToolResult has no .content list - "
                            f"stringifying entire object: {result[:200]}"
                        )

                # Handle direct list responses (legacy MCP protocol)
                elif isinstance(result_content_list, list) and result_content_list:
                    first_content_part = result_content_list[0]
                    if hasattr(first_content_part, "text"):  # Handles TextContent
                        # Langchain tools expect string outputs.
                        # If the tool returns a JSON string, it will be in first_content_part.text.
                        result = first_content_part.text
                        logger.debug(
                            f"[MCP_UNWRAP] {self.actual_tool_name}: Extracted {len(result)} chars from list[0].text"
                        )
                    else:
                        # If not TextContent, or list is empty but not None, convert to string.
                        result = str(result_content_list)
                        logger.warning(
                            f"[MCP_UNWRAP] {self.actual_tool_name}: List response has no .text - "
                            f"stringifying: {result[:200]}"
                        )

                # Handle None results
                elif result_content_list is None:  # Tool might return None
                    result = ""
                    logger.debug(f"[MCP_UNWRAP] {self.actual_tool_name}: Tool returned None")

                # Fallback for unexpected response types
                else:
                    result = str(result_content_list)
                    logger.warning(
                        f"[MCP_UNWRAP] {self.actual_tool_name}: Unexpected response type: {type(result_content_list).__name__} - "
                        f"stringifying: {result[:200]}"
                    )

                # Complete observability tracking
                self._execution_end = time.time()

                # Create observability metadata
                metadata = self._create_observability_metadata(kwargs, result)

                # Log success with observability metadata
                duration = time.time() - start_time
                logger.info(
                    f"[MCP_TOOL_SUCCESS] tool={self.actual_tool_name}, "
                    f"duration={duration:.2f}s, result_len={len(result)}, "
                    f"session={self.mcp_session_id}"
                )

                # Log structured observability data
                logger.info(
                    f"[MCP_TOOL_OBSERVABILITY] {metadata}",
                    extra={"observability_metadata": metadata}
                )

                # Track tool output in Langfuse (Obs-2: Session 60)
                try:
                    from ...core.observability_factory import (
                        ObservabilityFactory,
                        truncate_for_observability,
                    )
                    obs_factory = ObservabilityFactory()
                    full_out, trunc_out = truncate_for_observability(result)
                    await obs_factory.track_tool_output(
                        thread_id=self.mcp_session_id or "unknown",
                        checkpoint_id=f"tool_{self.actual_tool_name}_{int(time.time())}",
                        tool_name=self.actual_tool_name,
                        full_output=full_out,
                        truncated_output=trunc_out,
                        output_size=len(result),
                        metadata=metadata,
                    )
                except Exception as obs_err:
                    logger.debug(
                        f"[MCP_TOOL_OBSERVABILITY] Non-blocking: failed to track tool output "
                        f"in Langfuse for {self.actual_tool_name}: {obs_err}"
                    )

                return result
        except ConnectionRefusedError as e:
            # Complete observability tracking for error case
            self._execution_end = time.time()
            self._error_context = f"{type(e).__name__}: {str(e)[:200]}"

            # Create observability metadata
            metadata = self._create_observability_metadata(kwargs, None, error=e)

            duration = time.time() - start_time
            logger.error(
                f"[MCP_TOOL_ERROR] tool={self.actual_tool_name}, "
                f"error_type=ConnectionRefusedError, url={self.mcp_client_url}, "
                f"duration={duration:.2f}s",
                exc_info=True,
            )

            # Log structured observability error data
            logger.error(
                f"[MCP_TOOL_ERROR_OBSERVABILITY] {metadata}",
                extra={"observability_metadata": metadata}
            )

            # Track tool error in Langfuse (Obs-2: Session 60)
            try:
                from ...core.observability_factory import ObservabilityFactory
                obs_factory = ObservabilityFactory()
                error_output = f"ConnectionRefusedError: {self.mcp_client_url}"
                await obs_factory.track_tool_output(
                    thread_id=self.mcp_session_id or "unknown",
                    checkpoint_id=f"tool_{self.actual_tool_name}_{int(time.time())}",
                    tool_name=self.actual_tool_name,
                    full_output=error_output,
                    truncated_output=error_output,
                    output_size=len(error_output),
                    metadata={**metadata, "status": "error"},
                )
            except Exception:
                pass  # Non-blocking

            return f"Error: Could not connect to MCP server to run tool {self.actual_tool_name}."
        except Exception as e:
            # Complete observability tracking for error case
            self._execution_end = time.time()
            self._error_context = f"{type(e).__name__}: {str(e)[:200]}"

            # Create observability metadata
            metadata = self._create_observability_metadata(kwargs, None, error=e)

            duration = time.time() - start_time
            logger.error(
                f"[MCP_TOOL_ERROR] tool={self.actual_tool_name}, "
                f"error_type={type(e).__name__}, error_msg={str(e)}, "
                f"duration={duration:.2f}s",
                exc_info=True,
            )

            # Log structured observability error data
            logger.error(
                f"[MCP_TOOL_ERROR_OBSERVABILITY] {metadata}",
                extra={"observability_metadata": metadata}
            )

            # Track tool error in Langfuse (Obs-2: Session 60)
            try:
                from ...core.observability_factory import ObservabilityFactory
                obs_factory = ObservabilityFactory()
                error_output = f"{type(e).__name__}: {str(e)[:200]}"
                await obs_factory.track_tool_output(
                    thread_id=self.mcp_session_id or "unknown",
                    checkpoint_id=f"tool_{self.actual_tool_name}_{int(time.time())}",
                    tool_name=self.actual_tool_name,
                    full_output=error_output,
                    truncated_output=error_output,
                    output_size=len(error_output),
                    metadata={**metadata, "status": "error"},
                )
            except Exception:
                pass  # Non-blocking

            return f"Error during MCP tool {self.actual_tool_name} execution: {e}"


# --- Define Pydantic models for structured tool inputs (recommended) ---
class QueryCSVToolInput(BaseModel):
    user_query: str = Field(description="The natural language query for the CSV data.")
    file_id: str = Field(
        description="The file_id of the CSV registered via 'register_uploaded_csv'."
    )
    top_k: int = Field(
        3, description="Number of top relevant chunks to retrieve for RAG."
    )


class PerformCalculationInput(BaseModel):
    expression: str = Field(description="The mathematical expression to evaluate.")


class StoreNoteInput(BaseModel):
    note_text: str = Field(description="The text of the note to store.")


class RetrieveNotesInput(BaseModel):
    pass


class QueryUniProtInput(BaseModel):
    accession_id: str = Field(description="The UniProt accession ID (e.g., P05067).")
    timeout_seconds: int = Field(
        30, description="Maximum time in seconds for the API call. Defaults to 30."
    )


class WebSearchAPIInput(BaseModel):
    query: str = Field(description="The search query for the web search.")
    num_results: int = Field(5, description="Number of search results to return.")


class WebSearchScrapingInput(BaseModel):
    """
    DEPRECATED: This web search method is deprecated and may be removed in a future version.

    Please use 'perform_web_search_api' (PerformWebSearchAPI tool) instead for more reliable results.
    The API-based search uses Brave Search API and provides better performance and stability.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "deprecated": True,
            "deprecation_message": "Use 'perform_web_search_api' tool instead. The scraping-based search is less reliable and will be removed in a future release.",
            "recommended_alternative": "perform_web_search_api",
        }
    )

    query: str = Field(
        description="DEPRECATED - Use perform_web_search_api instead. The search query for the web search."
    )
    num_results: int = Field(
        5,
        description="DEPRECATED - Use perform_web_search_api instead. Number of search results to return.",
    )
    timeout: int = Field(
        20,
        description="DEPRECATED - Use perform_web_search_api instead. Timeout in seconds for the scraping operation.",
    )


# class PerformBlastpSearchInput(BaseModel):
#     sequence: str = Field(description="The protein sequence to search with (FASTA format or raw sequence).")
#     database: str = Field("nr", description="The BLAST database to search against (e.g., 'nr', 'swissprot', 'pdb'). Defaults to 'nr'.")
#     expect: float = Field(10.0, description="The expectation value (E-value) threshold. Defaults to 10.0.")
#     hitlist_size: int = Field(10, description="The maximum number of hits to return. Defaults to 10.")

# class PerformBlastnSearchInput(BaseModel):
#     sequence: str = Field(description="The nucleotide sequence to search with (FASTA format or raw sequence).")
#     database: str = Field("nt", description="The BLAST database to search against (e.g., 'nt', 'refseq_rna'). Defaults to 'nt'.")
#     expect: float = Field(10.0, description="The expectation value (E-value) threshold. Defaults to 10.0.")
#     hitlist_size: int = Field(10, description="The maximum number of hits to return. Defaults to 10.")


# --- Pydantic models for Biopython-based BLAST tools (can be same as above if params match) ---
class PerformBlastpSearchBiopythonInput(BaseModel):
    sequence: str = Field(
        description="The protein sequence to search with (FASTA format or raw sequence)."
    )
    database: str = Field(
        "nr",
        description="The BLAST database to search against (e.g., 'nr', 'swissprot', 'pdb'). Defaults to 'nr'.",
    )
    expect: float = Field(
        10.0, description="The expectation value (E-value) threshold. Defaults to 10.0."
    )
    hitlist_size: int = Field(
        10, description="The maximum number of hits to return. Defaults to 10."
    )
    timeout_seconds: int = Field(
        120, description="Maximum time in seconds for the BLAST search. NCBI BLAST can take 1-2 minutes for large sequences. Defaults to 120."
    )


class PerformBlastnSearchBiopythonInput(BaseModel):
    sequence: str = Field(
        description="The nucleotide sequence to search with (FASTA format or raw sequence)."
    )
    database: str = Field(
        "nt",
        description="The BLAST database to search against (e.g., 'nt', 'refseq_rna'). Defaults to 'nt'.",
    )
    expect: float = Field(
        10.0, description="The expectation value (E-value) threshold. Defaults to 10.0."
    )
    hitlist_size: int = Field(
        10, description="The maximum number of hits to return. Defaults to 10."
    )
    timeout_seconds: int = Field(
        120, description="Maximum time in seconds for the BLAST search. NCBI BLAST can take 1-2 minutes for large sequences. Defaults to 120."
    )


# --- Pydantic models for PubChem tools (matching pubchem_tool.py parameters) ---
class SearchPubChemQueryInput(BaseModel):
    query: str = Field(
        description="The compound name, identifier (e.g., CID, SMILES), or general search query for PubChem."
    )
    max_results: int = Field(
        5, description="Maximum number of results to return. Defaults to 5."
    )
    timeout_seconds: int = Field(
        30, description="Maximum time in seconds for the PubChem API call. Defaults to 30."
    )


class SearchPubChemByNameInput(BaseModel):
    chemical_name: str = Field(
        description="The compound name, identifier (e.g., CID, SMILES), or search query for PubChem."
    )
    max_results: int = Field(
        5, description="Maximum number of results to return. Defaults to 5."
    )
    timeout_seconds: int = Field(
        30, description="Maximum time in seconds for the PubChem API call. Defaults to 30."
    )


class GetPubChemCompoundPropertiesInput(BaseModel):
    cid: int = Field(
        description="The PubChem Compound ID (CID) for which to retrieve properties."
    )
    properties: Optional[List[str]] = Field(
        None,
        description="A list of specific properties to retrieve (e.g., ['molecular_formula', 'iupac_name']). If None, a default set is returned.",
    )
    timeout_seconds: int = Field(
        30, description="Maximum time in seconds for the PubChem API call. Defaults to 30."
    )


class ListUploadedFilesInput(BaseModel):
    pass


# --- Pydantic models for AlphaFold tools ---
class GetAlphaFoldPredictionInput(BaseModel):
    uniprot_accession: str = Field(
        description="The UniProt accession ID for which to fetch the AlphaFold prediction (e.g., P05067)."
    )
    timeout_seconds: int = Field(
        60, description="Maximum time in seconds for the AlphaFold API call. Defaults to 60."
    )


class QueryStoredAlphaFoldPredictionsInput(BaseModel):
    query_text: str = Field(
        description="A natural language query to search stored AlphaFold prediction summaries."
    )
    top_k: int = Field(
        3, description="Maximum number of relevant stored predictions to return."
    )
    timeout_seconds: int = Field(
        60, description="Maximum time in seconds for the AlphaFold API query. Defaults to 60."
    )


# --- Pydantic model for Nextflow BLAST tool ---
class RunNextflowBlastInput(BaseModel):
    sequence: str = Field(
        description="The query sequence in FASTA format (as a string)."
    )
    database_name: str = Field(
        description="Name of the BLAST database (must be pre-formatted and accessible by BLAST)."
    )
    blast_program: str = Field(
        "blastp", description="The BLAST program to use (e.g., 'blastp', 'blastn')."
    )
    output_format: str = Field(
        "6",
        description="BLAST output format code (e.g., '6' for tabular, '5' for XML).",
    )


# --- Pydantic model for Video Transcription tool ---
class RunVideoTranscriptionInput(BaseModel):
    video_input_path_or_url: str = Field(
        description="URL of the video or an absolute path to a video file accessible by the HPC server (e.g., /app/data/uploaded_files/my_video.mp4)."
    )
    whisper_model_size: str = Field(
        "base",
        description="Size of the Whisper model to use for transcription (e.g., tiny, base, small, medium, large).",
    )


# --- Pydantic models for enhanced session context ---
class UserContext(BaseModel):
    user_id: str = Field(description="Unique user identifier for file ownership")
    username: str = Field(description="Human-readable username")
    client_type: str = Field(
        description="Type of client (notebook-user, service, cli-user, etc.)"
    )


class SessionHierarchy(BaseModel):
    gateway_session_id: Optional[str] = Field(
        None, description="Agent Gateway session ID"
    )
    multi_agent_session_id: Optional[str] = Field(
        None, description="Multi-agent orchestration session ID"
    )
    mcp_session_id: Optional[str] = Field(None, description="MCP tool session ID")


class ExecutionContext(BaseModel):
    workspace_type: str = Field(
        "isolated", description="Type of workspace isolation (isolated, shared)"
    )
    session_prefix: Optional[str] = Field(
        None, description="Custom session prefix for workspace naming"
    )


# --- Enhanced Pydantic model for Sandbox tool ---
class ExecuteCodeInput(BaseModel):
    code: str = Field(
        description="A string of code to be executed in the sandbox. The last line should be an expression for the result for Python/JavaScript."
    )
    language: str = Field(
        "python",
        description="The programming language of the code. Supported: 'python', 'javascript', 'shell'. Defaults to 'python'.",
    )
    generate_plot: bool = Field(
        False,
        description="⚠️ MANDATORY FOR PLOTS ⚠️: ALWAYS set to True when executing Python code that creates plots, charts, graphs, or ANY visualizations using matplotlib, seaborn, plotly, etc. If generate_plot=False (the default), ALL plots will be ignored and lost forever. For plotting tasks, generate_plot=True is NON-NEGOTIABLE.",
    )
    sandbox_image: Optional[str] = Field(
        None,
        description="Optional. The full URI of a custom Docker image to use for the sandbox (e.g., 'ubuntu:latest', 'ghcr.io/user/my-sandbox:tag'). If provided, this overrides the 'language' parameter for image selection.",
    )
    base_location: str = Field(
        "tmpfs",
        description="Storage location for code execution workspace. Options: 'tmpfs' (default, ephemeral, fast, cleared on restart — code runs in /workspace inside nsjail), 'workspace' (persistent volume at /workspace, survives container restarts — use for session-specific outputs that must persist), 'uploaded_files' (shared volume at /app/data/uploaded_files, accessible across all services — use for files other services need). Output files are automatically published to the shared volume regardless of base_location.",
    )
    execution_timeout: Optional[int] = Field(
        None,
        description="Execution timeout in seconds (default: 30, max: 300). For long-running tasks like large file downloads or complex computations, you can specify up to 5 minutes (300 seconds). Downloads are auto-detected and get 120s by default.",
    )

    # Enhanced context fields
    user_context: Optional[UserContext] = Field(
        None, description="User context for file ownership and session management"
    )
    session_hierarchy: Optional[SessionHierarchy] = Field(
        None, description="Multi-tier session hierarchy for workspace isolation"
    )
    execution_context: Optional[ExecutionContext] = Field(
        None, description="Execution preferences and workspace configuration"
    )


# --- Pydantic model for GitXRay tool ---
class ScanGithubRepoInput(BaseModel):
    repo_url: str = Field(
        description="The full URL of the public GitHub repository to scan for secrets (e.g., 'https://github.com/user/repo')."
    )


# --- Pydantic models for Multi-Agent tools ---
class RolePersonaConfig(BaseModel):
    """Advanced role configuration with custom LLM and prompt settings."""

    name: str = Field(description="Role name (e.g., 'python_developer', 'chemist')")
    llm_purpose: Optional[str] = Field(
        default=None,
        description="LLM purpose for model selection: 'agent_main' (default), 'coding_agent' (code generation). Defaults to 'agent_main' if omitted.",
    )
    system_prompt_template: Optional[str] = Field(
        default=None,
        description="Custom system prompt template. Use {role} for role name and {base_instruction} for default instructions.",
    )


class CreateMultiAgentSessionInput(BaseModel):
    roles: List[str] = Field(
        default=[],
        description="A list of expert roles as simple strings, e.g., ['chemist', 'data scientist']. Either 'roles' or 'role_configs' must be provided.",
    )
    role_configs: Optional[List[RolePersonaConfig]] = Field(
        default=None,
        description="Advanced role configuration with per-role LLM model and prompt settings. Use INSTEAD OF 'roles' when you need specific LLM models or custom prompts. Example: [{'name': 'python_developer', 'llm_purpose': 'coding_agent'}]",
    )
    execution_mode: str = Field(
        default="router",
        description="'router' for sequential execution (supervisor delegates one step at a time), 'graph' for parallel execution of independent plan steps. Defaults to 'router'.",
    )


class GeneratePlanForMultiAgentTaskInput(BaseModel):
    multi_agent_session_id: str = Field(
        description="The ID of the multi-agent session, returned by CreateMultiAgentSession."
    )
    task: str = Field(description="The high-level task for which to generate a plan.")


class GenerateAndReviewPlanForMultiAgentTaskInput(BaseModel):
    multi_agent_session_id: str = Field(
        description="The ID of the multi-agent session, returned by CreateMultiAgentSession."
    )
    task: str = Field(description="The high-level task for which to generate a plan.")


def get_mcp_generate_and_review_plan_for_multi_agent_task_tool_langchain(
    mcp_session_id: Optional[str] = None,
):
    return MCPToolWrapper(
        name="GenerateAndReviewPlanForMultiAgentTask",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="generate_and_review_plan_for_multi_agent_task",
        description="Generates a plan, has it reviewed by the agent team, and returns the refined plan for user approval. Use this for complex tasks.",
        args_schema=GenerateAndReviewPlanForMultiAgentTaskInput,
        mcp_session_id=mcp_session_id,
    )


class ExecuteApprovedPlanInput(BaseModel):
    multi_agent_session_id: str = Field(
        description="The ID of the multi-agent session which has a pending plan."
    )
    timeout_seconds: int = Field(
        default=600,
        description="Maximum execution time in seconds. Default 600 (10 minutes). Increase for complex plans with many workers.",
    )


class UpdatePendingPlanInput(BaseModel):
    multi_agent_session_id: str = Field(
        description="The ID of the multi-agent session which has a pending plan."
    )
    edited_plan: str = Field(
        description="The full, user-edited version of the plan to be executed."
    )


class TerminateMultiAgentSessionInput(BaseModel):
    multi_agent_session_id: str = Field(
        description="The ID of the multi-agent session to terminate."
    )


class ListActiveMultiAgentSessionsInput(BaseModel):
    pass


# --- Pydantic models for File Processing tools ---
class ProcessUploadedFileInput(BaseModel):
    file_id: Optional[str] = Field(
        None,
        description="The ID of the uploaded file to process (e.g., 'file-5ae71694-a382-4160-abdd-e26b5ac1c328'). Either file_id or file_path_on_server must be provided.",
    )
    file_path_on_server: Optional[str] = Field(
        None,
        description="The full path to the file on the server (e.g., /app/data/uploaded_files/filename.csv). Either file_id or file_path_on_server must be provided.",
    )
    original_filename: Optional[str] = Field(
        None, description="The original filename of the uploaded file"
    )
    processing_type: str = Field(
        "auto",
        description="Processing type: 'auto', 'rag', 'sql', 'dataframe', 'text', or 'image'. Auto-detects the best method if 'auto'.",
    )

    @validator("file_path_on_server")
    def validate_file_identifiers(cls, v, values):
        """Ensure at least one of file_id or file_path_on_server is provided."""
        if not v and not values.get("file_id"):
            raise ValueError("Either file_id or file_path_on_server must be provided")
        return v


class ProcessFileAdvancedInput(BaseModel):
    file_id: str = Field(description="The ID of the uploaded file to process")
    processing_type: str = Field(
        "auto",
        description="Processing type: 'auto', 'rag', 'sql', 'dataframe', 'text', or 'image'. Auto-detects the best method if 'auto'.",
    )
    custom_instructions: Optional[str] = Field(
        None, description="Optional custom processing instructions"
    )


class CreateRAGIndexInput(BaseModel):
    """
    Input schema for CreateRAGIndex tool.

    CRITICAL: This tool requires file_ids (list of registered file IDs), NOT folder_path.
    For filesystem folders, use CreateRAGIndexFromFolder instead.
    """
    file_ids: List[str] = Field(
        description="REQUIRED: List of file IDs (already registered files). Example: ['file-abc123', 'file-def456']. DO NOT pass folder_path here - use CreateRAGIndexFromFolder tool for folders."
    )
    index_name: Optional[str] = Field(
        None,
        description="Optional custom name for the RAG index (auto-generated if not provided)",
    )
    chunk_size: int = Field(1000, description="Size of text chunks for indexing in characters (default: 1000)")
    chunk_overlap: int = Field(200, description="Overlap between consecutive chunks in characters (default: 200)")
    visibility: str = Field(
        "session",
        description="Access scope for the created index: 'session' (current session only), 'user' (persists across sessions for this user), or 'world' (accessible to all authenticated users). Default: 'session'.",
    )


class ProcessFilesBatchInput(BaseModel):
    """
    Input schema for batch file processing tool.

    **ASYNC EXECUTION**: This tool executes asynchronously by default. It returns
    immediately with a task_id. Use CheckTaskStatus(task_id) to monitor progress
    and retrieve results when complete. Ideal for processing 5+ files to avoid
    timeouts and enable non-blocking execution.
    """
    file_ids: List[str] = Field(
        description="List of file IDs to process in parallel"
    )
    processing_type: str = Field(
        "auto",
        description="Processing type: 'auto', 'rag', 'sql', 'dataframe', or 'text'. Applied to all files.",
    )
    chunk_size: int = Field(
        5,
        description="Number of files to process concurrently (1-10, default: 5)",
    )
    visibility: str = Field(
        "session",
        description="Access scope for created indexes/databases: 'session' (current session only), 'user' (persists across sessions for this user), or 'world' (accessible to all authenticated users). Default: 'session'.",
    )
    timeout_seconds: int = Field(
        300,
        description="Maximum execution time in seconds (default: 300). Increase for large batches (e.g., 600 for 50+ files).",
    )


class CreateRAGIndexFromFolderInput(BaseModel):
    """
    Input schema for folder-to-RAG index creation tool.

    CRITICAL: This tool requires folder_path (filesystem folder path), NOT file_ids.
    For registered files with file_ids, use CreateRAGIndex instead.

    **ASYNC EXECUTION**: This tool executes asynchronously by default. It returns
    immediately with a task_id. Use CheckTaskStatus(task_id) to monitor progress
    and retrieve results when complete. This is especially important for large
    folders (10+ files) as the complete workflow (register → process → index) can
    take several minutes.

    **TIMEOUT**: The timeout_seconds parameter controls both the MCP HTTP client
    read timeout and the server-side asyncio timeout. For large folders (50+ files),
    increase to 900-1200s to allow CPU-based embedding to complete.
    """
    folder_path: str = Field(
        description="REQUIRED: Filesystem path to the folder to index (string). Example: '/app/data/scripts' or '/code/project'. DO NOT pass file_ids here - use CreateRAGIndex tool for registered files."
    )
    index_name: Optional[str] = Field(
        None,
        description="Custom name for the RAG index (auto-generated if not provided)",
    )
    file_patterns: Optional[List[str]] = Field(
        None,
        description="List of file patterns to include (e.g., ['*.py', '*.md']). If None, includes all files.",
    )
    exclude_patterns: Optional[List[str]] = Field(
        None,
        description="List of patterns to exclude (e.g., ['__pycache__', '.git'])",
    )
    recursive: bool = Field(
        True,
        description="If True, traverse subdirectories recursively",
    )
    processing_type: str = Field(
        "rag",
        description="Processing type: 'auto' or 'rag' (default: rag)",
    )
    chunk_size_files: int = Field(
        5,
        description="Number of files to process concurrently (1-10, default: 5)",
    )
    chunk_size_text: int = Field(
        1000,
        description="Size of text chunks for RAG indexing",
    )
    chunk_overlap: int = Field(
        200,
        description="Overlap between consecutive text chunks",
    )
    visibility: str = Field(
        "session",
        description="Access scope for the created RAG index: 'session' (current session only), 'user' (persists across sessions for this user), or 'world' (accessible to all authenticated users). Default: 'session'.",
    )
    copy_to_session: bool = Field(
        False,
        description="If True, copies source files into the current session directory. "
        "If False (default), registers references to files at their original location "
        "(saves disk space, but files must remain accessible).",
    )
    timeout_seconds: int = Field(
        600,
        description="Maximum execution time in seconds (default: 600). Increase for large folders (e.g., 900-1200 for 100+ files).",
    )


class QueryRAGIndexInput(BaseModel):
    index_id: str = Field(
        description="ID of the RAG index to query (typically the collection name)"
    )
    query: str = Field(description="Natural language query to search the index")
    top_k: int = Field(5, description="Number of most relevant chunks to return")


class ListRAGIndexesInput(BaseModel):
    include_world: bool = Field(
        True,
        description="Include world-scoped RAG indexes accessible to all users (default: True)",
    )
    include_user: bool = Field(
        True,
        description="Include user-scoped RAG indexes that persist across your sessions (default: True)",
    )


class TransformToSQLInput(BaseModel):
    file_id: str = Field(
        description="The ID of the uploaded file to convert to SQL database"
    )
    db_name: Optional[str] = Field(
        None, description="Custom name for the database (defaults to file_id)"
    )
    table_name: str = Field("data", description="Name for the table in the database")
    visibility: str = Field(
        "session",
        description="Access scope for the created database: 'session' (current session only), 'user' (persists across sessions for this user), or 'world' (accessible to all authenticated users). Default: 'session'.",
    )


class QuerySQLDatabaseInput(BaseModel):
    db_id: str = Field(description="The ID of the SQL database to query")
    query: str = Field(description="SQL query to execute against the database")
    limit: int = Field(
        100, description="Maximum number of rows to return for SELECT queries"
    )


class ListSQLDatabasesInput(BaseModel):
    pass


class GetSQLSchemaInput(BaseModel):
    db_id: str = Field(
        description="The ID of the database to get schema information for"
    )


# --- Factory functions to create Langchain tool instances ---
def get_mcp_query_csv_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="QueryProcessedDocumentData",  # Renamed for broader scope
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="query_file_content",  # Name on MCP Server
        description="Queries a previously uploaded and processed document (e.g., CSV, PDF, DOCX, image) using its file_id. Use this to get answers from the document's content.",
        args_schema=QueryCSVToolInput,  # Crucial for LLM to know how to structure input
        mcp_session_id=mcp_session_id,
    )


def get_mcp_perform_calculation_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="PerformSimpleCalculation",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="perform_calculation",
        description="Evaluates a simple mathematical expression (e.g., '2 + 2 * 3').",
        args_schema=PerformCalculationInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_store_note_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="StoreNoteInSession",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="store_note_in_session",
        description="Stores a textual note in the current user's session.",
        args_schema=StoreNoteInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_retrieve_notes_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="RetrieveSessionNotes",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="retrieve_session_notes",
        description="Retrieves all notes previously stored in the current user's session.",
        args_schema=RetrieveNotesInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_query_uniprot_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="QueryUniProt",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="query_uniprot_by_accession",  # Name on MCP Server
        description="Queries the UniProt database for protein information using an accession ID.",
        args_schema=QueryUniProtInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_web_search_api_tool_langchain(
    mcp_session_id: Optional[str] = None,
) -> MCPToolWrapper:
    return MCPToolWrapper(
        name="PerformWebSearchAPI",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="perform_web_search_api",
        description="Performs a robust web search using a dedicated search API. Returns a list of results including titles, links, and snippets. This is the preferred and most reliable method for web searches.",
        args_schema=WebSearchAPIInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_web_search_scraping_tool_langchain(
    mcp_session_id: Optional[str] = None,
) -> MCPToolWrapper:
    return MCPToolWrapper(
        name="PerformWebSearchScraping",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="perform_web_search_scraping",
        description="DEPRECATED: Use PerformWebSearchAPI tool instead. Performs a web search by scraping a search engine's results page. This method is less reliable than the API version and will be removed in a future release. Please migrate to 'perform_web_search_api' for better performance and stability.",
        args_schema=WebSearchScrapingInput,
        mcp_session_id=mcp_session_id,
    )


# def get_mcp_blastp_tool_langchain(mcp_session_id: Optional[str] = None):
#     return MCPToolWrapper(
#         name="PerformProteinBlastSearch", # Descriptive name for the agent
#         mcp_client_url=DEFAULT_MCP_SERVER_URL_FOR_LANGCHAIN,
#         actual_tool_name="perform_blastp_search", # Name on MCP Server
#         description="Performs a protein sequence homology search (BLASTP) against a database using the NCBI web service. Requires a protein sequence.",
#         args_schema=PerformBlastpSearchInput, # Use the Pydantic model for input
#         mcp_session_id=mcp_session_id
#     )

# def get_mcp_blastn_tool_langchain(mcp_session_id: Optional[str] = None):
#     return MCPToolWrapper(
#         name="PerformNucleotideBlastSearch", # Descriptive name for the agent
#         mcp_client_url=DEFAULT_MCP_SERVER_URL_FOR_LANGCHAIN,
#         actual_tool_name="perform_blastn_search", # Name on MCP Server
#         description="Performs a nucleotide sequence homology search (BLASTN) against a database using the NCBI web service. Requires a nucleotide sequence.",
#         args_schema=PerformBlastnSearchInput,
#         mcp_session_id=mcp_session_id
#     )


# --- Factory function for PubChem tool ---
def get_mcp_search_pubchem_by_query_tool_langchain(
    mcp_session_id: Optional[str] = None,
):
    return MCPToolWrapper(
        name="SearchPubChemByQuery",  # Descriptive name for the agent
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="search_pubchem_by_query",  # Correct name on MCP Server from pubchem_tool.py
        description="Searches the PubChem database for chemical compounds by query string and returns matching CIDs and basic info.",
        args_schema=SearchPubChemQueryInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_search_pubchem_by_name_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="SearchPubChemByName",  # Descriptive name for the agent
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="search_pubchem_by_name",  # Correct name on MCP Server from pubchem_tool.py
        description="Searches the PubChem database for chemical compounds by name or identifier and returns matching CIDs and basic info.",
        args_schema=SearchPubChemByNameInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_get_pubchem_compound_properties_tool_langchain(
    mcp_session_id: Optional[str] = None,
):
    return MCPToolWrapper(
        name="GetPubChemCompoundProperties",  # Descriptive name for the agent
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="get_pubchem_compound_properties",  # Correct name on MCP Server from pubchem_tool.py
        description="Retrieves detailed properties (like formula, weight, SMILES, InChI, IUPAC name) for a specific PubChem Compound ID (CID).",
        args_schema=GetPubChemCompoundPropertiesInput,
        mcp_session_id=mcp_session_id,
    )


# --- Factory functions for Biopython-based BLAST tools ---
def get_mcp_blastp_biopython_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="PerformProteinBlastSearchBiopython",  # Descriptive name for the agent
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="perform_blastp_search_biopython",  # Name on MCP Server from blastq_tool.py
        description="Performs a protein sequence homology search (BLASTP) using Biopython against a database via the NCBI web service. Requires a protein sequence.",
        args_schema=PerformBlastpSearchBiopythonInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_blastn_biopython_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="PerformNucleotideBlastSearchBiopython",  # Descriptive name for the agent
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="perform_blastn_search_biopython",  # Name on MCP Server from blastq_tool.py
        description="Performs a nucleotide sequence homology search (BLASTN) using Biopython against a database via the NCBI web service. Requires a nucleotide sequence.",
        args_schema=PerformBlastnSearchBiopythonInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_list_uploaded_files_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="ListUploadedFiles",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="list_uploaded_files",
        description="Lists all files that have been uploaded and processed in the current session, showing their file_id and original filename. Use this to know what files are available for querying.",
        args_schema=ListUploadedFilesInput,
        mcp_session_id=mcp_session_id,
    )


class RegisterLocalFileInput(BaseModel):
    file_path: str = Field(
        description="Full path to the file on the filesystem (e.g., /app/data/uploaded_files/sessions/old_session/file.pdf)"
    )
    alias: Optional[str] = Field(
        default=None, description="Optional friendly name/alias for the file"
    )
    copy_to_session: bool = Field(
        default=True,
        description="If True, copies file to current session; if False, just registers reference",
    )


def get_mcp_register_local_file_tool_langchain(
    mcp_session_id: Optional[str] = None,
    user_context: Optional[Dict[str, Any]] = None,
):
    return MCPToolWrapper(
        name="RegisterLocalFile",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="register_local_file",
        description="Register an existing file from the filesystem with your current session. Use this to access files from other sessions or directories. Example: RegisterLocalFile(file_path='/app/data/uploaded_files/sessions/old_session/file-abc.pdf', alias='report.pdf')",
        args_schema=RegisterLocalFileInput,
        mcp_session_id=mcp_session_id,
        user_context=user_context,
    )


# --- Factory functions for AlphaFold tools ---
def get_mcp_alphafold_prediction_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="GetAlphaFoldPrediction",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="get_alphafold_prediction_and_store",  # Name on MCP Server
        description="Fetches a protein structure prediction from AlphaFold EBI using a UniProt accession ID. Stores a summary for future RAG queries and returns the prediction data.",
        args_schema=GetAlphaFoldPredictionInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_query_stored_alphafold_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="SearchStoredAlphaFoldPredictions",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="query_stored_alphafold_predictions",  # Name on MCP Server
        description="Searches previously fetched and stored AlphaFold prediction summaries based on a natural language query. Returns information about relevant stored predictions.",
        args_schema=QueryStoredAlphaFoldPredictionsInput,
        mcp_session_id=mcp_session_id,
    )


# --- Factory function for HPC Nextflow BLAST tool ---
def get_mcp_run_nextflow_blast_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="RunNextflowBlastPipelineHPC",  # Name for Langchain agent
        mcp_client_url=HPC_MCP_SERVER_URL,  # Target HPC server
        actual_tool_name="run_nextflow_blast_pipeline",  # Actual tool name on HPC MCP Server
        description="Runs a Nextflow pipeline on the HPC server to perform a BLAST search. "
        "Provide the sequence, database name, BLAST program (e.g., blastp, blastn), and output format.",
        args_schema=RunNextflowBlastInput,
        mcp_session_id=mcp_session_id,  # mcp_session_id is optional for this specific HPC tool
    )


# --- Factory function for HPC Video Transcription tool ---
def get_mcp_run_video_transcription_tool_langchain(
    mcp_session_id: Optional[str] = None,
):
    return MCPToolWrapper(
        name="RunVideoTranscriptionPipelineHPC",
        mcp_client_url=HPC_MCP_SERVER_URL,  # Target HPC server
        actual_tool_name="run_video_transcription_pipeline",
        description="Runs a pipeline on the HPC server to download/process a video, transcribe its audio using Whisper, "
        "and summarize the transcript. The transcript is also indexed for RAG. "
        "Input must be a video URL or an absolute server-accessible file path (e.g., from a shared volume like /app/data/uploaded_files/video.mp4). Returns a summary and a file_id for the indexed transcript.",
        args_schema=RunVideoTranscriptionInput,
        mcp_session_id=mcp_session_id,
    )


# --- Factory function for Sandbox Code Execution tool ---
def get_mcp_execute_code_tool_langchain(
    mcp_session_id: Optional[str] = None,
    user_context: Optional[Dict[str, Any]] = None,
    session_hierarchy: Optional[Dict[str, Any]] = None,
    execution_context: Optional[Dict[str, Any]] = None,
):
    """
    Factory function that creates a session-aware sandbox execution tool.

    This function implements proper session isolation by:
    1. Creating composite session IDs from the multi-tier session hierarchy
    2. Handling all session context at the orchestration service level
    3. Providing the sandbox tool with an opaque workspace path
    4. Managing file registration after execution with proper user ownership
    """

    # Create composite session ID that incorporates the full session hierarchy
    def _create_composite_session_id(
        user_ctx: Dict, session_hier: Dict, mcp_sess_id: str
    ) -> str:
        """Generate a composite session ID that encodes the full session hierarchy."""
        parts = []

        # Add client type prefix
        if user_ctx and user_ctx.get("client_type"):
            parts.append(user_ctx["client_type"])

        # Add session hierarchy components
        if session_hier:
            if session_hier.get("gateway_session_id"):
                parts.append(f"gw{session_hier['gateway_session_id'][:8]}")
            if session_hier.get("multi_agent_session_id"):
                parts.append(f"ma{session_hier['multi_agent_session_id'][:8]}")

        # Always include mcp_session_id
        if mcp_sess_id:
            parts.append(f"mcp{mcp_sess_id[:8]}")

        return "_".join(parts) if parts else f"session_{mcp_sess_id[:8]}"

    # Create session-aware ExecuteCode tool that handles session isolation at orchestration level
    class SessionAwareExecuteCodeTool(MCPToolWrapper):
        """
        Specialized MCPToolWrapper for ExecuteCode that handles session isolation at the orchestration level.
        """

        def __init__(
            self,
            user_context: Optional[Dict[str, Any]] = None,
            session_hierarchy: Optional[Dict[str, Any]] = None,
            execution_context: Optional[Dict[str, Any]] = None,
            **kwargs,
        ):
            """Initialize SessionAwareExecuteCodeTool with enhanced context parameters."""
            super().__init__(**kwargs)
            self.user_context = user_context
            self.session_hierarchy = session_hierarchy
            self.execution_context = execution_context
            logger.info(
                f"SessionAwareExecuteCodeTool initialized with user_context: {user_context}"
            )

        async def _arun(self, **kwargs: Any) -> str:
            """Override _arun to implement orchestration-level session management."""
            logger.info(f"SessionAware ExecuteCode tool called with kwargs: {kwargs}")

            # Generate composite session ID from the multi-tier session hierarchy
            composite_session_id = _create_composite_session_id(
                user_ctx=self.user_context or {},
                session_hier=self.session_hierarchy or {},
                mcp_sess_id=self.mcp_session_id or "unknown",
            )

            logger.info(f"Generated composite session ID: {composite_session_id}")

            # Create enhanced parameters for the sandbox tool (WITH user context for file ownership)
            sandbox_params = kwargs.copy()
            # Note: composite_session_id is generated for logging but not passed to sandbox
            # The sandbox tool uses the individual session parameters instead

            # Pass user context to sandbox for proper file ownership
            if hasattr(self, "user_context") and self.user_context:
                sandbox_params["user_context"] = self.user_context
                sandbox_params["user_id"] = self.user_context.get("user_id", "unknown")
                logger.info(
                    f"Passing user context to sandbox: user_id={sandbox_params['user_id']}"
                )
            else:
                sandbox_params["user_id"] = "unknown"
                logger.warning("No user context available, defaulting to 'unknown'")

            # Pass session hierarchy for multi-tier session management
            if hasattr(self, "session_hierarchy") and self.session_hierarchy:
                sandbox_params["session_hierarchy"] = self.session_hierarchy

            # Remove execution_context as it's not needed by sandbox
            sandbox_params.pop("execution_context", None)

            try:
                # Call the sandbox tool with simplified parameters
                async with MCPClient(self.mcp_client_url) as client:
                    logger.info(
                        f"Calling sandbox ExecuteCode with composite session: {composite_session_id}"
                    )
                    result_content_list = await client.call_tool(
                        self.actual_tool_name, sandbox_params
                    )

                    # Process the execution result
                    # Handle both CallToolResult objects and direct list responses
                    result_text = ""

                    # Check if result is a CallToolResult object (FastMCP protocol)
                    if hasattr(result_content_list, "__class__") and result_content_list.__class__.__name__ == "CallToolResult":
                        # Extract actual data from CallToolResult.content[0].text
                        if hasattr(result_content_list, "content") and isinstance(result_content_list.content, list):
                            if len(result_content_list.content) > 0:
                                first_content = result_content_list.content[0]
                                if hasattr(first_content, "text"):
                                    result_text = first_content.text
                                    logger.debug(
                                        f"[SANDBOX_UNWRAP] Unwrapped CallToolResult from sandbox - "
                                        f"extracted {len(result_text)} chars from .content[0].text"
                                    )
                                else:
                                    result_text = str(result_content_list.content)
                                    logger.warning(
                                        f"[SANDBOX_UNWRAP] CallToolResult.content[0] has no .text attribute - "
                                        f"stringifying content: {result_text[:200]}"
                                    )
                            else:
                                result_text = ""
                                logger.warning("[SANDBOX_UNWRAP] CallToolResult.content is empty list")
                        else:
                            result_text = str(result_content_list)
                            logger.warning(
                                f"[SANDBOX_UNWRAP] CallToolResult has no .content list - "
                                f"stringifying entire object: {result_text[:200]}"
                            )

                    # Handle direct list responses (legacy MCP protocol)
                    elif isinstance(result_content_list, list) and result_content_list:
                        first_content_part = result_content_list[0]
                        if hasattr(first_content_part, "text"):
                            result_text = first_content_part.text
                            logger.debug(
                                f"[SANDBOX_UNWRAP] Extracted {len(result_text)} chars from list[0].text"
                            )
                        else:
                            result_text = str(result_content_list)
                            logger.warning(
                                f"[SANDBOX_UNWRAP] List response has no .text - "
                                f"stringifying: {result_text[:200]}"
                            )

                    # Fallback for unexpected response types
                    else:
                        result_text = (
                            str(result_content_list) if result_content_list else ""
                        )
                        logger.warning(
                            f"[SANDBOX_UNWRAP] Unexpected response type: {type(result_content_list).__name__} - "
                            f"stringifying: {result_text[:200]}"
                        )

                    # TODO: Implement post-execution file registration at orchestration level
                    # This is where we would:
                    # 1. Parse execution result for generated file paths
                    # 2. Register files with proper user ownership using self.user_context
                    # 3. Update session context with registered file metadata
                    logger.info(
                        "Post-execution file registration would happen here at orchestration level"
                    )

                    return result_text

            except Exception as e:
                logger.error(
                    f"Error in SessionAware ExecuteCode tool: {e}", exc_info=True
                )
                return f"Error executing code: {e}"

    return SessionAwareExecuteCodeTool(
        name="ExecuteCode",
        mcp_client_url=SANDBOX_MCP_SERVER_URL,  # Target Sandbox server
        actual_tool_name="execute_code",  # Actual tool name on Sandbox MCP Server
        description="""Executes a snippet of code in a secure, isolated sandbox environment and returns the output.

⚠️ CRITICAL FOR PLOTTING ⚠️: When your Python code creates plots, charts, graphs, or visualizations (matplotlib, seaborn, plotly, etc.), you MUST ALWAYS set 'generate_plot=True' or the plots will be COMPLETELY LOST and not returned to the user. This is the most common error - forgetting generate_plot=True for plotting code.

Supported languages: 'python', 'javascript', 'shell'. You can also specify a custom Docker image with the 'sandbox_image' parameter. Useful for calculations, data manipulation, and visualization. The sandbox has no outbound network access (nftables egress deny-by-default).

ISOLATION: Code executes inside an nsjail process jail with seccomp-bpf syscall filtering when available. The working directory is /workspace inside the jail. Use relative paths or /workspace/ for file I/O. Filesystem outside /workspace is read-only.

STORAGE OPTIONS: Use 'base_location' parameter to choose where files are created: 'tmpfs' (default, ephemeral, fast, cleared on restart), 'workspace' (persistent across container restarts at /workspace), or 'uploaded_files' (shared across all services at /app/data/uploaded_files). Output files are automatically published to the shared volume for access by other services.

TIMEOUT: Use 'execution_timeout' parameter for long-running tasks (default: 30s, max: 300s). Downloads auto-detect for 120s timeout.

**RETURN STRUCTURE** (when generate_plot=True):
The tool returns comprehensive plot metadata in the 'plots' array:
- plot_url: Direct URL for plot viewing (e.g., http://localhost:8083/v1/plots/plot_abc123.png)
- filename: Plot filename (e.g., plot_abc123.png)
- file_path: Absolute path on shared filesystem (e.g., /app/data/uploaded_files/plots/plot_abc123.png)
- relative_path: Relative path (e.g., data/uploaded_files/plots/plot_abc123.png)
- format: Image format (png, jpeg, bmp, tiff, gif, webp, ico, svg, eps, pdf, html - EXPANDED support)
- size_bytes: File size in bytes
- width_pixels: Image width in pixels (raster formats only)
- height_pixels: Image height in pixels (raster formats only)
- mime_type: MIME type (e.g., image/png, image/svg+xml, application/pdf)
- created_at: ISO8601 timestamp
- session_id: MCP session identifier

Use plot_url for simple display (markdown syntax), or file_path for advanced workflows (RegisterLocalFile + GeneratePresignedURL for secure links, or GeneratePlotEmbedCode for platform-specific embedding). Note: RegisterLocalFile and GeneratePresignedURL are general-purpose tools that work with ANY file type, not just plots.""",
        args_schema=ExecuteCodeInput,
        mcp_session_id=mcp_session_id,
        user_context=user_context,
        session_hierarchy=session_hierarchy,
        execution_context=execution_context,
    )


# --- Factory function for HPC GitXRay Scan tool ---
def get_mcp_gitxray_scan_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="ScanGithubRepositoryForSecrets",
        mcp_client_url=HPC_MCP_SERVER_URL,  # Target HPC server
        actual_tool_name="scan_github_repository_with_gitxray",
        description="Scans a public GitHub repository for secrets and other sensitive data using GitXRay. This is a powerful security tool. Provide the full repository URL.",
        args_schema=ScanGithubRepoInput,
        mcp_session_id=mcp_session_id,
    )


# --- Factory functions for Sandbox File Management tools ---
class ListSandboxGeneratedFilesInput(BaseModel):
    pass


class QueryGeneratedFileContentInput(BaseModel):
    file_id: str = Field(
        description="ID of the generated file to query (from ListSandboxGeneratedFiles)"
    )
    query: str = Field(description="Search query string to find in the file content")


def get_sandbox_list_uploaded_files_tool_langchain(
    mcp_session_id: Optional[str] = None,
):
    return MCPToolWrapper(
        name="ListSandboxGeneratedFiles",
        mcp_client_url=SANDBOX_MCP_SERVER_URL,  # Points to sandbox, not mcp_server
        actual_tool_name="list_uploaded_files",
        description="Lists all files that have been generated by sandbox code execution in the current session. This is separate from uploaded document files - use this for files created by ExecuteCode tool.",
        args_schema=ListSandboxGeneratedFilesInput,
        mcp_session_id=mcp_session_id,
    )


def get_sandbox_query_file_content_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="QuerySandboxGeneratedFileContent",
        mcp_client_url=SANDBOX_MCP_SERVER_URL,  # Points to sandbox, not mcp_server
        actual_tool_name="query_generated_file_content",
        description="Performs basic content search on files generated by sandbox code execution. Use the file_id from ListSandboxGeneratedFiles. For advanced RAG on uploaded documents, use QueryProcessedDocumentData instead.",
        args_schema=QueryGeneratedFileContentInput,
        mcp_session_id=mcp_session_id,
    )


# --- Factory functions for Multi-Agent tools (as local tools) ---
if TYPE_CHECKING:
    from .langchain_agent import ScientificWorkflowAgent


def get_create_multi_agent_session_tool(agent: "ScientificWorkflowAgent"):
    logger.info("[MULTI_AGENT_TOOL] Creating CreateMultiAgentSession tool factory")

    async def _create_session(
        roles: List[str] = None,
        role_configs: list = None,
        execution_mode: str = "router",
    ):
        logger.info(
            f"[MULTI_AGENT_TOOL] CreateMultiAgentSession._create_session called with roles={roles}, role_configs={role_configs}, execution_mode={execution_mode}"
        )

        # Merge roles and role_configs — role_configs takes precedence
        merged_roles: list = []
        if role_configs:
            for rc in role_configs:
                if isinstance(rc, dict):
                    merged_roles.append(rc)
                elif hasattr(rc, "model_dump"):
                    merged_roles.append(rc.model_dump())
                else:
                    merged_roles.append({"name": str(rc)})
            logger.info(
                f"[MULTI_AGENT_TOOL] Using role_configs ({len(merged_roles)} roles with persona config)"
            )
        elif roles:
            merged_roles = list(roles)
            logger.info(
                f"[MULTI_AGENT_TOOL] Using simple string roles ({len(merged_roles)} roles)"
            )
        else:
            logger.error("[MULTI_AGENT_TOOL] Neither 'roles' nor 'role_configs' provided")
            return {
                "status": "error",
                "message": "Either 'roles' or 'role_configs' must be provided.",
            }
        try:
            from ..multi_agent_manager import create_multi_agent_session_impl

            if not agent.user_credentials:
                logger.error(
                    "[MULTI_AGENT_TOOL] No user credentials available in agent"
                )
                raise ValueError(
                    "User credentials are required to create a multi-agent session."
                )

            # Build authorized tool configs for multi-agent worker sessions
            # 1. Dynamically discover built-in MCP tools (eliminates dual maintenance)
            # 2. Add external tools from gateway_registry based on user permissions
            from ..external_tool_manager import tool_manager
            from ...core.mcp_tool_discovery import mcp_discovery

            # Dynamically discover built-in MCP tools from servers
            try:
                logger.info(
                    "[MULTI_AGENT_TOOL] Starting MCP tool discovery for multi-agent session"
                )
                discovered_tools = await mcp_discovery.discover_all_tools()
                builtin_mcp_tools = [
                    {
                        "name": tool.name,
                        "type": tool.tool_type,
                        "server": tool.server,
                        "description": tool.description,
                        "args_schema": tool.args_schema,
                    }
                    for tool in discovered_tools
                ]
                logger.info(
                    f"[MULTI_AGENT_TOOL] Dynamically discovered {len(builtin_mcp_tools)} MCP tools for multi-agent session"
                )
                logger.debug(
                    f"[MULTI_AGENT_TOOL] Discovered tools: {[t['name'] for t in builtin_mcp_tools[:5]]}..."
                )
            except Exception as e:
                logger.error(
                    f"[MULTI_AGENT_TOOL] MCP tool discovery failed: {e}, using fallback configuration",
                    exc_info=True,
                )
                # Fallback to minimal essential tools if discovery fails completely
                builtin_mcp_tools = [
                    {
                        "name": "query_csv",
                        "type": "mcp",
                        "server": "mcp_server",
                        "description": "Query CSV data",
                    },
                    {
                        "name": "execute_code",
                        "type": "mcp",
                        "server": "sandbox_mcp_server",
                        "description": "Execute code in sandbox",
                    },
                    {
                        "name": "websearch",
                        "type": "mcp",
                        "server": "mcp_server",
                        "description": "Search the web",
                    },
                ]

            # Get external tools from tool_manager (includes ACL filtering for user)
            external_tools = []
            if agent.user_credentials:
                external_tools = await tool_manager.get_authorized_tools(
                    user_id=agent.user_credentials.user_id,
                    user_groups=agent.user_credentials.groups,
                )

            # Retrieve serializable configs from Redis (not live tool objects)
            # tool_manager.get_tool_config() returns the JSON config dict stored
            # by register_tool(), which includes the full invocation block with
            # protocol, connection URL, etc. — already JSON-serializable.
            external_tool_configs = []
            for tool in external_tools:
                if hasattr(tool, "name") and hasattr(tool, "description"):
                    tool_config = await tool_manager.get_tool_config(tool.name)
                    if tool_config:
                        external_tool_configs.append(tool_config)
                    else:
                        # Fallback: minimal serializable config (no tool_instance)
                        logger.warning(
                            f"[MULTI_AGENT_TOOL] Could not get config for external tool '{tool.name}', using minimal config"
                        )
                        external_tool_configs.append(
                            {
                                "name": tool.name,
                                "description": tool.description,
                                "type": "external",
                            }
                        )

            # Combine built-in and external tools
            authorized_tool_configs = builtin_mcp_tools + external_tool_configs
            logger.info(
                f"[MULTI_AGENT_TOOL] Total authorized tools: {len(authorized_tool_configs)}"
            )

            logger.info(
                f"[MULTI_AGENT_TOOL] Calling create_multi_agent_session_impl with mcp_session_id={agent.mcp_session_id}"
            )
            result = await create_multi_agent_session_impl(
                roles=merged_roles,
                mcp_session_id=agent.mcp_session_id,
                authorized_tool_configs=authorized_tool_configs,
                execution_mode=execution_mode,
                user_credentials=agent.user_credentials,
            )
            logger.info(
                f"[MULTI_AGENT_TOOL] create_multi_agent_session_impl returned: {result}"
            )
            return result
        except Exception as e:
            logger.error(
                f"[MULTI_AGENT_TOOL] Failed to create multi-agent session: {e}",
                exc_info=True,
            )
            return {"status": "error", "message": str(e)}

    return StructuredTool(
        name="CreateMultiAgentSession",
        coroutine=_create_session,
        description="Creates a new multi-agent session. Returns a session ID. IMPORTANT: After creating a session, you must call GeneratePlan before ExecuteApprovedPlan.",
        args_schema=CreateMultiAgentSessionInput,
    )


def get_generate_plan_for_multi_agent_task_tool():
    logger.info("[MULTI_AGENT_TOOL] Creating GeneratePlanForMultiAgentTask tool")

    async def _generate_plan(multi_agent_session_id: str, task: str):
        logger.info(
            f"[MULTI_AGENT_TOOL] GeneratePlan called for session={multi_agent_session_id}, task='{task[:100]}...'"
        )

        # Normalize session ID format - accept both "multi-agent:<uuid>" and plain "<uuid>"
        # LLMs may extract just the UUID from the CreateMultiAgentSession response
        if not multi_agent_session_id:
            logger.error("[MULTI_AGENT_TOOL] Empty session ID provided")
            return {
                "status": "error",
                "message": "Session ID is required. Please use the session ID returned by CreateMultiAgentSession.",
            }

        # If plain UUID format, add the "multi-agent:" prefix
        if not multi_agent_session_id.startswith("multi-agent:"):
            # Validate it's a valid UUID format before adding prefix
            import uuid
            try:
                uuid.UUID(multi_agent_session_id)
                original_id = multi_agent_session_id
                multi_agent_session_id = f"multi-agent:{multi_agent_session_id}"
                logger.info(
                    f"[MULTI_AGENT_TOOL] Normalized session ID from '{original_id}' to '{multi_agent_session_id}'"
                )
            except ValueError:
                logger.error(
                    f"[MULTI_AGENT_TOOL] Invalid session ID format (not a valid UUID): {multi_agent_session_id}"
                )
                return {
                    "status": "error",
                    "message": f"Invalid session ID format. Expected 'multi-agent:<uuid>' or valid UUID. Got: {multi_agent_session_id}",
                }

        try:
            from ..multi_agent_manager import generate_plan_for_multi_agent_task_impl

            result = await generate_plan_for_multi_agent_task_impl(
                multi_agent_session_id, task
            )
            logger.info(
                f"[MULTI_AGENT_TOOL] GeneratePlan result: {result.get('status')}"
            )
            return result
        except Exception as e:
            logger.error(
                f"[MULTI_AGENT_TOOL] Failed to generate plan: {e}", exc_info=True
            )
            return {"status": "error", "message": str(e)}

    return StructuredTool.from_function(
        coroutine=_generate_plan,
        name="GeneratePlanForMultiAgentTask",
        description="Generates a plan for a task in a multi-agent session.",
        args_schema=GeneratePlanForMultiAgentTaskInput,
    )


def get_execute_approved_plan_tool():
    logger.info("[MULTI_AGENT_TOOL] Creating ExecuteApprovedPlan tool")

    async def _execute_plan(multi_agent_session_id: str, timeout_seconds: int = 600):
        logger.info(
            f"[MULTI_AGENT_TOOL] ExecuteApprovedPlan called for session={multi_agent_session_id}, "
            f"timeout={timeout_seconds}s (runs via async task queue)"
        )

        # Normalize session ID format - accept both "multi-agent:<uuid>" and plain "<uuid>"
        # LLMs may extract just the UUID from the CreateMultiAgentSession response
        if not multi_agent_session_id:
            logger.error("[MULTI_AGENT_TOOL] Empty session ID provided")
            return {
                "status": "error",
                "message": "Session ID is required. Please use the session ID returned by CreateMultiAgentSession.",
            }

        # If plain UUID format, add the "multi-agent:" prefix
        if not multi_agent_session_id.startswith("multi-agent:"):
            # Validate it's a valid UUID format before adding prefix
            import uuid
            try:
                uuid.UUID(multi_agent_session_id)
                original_id = multi_agent_session_id
                multi_agent_session_id = f"multi-agent:{multi_agent_session_id}"
                logger.info(
                    f"[MULTI_AGENT_TOOL] Normalized session ID from '{original_id}' to '{multi_agent_session_id}'"
                )
            except ValueError:
                logger.error(
                    f"[MULTI_AGENT_TOOL] Invalid session ID format (not a valid UUID): {multi_agent_session_id}"
                )
                return {
                    "status": "error",
                    "message": f"Invalid session ID format. Expected 'multi-agent:<uuid>' or valid UUID. Got: {multi_agent_session_id}",
                }

        try:
            from ..multi_agent_manager import execute_approved_plan_in_session_impl

            result = await execute_approved_plan_in_session_impl(multi_agent_session_id)

            # Log the result for debugging
            if result.get("status") == "error":
                logger.warning(
                    f"[MULTI_AGENT_TOOL] ExecuteApprovedPlan error: {result.get('message')}"
                )
            else:
                logger.info(
                    f"[MULTI_AGENT_TOOL] ExecuteApprovedPlan result: {result.get('status')}"
                )

            return result
        except Exception as e:
            logger.error(
                f"[MULTI_AGENT_TOOL] Failed to execute plan: {e}", exc_info=True
            )
            return {"status": "error", "message": str(e)}

    return StructuredTool.from_function(
        coroutine=_execute_plan,
        name="ExecuteApprovedPlan",
        description="Executes an approved plan in a multi-agent session. IMPORTANT: You must first call GeneratePlan to create a plan before executing.",
        args_schema=ExecuteApprovedPlanInput,
    )


def get_terminate_multi_agent_session_tool():
    logger.info("[MULTI_AGENT_TOOL] Creating TerminateMultiAgentSession tool")

    async def _terminate_session(multi_agent_session_id: str):
        logger.info(
            f"[MULTI_AGENT_TOOL] TerminateSession called for session={multi_agent_session_id}"
        )
        try:
            from ..multi_agent_manager import terminate_multi_agent_session_impl

            result = await terminate_multi_agent_session_impl(multi_agent_session_id)
            logger.info(
                f"[MULTI_AGENT_TOOL] TerminateSession result: {result.get('status')}"
            )
            return result
        except Exception as e:
            logger.error(
                f"[MULTI_AGENT_TOOL] Failed to terminate session: {e}", exc_info=True
            )
            return {"status": "error", "message": str(e)}

    return Tool(
        name="TerminateMultiAgentSession",
        func=None,
        coroutine=_terminate_session,
        description="Terminates a multi-agent session.",
        args_schema=TerminateMultiAgentSessionInput,
    )


# --- Factory functions for Sandbox File Management tools ---


# --- Factory functions for File Processing tools ---
def get_mcp_process_uploaded_file_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="ProcessUploadedFile",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="process_uploaded_file",
        description="Process an uploaded file with auto-detection or specific processing type. Supports CSV, PDF, DOCX, TXT, JSON, Excel, Parquet, HTML, XML. Can extract text, create DataFrames, prepare for RAG indexing, or convert to SQL.",
        args_schema=ProcessUploadedFileInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_process_file_advanced_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="ProcessFileAdvanced",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="process_file_advanced",
        description="Advanced file processing with comprehensive capabilities. Automatically detects file type and applies appropriate processing. Supports structured data (CSV, Excel, JSON, Parquet), documents (PDF, DOCX, TXT, HTML, XML), code files, and images. Can convert to DataFrames, prepare for RAG indexing, extract text, or transform to SQL.",
        args_schema=ProcessFileAdvancedInput,
        mcp_session_id=mcp_session_id,
    )


# --- Factory functions for RAG tools ---
def get_mcp_create_rag_index_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="CreateRAGIndex",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="create_rag_index",
        description="Create a RAG index from REGISTERED FILES (requires file_ids list). Use this when you already have file_ids from uploaded or registered files. DO NOT use this for folders - use CreateRAGIndexFromFolder instead. Supports visibility scoping: 'session' (default, current session only), 'user' (persists across sessions), or 'world' (all users).",
        args_schema=CreateRAGIndexInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_process_files_batch_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="ProcessFilesBatch",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="process_files_batch",
        description="Process multiple files in parallel with concurrency control and error handling. Automatically handles failures gracefully, tracks progress, and returns comprehensive metrics. Much faster than processing files individually (5-10x speedup with default concurrency of 5 files). Supports visibility scoping ('session'/'user'/'world') and configurable timeout_seconds.",
        args_schema=ProcessFilesBatchInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_create_rag_index_from_folder_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="CreateRAGIndexFromFolder",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="create_rag_index_from_folder",
        description="Create a RAG index from FILESYSTEM FOLDER (requires folder_path string). Complete workflow: registers files → processes → creates index. Use this when user specifies a folder path. DO NOT use this with file_ids - use CreateRAGIndex instead. Supports file patterns (e.g., '*.py'), exclusions (e.g., '__pycache__'), recursive traversal, visibility scoping ('session'/'user'/'world'), and configurable timeout_seconds.",
        args_schema=CreateRAGIndexFromFolderInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_query_rag_index_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="QueryRAGIndex",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="query_rag_index",
        description="Search a RAG index with a natural language query. Returns the most semantically relevant chunks from the indexed documents.",
        args_schema=QueryRAGIndexInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_list_rag_indexes_tool_langchain(
    mcp_session_id: Optional[str] = None,
    user_context: Optional[Dict[str, Any]] = None,
):
    return MCPToolWrapper(
        name="ListRAGIndexes",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="list_rag_indexes",
        description=(
            "List available RAG indexes. By default includes session-scoped, "
            "user-scoped (your persistent indexes), and world-scoped (shared) indexes. "
            "Use include_world=False or include_user=False to filter."
        ),
        args_schema=ListRAGIndexesInput,
        mcp_session_id=mcp_session_id,
        user_context=user_context,
    )


# --- Factory functions for SQL tools ---
def get_mcp_transform_to_sql_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="TransformToSQL",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="file_to_sql",
        description="Convert an uploaded file (CSV, Excel, JSON, Parquet) to a SQL-queryable SQLite database. Enables complex SQL queries on structured data. Supports visibility scoping: 'session' (default), 'user', or 'world'.",
        args_schema=TransformToSQLInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_query_sql_database_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="QuerySQLDatabase",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="query_file_sql",
        description="Execute SQL queries against a file-based SQLite database. Supports SELECT, INSERT, UPDATE, DELETE operations.",
        args_schema=QuerySQLDatabaseInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_list_sql_databases_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="ListSQLDatabases",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="list_sql_databases",
        description="List all SQL databases available in the current session with their metadata.",
        args_schema=ListSQLDatabasesInput,
        mcp_session_id=mcp_session_id,
    )


def get_mcp_get_sql_schema_tool_langchain(mcp_session_id: Optional[str] = None):
    return MCPToolWrapper(
        name="GetSQLSchema",
        mcp_client_url=DEFAULT_MCP_SERVER_URL,
        actual_tool_name="get_sql_schema",
        description="Get the schema information for a SQL database including tables, columns, and data types.",
        args_schema=GetSQLSchemaInput,
        mcp_session_id=mcp_session_id,
    )


# Add more Langchain tool wrappers for other MCP tools as needed.
