import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.skill_packs import (
    SkillPackAccessForm,
    SkillPackInstallForm,
    SkillPackSkillEnabledForm,
    SkillPackUpdateForm,
    SkillPacks,
)
from open_webui.models.org_catalog import (
    RESOURCE_SKILL,
    RESOURCE_SKILL_ITEM,
    CatalogEnabledForm,
    OrgCatalogOverrides,
)
from open_webui.utils.catalog import (
    can_toggle,
    can_write_item,
    is_public_item,
    is_visible,
    stamp_create,
)
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.organizations import get_active_organization_id
from open_webui.utils.skills import (
    SkillInstallBusyError,
    SkillInstallError,
    delete_skill_pack,
    install_skill_pack,
    respond_pack,
    resync_all_skill_pack_tools,
    set_pack_access_control,
    set_skill_active,
    set_skill_enabled,
    update_skill_pack,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()

SHARING_PERMISSION_KEY = "sharing.public_skills"


def _can_read(user, pack, organization_id: str) -> bool:
    return is_visible(organization_id, RESOURCE_SKILL, pack)


def _can_write(user, pack, organization_id: Optional[str] = None) -> bool:
    if getattr(pack, "visibility", None) == "public":
        from open_webui.utils.organizations import is_platform_admin

        return is_platform_admin(user.id)
    org_id = organization_id or getattr(pack, "organization_id", None)
    return can_write_item(user, org_id, pack)


def _require_pack_access(user, pack, permission: str = "read", organization_id: Optional[str] = None):
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if permission == "read":
        org_id = organization_id or getattr(pack, "organization_id", None)
        if organization_id:
            visible = _can_read(user, pack, organization_id)
        elif getattr(pack, "visibility", None) == "public":
            from open_webui.models.organizations import Organizations

            visible = any(
                _can_read(user, pack, oid)
                for oid in Organizations.user_organization_ids(user.id)
            )
        else:
            visible = _can_read(user, pack, org_id)
        if not visible:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
            )
    if permission == "write" and not _can_write(user, pack, organization_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )
    return pack


def _require_skills_workspace(request: Request, user) -> None:
    return


def _raise_install_error(exc: Exception):
    if isinstance(exc, SkillInstallBusyError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, SkillInstallError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    log.exception("Skill pack operation failed")
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/")
async def list_skill_packs(
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    packs = SkillPacks.get_all()
    overrides = OrgCatalogOverrides.for_organizations([organization_id])
    return [
        respond_pack(p, organization_id, overrides)
        for p in packs
        if is_visible(organization_id, RESOURCE_SKILL, p)
    ]


@router.post("/resync")
async def resync_skill_tools(request: Request, user=Depends(get_admin_user)):
    """Regenerate skill tool wrappers from on-disk packs (no git pull)."""
    try:
        return await run_in_threadpool(
            resync_all_skill_pack_tools, request.app.state.TOOLS
        )
    except Exception as e:
        _raise_install_error(e)


@router.get("/{pack_id}")
async def get_skill_pack(
    pack_id: str,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    pack = SkillPacks.get_by_id(pack_id)
    if not pack or not is_visible(organization_id, RESOURCE_SKILL, pack):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return respond_pack(pack, organization_id)


@router.get("/{pack_id}/skills")
async def get_skill_pack_skills(
    pack_id: str,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    pack = _require_pack_access(
        user, SkillPacks.get_by_id(pack_id), "read", organization_id
    )
    data = respond_pack(pack, organization_id)
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
    organization_id: str = Depends(get_active_organization_id),
):
    try:
        org_id, visibility = stamp_create(user, organization_id, RESOURCE_SKILL)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    try:
        pack = await run_in_threadpool(
            install_skill_pack,
            user.id,
            form_data.git_url,
            form_data.ref or "main",
            request.app.state.TOOLS,
            organization_id=org_id,
            visibility=visibility,
            enabled_by_default=form_data.enabled_by_default
            if visibility == "public"
            else True,
        )
        return respond_pack(pack, organization_id)
    except Exception as e:
        _raise_install_error(e)


@router.post("/{pack_id}/update")
async def update_skills(
    request: Request,
    pack_id: str,
    form_data: Optional[SkillPackUpdateForm] = None,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    _require_skills_workspace(request, user)
    pack = _require_pack_access(user, SkillPacks.get_by_id(pack_id), "write")
    form_data = form_data or SkillPackUpdateForm()
    try:
        pack = await run_in_threadpool(
            update_skill_pack,
            pack.id,
            request.app.state.TOOLS,
            form_data.ref,
        )
        return respond_pack(pack, organization_id)
    except Exception as e:
        _raise_install_error(e)


@router.post("/{pack_id}/enabled")
async def set_skill_pack_enabled(
    pack_id: str,
    form_data: CatalogEnabledForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    pack = SkillPacks.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if getattr(pack, "visibility", None) != "public":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if not can_toggle(user, organization_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    OrgCatalogOverrides.set(organization_id, RESOURCE_SKILL, pack_id, form_data.enabled)
    return respond_pack(pack, organization_id)


@router.post("/{pack_id}/enabled-by-default")
async def set_skill_pack_enabled_by_default(
    pack_id: str,
    form_data: CatalogEnabledForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    pack = SkillPacks.get_by_id(pack_id)
    if not pack or not can_write_item(user, organization_id, pack):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    pack = SkillPacks.set_enabled_by_default(pack_id, form_data.enabled)
    if not pack:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating skill pack"),
        )
    return respond_pack(pack, organization_id)


@router.post("/{pack_id}/toggle")
async def toggle_skill_pack_active(
    pack_id: str,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    pack = SkillPacks.get_by_id(pack_id)
    if not pack or not can_write_item(user, organization_id, pack):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    pack = SkillPacks.toggle_active(pack_id)
    if not pack:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating skill pack"),
        )
    return respond_pack(pack, organization_id)


@router.post("/{pack_id}/skills/{tool_id}/enabled")
async def update_skill_enabled(
    request: Request,
    pack_id: str,
    tool_id: str,
    form_data: SkillPackSkillEnabledForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    pack = SkillPacks.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    skill = next(
        (
            s
            for s in ((pack.meta or {}).get("skills") or [])
            if isinstance(s, dict) and s.get("tool_id") == tool_id
        ),
        None,
    )
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Skill tool {tool_id} not found in pack",
        )
    if is_public_item(pack):
        if not can_toggle(user, organization_id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.UNAUTHORIZED,
            )
        OrgCatalogOverrides.set(
            organization_id, RESOURCE_SKILL_ITEM, tool_id, form_data.enabled
        )
        return respond_pack(pack, organization_id)
    _require_pack_access(user, pack, "write", organization_id)
    try:
        pack = set_skill_enabled(pack.id, tool_id, form_data.enabled)
        return respond_pack(pack, organization_id)
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{pack_id}/skills/{tool_id}/enabled-by-default")
async def set_skill_enabled_by_default(
    pack_id: str,
    tool_id: str,
    form_data: SkillPackSkillEnabledForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    pack = SkillPacks.get_by_id(pack_id)
    if not pack or not can_write_item(user, organization_id, pack):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    try:
        pack = set_skill_enabled(pack.id, tool_id, form_data.enabled)
        return respond_pack(pack, organization_id)
    except SkillInstallError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{pack_id}/skills/{tool_id}/toggle")
async def toggle_skill_active(
    pack_id: str,
    tool_id: str,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    pack = SkillPacks.get_by_id(pack_id)
    if not pack or not can_write_item(user, organization_id, pack):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    skill = next(
        (
            s
            for s in ((pack.meta or {}).get("skills") or [])
            if isinstance(s, dict) and s.get("tool_id") == tool_id
        ),
        None,
    )
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Skill tool {tool_id} not found in pack",
        )
    try:
        pack = set_skill_active(
            pack.id, tool_id, not bool(skill.get("is_active", True))
        )
        return respond_pack(pack, organization_id)
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
        for skill in (pack.meta or {}).get("skills") or []:
            if isinstance(skill, dict) and skill.get("tool_id"):
                OrgCatalogOverrides.delete_for_resource(
                    RESOURCE_SKILL_ITEM, skill["tool_id"]
                )
        OrgCatalogOverrides.delete_for_resource(RESOURCE_SKILL, pack.id)
        await run_in_threadpool(delete_skill_pack, pack.id, request.app.state.TOOLS)
        return {"success": True}
    except Exception as e:
        _raise_install_error(e)
