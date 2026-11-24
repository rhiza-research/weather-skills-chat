"""GZipJSONMiddleware compresses complete JSON bodies and leaves everything else alone."""

from __future__ import annotations

import asyncio
import gzip
import json

from open_webui.utils.gzip_json import GZipJSONMiddleware

BIG_JSON = json.dumps({"messages": ["tool output " * 20] * 500}).encode()


def _app(content_type: bytes, chunks: list[bytes], extra_headers=(), sized=None):
    """sized: send Content-Length (defaults to True for a single chunk)."""

    async def app(scope, receive, send):
        headers = [(b"content-type", content_type), *extra_headers]
        if sized if sized is not None else len(chunks) == 1:
            headers.append((b"content-length", str(sum(map(len, chunks))).encode()))
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        for i, chunk in enumerate(chunks):
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": i < len(chunks) - 1,
                }
            )

    return app


def _call(app, accept_encoding: bytes | None = b"gzip, deflate, br"):
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    headers = [(b"accept-encoding", accept_encoding)] if accept_encoding else []
    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers}
    asyncio.run(GZipJSONMiddleware(app)(scope, receive, send))
    start = sent[0]
    return (
        {k.decode().lower(): v.decode() for k, v in start["headers"]},
        [m.get("body", b"") for m in sent[1:]],
    )


def test_large_json_is_gzipped():
    headers, bodies = _call(_app(b"application/json", [BIG_JSON]))
    assert headers["content-encoding"] == "gzip"
    assert "accept-encoding" in headers["vary"].lower()
    assert len(bodies) == 1
    assert headers["content-length"] == str(len(bodies[0]))
    assert len(bodies[0]) < len(BIG_JSON) / 5
    assert gzip.decompress(bodies[0]) == BIG_JSON


def test_sized_json_split_across_messages_is_gzipped():
    # @app.middleware("http") layers resend a body as chunks plus an empty last message.
    half = len(BIG_JSON) // 2
    chunks = [BIG_JSON[:half], BIG_JSON[half:], b""]
    headers, bodies = _call(_app(b"application/json", chunks, sized=True))
    assert headers["content-encoding"] == "gzip"
    assert len(bodies) == 1
    assert headers["content-length"] == str(len(bodies[0]))
    assert gzip.decompress(bodies[0]) == BIG_JSON


def test_json_with_charset_is_gzipped():
    headers, bodies = _call(_app(b"application/json; charset=utf-8", [BIG_JSON]))
    assert headers["content-encoding"] == "gzip"
    assert gzip.decompress(bodies[0]) == BIG_JSON


def test_client_without_gzip_gets_plain_json():
    headers, bodies = _call(_app(b"application/json", [BIG_JSON]), accept_encoding=None)
    assert "content-encoding" not in headers
    assert bodies == [BIG_JSON]


def test_small_json_is_not_gzipped():
    headers, bodies = _call(_app(b"application/json", [b'{"ok": true}']))
    assert "content-encoding" not in headers
    assert bodies == [b'{"ok": true}']


def test_streamed_responses_pass_through_chunk_by_chunk():
    chunks = [b"data: " + b"x" * 2000 + b"\n\n", b"data: [DONE]\n\n"]
    for content_type in (b"text/event-stream", b"application/json"):
        headers, bodies = _call(_app(content_type, chunks))
        assert "content-encoding" not in headers
        assert bodies == chunks


def test_non_json_is_not_gzipped():
    headers, bodies = _call(_app(b"image/png", [b"\x89PNG" + b"\x00" * 5000]))
    assert "content-encoding" not in headers
    assert bodies == [b"\x89PNG" + b"\x00" * 5000]


def test_already_encoded_body_is_untouched():
    headers, bodies = _call(
        _app(b"application/json", [BIG_JSON], extra_headers=[(b"content-encoding", b"br")])
    )
    assert headers["content-encoding"] == "br"
    assert bodies == [BIG_JSON]
