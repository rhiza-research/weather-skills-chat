from typing import Optional
import logging

from fastapi import Depends, Header, HTTPException, Request, status
from open_webui.config import ENABLE_ADMIN_CHAT_ACCESS
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.automations import AutomationModel
from open_webui.models.chats import ChatModel
from open_webui.models.organizations import (
    ORG_KIND_PERSONAL,
    ORG_KIND_PLATFORM,
    PLATFORM_ORG_ID,
    ROLE_RANK,
    VISIBILITY_ORGANIZATION,
    VISIBILITY_PRIVATE,
    Organizations,
)
from open_webui.models.users import UserModel
from open_webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)


def user_organization_ids(user_id: str) -> list[str]:
    return Organizations.user_organization_ids(user_id)


def is_member(organization_id: str, user_id: str) -> bool:
    return Organizations.get_member(organization_id, user_id) is not None


def org_role(organization_id: str, user_id: str) -> Optional[str]:
    member = Organizations.get_member(organization_id, user_id)
    return member.role if member else None


def is_at_least(organization_id: str, user_id: str, role: str) -> bool:
    member = Organizations.get_member(organization_id, user_id)
    if not member:
        return False
    return ROLE_RANK.get(member.role, 0) >= ROLE_RANK.get(role, 0)


def is_owner(organization_id: str, user_id: str) -> bool:
    return is_at_least(organization_id, user_id, "owner")


def is_org_admin(organization_id: str, user_id: str) -> bool:
    return is_at_least(organization_id, user_id, "admin")


def is_platform_admin(user_id: str) -> bool:
    return is_at_least(PLATFORM_ORG_ID, user_id, "admin")


def effective_user_role(user: UserModel, organization_id: Optional[str] = None) -> str:
    """Admin is platform-org membership, and only in the platform context."""
    stored = getattr(user, "role", None) or "pending"
    if stored == "pending":
        return "pending"
    if stored == "admin" and not is_platform_admin(user.id):
        try:
            Organizations.ensure_platform()
            if not Organizations.get_member(PLATFORM_ORG_ID, user.id):
                Organizations.add_member(PLATFORM_ORG_ID, user.id, "admin")
        except Exception:
            log.exception("Failed to adopt legacy admin into platform org")
    org_id = (organization_id or "").strip() or user.id
    if org_id == PLATFORM_ORG_ID and is_platform_admin(user.id):
        return "admin"
    return "user"


def apply_effective_user_role(
    user: UserModel, request: Optional[Request] = None
) -> UserModel:
    org_id = None
    if request is not None:
        org_id = request.headers.get("X-Organization-Id")
    user.role = effective_user_role(user, org_id)
    return user


def require_platform_admin(user: UserModel, request: Optional[Request] = None) -> None:
    if not is_platform_admin(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if request is None:
        return
    org_id = (request.headers.get("X-Organization-Id") or "").strip()
    if org_id and org_id != PLATFORM_ORG_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


def is_personal_org(organization_id: str) -> bool:
    org = Organizations.get_organization_by_id(organization_id)
    return bool(org and org.kind == ORG_KIND_PERSONAL)


def resolve_visibility(organization_id: str, visibility: Optional[str]) -> str:
    if is_personal_org(organization_id) or organization_id == "":
        return VISIBILITY_PRIVATE
    if visibility == VISIBILITY_ORGANIZATION:
        return VISIBILITY_ORGANIZATION
    return VISIBILITY_PRIVATE


def folder_chat_error(folder, chat) -> Optional[str]:
    """Why a chat cannot be filed in this folder, or None when it can."""
    if folder is None or chat is None:
        return "Folder not found"
    folder_visibility = getattr(folder, "visibility", VISIBILITY_PRIVATE) or VISIBILITY_PRIVATE
    chat_visibility = getattr(chat, "visibility", VISIBILITY_PRIVATE) or VISIBILITY_PRIVATE
    if folder_visibility != chat_visibility:
        if folder_visibility == VISIBILITY_ORGANIZATION:
            return (
                "Share the chat with the organization before moving it into a team folder."
            )
        return "Team chats stay in team folders."
    if folder_visibility == VISIBILITY_ORGANIZATION:
        if getattr(folder, "organization_id", None) != getattr(chat, "organization_id", None):
            return "That folder belongs to a different organization."
        return None
    if getattr(folder, "user_id", None) != getattr(chat, "user_id", None):
        return "That folder belongs to another user."
    return None


def can_read_chat(user: UserModel, chat: Optional[ChatModel]) -> bool:
    if chat is None:
        return False
    if chat.user_id == user.id:
        return True
    if not is_member(chat.organization_id, user.id) and not (
        ENABLE_ADMIN_CHAT_ACCESS
        and getattr(user, "role", None) == "admin"
        and chat.visibility == VISIBILITY_ORGANIZATION
    ):
        return False
    if chat.visibility == VISIBILITY_ORGANIZATION:
        return True
    return False


def can_write_chat(user: UserModel, chat: Optional[ChatModel]) -> bool:
    if chat is None:
        return False
    return chat.user_id == user.id


def can_read_org_resource(user: UserModel, resource) -> bool:
    if resource is None:
        return False
    if getattr(resource, "user_id", None) == user.id:
        return True
    organization_id = getattr(resource, "organization_id", None)
    visibility = getattr(resource, "visibility", VISIBILITY_PRIVATE)
    if visibility == VISIBILITY_ORGANIZATION and organization_id:
        return is_member(organization_id, user.id)
    return False


def can_write_org_resource(user: UserModel, resource) -> bool:
    if resource is None:
        return False
    if getattr(resource, "user_id", None) == user.id:
        return True
    organization_id = getattr(resource, "organization_id", None)
    visibility = getattr(resource, "visibility", VISIBILITY_PRIVATE)
    return bool(
        visibility == VISIBILITY_ORGANIZATION
        and organization_id
        and is_org_admin(organization_id, user.id)
    )


def can_manage_automation(
    user: UserModel, automation: Optional[AutomationModel]
) -> bool:
    if automation is None:
        return False
    if automation.user_id == user.id:
        return True
    return is_org_admin(automation.organization_id, user.id) and (
        automation.visibility == VISIBILITY_ORGANIZATION
    )


def can_view_automation(
    user: UserModel, automation: Optional[AutomationModel]
) -> bool:
    if automation is None:
        return False
    if can_manage_automation(user, automation):
        return True
    if automation.user_id == user.id:
        return True
    return (
        automation.visibility == VISIBILITY_ORGANIZATION
        and is_member(automation.organization_id, user.id)
    )


def get_active_organization_id(
    x_organization_id: Optional[str] = Header(None, alias="X-Organization-Id"),
    user: UserModel = Depends(get_verified_user),
) -> str:
    requested = (x_organization_id or "").strip()
    if not requested or requested == user.id:
        org = Organizations.ensure_personal(user.id)
        if not org.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is not active",
            )
        return org.id

    org, member = Organizations.get_organization_for_member(requested, user.id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if not org.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization is not active",
        )
    return org.id
