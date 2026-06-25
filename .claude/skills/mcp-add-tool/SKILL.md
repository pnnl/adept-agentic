---
name: mcp-add-tool
description: Add a new tool to an existing MCP server following the canonical register(mcp) + Pydantic pattern. Use during Phase 4 (Implement) of the feature development lifecycle.
disable-model-invocation: true
allowed-tools: Bash(grep *) Bash(find *) Bash(ls *) Bash(make *) Bash(git *) Read Write Edit Glob Grep
argument-hint: [optional: server-directory tool-name]
---

You are assisting an ADEPT developer with adding a new tool to an existing MCP server. This skill corresponds to Phase 4 (Implement) in the feature development lifecycle.

Do not use emojis in any output.
Enforce all rules in `docs/development/AGENT_CODING_RULES.md` throughout this skill execution.
Do not include any AI agent references in commit messages, trailers, or document metadata.
Pause for developer confirmation before writing any files.

---

## Step 1: Identify Target Server

If `$ARGUMENTS` provides the server directory and tool name, use those. Otherwise ask:

**"Which MCP server are you adding a tool to?"**

List available servers:
```bash
ls -d examples/*_mcp_server/ examples/*_mcp/ 2>/dev/null
```

Then identify the server's package directory and existing tools:
```bash
find <server_dir>/ -name "tools" -type d
ls <server_dir>/<package>/tools/
```

Read one existing tool file to understand the server's conventions (imports, config usage, return patterns).

---

## Step 2: Gather Tool Details

Ask the developer for:

1. **Tool name**: lowercase_snake_case (e.g., `predict_structure`)
2. **Tool description**: one-line docstring (e.g., "Predict 3D protein structure from amino acid sequence")
3. **Parameters**: for each parameter, collect:
   - Name (snake_case)
   - Type (str, int, float, bool, list, dict)
   - Description (for Field annotation)
   - Default value (optional)
4. **Return type**: what the tool returns (default: `dict`)

---

## Step 3: Validate Conventions

Before creating the tool, verify these critical patterns from the server's existing tools:

```bash
# Check the register(mcp) pattern is used (not bare @mcp.tool)
grep -rn 'def register(mcp)' <server_dir>/<package>/tools/

# Check Annotated[Type, Field()] pattern
grep -rn 'Annotated\[' <server_dir>/<package>/tools/ | head -5

# Check mcp_session_id presence
grep -rn 'mcp_session_id' <server_dir>/<package>/tools/ | head -5

# Check how server.py imports and calls register
grep -n 'register\|import.*tools' <server_dir>/<package>/server.py
```

If the server does not follow these patterns (older server), warn the developer and ask whether to follow the canonical pattern or match the server's existing style.

---

## Step 4: Create Tool File

Create `<server_dir>/<package>/tools/<tool_name>.py` following the canonical pattern:

```python
"""
<tool_description>
"""

from typing import Annotated
from pydantic import Field

from <package>.config import settings


def register(mcp):
    @mcp.tool()
    async def <tool_name>(
        <param1>: Annotated[<type>, Field(description="<description>")],
        <param2>: Annotated[<type>, Field(description="<description>")] = <default>,
        mcp_session_id: str = "",
    ) -> dict:
        """<tool_description>"""
        # TODO: Implementation
        return {"status": "success"}
```

**Mandatory elements** (present the checklist to the developer):
- [ ] `def register(mcp):` wrapper function (not bare `@mcp.tool()`)
- [ ] All parameters use `Annotated[Type, Field(description=...)]`
- [ ] `mcp_session_id: str = ""` is the last parameter
- [ ] Return type is `dict`
- [ ] Docstring matches the tool description

Present the full file content and ask the developer to confirm before writing.

---

## Step 5: Update Server Registration

Read `<server_dir>/<package>/server.py` and add the import + registration call.

The pattern varies by server -- match what exists:

**Pattern A** (explicit imports in server.py):
```python
from <package>.tools import <tool_name>
# ... in create_app() or setup:
<tool_name>.register(mcp)
```

**Pattern B** (tools/__init__.py re-exports):
```python
# In tools/__init__.py, add:
from . import <tool_name>

# In server.py, the existing loop registers all:
for module in [existing_tool, <tool_name>]:
    module.register(mcp)
```

Show the developer the proposed edit and confirm before applying.

---

## Step 6: Create Test Stub

Create a unit test at `<server_dir>/tests/test_<tool_name>.py`:

```python
"""Unit tests for <tool_name> tool."""

import pytest


class TestToolSchema:
    """Verify <tool_name> appears in schema discovery."""

    def test_tool_registered(self):
        """Tool should be discoverable after register(mcp) call."""
        from <package>.tools import <tool_name>
        assert hasattr(<tool_name>, "register")
        assert callable(<tool_name>.register)


class TestToolLogic:
    """Unit tests for <tool_name> business logic."""

    @pytest.mark.asyncio
    async def test_basic_invocation(self):
        """Tool should return success dict with valid input."""
        # TODO: Implement with realistic test data
        pass
```

---

## Step 7: Update Documentation

Check if the server has a README.md or QUICKSTART.md with a tool count or tool list:

```bash
grep -n 'TOOL_COUNT\|tool_count\|tools available\|## Tools' <server_dir>/README.md <server_dir>/QUICKSTART.md 2>/dev/null
```

If found, update the count and add the new tool to the list.

---

## Step 8: Validate

Run the server's unit tests to verify the new tool is discoverable:

```bash
cd <server_dir> && make test-unit 2>&1 | tail -20
```

If `make test-unit` is not available, try:
```bash
cd <server_dir> && python3 -m pytest tests/test_<tool_name>.py -v 2>&1
```

**Validation checklist**:
- [ ] Tool file exists at `<package>/tools/<tool_name>.py`
- [ ] `register(mcp)` function present in tool file
- [ ] `server.py` imports and calls `<tool_name>.register(mcp)`
- [ ] Test file exists at `tests/test_<tool_name>.py`
- [ ] Unit tests pass (or are marked TODO with passing stubs)

Report results. If adding more tools, the developer can run `/mcp-add-tool` again.

Remind the developer of next steps in the lifecycle:
- More tools: `/mcp-add-tool`
- Run full test suite: `/mcp-test`
- Register with ADEPT: `/mcp-register`
- Close the task: `/close-task` (Phases 5-9)
