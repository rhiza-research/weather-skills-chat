from fastapi import APIRouter, Depends

from open_webui.models.usage import UsageMeModel
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import get_active_organization_id
from open_webui.utils.usage import usage_snapshot

router = APIRouter()


@router.get("/me", response_model=UsageMeModel)
async def get_my_usage(
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    return usage_snapshot(organization_id, user.id)
