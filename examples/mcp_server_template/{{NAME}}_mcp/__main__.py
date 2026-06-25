"""Entry point for ``python -m {{NAME}}_mcp``."""

if __name__ == "__main__":
    import uvicorn
    from {{NAME}}_mcp.config import settings
    uvicorn.run("{{NAME}}_mcp.app:app", host="0.0.0.0", port=settings.port)
