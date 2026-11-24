from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.text_skills import (
    TextSkillForm,
    TextSkillModel,
    TextSkills,
    TextSkillUpdateForm,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import (
    get_active_organization_id,
    is_member,
    is_org_admin,
    is_personal_org,
    resolve_visibility,
)
from open_webui.utils.text_skills import can_manage_text_skill, list_text_skill_metadata

router = APIRouter()


def _require_manage(user, row):
    if not can_manage_text_skill(user, row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )


def _check_share(organization_id: str, user_id: str):
    if is_personal_org(organization_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share skills in the personal organization",
        )
    if not is_org_admin(organization_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


def _check_unique_title(organization_id, user_id, title, visibility, own_id=None):
    existing = TextSkills.get_by_title(organization_id, user_id, title, visibility)
    if existing and existing.id != own_id:
        scope = "An organization" if visibility == "organization" else "A private"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{scope} skill with that title already exists",
        )


@router.get("/", response_model=list[TextSkillModel])
async def list_text_skills(
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    return list_text_skill_metadata(user, organization_id)


@router.post("/", response_model=TextSkillModel)
async def create_text_skill(
    form_data: TextSkillForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    form_data.organization_id = form_data.organization_id or organization_id
    if not is_member(form_data.organization_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    form_data.visibility = resolve_visibility(
        form_data.organization_id, form_data.visibility
    )
    if form_data.visibility == "organization":
        _check_share(form_data.organization_id, user.id)
    _check_unique_title(
        form_data.organization_id, user.id, form_data.title, form_data.visibility
    )
    skill = TextSkills.insert(user.id, form_data)
    skill.can_manage = True
    return skill


@router.post("/{id}/update", response_model=TextSkillModel)
async def update_text_skill(
    id: str,
    form_data: TextSkillUpdateForm,
    user=Depends(get_verified_user),
):
    row = TextSkills.get_by_id(id)
    _require_manage(user, row)
    if form_data.visibility is not None:
        form_data.visibility = resolve_visibility(
            row.organization_id, form_data.visibility
        )
        if form_data.visibility == "organization":
            _check_share(row.organization_id, user.id)
    _check_unique_title(
        row.organization_id,
        user.id,
        form_data.title or row.title,
        form_data.visibility or row.visibility,
        own_id=row.id,
    )
    skill = TextSkills.update(id, form_data)
    skill.can_manage = True
    return skill


@router.delete("/{id}", response_model=bool)
async def delete_text_skill(id: str, user=Depends(get_verified_user)):
    _require_manage(user, TextSkills.get_by_id(id))
    return TextSkills.delete(id)
