"""Example tool with Annotated parameter pattern and session isolation."""

from pathlib import Path
from typing import Annotated

from pydantic import Field

from {{NAME}}_mcp.config import settings


def register(mcp):
    @mcp.tool()
    async def {{NAME}}_example_tool(
        input_file: Annotated[str, Field(description="Path to input data file")],
        model: Annotated[str, Field(default="default", description="Model name to use")] = "default",
        batch_size: Annotated[int, Field(default=16, description="Processing batch size")] = 16,
        mcp_session_id: str = "",  # Framework-injected, stripped from registration
    ) -> dict:
        """Run {{DISPLAY_NAME}} example tool on input data.

        Processes the input file using the specified model and returns results.
        Replace this with your domain-specific logic.
        """
        # Session isolation — each MCP session gets its own results directory
        session_dir = Path(settings.results_dir) / mcp_session_id if mcp_session_id else Path(settings.results_dir)
        session_dir.mkdir(parents=True, exist_ok=True)

        # TODO: Replace with domain-specific processing logic
        output_path = session_dir / "output.json"
        output_path.write_text('{"result": "placeholder"}')

        return {
            "status": "completed",
            "model": model,
            "batch_size": batch_size,
            "input_file": input_file,
            "output_file": str(output_path),
        }
