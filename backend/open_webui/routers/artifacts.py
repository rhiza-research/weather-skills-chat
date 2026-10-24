import asyncio
import hashlib
import io
import logging
import zlib
from email.utils import formatdate, parsedate_to_datetime
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.artifacts import (
    HTML_SUFFIXES,
    extract_sandbox_archive,
    is_zarr_store,
    list_artifacts_async,
    pack_sandbox_archive,
    pack_sandbox_zip,
    resolve_in_sandbox,
    write_bytes,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import require_chat_read, require_chat_write

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


@router.get("/{chat_id}/artifacts")
async def get_artifacts(
    chat_id: str,
    depth: Optional[int] = Query(None, ge=1),
    provenance: bool = True,
    user=Depends(get_verified_user),
):
    await asyncio.to_thread(require_chat_read, chat_id, user)
    return await list_artifacts_async(chat_id, depth=depth, provenance=provenance)


@router.get("/{chat_id}/artifacts/content")
def get_artifact_content(
    chat_id: str, path: str, request: Request, user=Depends(get_verified_user)
):
    require_chat_read(chat_id, user)
    try:
        target = resolve_in_sandbox(chat_id, path)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if is_zarr_store(target) or target.is_dir():
        try:
            data = pack_sandbox_zip(chat_id, [path])
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        name = target.name.rstrip("/") or "artifacts"
        if not name.endswith(".zip"):
            name = f"{name}.zip"
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    # The chat shows images by fetching this. Same policy as HTML views: the
    # browser keeps a copy and asks before each use, and an unchanged file
    # answers 304 with no body.
    st = target.stat()
    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
    last_modified = formatdate(st.st_mtime, usegmt=True)
    headers = {
        "Cache-Control": "private, no-cache",
        "ETag": etag,
        "Last-Modified": last_modified,
    }
    if _not_modified(request, etag, last_modified):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return FileResponse(
        target,
        filename=target.name,
        content_disposition_type="attachment",
        headers=headers,
        stat_result=st,
    )


# HTML artifacts (for example Plotly figures) are shown in iframes. The CSP
# sandbox makes the browser give the page its own opaque origin, so its scripts
# cannot read this app's storage or cookies or call its API as the user. The
# header applies even when the URL is opened directly in a tab.
HTML_VIEW_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-downloads",
    "X-Content-Type-Options": "nosniff",
    # Third-party scripts the page loads (Plotly's CDN) do not learn the chat id.
    "Referrer-Policy": "no-referrer",
    # The browser keeps a copy but asks before each use; an unchanged file
    # answers 304 with no body (see the ETag below).
    "Cache-Control": "private, no-cache",
    "Vary": "Accept-Encoding",
}

# Reports a fixed-size Plotly figure's size so the chat can scale the frame;
# read only. Appended inline because the sandboxed page cannot load the app's
# own files.
REPORT_SIZE_SCRIPT = (
    Path(__file__).resolve().parent.parent / "static" / "artifact" / "report-size.js"
).read_bytes()
VIEW_CHUNK_BYTES = 1024 * 1024
# Part of the ETag, so a deploy that changes the appended script is not served
# from a browser's cached copy.
REPORT_SIZE_SCRIPT_TAG = hashlib.sha256(REPORT_SIZE_SCRIPT).hexdigest()[:8]


def _html_with_size_report(target: Path):
    with target.open("rb") as f:
        while chunk := f.read(VIEW_CHUNK_BYTES):
            yield chunk
    yield b"\n<script>\n" + REPORT_SIZE_SCRIPT + b"\n</script>\n"


def _gzip_stream(chunks):
    """Gzip a byte stream as it goes. Plotly pages are mostly JSON and shrink
    about 3x; nothing in front of the app compresses them."""
    compressor = zlib.compressobj(6, zlib.DEFLATED, 31)
    for chunk in chunks:
        out = compressor.compress(chunk)
        if out:
            yield out
    yield compressor.flush()


def _view_validators(target: Path) -> tuple[str, str]:
    st = target.stat()
    # Weak: the gzipped and plain bodies differ byte for byte.
    etag = f'W/"{st.st_mtime_ns:x}-{st.st_size:x}-{REPORT_SIZE_SCRIPT_TAG}"'
    return etag, formatdate(st.st_mtime, usegmt=True)


def _not_modified(request: Request, etag: str, last_modified: str) -> bool:
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        tags = [t.strip() for t in if_none_match.split(",")]
        return "*" in tags or etag in tags or etag.removeprefix("W/") in tags
    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since:
        try:
            return parsedate_to_datetime(last_modified) <= parsedate_to_datetime(
                if_modified_since
            )
        except (TypeError, ValueError):
            return False
    return False


@router.get("/{chat_id}/artifacts/view/{path:path}")
def view_html_artifact(
    chat_id: str, path: str, request: Request, user=Depends(get_verified_user)
):
    require_chat_read(chat_id, user)
    try:
        target = resolve_in_sandbox(chat_id, path)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if target.suffix.lower() not in HTML_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only .html artifacts can be viewed",
        )
    etag, last_modified = _view_validators(target)
    headers = {**HTML_VIEW_HEADERS, "ETag": etag, "Last-Modified": last_modified}
    if _not_modified(request, etag, last_modified):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    body = _html_with_size_report(target)
    if "gzip" in request.headers.get("accept-encoding", "").lower():
        headers["Content-Encoding"] = "gzip"
        body = _gzip_stream(body)
    return StreamingResponse(
        body, media_type="text/html; charset=utf-8", headers=headers
    )


@router.get("/{chat_id}/artifacts/archive")
def get_artifact_archive(
    chat_id: str,
    path: list[str] = Query(..., min_length=1),
    format: str = Query("tar.gz"),
    user=Depends(get_verified_user),
):
    require_chat_read(chat_id, user)
    fmt = (format or "tar.gz").lower().strip()
    if fmt not in ("tar.gz", "zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="format must be tar.gz or zip",
        )
    try:
        data = (
            pack_sandbox_zip(chat_id, path)
            if fmt == "zip"
            else pack_sandbox_archive(chat_id, path)
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    ext = ".zip" if fmt == "zip" else ".tar.gz"
    media_type = "application/zip" if fmt == "zip" else "application/gzip"
    if len(path) == 1:
        name = path[0].rstrip("/").split("/")[-1] or "artifacts"
        if not name.endswith(ext):
            name = f"{name}{ext}"
        disposition = f'attachment; filename="{name}"'
    else:
        disposition = f'attachment; filename="artifacts{ext}"'
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@router.post("/{chat_id}/artifacts/archive")
async def upload_artifact_archive(
    chat_id: str,
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
):
    await asyncio.to_thread(require_chat_write, chat_id, user)
    data = await file.read()
    try:
        written = await asyncio.to_thread(extract_sandbox_archive, chat_id, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    from open_webui.utils.chat_realtime import schedule_artifacts

    schedule_artifacts(chat_id)
    return {"ok": True, "written": written}


@router.post("/{chat_id}/artifacts")
async def upload_artifact(
    chat_id: str,
    path: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
):
    await asyncio.to_thread(require_chat_write, chat_id, user)
    data = await file.read()
    try:
        await asyncio.to_thread(write_bytes, chat_id, path, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    from open_webui.utils.chat_realtime import schedule_artifacts

    schedule_artifacts(chat_id)
    return await list_artifacts_async(chat_id)


@router.get("/{chat_id}/artifacts/zarr/meta")
def zarr_meta(chat_id: str, path: str, user=Depends(get_verified_user)):
    require_chat_read(chat_id, user)
    try:
        target = resolve_in_sandbox(chat_id, path)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not is_zarr_store(target):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a zarr store"
        )
    try:
        import xarray as xr

        ds = xr.open_zarr(target, consolidated=False)
        return {
            "variables": {
                name: {
                    "dims": list(da.dims),
                    "shape": list(da.shape),
                    "attrs": {k: str(v) for k, v in da.attrs.items()},
                }
                for name, da in ds.data_vars.items()
            },
            "dims": {name: int(size) for name, size in ds.sizes.items()},
            "attrs": {k: str(v) for k, v in ds.attrs.items()},
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
