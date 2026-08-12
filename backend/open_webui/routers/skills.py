import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.skill_packs import (
    SkillPackAccessForm,
    SkillPackInstallForm,
    SkillPackUpdateForm,
    SkillPacks,
)
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.skills import (
    SkillInstallError,
    delete_skill_pack,
    install_skill_pack,
    pack_to_response,
    resync_all_skill_pack_tools,
    set_pack_access_control,
    update_skill_pack,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


@router.get("/")
async def list_skill_packs(user=Depends(get_verified_user)):
    packs = SkillPacks.get_all()
    # Non-admins still see pack metadata for tools they can access;
    # tool ACL remains the gate for use.
    return [pack_to_response(p) for p in packs]


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
    pack = SkillPacks.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return pack_to_response(pack)


@router.get("/{pack_id}/skills")
async def get_skill_pack_skills(pack_id: str, user=Depends(get_verified_user)):
    pack = SkillPacks.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
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
    user=Depends(get_admin_user),
):
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
    user=Depends(get_admin_user),
):
    form_data = form_data or SkillPackUpdateForm()
    try:
        pack = update_skill_pack(
            pack_id,
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
    pack_id: str,
    form_data: SkillPackAccessForm,
    user=Depends(get_admin_user),
):
    try:
        pack = set_pack_access_control(pack_id, form_data.access_control)
        return pack_to_response(pack)
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{pack_id}")
async def remove_skill_pack(
    request: Request,
    pack_id: str,
    user=Depends(get_admin_user),
):
    try:
        delete_skill_pack(pack_id, request.app.state.TOOLS)
        return {"success": True}
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
