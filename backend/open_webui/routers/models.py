from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from open_webui.constants import ERROR_MESSAGES
from open_webui.models.models import (
    ModelForm,
    ModelModel,
    ModelResponse,
    ModelUserResponse,
    Models,
)
from open_webui.models.org_catalog import RESOURCE_MODEL, OrgCatalogOverrides
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.catalog import (
    annotate,
    can_manage_public,
    can_toggle,
    can_write_item,
    is_visible,
    stamp_create,
)
from open_webui.utils.organizations import get_active_organization_id

router = APIRouter()


class CatalogEnabledForm(BaseModel):
    enabled: bool


def _visible_models(user, organization_id: str) -> list[ModelUserResponse]:
    return Models.list_for_organization(organization_id)


@router.get("/", response_model=list[ModelUserResponse])
async def get_models(
    id: Optional[str] = None,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    models = _visible_models(user, organization_id)
    if id:
        models = [m for m in models if m.id == id]
    return models


@router.get("/base", response_model=list[ModelResponse])
async def get_base_models(user=Depends(get_admin_user)):
    return Models.get_base_models()


@router.post("/create", response_model=Optional[ModelModel])
async def create_new_model(
    request: Request,
    form_data: ModelForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    try:
        org_id, visibility = stamp_create(user, organization_id, RESOURCE_MODEL)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    if Models.get_model_by_id(form_data.id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.MODEL_ID_TAKEN,
        )

    form_data.organization_id = org_id
    form_data.visibility = visibility
    if visibility != "public":
        form_data.enabled_by_default = True

    model = Models.insert_new_model(form_data, user.id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.DEFAULT(),
        )
    return ModelModel.model_validate(
        annotate(model, organization_id, RESOURCE_MODEL)
    )


@router.get("/model", response_model=Optional[ModelResponse])
async def get_model_by_id(
    id: str,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    model = Models.get_model_by_id(id)
    if model and is_visible(organization_id, RESOURCE_MODEL, model):
        return ModelResponse.model_validate(
            annotate(model, organization_id, RESOURCE_MODEL)
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


@router.post("/model/toggle", response_model=Optional[ModelResponse])
async def toggle_model_by_id(
    id: str,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    model = Models.get_model_by_id(id)
    if not model or not can_write_item(user, organization_id, model):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    model = Models.toggle_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating function"),
        )
    return ModelResponse.model_validate(
        annotate(model, organization_id, RESOURCE_MODEL)
    )


@router.post("/model/enabled-by-default", response_model=Optional[ModelResponse])
async def set_model_enabled_by_default(
    id: str,
    form_data: CatalogEnabledForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    model = Models.get_model_by_id(id)
    if not model or not can_write_item(user, organization_id, model):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    model = Models.set_enabled_by_default(id, form_data.enabled)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating model"),
        )
    return ModelResponse.model_validate(
        annotate(model, organization_id, RESOURCE_MODEL)
    )


@router.post("/model/enabled", response_model=Optional[ModelResponse])
async def set_model_enabled(
    id: str,
    form_data: CatalogEnabledForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if getattr(model, "visibility", None) != "public":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if not can_toggle(user, organization_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    OrgCatalogOverrides.set(organization_id, RESOURCE_MODEL, id, form_data.enabled)
    return ModelResponse.model_validate(
        annotate(model, organization_id, RESOURCE_MODEL)
    )


@router.post("/model/update", response_model=Optional[ModelModel])
async def update_model_by_id(
    request: Request,
    id: str,
    form_data: ModelForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if not can_write_item(user, organization_id, model):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    form_data.organization_id = model.organization_id
    form_data.visibility = model.visibility
    if model.visibility != "public":
        form_data.enabled_by_default = model.enabled_by_default

    model = Models.update_model_by_id(id, form_data)
    return ModelModel.model_validate(
        annotate(model, organization_id, RESOURCE_MODEL)
    )


@router.delete("/model/delete", response_model=bool)
async def delete_model_by_id(
    id: str,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    model = Models.get_model_by_id(id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if not can_write_item(user, organization_id, model):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    OrgCatalogOverrides.delete_for_resource(RESOURCE_MODEL, id)
    return Models.delete_model_by_id(id)


@router.delete("/delete/all", response_model=bool)
async def delete_all_models(user=Depends(get_admin_user)):
    return Models.delete_all_models()
