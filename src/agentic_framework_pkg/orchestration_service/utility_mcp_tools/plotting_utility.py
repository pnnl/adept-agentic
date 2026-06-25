"""Plotting Utility MCP Tool

Provides client-specific rendering for plot visualizations with embedded presigned URLs.
"""
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)


class PlottingUtility:
    """Generate client-specific rendering for plot visualizations.

    This tool helps the orchestration agent format plot presigned URLs for optimal
    display in different client environments (Streamlit, OpenWebUI, Markdown, HTML).

    Args:
        presigned_url: Full presigned URL to the plot file
        title: Optional title/caption for the plot (default: "Plot")
        format: Output format - "markdown", "html", or "streamlit" (default: "markdown")
        width: Optional image width in pixels (only for HTML format)
        height: Optional image height in pixels (only for HTML format)
        alt_text: Optional alt text for accessibility (default: uses title)

    Returns:
        Dict with keys:
        - success: bool - Whether operation succeeded
        - rendered_output: str - Formatted rendering string ready for display
        - format: str - Output format used
        - error: str - Error message if success=False

    Example:
        >>> result = await PlottingUtility.execute(
        ...     presigned_url="https://api.agentic.local/v1/files/file-abc123.../download?token=xyz",
        ...     title="Iris Dataset Scatter Plot",
        ...     format="markdown"
        ... )
        >>> print(result["rendered_output"])
        ![Iris Dataset Scatter Plot](https://api.agentic.local/v1/files/file-abc123.../download?token=xyz)

    Format-Specific Outputs:

    1. **Markdown** (default):
       - Simple image syntax: `![title](url)`
       - Works in: Jupyter, GitHub, most Markdown renderers
       - Best for: General-purpose documentation

    2. **HTML**:
       - Full HTML img tag with optional width/height
       - Works in: Web browsers, rich text editors
       - Best for: Email, web embedding, custom styling

    3. **Streamlit**:
       - Bold title + Markdown image
       - Works in: Streamlit apps via st.markdown()
       - Best for: Streamlit Response API integration

    Use Cases:
        - Embedding plots in conversation responses
        - Formatting for specific client types
        - Accessibility-friendly image rendering
        - Responsive image sizing
    """

    name = "plotting_utility"
    description = """Format plot presigned URLs for optimal display in different client environments.

    Use this tool when you need to:
    - Present a plot to the user in their preferred format
    - Embed a plot visualization in your response
    - Format an image for Streamlit, OpenWebUI, or Markdown clients

    This tool takes a presigned URL and generates client-appropriate rendering
    (Markdown, HTML, or Streamlit format).
    """

    # Pydantic schema for LangChain tool arguments
    class ArgsSchema(BaseModel):
        presigned_url: str = Field(
            description="Full presigned URL to the plot file (from GeneratePresignedURL tool)"
        )
        title: Optional[str] = Field(
            default="Plot",
            description="Title or caption for the plot (default: 'Plot')"
        )
        format: str = Field(
            default="markdown",
            description="Output format: 'markdown', 'html', or 'streamlit' (default: 'markdown')"
        )
        width: Optional[int] = Field(
            default=None,
            description="Image width in pixels (only for HTML format)"
        )
        height: Optional[int] = Field(
            default=None,
            description="Image height in pixels (only for HTML format)"
        )
        alt_text: Optional[str] = Field(
            default=None,
            description="Alt text for accessibility (default: uses title)"
        )

    @classmethod
    async def execute(
        cls,
        presigned_url: str,
        title: Optional[str] = "Plot",
        format: str = "markdown",
        width: Optional[int] = None,
        height: Optional[int] = None,
        alt_text: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate client-specific rendering for a plot.

        Args:
            presigned_url: Full presigned URL to the plot file
            title: Title/caption for the plot
            format: Output format (markdown, html, streamlit)
            width: Image width in pixels (HTML only)
            height: Image height in pixels (HTML only)
            alt_text: Alt text for accessibility

        Returns:
            Dict with success status and rendered output
        """
        try:
            # Validate format
            valid_formats = ["markdown", "html", "streamlit"]
            if format not in valid_formats:
                return {
                    "success": False,
                    "error": f"Invalid format '{format}'. Must be one of: {', '.join(valid_formats)}"
                }

            # Use title as alt_text if not provided
            alt = alt_text or title

            # Generate format-specific rendering
            if format == "markdown":
                rendered = f"![{alt}]({presigned_url})"

            elif format == "html":
                # Build HTML img tag with optional width/height
                style_attrs = []
                if width:
                    style_attrs.append(f"width: {width}px")
                if height:
                    style_attrs.append(f"height: {height}px")

                style = f' style="{"; ".join(style_attrs)}"' if style_attrs else ""
                rendered = f'<img src="{presigned_url}" alt="{alt}" title="{title}"{style} />'

            elif format == "streamlit":
                # Streamlit format: Bold title + Markdown image
                rendered = f"**{title}**\n\n![{alt}]({presigned_url})"

            else:
                # This should never happen due to validation above
                return {
                    "success": False,
                    "error": f"Unsupported format: {format}"
                }

            logger.info(f"Generated {format} rendering for plot: {title}")
            return {
                "success": True,
                "rendered_output": rendered,
                "format": format
            }

        except Exception as e:
            logger.error(f"PlottingUtility error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Failed to generate plot rendering: {str(e)}"
            }
