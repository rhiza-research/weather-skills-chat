from typing import Optional

from open_webui.config import ENABLE_ADMIN_CHAT_ACCESS
from open_webui.models.automations import AutomationModel
from open_webui.models.chats import ChatModel
from open_webui.models.teams import Teams
from open_webui.models.users import UserModel


def user_team_ids(user_id: str) -> list[str]:
    return Teams.user_team_ids(user_id)


def is_team_member(team_id: str, user_id: str) -> bool:
    return Teams.get_member(team_id, user_id) is not None


def is_team_admin(team_id: str, user_id: str, user_role: Optional[str] = None) -> bool:
    if user_role == "admin":
        return True
    member = Teams.get_member(team_id, user_id)
    return bool(member and member.role == "admin")


def can_read_chat(user: UserModel, chat: Optional[ChatModel]) -> bool:
    if chat is None:
        return False
    if user.role == "admin" and ENABLE_ADMIN_CHAT_ACCESS:
        return True
    if chat.user_id == user.id:
        return True
    if chat.team_id and is_team_member(chat.team_id, user.id):
        return True
    return False


def can_write_chat(user: UserModel, chat: Optional[ChatModel]) -> bool:
    if chat is None:
        return False
    if user.role == "admin" and ENABLE_ADMIN_CHAT_ACCESS:
        return True
    return chat.user_id == user.id


def can_manage_automation(user: UserModel, automation: Optional[AutomationModel]) -> bool:
    if automation is None:
        return False
    if user.role == "admin":
        return True
    if automation.user_id == user.id:
        return True
    if automation.team_id and is_team_admin(automation.team_id, user.id, user.role):
        return True
    return False


def can_view_automation(user: UserModel, automation: Optional[AutomationModel]) -> bool:
    if automation is None:
        return False
    if can_manage_automation(user, automation):
        return True
    if automation.team_id and is_team_member(automation.team_id, user.id):
        return True
    return False
