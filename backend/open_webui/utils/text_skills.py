import re
from typing import Iterable, Optional

from open_webui.models.text_skills import TextSkills
from open_webui.models.users import UserModel
from open_webui.utils.preferences import can_manage_preference

# A chat's text skills travel in tool_ids with this prefix, so they are saved
# and restored with the rest of the chat bar's selection.
TEXT_SKILL_ID_PREFIX = "text_skill:"

TEXT_SKILL_BLOCK_RE = re.compile(
    r"\n*## Skills\n.*?\n## End skills\s*",
    re.DOTALL,
)

# Same rule as preferences: private rows by their owner, shared rows by org admins.
can_manage_text_skill = can_manage_preference


def list_text_skill_metadata(user: UserModel, organization_id: str) -> list[dict]:
    return [
        {**row.model_dump(), "can_manage": can_manage_text_skill(user, row)}
        for row in TextSkills.list_for_org(organization_id, user.id)
    ]


def split_text_skill_ids(tool_ids: Optional[list]) -> tuple[Optional[list], list[str]]:
    """Separate text skill ids from real tool ids."""
    if not tool_ids:
        return tool_ids, []
    tools, skills = [], []
    for tool_id in tool_ids:
        if isinstance(tool_id, str) and tool_id.startswith(TEXT_SKILL_ID_PREFIX):
            skills.append(tool_id[len(TEXT_SKILL_ID_PREFIX) :])
        else:
            tools.append(tool_id)
    return tools, skills


def text_skills_prompt(
    user: UserModel, organization_id: str, skill_ids: Iterable[str]
) -> str:
    """The chosen skills the user can see in this org, enabled ones only."""
    wanted = set(skill_ids or [])
    if not wanted:
        return ""
    items = [
        row
        for row in TextSkills.list_for_org(organization_id, user.id)
        if row.id in wanted and row.enabled
    ]
    if not items:
        return ""
    lines = [
        "## Skills",
        "The user turned on these skills for this chat. Follow each one when it applies.",
    ]
    for item in items:
        lines.append("")
        lines.append(f"### {item.title}")
        lines.append(item.content.strip())
    lines.append("")
    lines.append("## End skills")
    return "\n".join(lines)


def inject_text_skills(messages: list, prompt: str) -> list:
    """Append the current skills block to the system message, replacing any previous one."""
    messages = list(messages or [])
    if messages and messages[0].get("role") == "system":
        content = TEXT_SKILL_BLOCK_RE.sub("\n", messages[0].get("content") or "")
        messages[0] = {**messages[0], "content": content.strip()}
    prompt = (prompt or "").strip()
    if not prompt:
        return messages
    if messages and messages[0].get("role") == "system":
        existing = messages[0]["content"]
        messages[0]["content"] = f"{existing}\n\n{prompt}" if existing else prompt
    else:
        messages.insert(0, {"role": "system", "content": prompt})
    return messages
