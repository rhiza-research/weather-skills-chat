import logging

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.preferences import (
    PreferenceForm,
    PreferenceModel,
    PreferenceUpdateForm,
    Preferences,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import (
    get_active_organization_id,
    is_member,
    is_org_admin,
    is_personal_org,
    resolve_visibility,
)
from open_webui.utils.preferences import can_manage_preference, list_preference_metadata

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


def _require_manage(user, row):
    if not can_manage_preference(user, row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )


@router.get("/", response_model=list[PreferenceModel])
async def list_preferences(
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    return [
        PreferenceModel.model_validate(item)
        for item in list_preference_metadata(user, organization_id)
    ]


@router.post("/", response_model=PreferenceModel)
async def create_preference(
    form_data: PreferenceForm,
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
        if is_personal_org(form_data.organization_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot share preferences in the personal organization",
            )
        if not is_org_admin(form_data.organization_id, user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
        if Preferences.get_shared(form_data.organization_id, form_data.title):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An organization preference with that title already exists",
            )
    elif Preferences.get_private(
        form_data.organization_id, user.id, form_data.title
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A private preference with that title already exists",
        )
    try:
        preference = Preferences.insert(user.id, form_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not preference:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating preference"),
        )
    preference.can_manage = True
    return preference


@router.post("/{id}/update", response_model=PreferenceModel)
async def update_preference(
    id: str,
    form_data: PreferenceUpdateForm,
    user=Depends(get_verified_user),
):
    row = Preferences.get_by_id(id)
    _require_manage(user, row)
    if form_data.visibility == "organization":
        if is_personal_org(row.organization_id) or not is_org_admin(
            row.organization_id, user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
    title = form_data.title if form_data.title is not None else row.title
    visibility = form_data.visibility or row.visibility
    if visibility == "organization":
        existing = Preferences.get_shared(row.organization_id, title)
        if existing and existing.id != row.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An organization preference with that title already exists",
            )
    else:
        existing = Preferences.get_private(row.organization_id, user.id, title)
        if existing and existing.id != row.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A private preference with that title already exists",
            )
    try:
        preference = Preferences.update(id, form_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    preference.can_manage = True
    return preference


@router.delete("/{id}", response_model=bool)
async def delete_preference(id: str, user=Depends(get_verified_user)):
    row = Preferences.get_by_id(id)
    _require_manage(user, row)
    return Preferences.delete(id)
