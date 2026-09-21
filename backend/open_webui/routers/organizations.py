import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.organizations import (
    ORG_KIND_PERSONAL,
    ORG_KIND_PLATFORM,
    OrganizationForm,
    OrganizationMemberAddForm,
    OrganizationMemberLimitForm,
    OrganizationMemberRoleForm,
    OrganizationModel,
    Organizations,
    OrganizationUpdateForm,
    PLATFORM_ORG_ID,
)
from open_webui.models.users import Users
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import (
    is_at_least,
    is_member,
    is_owner,
    require_platform_admin,
)
from open_webui.utils.usage import attach_org_usage, attach_org_usage_list

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


def _with_members(
    org: OrganizationModel, user_id: str, *, include_usage: bool = True
) -> OrganizationModel:
    org.members = Organizations.get_members(org.id)
    member = Organizations.get_member(org.id, user_id)
    org.role = member.role if member else None
    if include_usage:
        return attach_org_usage(org, include_members=True)
    return org


@router.get("/", response_model=list[OrganizationModel])
async def get_organizations(user=Depends(get_verified_user)):
    Organizations.ensure_personal(user.id)
    return attach_org_usage_list(Organizations.get_organizations_by_user_id(user.id))


@router.get("/all", response_model=list[OrganizationModel])
async def get_all_organizations(request: Request, user=Depends(get_verified_user)):
    require_platform_admin(user, request)
    orgs = [
        _with_members(org, user.id, include_usage=False)
        for org in Organizations.get_all_organizations()
    ]
    return attach_org_usage_list(orgs)


@router.post("/", response_model=OrganizationModel)
async def create_organization(
    form_data: OrganizationForm, user=Depends(get_verified_user)
):
    try:
        org = Organizations.insert_new_organization(user.id, form_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating organization"),
        )
    return _with_members(org, user.id)


@router.post("/{id}/activate", response_model=OrganizationModel)
async def activate_organization(id: str, request: Request, user=Depends(get_verified_user)):
    require_platform_admin(user, request)
    org = Organizations.get_organization_by_id(id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    try:
        org = Organizations.set_active(id, True)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _with_members(org, user.id)


@router.get("/{id}", response_model=OrganizationModel)
async def get_organization(id: str, request: Request, user=Depends(get_verified_user)):
    org = Organizations.get_organization_by_id(id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if not is_member(id, user.id):
        require_platform_admin(user, request)
    return _with_members(org, user.id)


@router.post("/{id}/update", response_model=OrganizationModel)
async def update_organization(
    id: str,
    form_data: OrganizationUpdateForm,
    request: Request,
    user=Depends(get_verified_user),
):
    org = Organizations.get_organization_by_id(id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    raw = form_data.model_dump(exclude_unset=True)
    flag_keys = {"can_add_models", "can_add_skills", "can_add_knowledge"}
    flags = {k: raw.pop(k) for k in list(raw.keys()) if k in flag_keys}
    limit_set = "monthly_limit_usd" in raw
    limit_val = raw.pop("monthly_limit_usd", None)
    updates = {k: v for k, v in raw.items() if v is not None}
    if flags or limit_set:
        require_platform_admin(user, request)
    if limit_set:
        updates["monthly_limit_usd"] = limit_val
    if org.kind == ORG_KIND_PERSONAL:
        extra = set(updates.keys()) - {"monthly_limit_usd"}
        if extra:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot update a personal organization",
            )
        updates = {**updates, **flags}
    else:
        if not is_at_least(id, user.id, "admin"):
            require_platform_admin(user, request)
        updates = {**updates, **flags}
    try:
        org = Organizations.update_organization(
            id, OrganizationUpdateForm(**updates)
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating organization"),
        )
    return _with_members(org, user.id)


@router.post("/{id}/members", response_model=OrganizationModel)
async def add_organization_member(
    id: str, form_data: OrganizationMemberAddForm, user=Depends(get_verified_user)
):
    org = Organizations.get_organization_by_id(id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if form_data.role == "owner":
        if not is_owner(id, user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
    elif not is_at_least(id, user.id, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if not Users.get_user_by_id(form_data.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.USER_NOT_FOUND
        )
    try:
        Organizations.add_member(id, form_data.user_id, form_data.role)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _with_members(Organizations.get_organization_by_id(id), user.id)


@router.post("/{id}/members/{user_id}", response_model=OrganizationModel)
async def update_organization_member_role(
    id: str,
    user_id: str,
    form_data: OrganizationMemberRoleForm,
    user=Depends(get_verified_user),
):
    if form_data.role == "owner":
        if not is_owner(id, user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
    else:
        target = Organizations.get_member(id, user_id)
        if target and target.role == "owner" and not is_owner(id, user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
        if not is_at_least(id, user.id, "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
    try:
        member = Organizations.update_member_role(id, user_id, form_data.role)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return _with_members(Organizations.get_organization_by_id(id), user.id)


@router.post("/{id}/members/{user_id}/usage-limit", response_model=OrganizationModel)
async def update_organization_member_limit(
    id: str,
    user_id: str,
    form_data: OrganizationMemberLimitForm,
    user=Depends(get_verified_user),
):
    org = Organizations.get_organization_by_id(id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if not is_at_least(id, user.id, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    try:
        member = Organizations.update_member_limit(
            id, user_id, form_data.monthly_limit_usd
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return _with_members(Organizations.get_organization_by_id(id), user.id)


@router.delete("/{id}/members/{user_id}", response_model=OrganizationModel)
async def remove_organization_member(
    id: str, user_id: str, user=Depends(get_verified_user)
):
    target = Organizations.get_member(id, user_id)
    if target and target.role == "owner":
        if not is_owner(id, user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
    elif not is_at_least(id, user.id, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    try:
        removed = Organizations.remove_member(id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return _with_members(Organizations.get_organization_by_id(id), user.id)


@router.delete("/{id}", response_model=bool)
async def delete_organization(
    id: str, request: Request, user=Depends(get_verified_user)
):
    org = Organizations.get_organization_by_id(id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if org.kind in (ORG_KIND_PERSONAL, ORG_KIND_PLATFORM) or id == PLATFORM_ORG_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete this organization",
        )
    if not is_owner(id, user.id):
        require_platform_admin(user, request)
    try:
        return Organizations.delete_organization(id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
