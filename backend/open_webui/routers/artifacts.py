import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.artifacts import (
    is_zarr_store,
    is_zarr_view,
    list_artifacts,
    read_view,
    resolve_in_sandbox,
    write_bytes,
    write_json,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.teams import can_read_chat, can_write_chat
from open_webui.models.chats import Chats
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


def _readable(chat_id: str, user):
    chat = Chats.get_chat_by_id(chat_id)
    if not can_read_chat(user, chat):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return chat


def _writable(chat_id: str, user):
    chat = Chats.get_chat_by_id(chat_id)
    if not can_write_chat(user, chat):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return chat


@router.get("/{chat_id}/artifacts")
async def get_artifacts(chat_id: str, user=Depends(get_verified_user)):
    _readable(chat_id, user)
    return list_artifacts(chat_id)


@router.get("/{chat_id}/artifacts/content")
async def get_artifact_content(
    chat_id: str, path: str, user=Depends(get_verified_user)
):
    _readable(chat_id, user)
    try:
        target = resolve_in_sandbox(chat_id, path)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return FileResponse(target, filename=target.name)


@router.post("/{chat_id}/artifacts")
async def upload_artifact(
    chat_id: str,
    path: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
):
    _writable(chat_id, user)
    data = await file.read()
    try:
        write_bytes(chat_id, path, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return list_artifacts(chat_id)


class ZarrViewForm(BaseModel):
    path: Optional[str] = None
    zarr: str
    title: Optional[str] = None
    variable: Optional[str] = None
    style: str = "heatmap"
    colormap: str = "viridis"
    index: Optional[dict] = None
    bbox: Optional[list] = None


@router.get("/{chat_id}/artifacts/zarr/meta")
async def zarr_meta(chat_id: str, path: str, user=Depends(get_verified_user)):
    _readable(chat_id, user)
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


@router.post("/{chat_id}/artifacts/zarr/views")
async def create_zarr_view(
    chat_id: str, form_data: ZarrViewForm, user=Depends(get_verified_user)
):
    _writable(chat_id, user)
    relpath = form_data.path or f"views/{(form_data.title or 'view').replace(' ', '-').lower()}.zarrview.json"
    payload = {
        "type": "zarr_view",
        "zarr": form_data.zarr,
        "title": form_data.title or relpath,
        "variable": form_data.variable,
        "style": form_data.style,
        "colormap": form_data.colormap,
        "index": form_data.index or {},
        "bbox": form_data.bbox,
    }
    try:
        write_json(chat_id, relpath, payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"path": relpath, **payload}


@router.get("/{chat_id}/artifacts/zarr/render")
async def render_zarr_view(
    chat_id: str, view: str, user=Depends(get_verified_user)
):
    _readable(chat_id, user)
    try:
        view_path = resolve_in_sandbox(chat_id, view)
        spec = read_view(view_path) if is_zarr_view(view_path) else None
        if not spec:
            raise ValueError("Not a zarr view")
        store = resolve_in_sandbox(chat_id, spec.get("zarr") or "")
        if not is_zarr_store(store):
            raise ValueError("Referenced zarr is missing")
        png = _render_view(store, spec)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return StreamingResponse(io.BytesIO(png), media_type="image/png")


def _render_view(store, spec: dict) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import xarray as xr

    ds = xr.open_zarr(store, consolidated=False)
    variable = spec.get("variable") or next(iter(ds.data_vars))
    da = ds[variable]
    for dim, value in (spec.get("index") or {}).items():
        if dim in da.dims:
            da = da.isel({dim: int(value)})
    bbox = spec.get("bbox")
    if bbox and "latitude" in da.coords and "longitude" in da.coords:
        lat_min, lon_min, lat_max, lon_max = bbox
        da = da.sel(latitude=slice(lat_min, lat_max), longitude=slice(lon_min, lon_max))

    fig, ax = plt.subplots(figsize=(7, 4))
    style = spec.get("style") or "heatmap"
    cmap = spec.get("colormap") or "viridis"
    if style == "timeseries":
        reduce_dims = [d for d in da.dims if d not in ("time", "step")]
        if reduce_dims:
            da = da.mean(dim=reduce_dims)
        xdim = "time" if "time" in da.dims else (da.dims[0] if da.dims else None)
        if xdim:
            ax.plot(da[xdim], np.asarray(da))
            ax.set_xlabel(xdim)
        else:
            ax.plot(np.asarray(da).ravel())
    else:
        while da.ndim > 2:
            da = da.isel({da.dims[0]: 0})
        if da.ndim == 2:
            da.plot(ax=ax, cmap=cmap, add_colorbar=True)
        else:
            ax.plot(np.asarray(da).ravel())
    ax.set_title(spec.get("title") or variable)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()
