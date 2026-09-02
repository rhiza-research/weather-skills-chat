import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.skill_packs import (
    SkillPackAccessForm,
    SkillPackInstallForm,
    SkillPackSkillEnabledForm,
    SkillPackUpdateForm,
    SkillPacks,
)
from open_webui.utils.access_control import (
    can_update_access_control,
    has_permission,
    user_owns_or_has_access,
)
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.skills import (
    SkillInstallError,
    delete_skill_pack,
    install_skill_pack,
    pack_to_response,
    resync_all_skill_pack_tools,
    set_pack_access_control,
    set_skill_enabled,
    update_skill_pack,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()

SHARING_PERMISSION_KEY = "sharing.public_skills"


def _can_read(user, pack) -> bool:
    return user_owns_or_has_access(
        user.id, pack.user_id, pack.access_control, "read", user.role
    )


def _can_write(user, pack) -> bool:
    return user_owns_or_has_access(
        user.id, pack.user_id, pack.access_control, "write", user.role
    )


def _require_pack_access(user, pack, permission: str = "read"):
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if permission == "read" and not _can_read(user, pack):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )
    if permission == "write" and not _can_write(user, pack):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )
    return pack


def _require_skills_workspace(request: Request, user) -> None:
    if user.role != "admin" and not has_permission(
        user.id, "workspace.skills", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )


@router.get("/")
async def list_skill_packs(user=Depends(get_verified_user)):
    packs = SkillPacks.get_all()
    return [
        pack_to_response(p)
        for p in packs
        if _can_read(user, p)
    ]


@router.post("/resync")
async def resync_skill_tools(request: Request, user=Depends(get_admin_user)):
    """Regenerate skill tool wrappers from on-disk packs (no git pull)."""
    try:
        return resync_all_skill_pack_tools(request.app.state.TOOLS)
    except Exception as e:
        log.exception("Skill pack resync failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get("/{pack_id}")
async def get_skill_pack(pack_id: str, user=Depends(get_verified_user)):
    pack = _require_pack_access(user, SkillPacks.get_by_id(pack_id), "read")
    return pack_to_response(pack)


@router.get("/{pack_id}/skills")
async def get_skill_pack_skills(pack_id: str, user=Depends(get_verified_user)):
    pack = _require_pack_access(user, SkillPacks.get_by_id(pack_id), "read")
    data = pack_to_response(pack)
    return {
        "id": pack.id,
        "git_url": pack.git_url,
        "git_ref": pack.git_ref,
        "commit_sha": pack.commit_sha,
        "skills": data.get("skills") or [],
    }


@router.post("/install")
async def install_skills(
    request: Request,
    form_data: SkillPackInstallForm,
    user=Depends(get_verified_user),
):
    _require_skills_workspace(request, user)
    try:
        pack = install_skill_pack(
            user.id,
            form_data.git_url,
            form_data.ref or "main",
            request.app.state.TOOLS,
        )
        return pack_to_response(pack)
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        log.exception("Skill pack install failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.post("/{pack_id}/update")
async def update_skills(
    request: Request,
    pack_id: str,
    form_data: Optional[SkillPackUpdateForm] = None,
    user=Depends(get_verified_user),
):
    _require_skills_workspace(request, user)
    pack = _require_pack_access(user, SkillPacks.get_by_id(pack_id), "write")
    form_data = form_data or SkillPackUpdateForm()
    try:
        pack = update_skill_pack(
            pack.id,
            request.app.state.TOOLS,
            new_ref=form_data.ref,
        )
        return pack_to_response(pack)
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        log.exception("Skill pack update failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.post("/{pack_id}/access")
async def update_skill_pack_access(
    request: Request,
    pack_id: str,
    form_data: SkillPackAccessForm,
    user=Depends(get_verified_user),
):
    _require_skills_workspace(request, user)
    pack = _require_pack_access(user, SkillPacks.get_by_id(pack_id), "write")
    if not can_update_access_control(
        user.id,
        user.role,
        pack.user_id,
        pack.access_control,
        form_data.access_control,
        SHARING_PERMISSION_KEY,
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    try:
        pack = set_pack_access_control(pack.id, form_data.access_control)
        return pack_to_response(pack)
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{pack_id}/skills/{tool_id}/enabled")
async def update_skill_enabled(
    request: Request,
    pack_id: str,
    tool_id: str,
    form_data: SkillPackSkillEnabledForm,
    user=Depends(get_verified_user),
):
    _require_skills_workspace(request, user)
    pack = _require_pack_access(user, SkillPacks.get_by_id(pack_id), "write")
    try:
        pack = set_skill_enabled(pack.id, tool_id, form_data.enabled)
        return pack_to_response(pack)
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{pack_id}")
async def remove_skill_pack(
    request: Request,
    pack_id: str,
    user=Depends(get_verified_user),
):
    _require_skills_workspace(request, user)
    pack = _require_pack_access(user, SkillPacks.get_by_id(pack_id), "write")
    try:
        delete_skill_pack(pack.id, request.app.state.TOOLS)
        return {"success": True}
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
