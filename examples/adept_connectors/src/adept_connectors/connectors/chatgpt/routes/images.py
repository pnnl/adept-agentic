"""Image proxy route — GET /v1/images/{token}.

Serves image bytes from the in-memory cache populated by
ChatGPTImageRenderer. ChatGPT embeds these URLs as markdown images.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter()


@router.get("/images/{token}")
async def get_image(request: Request, token: str) -> Response:
    """Serve a cached image by its proxy token.

    Returns the raw image bytes with the correct Content-Type.
    Tokens expire after the configured TTL (default: 10 minutes).
    """
    image_cache = request.app.state.image_cache
    image = image_cache.get(token)

    if image is None:
        return Response(
            content=b'{"error": "Image not found or expired"}',
            status_code=404,
            media_type="application/json",
        )

    return Response(
        content=image.data,
        media_type=image.mime_type,
        headers={
            "Cache-Control": "public, max-age=300",
            "X-Image-Size": str(image.size_bytes),
        },
    )
