"""Which accounts may authorize a client and use the endpoint."""

from typing import Optional

from open_webui.models.users import UserModel, Users

# Roles the interface allows. The interface's own check is in its auth module, which the endpoint
# does not import.
ACTIVE_ROLES = frozenset({"user", "admin"})


def active_account(user_id: Optional[str]) -> Optional[UserModel]:
    """The account with this id when its current role is in ACTIVE_ROLES, otherwise None."""
    if not user_id:
        return None
    account = Users.get_user_by_id(user_id)
    if account is None or account.role not in ACTIVE_ROLES:
        return None
    return account
