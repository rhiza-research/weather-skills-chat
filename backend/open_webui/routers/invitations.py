import datetime
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    SRC_LOG_LEVELS,
    WEBUI_AUTH_COOKIE_SAME_SITE,
    WEBUI_AUTH_COOKIE_SECURE,
)
from open_webui.models.auths import Auths
from open_webui.models.invitations import (
    KIND_ORGANIZATION,
    KIND_PLATFORM,
    InvitationModel,
    Invitations,
)
from open_webui.models.organizations import (
    ORG_KIND_PERSONAL,
    ORG_KIND_PLATFORM,
    OrganizationUpdateForm,
    Organizations,
)
from open_webui.models.users import Users
from open_webui.utils.access_control import get_permissions
from open_webui.utils.auth import (
    create_token,
    decode_token,
    get_password_hash,
    get_verified_user,
)
from open_webui.utils.invite_email import InviteEmailError, deliver_invite_email, smtp_is_configured
from open_webui.utils.misc import parse_duration, validate_email_format
from open_webui.utils.organizations import is_at_least, is_platform_admin

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


class InviteEmailForm(BaseModel):
    email: str
    monthly_limit_usd: Optional[float] = None


class PlatformInviteEmailForm(BaseModel):
    email: str
    monthly_limit_usd: Optional[float] = 300


class AcceptInviteForm(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None


class InvitationResponse(BaseModel):
    id: str
    email: str
    kind: str
    organization_id: Optional[str] = None
    role: str
    expires_at: int
    created_at: int
    expired: bool
    monthly_limit_usd: Optional[float] = None


class InvitationPublicResponse(BaseModel):
    email: str
    kind: str
    organization_name: Optional[str] = None
    organization_id: Optional[str] = None
    expired: bool
    accepted: bool
    account_exists: bool


def get_optional_user(request: Request):
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token and "token" in request.cookies:
        token = request.cookies.get("token")
    if not token or token.startswith("sk-"):
        return None
    try:
        data = decode_token(token)
    except Exception:
        return None
    if not data or "id" not in data:
        return None
    return Users.get_user_by_id(data["id"])


def _response(invite: InvitationModel) -> InvitationResponse:
    return InvitationResponse(
        id=invite.id,
        email=invite.email,
        kind=invite.kind,
        organization_id=invite.organization_id,
        role=invite.role,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        expired=invite.expired,
        monthly_limit_usd=invite.monthly_limit_usd,
    )


def _normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not validate_email_format(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.INVALID_EMAIL_FORMAT,
        )
    return email


def _require_smtp(request: Request) -> None:
    missing = smtp_is_configured(request.app.state.config)
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=missing)


def _send(request: Request, invite: InvitationModel, token: str) -> None:
    organization_name = ""
    if invite.organization_id:
        org = Organizations.get_organization_by_id(invite.organization_id)
        organization_name = org.name if org else "organization"
    inviter = Users.get_user_by_id(invite.created_by)
    inviter_name = inviter.name if inviter and inviter.name else ""
    try:
        deliver_invite_email(
            request.app.state.config,
            invite.email,
            invite.kind,
            token,
            organization_name=organization_name,
            expires_at=invite.expires_at,
            inviter_name=inviter_name,
        )
    except InviteEmailError as exc:
        code = (
            status.HTTP_502_BAD_GATEWAY
            if exc.saved
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc))


def _require_platform_admin(user) -> None:
    if not is_platform_admin(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


def _org_for_invite(organization_id: str, user):
    org = Organizations.get_organization_by_id(organization_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if org.kind == ORG_KIND_PERSONAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot invite members to a personal organization",
        )
    if not is_at_least(organization_id, user.id, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return org


def _clean_limit(monthly_limit_usd: Optional[float]) -> Optional[float]:
    if monthly_limit_usd is not None and monthly_limit_usd < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Monthly usage limit must be a number greater than or equal to 0.",
        )
    return monthly_limit_usd


def _check_member_limit(org, monthly_limit_usd: Optional[float]) -> None:
    if (
        monthly_limit_usd is not None
        and org.monthly_limit_usd is not None
        and monthly_limit_usd > org.monthly_limit_usd
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Member limit cannot exceed the organization monthly limit",
        )


def _apply_invite_limit(invite: InvitationModel, user_id: str) -> None:
    if invite.kind == KIND_ORGANIZATION and invite.organization_id:
        org = Organizations.get_organization_by_id(invite.organization_id)
        if org:
            _check_member_limit(org, invite.monthly_limit_usd)
        try:
            Organizations.update_member_limit(
                invite.organization_id, user_id, invite.monthly_limit_usd
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return
    if invite.kind == KIND_PLATFORM:
        Organizations.ensure_personal(user_id)
        Organizations.update_organization(
            user_id,
            OrganizationUpdateForm(monthly_limit_usd=invite.monthly_limit_usd),
        )


def _issue_platform(request: Request, email: str, user, monthly_limit_usd) -> InvitationResponse:
    _require_platform_admin(user)
    _require_smtp(request)
    if Users.get_user_by_email(email):
        raise HTTPException(status_code=400, detail=ERROR_MESSAGES.EMAIL_TAKEN)
    invite, token = Invitations.issue(
        email=email,
        kind=KIND_PLATFORM,
        created_by=user.id,
        role="user",
        monthly_limit_usd=_clean_limit(monthly_limit_usd),
    )
    _send(request, invite, token)
    return _response(invite)


def _issue_organization(
    request: Request, organization_id: str, email: str, user, monthly_limit_usd
):
    org = _org_for_invite(organization_id, user)
    _require_smtp(request)
    existing = Users.get_user_by_email(email)
    if existing and Organizations.get_member(organization_id, existing.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That user is already a member of this organization",
        )
    role = "admin" if org.kind == ORG_KIND_PLATFORM else "user"
    limit = _clean_limit(monthly_limit_usd)
    _check_member_limit(org, limit)
    invite, token = Invitations.issue(
        email=email,
        kind=KIND_ORGANIZATION,
        created_by=user.id,
        role=role,
        organization_id=organization_id,
        monthly_limit_usd=limit,
    )
    _send(request, invite, token)
    return _response(invite)


def _session_payload(request: Request, response: Response, user):
    expires_delta = parse_duration(request.app.state.config.JWT_EXPIRES_IN)
    expires_at = None
    if expires_delta:
        expires_at = int(time.time()) + int(expires_delta.total_seconds())
    token = create_token(data={"id": user.id}, expires_delta=expires_delta)
    datetime_expires_at = (
        datetime.datetime.fromtimestamp(expires_at, datetime.timezone.utc)
        if expires_at
        else None
    )
    response.set_cookie(
        key="token",
        value=token,
        expires=datetime_expires_at,
        httponly=True,
        samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
        secure=WEBUI_AUTH_COOKIE_SECURE,
    )
    return {
        "token": token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "profile_image_url": user.profile_image_url,
        "permissions": get_permissions(
            user.id, request.app.state.config.USER_PERMISSIONS
        ),
    }


@router.post("/users/invitations", response_model=InvitationResponse)
async def create_platform_invitation(
    request: Request,
    form_data: PlatformInviteEmailForm,
    user=Depends(get_verified_user),
):
    return _issue_platform(
        request,
        _normalize_email(form_data.email),
        user,
        form_data.monthly_limit_usd,
    )


@router.get("/users/invitations", response_model=list[InvitationResponse])
async def list_platform_invitations(user=Depends(get_verified_user)):
    _require_platform_admin(user)
    return [
        _response(invite)
        for invite in Invitations.list_outstanding(KIND_PLATFORM)
    ]


@router.post("/users/invitations/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_platform_invitation(
    request: Request,
    invitation_id: str,
    user=Depends(get_verified_user),
):
    _require_platform_admin(user)
    _require_smtp(request)
    invite = Invitations.get_by_id(invitation_id)
    if not invite or invite.kind != KIND_PLATFORM or invite.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.INVITATION_NOT_FOUND
        )
    if Users.get_user_by_email(invite.email):
        raise HTTPException(status_code=400, detail=ERROR_MESSAGES.EMAIL_TAKEN)
    try:
        updated, token = Invitations.resend(invitation_id, user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.INVITATION_NOT_FOUND,
        )
    _send(request, updated, token)
    return _response(updated)


@router.delete("/users/invitations/{invitation_id}")
async def cancel_platform_invitation(
    invitation_id: str,
    user=Depends(get_verified_user),
):
    _require_platform_admin(user)
    invite = Invitations.get_by_id(invitation_id)
    if not invite or invite.kind != KIND_PLATFORM or invite.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.INVITATION_NOT_FOUND
        )
    if not Invitations.cancel(invitation_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.INVITATION_NOT_FOUND
        )
    return {"status": True}


@router.post(
    "/organizations/{organization_id}/invitations",
    response_model=InvitationResponse,
)
async def create_organization_invitation(
    request: Request,
    organization_id: str,
    form_data: InviteEmailForm,
    user=Depends(get_verified_user),
):
    return _issue_organization(
        request,
        organization_id,
        _normalize_email(form_data.email),
        user,
        form_data.monthly_limit_usd,
    )


@router.get(
    "/organizations/{organization_id}/invitations",
    response_model=list[InvitationResponse],
)
async def list_organization_invitations(
    organization_id: str, user=Depends(get_verified_user)
):
    _org_for_invite(organization_id, user)
    return [
        _response(invite)
        for invite in Invitations.list_outstanding(
            KIND_ORGANIZATION, organization_id
        )
    ]


@router.post(
    "/organizations/{organization_id}/invitations/{invitation_id}/resend",
    response_model=InvitationResponse,
)
async def resend_organization_invitation(
    request: Request,
    organization_id: str,
    invitation_id: str,
    user=Depends(get_verified_user),
):
    _org_for_invite(organization_id, user)
    _require_smtp(request)
    invite = Invitations.get_by_id(invitation_id)
    if (
        not invite
        or invite.kind != KIND_ORGANIZATION
        or invite.organization_id != organization_id
        or invite.accepted_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.INVITATION_NOT_FOUND
        )
    existing = Users.get_user_by_email(invite.email)
    if existing and Organizations.get_member(organization_id, existing.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That user is already a member of this organization",
        )
    try:
        updated, token = Invitations.resend(invitation_id, user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.INVITATION_NOT_FOUND,
        )
    _send(request, updated, token)
    return _response(updated)


@router.delete("/organizations/{organization_id}/invitations/{invitation_id}")
async def cancel_organization_invitation(
    organization_id: str,
    invitation_id: str,
    user=Depends(get_verified_user),
):
    _org_for_invite(organization_id, user)
    invite = Invitations.get_by_id(invitation_id)
    if (
        not invite
        or invite.kind != KIND_ORGANIZATION
        or invite.organization_id != organization_id
        or invite.accepted_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.INVITATION_NOT_FOUND
        )
    if not Invitations.cancel(invitation_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.INVITATION_NOT_FOUND
        )
    return {"status": True}


@router.get("/invitations/{token}", response_model=InvitationPublicResponse)
async def get_invitation(token: str):
    invite = Invitations.get_by_token(token)
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.INVITATION_NOT_FOUND
        )
    organization_name = None
    if invite.organization_id:
        org = Organizations.get_organization_by_id(invite.organization_id)
        organization_name = org.name if org else None
    account = Users.get_user_by_email(invite.email)
    return InvitationPublicResponse(
        email=invite.email,
        kind=invite.kind,
        organization_name=organization_name,
        organization_id=invite.organization_id,
        expired=bool(invite.accepted_at is None and invite.expired),
        accepted=invite.accepted_at is not None,
        account_exists=account is not None,
    )


@router.post("/invitations/{token}/accept")
async def accept_invitation(
    request: Request,
    response: Response,
    token: str,
    form_data: AcceptInviteForm,
    session_user=Depends(get_optional_user),
):
    invite = Invitations.get_by_token(token)
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.INVITATION_NOT_FOUND
        )
    if invite.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has already been used.",
        )
    if invite.expired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation has expired.",
        )
    if session_user and session_user.email.lower() != invite.email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You are signed in as {session_user.email}. "
                "Sign out to accept this invite."
            ),
        )

    existing = Users.get_user_by_email(invite.email)
    if existing is None:
        name = (form_data.name or "").strip()
        password = form_data.password or ""
        if not name or not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Name and password are required to create an account.",
            )
        if len(password.encode("utf-8")) > 72:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.PASSWORD_TOO_LONG,
            )
        existing = Auths.insert_new_auth(
            invite.email,
            get_password_hash(password),
            name,
            "/user.png",
            "user",
        )
        if not existing:
            raise HTTPException(500, detail=ERROR_MESSAGES.CREATE_USER_ERROR)
    else:
        if session_user is None or session_user.id != existing.id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign in as this email to accept the invitation.",
            )

    if invite.kind == KIND_ORGANIZATION and invite.organization_id:
        try:
            Organizations.add_member(
                invite.organization_id, existing.id, invite.role or "user"
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    elif invite.kind == KIND_PLATFORM and existing.role == "pending":
        Users.update_user_role_by_id(existing.id, "user")

    _apply_invite_limit(invite, existing.id)
    Invitations.mark_accepted(invite.id)
    fresh = Users.get_user_by_id(existing.id)
    return _session_payload(request, response, fresh or existing)
