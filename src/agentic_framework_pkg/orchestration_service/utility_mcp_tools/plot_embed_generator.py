"""
Plot Embed Code Generator - Utility MCP Tool

Generates platform-specific embeddable code for plots created by ExecuteCode.

This tool enables agents to provide copy-paste ready embedding code for various
platforms (Streamlit, HTML, Jupyter, OpenWebUI, etc.) based on user requests.

Key Features:
- Multiple output formats (markdown, streamlit, html, jupyter, openwebui, all)
- Support for single and multiple plots
- Flexible layouts (vertical, horizontal, grid, single)
- Optional captions and download links
- Customizable width settings

Usage:
    User: "Generate an iris plot and give me Streamlit code to display it"
    Agent: ExecuteCode → RegisterLocalFile → GeneratePresignedURL → GeneratePlotEmbedCode(format="streamlit")
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
import logging

logger = logging.getLogger(__name__)


class GeneratePlotEmbedCodeInput(BaseModel):
    """Input schema for GeneratePlotEmbedCode tool."""

    urls: List[str] = Field(
        ...,
        description="List of plot URLs to embed (can be plot_url from ExecuteCode or presigned_url from GeneratePresignedURL)"
    )
    format: Literal["markdown", "streamlit", "html", "jupyter", "openwebui", "all"] = Field(
        default="markdown",
        description="Output format: 'markdown' (GitHub/Notion/OpenWebUI), 'streamlit' (st.image code), 'html' (img tags), 'jupyter' (IPython.display), 'openwebui' (optimized markdown), 'all' (all formats)"
    )
    captions: Optional[List[str]] = Field(
        default=None,
        description="Optional captions for each plot (must match length of urls if provided)"
    )
    layout: Literal["vertical", "horizontal", "grid", "single"] = Field(
        default="vertical",
        description="Layout for multiple plots: 'vertical' (stacked), 'horizontal' (side-by-side), 'grid' (2-column grid), 'single' (first plot only)"
    )
    width: Optional[int] = Field(
        default=None,
        description="Optional width in pixels for HTML/Streamlit output (e.g., 800)"
    )
    include_download_links: bool = Field(
        default=False,
        description="Whether to include download links alongside embed code"
    )
    auto_render: bool = Field(
        default=False,
        description="If True, returns embedded markdown/HTML for direct display (like plotting_utility). If False (default), returns copy-paste code snippets."
    )


class GeneratePlotEmbedCode:
    """
    Generate platform-specific embeddable code for plots.

    This utility tool transforms plot URLs into copy-paste ready embedding code
    for various platforms. It supports single and multiple plots with flexible
    layouts and formatting options.

    Supported Platforms:
    - Markdown: GitHub, Notion, general markdown viewers
    - Streamlit: st.image() code with optional width/captions
    - HTML: <img> tags with optional CSS styling
    - Jupyter: IPython.display.Image() code
    - OpenWebUI: Optimized markdown for chat interfaces
    - All: Returns code for all platforms

    Examples:
        # Single plot, markdown format
        result = await GeneratePlotEmbedCode.execute(
            urls=["http://localhost:8083/v1/plots/plot_abc123.png"],
            format="markdown"
        )

        # Multiple plots, Streamlit with captions
        result = await GeneratePlotEmbedCode.execute(
            urls=["http://plot1.png", "http://plot2.png"],
            format="streamlit",
            captions=["Iris Pairplot", "Feature Distribution"],
            layout="horizontal"
        )

        # HTML with custom width
        result = await GeneratePlotEmbedCode.execute(
            urls=["http://plot.png"],
            format="html",
            width=800
        )
    """

    @staticmethod
    def _generate_markdown_embed(urls: List[str], captions: Optional[List[str]] = None, layout: str = "vertical") -> str:
        """Generate markdown image syntax."""
        if not urls:
            return ""

        if layout == "single":
            urls = urls[:1]
            captions = captions[:1] if captions else None

        lines = []
        for i, url in enumerate(urls):
            caption = captions[i] if captions and i < len(captions) else f"Plot {i+1}"
            lines.append(f"![{caption}]({url})")

        if layout == "horizontal":
            # Markdown doesn't natively support horizontal layout, add spacing
            return " ".join(lines)
        elif layout == "grid":
            # 2-column grid using line breaks
            result = []
            for i in range(0, len(lines), 2):
                if i + 1 < len(lines):
                    result.append(f"{lines[i]} {lines[i+1]}")
                else:
                    result.append(lines[i])
            return "\n\n".join(result)
        else:  # vertical
            return "\n\n".join(lines)

    @staticmethod
    def _generate_streamlit_embed(urls: List[str], captions: Optional[List[str]] = None, layout: str = "vertical", width: Optional[int] = None) -> str:
        """Generate Streamlit st.image() code."""
        if not urls:
            return ""

        if layout == "single":
            urls = urls[:1]
            captions = captions[:1] if captions else None

        lines = ["import streamlit as st", ""]

        if layout == "horizontal":
            # Use st.columns for horizontal layout
            lines.append(f"cols = st.columns({len(urls)})")
            for i, url in enumerate(urls):
                caption = captions[i] if captions and i < len(captions) else None
                width_param = f", width={width}" if width else ""
                caption_param = f", caption='{caption}'" if caption else ""
                lines.append(f"with cols[{i}]:")
                lines.append(f"    st.image('{url}'{width_param}{caption_param})")
        elif layout == "grid":
            # 2-column grid
            lines.append("# 2-column grid layout")
            for i in range(0, len(urls), 2):
                lines.append(f"cols = st.columns(2)")
                for j, idx in enumerate(range(i, min(i+2, len(urls)))):
                    url = urls[idx]
                    caption = captions[idx] if captions and idx < len(captions) else None
                    width_param = f", width={width}" if width else ""
                    caption_param = f", caption='{caption}'" if caption else ""
                    lines.append(f"with cols[{j}]:")
                    lines.append(f"    st.image('{url}'{width_param}{caption_param})")
        else:  # vertical or single
            for i, url in enumerate(urls):
                caption = captions[i] if captions and i < len(captions) else None
                width_param = f", width={width}" if width else ""
                caption_param = f", caption='{caption}'" if caption else ""
                lines.append(f"st.image('{url}'{width_param}{caption_param})")

        return "\n".join(lines)

    @staticmethod
    def _generate_html_embed(urls: List[str], captions: Optional[List[str]] = None, layout: str = "vertical", width: Optional[int] = None) -> str:
        """Generate HTML img tags with optional CSS."""
        if not urls:
            return ""

        if layout == "single":
            urls = urls[:1]
            captions = captions[:1] if captions else None

        width_style = f"width: {width}px;" if width else ""

        if layout == "horizontal":
            # Use flexbox for horizontal layout
            html = ['<div style="display: flex; gap: 20px; flex-wrap: wrap;">']
            for i, url in enumerate(urls):
                caption = captions[i] if captions and i < len(captions) else None
                html.append('  <div style="flex: 1;">')
                html.append(f'    <img src="{url}" alt="Plot {i+1}" style="{width_style}">')
                if caption:
                    html.append(f'    <p style="text-align: center;">{caption}</p>')
                html.append('  </div>')
            html.append('</div>')
        elif layout == "grid":
            # CSS grid layout (2 columns)
            html = ['<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px;">']
            for i, url in enumerate(urls):
                caption = captions[i] if captions and i < len(captions) else None
                html.append('  <div>')
                html.append(f'    <img src="{url}" alt="Plot {i+1}" style="{width_style} width: 100%;">')
                if caption:
                    html.append(f'    <p style="text-align: center;">{caption}</p>')
                html.append('  </div>')
            html.append('</div>')
        else:  # vertical or single
            html = []
            for i, url in enumerate(urls):
                caption = captions[i] if captions and i < len(captions) else None
                html.append(f'<img src="{url}" alt="Plot {i+1}" style="{width_style}">')
                if caption:
                    html.append(f'<p>{caption}</p>')

        return "\n".join(html)

    @staticmethod
    def _generate_openwebui_embed(urls: List[str], captions: Optional[List[str]] = None, layout: str = "vertical") -> str:
        """Generate optimized markdown for OpenWebUI chat interface."""
        # OpenWebUI works best with simple markdown, similar to base markdown but optimized for chat
        return GeneratePlotEmbedCode._generate_markdown_embed(urls, captions, layout)

    @staticmethod
    def _generate_jupyter_embed(urls: List[str], captions: Optional[List[str]] = None, layout: str = "vertical", width: Optional[int] = None) -> str:
        """Generate IPython.display.Image code for Jupyter notebooks."""
        if not urls:
            return ""

        if layout == "single":
            urls = urls[:1]
            captions = captions[:1] if captions else None

        lines = ["from IPython.display import Image, display", ""]

        for i, url in enumerate(urls):
            caption = captions[i] if captions and i < len(captions) else None
            width_param = f", width={width}" if width else ""
            if caption:
                lines.append(f"# {caption}")
            lines.append(f"display(Image(url='{url}'{width_param}))")

        return "\n".join(lines)

    @staticmethod
    async def execute(
        urls: List[str],
        format: str = "markdown",
        captions: Optional[List[str]] = None,
        layout: str = "vertical",
        width: Optional[int] = None,
        include_download_links: bool = False,
        auto_render: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the GeneratePlotEmbedCode tool.

        Args:
            urls: List of plot URLs to embed
            format: Output format (markdown, streamlit, html, jupyter, openwebui, all)
            captions: Optional captions for each plot
            layout: Layout for multiple plots (vertical, horizontal, grid, single)
            width: Optional width in pixels
            include_download_links: Whether to include download links
            auto_render: If True, returns embedded markdown for direct display (uses plotting_utility internally)

        Returns:
            Dictionary with embed_code and optional download_links
        """
        try:
            # Validate inputs
            if not urls:
                return {
                    "success": False,
                    "error": "No URLs provided",
                    "embed_code": ""
                }

            # NEW: Auto-render mode (use plotting_utility internally)
            if auto_render:
                # Only supports single plot for now (plotting_utility limitation)
                if len(urls) > 1:
                    logger.warning(f"auto_render only supports single plot, using first URL from {len(urls)}")
                    urls = urls[:1]

                if format not in ["markdown", "html", "streamlit"]:
                    return {
                        "success": False,
                        "error": f"auto_render only supports markdown/html/streamlit, got: {format}"
                    }

                # Call plotting_utility internally
                from .plotting_utility import PlottingUtility
                caption = captions[0] if captions else "Plot"

                result = await PlottingUtility.execute(
                    presigned_url=urls[0],
                    title=caption,
                    format=format,
                    width=width,
                    height=None,
                    alt_text=None
                )

                # Transform PlottingUtility output to GeneratePlotEmbedCode format
                if result["success"]:
                    return {
                        "success": True,
                        "embed_code": result["rendered_output"],  # Embedded markdown/HTML
                        "format": format,
                        "plot_count": 1,
                        "layout": "single",
                        "auto_rendered": True  # Flag indicating direct rendering
                    }
                else:
                    return result  # Pass through error

            if captions and len(captions) != len(urls):
                logger.warning(f"Captions length ({len(captions)}) doesn't match URLs length ({len(urls)}), truncating")
                captions = captions[:len(urls)]

            # Generate embed code based on format
            if format == "all":
                embed_code = {
                    "markdown": GeneratePlotEmbedCode._generate_markdown_embed(urls, captions, layout),
                    "streamlit": GeneratePlotEmbedCode._generate_streamlit_embed(urls, captions, layout, width),
                    "html": GeneratePlotEmbedCode._generate_html_embed(urls, captions, layout, width),
                    "jupyter": GeneratePlotEmbedCode._generate_jupyter_embed(urls, captions, layout, width),
                    "openwebui": GeneratePlotEmbedCode._generate_openwebui_embed(urls, captions, layout)
                }
            elif format == "markdown":
                embed_code = GeneratePlotEmbedCode._generate_markdown_embed(urls, captions, layout)
            elif format == "streamlit":
                embed_code = GeneratePlotEmbedCode._generate_streamlit_embed(urls, captions, layout, width)
            elif format == "html":
                embed_code = GeneratePlotEmbedCode._generate_html_embed(urls, captions, layout, width)
            elif format == "jupyter":
                embed_code = GeneratePlotEmbedCode._generate_jupyter_embed(urls, captions, layout, width)
            elif format == "openwebui":
                embed_code = GeneratePlotEmbedCode._generate_openwebui_embed(urls, captions, layout)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported format: {format}",
                    "embed_code": ""
                }

            result = {
                "success": True,
                "embed_code": embed_code,
                "format": format,
                "plot_count": len(urls),
                "layout": layout
            }

            # Add download links if requested
            if include_download_links:
                result["download_links"] = urls

            logger.info(f"Generated {format} embed code for {len(urls)} plot(s) with {layout} layout")
            return result

        except Exception as e:
            logger.error(f"Error generating plot embed code: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "embed_code": ""
            }
