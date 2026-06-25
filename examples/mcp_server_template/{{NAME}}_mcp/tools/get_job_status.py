"""Zero-user-param tool pattern — only framework-injected parameters."""

import json


def register(mcp):
    @mcp.tool()
    async def {{NAME}}_get_job_status(
        job_session_id: str = "",
        mcp_session_id: str = "",  # Framework-injected, stripped from registration
    ) -> dict:
        """Get the status of a {{DISPLAY_NAME}} processing job.

        Returns the current status, progress, and any available results
        for the specified job session.
        """
        # TODO: Replace with actual job status lookup (e.g., from Redis or database)
        return {
            "job_session_id": job_session_id or mcp_session_id,
            "status": "unknown",
            "progress": 0,
            "message": "No active job found for this session",
        }
