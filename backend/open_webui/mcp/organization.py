"""The organization an endpoint call runs in.

The caller names it with an X-Organization-Id header on the MCP request, the header the interface
sends. A blank or absent header, or one equal to the account id, names the account's personal
organization. Membership and the organization's active flag are checked as the interface's
get_active_organization_id checks them; a refusal is a ToolError instead of an HTTP error.

The organization scopes the skills the catalog offers, the secrets a run resolves, and the session
the call is recorded in. call_organization_id also sets the account's role for the call; see its
docstring.
"""

import logging
from typing import Optional

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from open_webui.mcp.request import ORGANIZATION_HEADER
from open_webui.models.organizations import Organizations
from open_webui.models.users import UserModel
from open_webui.utils.organizations import effective_user_role

log = logging.getLogger(__name__)

UNKNOWN_ORGANIZATION_MESSAGE = (
    "No organization with id {organization_id!r} exists. Nothing was run. Send an "
    f"{ORGANIZATION_HEADER} header naming an organization this account belongs to, or omit it to "
    "use the personal organization."
)

NOT_A_MEMBER_MESSAGE = (
    "This account is not a member of organization {organization_id!r}. Nothing was run. Send an "
    f"{ORGANIZATION_HEADER} header naming an organization this account belongs to, or omit it to "
    "use the personal organization."
)

INACTIVE_ORGANIZATION_MESSAGE = (
    "Organization {organization_id!r} is not active. Nothing was run. An administrator can "
    "activate it in the web interface."
)


def requested_organization_id() -> Optional[str]:
    """The X-Organization-Id header of the current MCP request, or None without one."""
    # get_http_headers lowercases names and returns {} outside an HTTP request.
    return get_http_headers().get(ORGANIZATION_HEADER.lower())


def active_organization_id(account: UserModel, requested: Optional[str]) -> str:
    """The id of the organization the call runs in.

    Blank, absent, or the account id: the personal organization, created if it does not exist.
    Otherwise the requested organization. Raises ToolError when the organization does not exist,
    the account is not a member, or the organization is not active.
    """
    requested = (requested or "").strip()
    if not requested or requested == account.id:
        organization = Organizations.ensure_personal(account.id)
        if not organization.active:
            raise ToolError(
                INACTIVE_ORGANIZATION_MESSAGE.format(organization_id=organization.id)
            )
        return organization.id

    organization, member = Organizations.get_organization_for_member(
        requested, account.id
    )
    if organization is None:
        raise ToolError(UNKNOWN_ORGANIZATION_MESSAGE.format(organization_id=requested))
    if member is None:
        raise ToolError(NOT_A_MEMBER_MESSAGE.format(organization_id=requested))
    if not organization.active:
        raise ToolError(INACTIVE_ORGANIZATION_MESSAGE.format(organization_id=requested))
    return organization.id


def call_organization_id(account: UserModel) -> str:
    """active_organization_id for the current MCP request's header.

    Also sets account.role to effective_user_role(account, organization_id) from
    open_webui.utils.organizations, before the catalog and the run context read it. The role rule
    and the database writes effective_user_role makes are defined there.
    """
    organization_id = active_organization_id(account, requested_organization_id())
    account.role = effective_user_role(account, organization_id)
    return organization_id
