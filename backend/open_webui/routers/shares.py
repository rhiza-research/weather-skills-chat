"""Share links, public: anyone with a live link can read it and its files.

These routes only ever serve a live share's frozen copy, so the /chats routes
can keep requiring a sign-in for everything else.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.chats import ChatResponse, Chats
from open_webui.routers import artifacts
from open_webui.utils.artifacts import LISTED_PROVENANCE_DEPTH

router = APIRouter()


def _require_live_share(share_id: str) -> None:
    if not Chats.is_live_share(share_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )


@router.get("/{share_id}", response_model=ChatResponse)
def get_share(share_id: str):
    chat = Chats.get_chat_by_share_id(share_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return ChatResponse(**chat.model_dump())


# The artifact handlers let anyone read a live share, so they run with no user.
@router.get("/{share_id}/artifacts")
async def get_share_artifacts(
    share_id: str,
    depth: Optional[int] = Query(None, ge=1),
    provenance: bool = True,
    provenance_depth: int = Query(LISTED_PROVENANCE_DEPTH, ge=1),
):
    _require_live_share(share_id)
    return await artifacts.get_artifacts(
        share_id, depth, provenance, provenance_depth, user=None
    )


@router.get("/{share_id}/artifacts/provenance")
def get_share_artifact_provenance(share_id: str, path: str):
    _require_live_share(share_id)
    return artifacts.get_artifact_provenance(share_id, path, user=None)


@router.get("/{share_id}/artifacts/content")
def get_share_artifact_content(share_id: str, path: str, request: Request):
    _require_live_share(share_id)
    return artifacts.get_artifact_content(share_id, path, request, user=None)


@router.get("/{share_id}/artifacts/view/{path:path}")
def view_share_html_artifact(share_id: str, path: str, request: Request):
    _require_live_share(share_id)
    return artifacts.view_html_artifact(share_id, path, request, user=None)


@router.get("/{share_id}/artifacts/archive")
def get_share_artifact_archive(
    share_id: str,
    path: list[str] = Query(..., min_length=1),
    format: str = Query("tar.gz"),
):
    _require_live_share(share_id)
    return artifacts.get_artifact_archive(share_id, path, format, user=None)


@router.get("/{share_id}/artifacts/zarr/meta")
def get_share_zarr_meta(share_id: str, path: str):
    _require_live_share(share_id)
    return artifacts.zarr_meta(share_id, path, user=None)
