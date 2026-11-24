"""Share links, public: anyone with a live link can read it and its files.

These routes only ever serve a live share's frozen copy, so the /chats routes
can keep requiring a sign-in for everything else.
"""

from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.chats import ChatResponse, Chats
from open_webui.routers import artifacts
from open_webui.utils.artifacts import is_zarr_store, resolve_in_sandbox
from open_webui.utils.auth import bearer_security, get_current_user, get_verified_user

router = APIRouter()


def _require_live_share(share_id: str) -> None:
    if not Chats.is_live_share(share_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )


def _optional_user(
    request: Request,
    background_tasks: BackgroundTasks,
    auth_token: Optional[HTTPAuthorizationCredentials] = Depends(bearer_security),
):
    """The signed-in user, or None for an anonymous visitor."""
    try:
        return get_verified_user(
            get_current_user(request, background_tasks, auth_token)
        )
    except HTTPException:
        return None


def _require_sign_in_to_zip(user) -> None:
    """Folders and Zarr stores are zipped on the server; only signed-in
    visitors may start that."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to download folders and Zarr stores.",
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
):
    _require_live_share(share_id)
    return await artifacts.get_artifacts(share_id, depth, provenance, user=None)


@router.get("/{share_id}/artifacts/provenance")
def get_share_artifact_provenance(share_id: str, path: str):
    _require_live_share(share_id)
    return artifacts.get_artifact_provenance(share_id, path, user=None)


@router.get("/{share_id}/artifacts/size")
def get_share_artifact_size(share_id: str, path: str, user=Depends(_optional_user)):
    _require_live_share(share_id)
    _require_sign_in_to_zip(user)
    return artifacts.get_artifact_size(share_id, path, user=None)


@router.get("/{share_id}/artifacts/content")
def get_share_artifact_content(
    share_id: str, path: str, request: Request, user=Depends(_optional_user)
):
    _require_live_share(share_id)
    try:
        target = resolve_in_sandbox(share_id, path)
    except ValueError:
        target = None  # get_artifact_content answers 400.
    if target is not None and (is_zarr_store(target) or target.is_dir()):
        _require_sign_in_to_zip(user)
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
    user=Depends(_optional_user),
):
    _require_live_share(share_id)
    _require_sign_in_to_zip(user)
    return artifacts.get_artifact_archive(share_id, path, format, user=None)


@router.get("/{share_id}/artifacts/zarr/meta")
def get_share_zarr_meta(share_id: str, path: str):
    _require_live_share(share_id)
    return artifacts.zarr_meta(share_id, path, user=None)
