# vulture_whitelist.py
# Whitelist for vulture dead-code detection.
# Items listed here are intentionally unused in static analysis but required at runtime.
# See: https://github.com/jendrikseipp/vulture#whitelisting

# --- FastAPI/Starlette route handlers (discovered via decorators, not direct calls) ---
app  # noqa: FastAPI app instances
router  # noqa: APIRouter instances

# --- Pydantic model fields (accessed via serialization, not direct attribute access) ---
model_config  # noqa: Pydantic ConfigDict
model_validator  # noqa: Pydantic validator decorator

# --- Click CLI commands (registered via decorator, invoked by CLI framework) ---
cli  # noqa: Click group

# --- __all__ exports (used by importers, not within the defining module) ---
__all__  # noqa: module public API

# --- MCP tool decorators (registered at import time, called by MCP framework) ---
mcp  # noqa: FastMCP instance

# --- LangGraph/LangChain callbacks (invoked by framework, not direct callers) ---
on_tool_start  # noqa: callback
on_tool_end  # noqa: callback
on_llm_start  # noqa: callback
on_llm_end  # noqa: callback
on_chain_start  # noqa: callback
on_chain_end  # noqa: callback

# --- Pytest fixtures (discovered by pytest, not called directly) ---
fixture  # noqa: pytest fixture decorator pattern

# --- Streamlit session state keys (accessed dynamically) ---
session_state  # noqa: st.session_state
