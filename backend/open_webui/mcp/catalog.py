"""The endpoint's tool catalog: the shared catalog filtered to entries marked for the endpoint."""

import logging

from open_webui.mcp.request import core_request
from open_webui.models.tools import Tools
from open_webui.models.users import UserModel
from open_webui.utils.tool_surfaces import (
    Surface,
    published_to,
    surfaces_for_tool_record,
)
from open_webui.utils.tools import accessible_tool_ids, merged_catalog

log = logging.getLogger(__name__)


def endpoint_tool_ids(user: UserModel, organization_id: str, catalog) -> list[str]:
    """The default tool set automations use in the organization, limited to tools published to the
    endpoint.

    Tools not published to the endpoint are dropped before get_tools loads their modules.
    """
    surfaces = {tool.id: surfaces_for_tool_record(tool) for tool in catalog}
    return [
        tool_id
        for tool_id in accessible_tool_ids(user, organization_id, catalog=catalog)
        if Surface.ENDPOINT in surfaces[tool_id]
    ]


def endpoint_catalog(
    app, user: UserModel, organization_id: str, extra_params: dict
) -> dict:
    """Catalog entries published to the endpoint in the organization, keyed by tool name.

    Built on every call, so installed, updated and removed skills, and skills the organization
    enables or disables, are reflected immediately.
    """
    catalog = Tools.get_tool_catalog()
    entries = merged_catalog(
        core_request(app, organization_id),
        endpoint_tool_ids(user, organization_id, catalog),
        user,
        extra_params,
        catalog=catalog,
    )
    published = published_to(entries, Surface.ENDPOINT)
    log.debug(
        "Endpoint catalog: %d of %d entries published", len(published), len(entries)
    )
    return published
