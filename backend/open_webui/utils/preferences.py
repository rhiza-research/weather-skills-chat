import re
from typing import Optional

from open_webui.models.preferences import Preference, Preferences
from open_webui.models.users import UserModel
from open_webui.utils.organizations import is_org_admin

PREFERENCE_BLOCK_RE = re.compile(
    r"\n*## Saved preferences\n.*?\n## End saved preferences\s*",
    re.DOTALL,
)


def can_manage_preference(user: UserModel, row: Optional[Preference]) -> bool:
    if row is None:
        return False
    if row.visibility == "private":
        return row.user_id == user.id
    return is_org_admin(row.organization_id, user.id)


def list_preference_metadata(user: UserModel, organization_id: str) -> list[dict]:
    items = []
    for row in Preferences.list_for_org(organization_id, user.id):
        items.append(
            {
                **row.model_dump(),
                "can_manage": can_manage_preference(user, row),
            }
        )
    return items


def enabled_preferences(user: UserModel, organization_id: str) -> list[dict]:
    return [
        item
        for item in list_preference_metadata(user, organization_id)
        if item.get("enabled")
    ]


def preferences_prompt(user: UserModel, organization_id: str) -> str:
    items = enabled_preferences(user, organization_id)
    if not items:
        return ""
    lines = [
        "## Saved preferences",
        "Follow these saved preferences when they apply to the conversation.",
    ]
    for item in items:
        scope = "organization" if item.get("visibility") == "organization" else "private"
        lines.append("")
        lines.append(f"### {item.get('title')} ({scope})")
        lines.append((item.get("content") or "").strip())
    lines.append("")
    lines.append("## End saved preferences")
    return "\n".join(lines)


def inject_preferences(messages: list, prompt: str) -> list:
    """Append the current preference block, replacing any previous one."""
    if not messages:
        messages = []
    cleaned = []
    for index, message in enumerate(messages):
        if index == 0 and message.get("role") == "system":
            content = PREFERENCE_BLOCK_RE.sub("\n", message.get("content") or "")
            message = {**message, "content": content.strip()}
        cleaned.append(message)
    messages = cleaned
    prompt = (prompt or "").strip()
    if not prompt:
        return messages
    if messages and messages[0].get("role") == "system":
        existing = (messages[0].get("content") or "").strip()
        messages[0]["content"] = f"{existing}\n\n{prompt}".strip() if existing else prompt
    else:
        messages.insert(0, {"role": "system", "content": prompt})
    return messages
