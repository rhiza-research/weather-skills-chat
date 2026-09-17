import logging

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.secrets import SecretForm, SecretModel, SecretUpdateForm, Secrets
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import (
    get_active_organization_id,
    is_member,
    is_org_admin,
    is_personal_org,
    resolve_visibility,
)
from open_webui.utils.secrets import (
    can_manage_secret,
    list_secret_metadata,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


@router.get("/", response_model=list[SecretModel])
async def list_secrets(
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    return [
        SecretModel.model_validate(item)
        for item in list_secret_metadata(user, organization_id)
    ]


@router.post("/", response_model=SecretModel)
async def create_secret(
    form_data: SecretForm,
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
                detail="Cannot share secrets in the personal organization",
            )
        if not is_org_admin(form_data.organization_id, user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
        if Secrets.get_shared(form_data.organization_id, form_data.name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An organization secret with that name already exists",
            )
    else:
        if Secrets.get_private(
            form_data.organization_id, user.id, form_data.name
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A private secret with that name already exists",
            )
    try:
        secret = Secrets.insert(user.id, form_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating secret"),
        )
    secret.scope = secret.visibility
    secret.can_manage = True
    return secret


@router.post("/{id}/update", response_model=SecretModel)
async def update_secret(
    id: str, form_data: SecretUpdateForm, user=Depends(get_verified_user)
):
    row = Secrets.get_by_id(id)
    if not can_manage_secret(user, row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    visibility = form_data.visibility or row.visibility
    if visibility == "organization" and is_personal_org(row.organization_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share secrets in the personal organization",
        )
    if form_data.name and form_data.name != row.name:
        if visibility == "organization" and Secrets.get_shared(
            row.organization_id, form_data.name
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An organization secret with that name already exists",
            )
        if visibility == "private" and Secrets.get_private(
            row.organization_id, user.id, form_data.name
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A private secret with that name already exists",
            )
    try:
        secret = Secrets.update(id, form_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    secret.scope = secret.visibility
    secret.can_manage = True
    return secret


@router.delete("/{id}", response_model=bool)
async def delete_secret(id: str, user=Depends(get_verified_user)):
    row = Secrets.get_by_id(id)
    if not can_manage_secret(user, row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return Secrets.delete(id)
