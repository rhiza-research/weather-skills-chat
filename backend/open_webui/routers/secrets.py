import logging

from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.secrets import SecretForm, SecretModel, SecretUpdateForm, Secrets
from open_webui.utils.auth import get_verified_user
from open_webui.utils.secrets import (
    can_manage_secret,
    list_secret_metadata,
)
from open_webui.utils.teams import is_team_admin, is_team_member

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


@router.get("/", response_model=list[SecretModel])
async def list_secrets(user=Depends(get_verified_user)):
    return [SecretModel.model_validate(item) for item in list_secret_metadata(user)]


@router.post("/", response_model=SecretModel)
async def create_secret(form_data: SecretForm, user=Depends(get_verified_user)):
    if form_data.team_id:
        if not is_team_admin(form_data.team_id, user.id, user.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )
        if Secrets.get_team(form_data.team_id, form_data.name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A team secret with that name already exists",
            )
    else:
        if Secrets.get_personal(user.id, form_data.name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A personal secret with that name already exists",
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
    secret.scope = "team" if secret.team_id else "personal"
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
    if form_data.name and form_data.name != row.name:
        if row.team_id and Secrets.get_team(row.team_id, form_data.name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A team secret with that name already exists",
            )
        if not row.team_id and Secrets.get_personal(user.id, form_data.name):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A personal secret with that name already exists",
            )
    try:
        secret = Secrets.update(id, form_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    secret.scope = "team" if secret.team_id else "personal"
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


@router.get("/team/{team_id}", response_model=list[SecretModel])
async def list_team_secrets(team_id: str, user=Depends(get_verified_user)):
    if user.role != "admin" and not is_team_member(team_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    manage = is_team_admin(team_id, user.id, user.role)
    personal_names = {row.name for row in Secrets.list_personal(user.id)}
    secrets = Secrets.list_team(team_id)
    for secret in secrets:
        secret.scope = "team"
        secret.can_manage = manage
        secret.overridden = secret.name in personal_names
    return secrets
