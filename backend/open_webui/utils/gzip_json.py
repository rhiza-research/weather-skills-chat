"""Gzip JSON responses whose size is known up front.

Starlette's GZipMiddleware would also gzip streamed replies, holding small
chunks inside the compressor, and files that are already compressed. This one
compresses only JSON responses with a Content-Length and passes everything
else through. The Content-Length check, not the chunk count, separates them:
@app.middleware("http") layers resend every body as several messages, while
streamed replies never carry a Content-Length.
"""

from __future__ import annotations

import asyncio
import gzip

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MINIMUM_SIZE = 1024
# Larger bodies compress in a worker thread (zlib releases the GIL) so the event loop keeps running.
THREAD_SIZE = 64 * 1024
COMPRESS_LEVEL = 6


def _should_compress(headers: Headers) -> bool:
    content_type = headers.get("content-type", "").split(";")[0].strip()
    length = headers.get("content-length", "")
    return (
        content_type == "application/json"
        and "content-encoding" not in headers
        and length.isdigit()
        and int(length) >= MINIMUM_SIZE
    )


class GZipJSONMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or "gzip" not in Headers(scope=scope).get(
            "accept-encoding", ""
        ):
            await self.app(scope, receive, send)
            return

        start: Message | None = None
        chunks: list[bytes] = []

        async def send_wrapper(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                if _should_compress(Headers(raw=message["headers"])):
                    start = message
                else:
                    await send(message)
                return
            if start is None:
                await send(message)
                return
            chunks.append(message.get("body", b""))
            if message.get("more_body", False):
                return
            body = b"".join(chunks)
            if len(body) >= THREAD_SIZE:
                body = await asyncio.to_thread(gzip.compress, body, COMPRESS_LEVEL)
            else:
                body = gzip.compress(body, COMPRESS_LEVEL)
            headers = MutableHeaders(raw=start["headers"])
            headers["content-encoding"] = "gzip"
            headers["content-length"] = str(len(body))
            headers.add_vary_header("Accept-Encoding")
            await send(start)
            await send({"type": "http.response.body", "body": body, "more_body": False})

        await self.app(scope, receive, send_wrapper)
