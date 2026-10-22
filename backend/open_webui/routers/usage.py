import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from open_webui.models.organizations import PLATFORM_ORG_ID
from open_webui.models.usage import UsageMeModel
from open_webui.utils.auth import get_verified_user
from open_webui.utils.invite_email import InviteEmailError, deliver_credit_request
from open_webui.utils.organizations import admin_emails, get_active_organization_id
from open_webui.utils.usage import usage_snapshot

log = logging.getLogger(__name__)

router = APIRouter()

CREDIT_REQUEST_FAILED = "Your request could not be sent. Please try again later."


@router.get("/me", response_model=UsageMeModel)
def get_my_usage(
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    return usage_snapshot(organization_id, user.id)


class CreditRequestForm(BaseModel):
    credits: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/credit-request")
async def request_credit_increase(
    request: Request,
    form_data: CreditRequestForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    """Email the admins who can raise the limit the user is under."""
    reason = form_data.reason.strip()
    if not reason:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Please say why you need more credits."
        )
    usage = usage_snapshot(organization_id, user.id)
    org_over = (
        usage.org_limit_usd is not None and usage.org_cost_usd >= usage.org_limit_usd
    )
    member_over = (
        usage.user_limit_usd is not None and usage.cost_usd >= usage.user_limit_usd
    )

    # Organization admins set member limits; platform admins set organization
    # limits, and take a member request when the organization has no admin. A
    # requester who is one of those admins gets the email too.
    recipients = []
    if member_over and not org_over:
        recipients = admin_emails(organization_id)
        limit_label = "Member limit"
        used, limit = usage.cost_usd, usage.user_limit_usd
        review_path = "/organization/membership"
    else:
        limit_label = "Organization limit"
        used, limit = usage.org_cost_usd, usage.org_limit_usd
        review_path = "/admin/users"
    if not recipients:
        recipients = admin_emails(PLATFORM_ORG_ID)
        if member_over and not org_over:
            review_path = "/admin/users"

    try:
        await asyncio.to_thread(
            deliver_credit_request,
            request.app.state.config,
            recipients,
            user.name,
            user.email,
            usage.organization_name,
            limit_label,
            used,
            limit,
            form_data.credits,
            reason,
            review_path,
        )
    except InviteEmailError as e:
        log.warning(
            "Credit request not sent organization_id=%s user_id=%s: %s",
            organization_id,
            user.id,
            e,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=CREDIT_REQUEST_FAILED
        )
    return {"status": True}
