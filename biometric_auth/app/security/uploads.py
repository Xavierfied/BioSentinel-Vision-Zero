"""Upload size limits and image type checks."""

from fastapi import HTTPException, UploadFile, status
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings

JPEG_MAGIC = b"\xff\xd8\xff"


async def read_jpeg_upload(upload: UploadFile) -> bytes:
    """Read an uploaded frame, enforcing the size cap and JPEG-only input."""
    data = await upload.read(settings.max_request_bytes + 1)
    if len(data) > settings.max_request_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Image too large",
        )
    if not data.startswith(JPEG_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image must be a JPEG",
        )
    return data


class BodySizeLimitMiddleware:
    """Reject request bodies over ``max_bytes`` before they are parsed.

    Checks ``Content-Length`` up front and also counts streamed chunks, so a
    chunked upload without a length header cannot slip past.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    too_big = int(value) > self.max_bytes
                except ValueError:
                    too_big = False
                if too_big:
                    await _reject(send)
                    return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _reject(send)


class _BodyTooLarge(Exception):
    pass


async def _reject(send: Send) -> None:
    body = b'{"detail":"Request body too large"}'
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})
