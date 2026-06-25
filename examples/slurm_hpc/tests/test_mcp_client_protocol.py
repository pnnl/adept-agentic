"""
MCP Client Protocol Tests (Tier 2)
====================================

Validates MCP server functionality using the official FastMCP Client library
instead of raw HTTP/httpx. This provides higher-fidelity testing of the MCP
Streamable HTTP transport since the client handles session negotiation,
Accept headers, and SSE parsing automatically.

Complements test_slurm_deployment.py (httpx-based transport tests) by testing
the same endpoints through the canonical MCP client path that real ADEPT
orchestration services use.

Prerequisites:
    - Slurm MCP server running: cd examples/slurm_hpc && make start
    - Set SLURM_MCP_RUNNING=1 env var

Run with:
    make test-mcp-client        # requires: make start
    make nohup-test-mcp-client  # background with timestamped log
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("SLURM_MCP_RUNNING"),
    reason="Requires running MCP server (SLURM_MCP_RUNNING not set)",
)

MCP_URL = os.getenv("SLURM_MCP_URL", "http://slurm_mcp_server:8002")


class TestMCPClientConnection:
    """Validate MCP server connectivity using the official FastMCP Client."""

    @pytest.mark.asyncio
    async def test_client_connects_to_server(self):
        """FastMCP Client successfully connects and initializes session."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            # Connection + initialize handshake succeeded if we get here
            assert client is not None

    @pytest.mark.asyncio
    async def test_client_lists_tools(self):
        """FastMCP Client discovers all 27 registered Slurm tools.

        Validates the complete MCP Streamable HTTP lifecycle:
        1. Client connects → initialize handshake → mcp-session-id acquired
        2. Client calls tools/list → server returns registered tools via SSE
        3. Response includes all 27 expected Slurm MCP tools with schemas (6 local + 6 deception + 6 tahoma + 5 ssh_key + 4 workspace)
        """
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()

            tool_names = {t.name for t in tools}
            expected = {
                "submit_slurm_job",
                "get_job_details",
                "cancel_slurm_job",
                "ping",
                "list_cluster_jobs",
                "get_cluster_summary",
            }
            assert expected.issubset(tool_names), (
                f"Missing tools: {expected - tool_names}"
            )
            assert len(tools) >= 27, f"Expected at least 27 tools, got {len(tools)}"


class TestMCPClientToolSchemas:
    """Validate tool schemas exposed via the MCP protocol match expectations."""

    @pytest.mark.asyncio
    async def test_submit_slurm_job_has_request_param(self):
        """submit_slurm_job schema includes the 'request' parameter."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            submit_tool = next(
                (t for t in tools if t.name == "submit_slurm_job"), None
            )
            assert submit_tool is not None, "submit_slurm_job tool not found"
            schema = submit_tool.inputSchema
            assert "properties" in schema
            assert "request" in schema["properties"], (
                f"Missing 'request' param in submit_slurm_job schema: "
                f"{list(schema['properties'].keys())}"
            )

    @pytest.mark.asyncio
    async def test_get_job_details_has_job_id_param(self):
        """get_job_details schema includes the 'job_id' string parameter."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            detail_tool = next(
                (t for t in tools if t.name == "get_job_details"), None
            )
            assert detail_tool is not None
            schema = detail_tool.inputSchema
            assert "job_id" in schema.get("properties", {}), (
                f"Missing 'job_id' in get_job_details schema"
            )

    @pytest.mark.asyncio
    async def test_cancel_slurm_job_has_job_id_param(self):
        """cancel_slurm_job schema includes the 'job_id' string parameter."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            cancel_tool = next(
                (t for t in tools if t.name == "cancel_slurm_job"), None
            )
            assert cancel_tool is not None
            schema = cancel_tool.inputSchema
            assert "job_id" in schema.get("properties", {}), (
                f"Missing 'job_id' in cancel_slurm_job schema"
            )

    @pytest.mark.asyncio
    async def test_ping_requires_no_params(self):
        """ping tool requires no parameters (empty or optional-only schema)."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            ping_tool = next((t for t in tools if t.name == "ping"), None)
            assert ping_tool is not None
            schema = ping_tool.inputSchema
            required = schema.get("required", [])
            assert len(required) == 0, (
                f"ping should have no required params, got: {required}"
            )

    @pytest.mark.asyncio
    async def test_list_cluster_jobs_filters_optional(self):
        """list_cluster_jobs 'filters' parameter is optional."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            list_tool = next(
                (t for t in tools if t.name == "list_cluster_jobs"), None
            )
            assert list_tool is not None
            schema = list_tool.inputSchema
            required = schema.get("required", [])
            assert "filters" not in required, (
                "'filters' should be optional in list_cluster_jobs"
            )

    @pytest.mark.asyncio
    async def test_get_cluster_summary_partition_optional(self):
        """get_cluster_summary 'partition' parameter is optional."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            summary_tool = next(
                (t for t in tools if t.name == "get_cluster_summary"), None
            )
            assert summary_tool is not None
            schema = summary_tool.inputSchema
            required = schema.get("required", [])
            assert "partition" not in required, (
                "'partition' should be optional in get_cluster_summary"
            )


class TestMCPClientToolDescriptions:
    """Validate tool descriptions are verbose and informative for registration."""

    @pytest.mark.asyncio
    async def test_all_tools_have_descriptions(self):
        """Every registered tool has a non-empty description."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            for tool in tools:
                assert tool.description, (
                    f"Tool '{tool.name}' has no description"
                )

    @pytest.mark.asyncio
    async def test_descriptions_are_verbose(self):
        """Tool descriptions are informative (>50 chars) for registration display.

        When tools are registered with ADEPT, their descriptions are shown to
        orchestration agents and users. Terse descriptions lead to poor tool
        selection by LLMs. This test ensures descriptions are substantive.
        """
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            for tool in tools:
                desc = tool.description or ""
                assert len(desc) >= 50, (
                    f"Tool '{tool.name}' description too short ({len(desc)} chars): "
                    f"'{desc[:80]}...'. "
                    f"Descriptions should be verbose for registration display."
                )

    @pytest.mark.asyncio
    async def test_submit_tool_mentions_slurmrestd(self):
        """submit_slurm_job description mentions slurmrestd API for context."""
        from fastmcp import Client

        async with Client(f"{MCP_URL}/mcp") as client:
            tools = await client.list_tools()
            submit_tool = next(
                (t for t in tools if t.name == "submit_slurm_job"), None
            )
            desc = (submit_tool.description or "").lower()
            assert "slurmrestd" in desc or "rest api" in desc or "batch job" in desc, (
                f"submit_slurm_job description should mention slurmrestd/REST API: "
                f"{submit_tool.description[:100]}"
            )
