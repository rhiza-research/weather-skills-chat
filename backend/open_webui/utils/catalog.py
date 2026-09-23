from typing import Optional

from open_webui.models.org_catalog import (
    RESOURCE_KNOWLEDGE,
    RESOURCE_MODEL,
    RESOURCE_SKILL,
    RESOURCE_SKILL_ITEM,
    OrgCatalogOverrides,
)
from open_webui.models.organizations import (
    PLATFORM_ORG_ID,
    VISIBILITY_ORGANIZATION,
    VISIBILITY_PUBLIC,
    Organizations,
)
from open_webui.models.users import UserModel
from open_webui.utils.organizations import is_org_admin, is_platform_admin

KIND_FLAGS = {
    RESOURCE_MODEL: "can_add_models",
    RESOURCE_SKILL: "can_add_skills",
    RESOURCE_KNOWLEDGE: "can_add_knowledge",
}


def is_public_item(item) -> bool:
    return getattr(item, "visibility", None) == VISIBILITY_PUBLIC


def _stored_override(
    overrides: Optional[dict],
    organization_id: str,
    resource_type: str,
    resource_id: str,
):
    if overrides is None:
        return OrgCatalogOverrides.get(organization_id, resource_type, resource_id)
    return overrides.get((organization_id, resource_type, resource_id))


def effective_enabled(
    organization_id: str, resource_type: str, item, overrides: Optional[dict] = None
) -> bool:
    if not is_public_item(item):
        return True
    override = _stored_override(overrides, organization_id, resource_type, item.id)
    if override is not None:
        return override
    return bool(getattr(item, "enabled_by_default", True))


def is_catalog_active(item) -> bool:
    """False when a platform admin has withdrawn the item from the catalog."""
    return getattr(item, "is_active", True) is not False


def is_visible(organization_id: str, resource_type: str, item) -> bool:
    """Whether the item appears in workspace/admin catalog lists.

    Public items enabled in the admin catalog (``is_active``) are listed in
    every org/user workspace. ``enabled_by_default`` and per-org overrides
    only change the enable/disable state, not membership in that list.
    Withdrawn catalog items stay on the admin (platform) list so they can
    be turned back on. Org-private items are listed only in their own org.
    """
    if item is None:
        return False
    if is_public_item(item):
        if organization_id == PLATFORM_ORG_ID:
            return True
        return is_catalog_active(item)
    return getattr(item, "organization_id", None) == organization_id


def is_usable(
    organization_id: str, resource_type: str, item, overrides: Optional[dict] = None
) -> bool:
    """Whether the item may be used in chat/tools for this organization."""
    return (
        is_catalog_active(item)
        and is_visible(organization_id, resource_type, item)
        and effective_enabled(organization_id, resource_type, item, overrides)
    )


def is_catalog_chat_model(model_info) -> bool:
    """Curated wrappers only — raw connection models have no base_model_id."""
    return bool(model_info and getattr(model_info, "base_model_id", None))


def can_manage_public(user: UserModel, organization_id: str) -> bool:
    return organization_id == PLATFORM_ORG_ID and is_platform_admin(user.id)


def can_toggle(user: UserModel, organization_id: str) -> bool:
    return is_org_admin(organization_id, user.id)


def can_create_private(user: UserModel, organization_id: str, kind: str) -> bool:
    if organization_id == PLATFORM_ORG_ID:
        return False
    if not is_org_admin(organization_id, user.id):
        return False
    org = Organizations.get_organization_by_id(organization_id)
    if not org:
        return False
    return bool(getattr(org, KIND_FLAGS[kind], False))


def can_write_item(user: UserModel, organization_id: str, item) -> bool:
    if item is None:
        return False
    if is_public_item(item):
        return can_manage_public(user, organization_id)
    return (
        getattr(item, "organization_id", None) == organization_id
        and is_org_admin(organization_id, user.id)
    )


def stamp_create(
    user: UserModel, organization_id: str, kind: str
) -> tuple[str, str]:
    """Return (organization_id, visibility) for a new catalog item."""
    if can_manage_public(user, organization_id):
        return PLATFORM_ORG_ID, VISIBILITY_PUBLIC
    if can_create_private(user, organization_id, kind):
        return organization_id, VISIBILITY_ORGANIZATION
    raise PermissionError("Not allowed to add this catalog item")


def annotate(
    item, organization_id: str, resource_type: str, overrides: Optional[dict] = None
) -> dict:
    data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
    data["enabled"] = effective_enabled(
        organization_id, resource_type, item, overrides
    )
    data["enabled_by_default"] = bool(getattr(item, "enabled_by_default", True))
    data["is_active"] = is_catalog_active(item)
    return data


def _skill_get(skill, key, default=None):
    if skill is None:
        return default
    if isinstance(skill, dict):
        return skill.get(key, default)
    return getattr(skill, key, default)


def skill_default_enabled(skill) -> bool:
    if skill is None:
        return True
    default = _skill_get(skill, "enabled_by_default", None)
    if default is not None:
        return bool(default)
    return _skill_get(skill, "enabled", True) is not False


def skill_is_catalog_active(skill) -> bool:
    return _skill_get(skill, "is_active", True) is not False


def skill_effective_enabled(
    organization_id: str, skill, overrides: Optional[dict] = None
) -> bool:
    tool_id = _skill_get(skill, "tool_id")
    if tool_id:
        override = _stored_override(
            overrides, organization_id, RESOURCE_SKILL_ITEM, tool_id
        )
        if override is not None:
            return override
    return skill_default_enabled(skill)


def skill_is_visible(organization_id: str, pack, skill) -> bool:
    """Whether a skill appears in pack lists for this organization.

    Platform admins see withdrawn skills so they can turn them back on.
    Org-private packs always list their skills. Public catalog skills
    that are not ``is_active`` are hidden from user/org workspaces.
    """
    if skill is None:
        return False
    if organization_id == PLATFORM_ORG_ID:
        return True
    if not is_public_item(pack):
        return True
    return skill_is_catalog_active(skill)


def skill_is_usable(
    organization_id: str, pack, skill, overrides: Optional[dict] = None
) -> bool:
    """Pack must be usable, and the skill in-catalog and enabled."""
    return (
        is_usable(organization_id, RESOURCE_SKILL, pack, overrides)
        and skill_is_catalog_active(skill)
        and skill_is_visible(organization_id, pack, skill)
        and skill_effective_enabled(organization_id, skill, overrides)
    )


def annotate_skills(
    pack, organization_id: str, skills: list, overrides: Optional[dict] = None
) -> list:
    out = []
    for skill in skills or []:
        if hasattr(skill, "model_dump"):
            data = skill.model_dump()
        elif isinstance(skill, dict):
            data = dict(skill)
        else:
            continue
        if not skill_is_visible(organization_id, pack, data):
            continue
        data["is_active"] = skill_is_catalog_active(data)
        data["enabled_by_default"] = skill_default_enabled(data)
        data["enabled"] = skill_effective_enabled(organization_id, data, overrides)
        out.append(data)
    return out
