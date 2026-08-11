from typing import Optional

from open_webui.models.automations import AutomationForm, Automations
from open_webui.models.chats import Chats
from open_webui.models.secrets import SecretForm, Secrets
from open_webui.models.teams import Teams
from open_webui.models.users import Users
from open_webui.utils.automation_scheduler import sync_automation_job
from open_webui.utils.schedule import parse_schedule, prompt_from_messages
from open_webui.utils.teams import (
    can_read_chat,
    can_write_chat,
    is_team_admin,
    is_team_member,
)


async def create_automation(
    name: str,
    schedule: str,
    prompt: Optional[str] = None,
    team_id: Optional[str] = None,
    __user__: dict = {},
    __messages__: list = None,
    __metadata__: dict = None,
    __model__: dict = None,
) -> str:
    """Create a scheduled automation from the current chat.

    Call this when the user asks to repeat the current task on a schedule,
    e.g. "do this again every day at noon".

    :param name: Short title for the automation
    :param schedule: Cron (0 12 * * *) or a phrase like "every day at noon"
    :param prompt: Optional restatement of the task. If omitted, prior user turns are used.
    :param team_id: Optional team scope. Defaults to the current chat's team.
    """
    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot create an automation from a temporary chat. Save the chat first."

    cron = parse_schedule(schedule)
    if not cron:
        return (
            "I could not understand that schedule. "
            "Try cron like `0 12 * * *` or a phrase like `every day at noon`."
        )

    user = Users.get_user_by_id(__user__.get("id"))
    if not user:
        return "User not found."

    chat = Chats.get_chat_by_id(chat_id)
    if not can_read_chat(user, chat):
        return "You do not have access to this chat."

    recipe = (prompt or "").strip() or prompt_from_messages(__messages__ or [])
    if not recipe:
        return "I need a task description to schedule. Please restate what should run."

    scope_team_id = team_id if team_id is not None else getattr(chat, "team_id", None)
    if scope_team_id and not is_team_member(scope_team_id, user.id):
        return "You are not a member of that team."

    model_id = None
    if isinstance(__model__, dict):
        model_id = __model__.get("id")
    if not model_id and chat.chat:
        models = chat.chat.get("models") or []
        model_id = models[0] if models else None

    automation = Automations.insert_new_automation(
        user.id,
        AutomationForm(
            name=name.strip() or "Scheduled chat",
            prompt=recipe,
            model=model_id,
            cron=cron,
            enabled=True,
            team_id=scope_team_id,
            source_chat_id=chat_id,
        ),
    )
    if not automation:
        return "Failed to create the automation."
    sync_automation_job(automation)
    scope = f"team `{scope_team_id}`" if scope_team_id else "your private automations"
    return (
        f"Created automation **{automation.name}** ({cron}) under {scope}. "
        f"Open /automations to manage it."
    )


CREATE_AUTOMATION_SPEC = {
    "name": "create_automation",
    "description": (
        "Create a scheduled automation from the current chat. "
        "Use when the user asks to repeat this task on a schedule "
        "(for example: 'do this again every day at noon')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short title for the automation",
            },
            "schedule": {
                "type": "string",
                "description": (
                    "Cron expression (0 12 * * *) or a phrase such as "
                    "'every day at noon', 'hourly', 'weekly on Monday at 09:00'"
                ),
            },
            "prompt": {
                "type": "string",
                "description": "Optional restatement of the task to replay",
            },
            "team_id": {
                "type": "string",
                "description": "Optional team id; defaults to the current chat's team",
            },
        },
        "required": ["name", "schedule"],
    },
}


async def create_zarr_view(
    zarr: str,
    title: str,
    variable: Optional[str] = None,
    style: str = "heatmap",
    colormap: str = "viridis",
    __user__: dict = {},
    __metadata__: dict = None,
) -> str:
    """Create a zarr view JSON in the current chat sandbox."""
    from open_webui.utils.artifacts import write_json

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot create a zarr view in a temporary chat."
    user = Users.get_user_by_id(__user__.get("id"))
    chat = Chats.get_chat_by_id(chat_id)
    if not can_write_chat(user, chat):
        return "You do not have write access to this chat."
    relpath = f"views/{title.replace(' ', '-').lower()}.zarrview.json"
    write_json(
        chat_id,
        relpath,
        {
            "type": "zarr_view",
            "zarr": zarr,
            "title": title,
            "variable": variable,
            "style": style,
            "colormap": colormap,
            "index": {},
            "bbox": None,
        },
    )
    return f"Wrote zarr view `{relpath}` for `{zarr}`."


def _resolve_team_for_secret(user, team: Optional[str]):
    if not team or not str(team).strip():
        return None, None
    raw = str(team).strip()
    found = Teams.get_team_by_id(raw)
    if not found:
        candidates = Teams.get_teams_by_user_id(user.id)
        if user.role == "admin":
            candidates = Teams.get_all_teams()
        matches = [t for t in candidates if (t.name or "").lower() == raw.lower()]
        if len(matches) == 1:
            found = matches[0]
        elif len(matches) > 1:
            return None, "That team name is ambiguous; pass the team id."
    if not found:
        return None, "Team not found."
    if not is_team_admin(found.id, user.id, user.role):
        return None, "Only team admins can create team secrets."
    return found, None


async def create_secret(
    name: str,
    value: str,
    team: Optional[str] = None,
    replace: bool = False,
    __user__: dict = {},
) -> str:
    """Encrypt and store a secret. Never echo the value back."""
    user = Users.get_user_by_id(__user__.get("id"))
    if not user:
        return "User not found."
    if isinstance(replace, str):
        replace = replace.lower() in ("1", "true", "yes")

    team_row, error = _resolve_team_for_secret(user, team)
    if error:
        return error
    team_id = team_row.id if team_row else None

    try:
        form = SecretForm(name=name, value=value, team_id=team_id)
    except Exception as e:
        return str(e)

    existing = (
        Secrets.get_team(team_id, form.name)
        if team_id
        else Secrets.get_personal(user.id, form.name)
    )

    if existing:
        if not replace:
            scope = f"team `{team_row.name}`" if team_row else "your personal secrets"
            return (
                f"A secret named `{form.name}` already exists in {scope}. "
                "Pass replace=true to overwrite it, or choose a different name."
            )
        from open_webui.models.secrets import SecretUpdateForm
        from open_webui.utils.secrets import can_manage_secret

        if not can_manage_secret(user, existing):
            return "You cannot replace that secret."
        updated = Secrets.update(existing.id, SecretUpdateForm(value=form.value))
        if not updated:
            return "Failed to replace the secret."
        placeholder = f"{{{{secret:{updated.name}}}}}"
        scope = f"team `{team_row.name}`" if team_row else "your personal secrets"
        return (
            f"Replaced secret `{updated.name}` in {scope}. "
            f"Use `{placeholder}` in later tool calls. The value will not be shown again."
        )

    created = Secrets.insert(user.id, form)
    if not created:
        return "Failed to save the secret."
    placeholder = f"{{{{secret:{created.name}}}}}"
    scope = f"team `{team_row.name}`" if team_row else "your personal secrets"
    return (
        f"Saved secret `{created.name}` in {scope}. "
        f"Use `{placeholder}` in later tool calls. The value will not be shown again."
    )


CREATE_SECRET_SPEC = {
    "name": "create_secret",
    "description": (
        "Encrypt and store a credential, API key, token, or password. "
        "Use when the user asks to save a secret. After saving, never repeat "
        "the raw value; use {{secret:NAME}} in later tool calls."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Secret name: letter or underscore first, then letters, "
                    "digits, or underscores (e.g. ECMWF_API_KEY)"
                ),
            },
            "value": {
                "type": "string",
                "description": "The secret value to encrypt. Never echo this back.",
            },
            "team": {
                "type": "string",
                "description": (
                    "Optional team id or team name. Omit for a personal secret. "
                    "Only team admins can create team secrets."
                ),
            },
            "replace": {
                "type": "boolean",
                "description": "If true, overwrite an existing secret with the same name.",
            },
        },
        "required": ["name", "value"],
    },
}


CREATE_ZARR_VIEW_SPEC = {
    "name": "create_zarr_view",
    "description": "Create a zarr view JSON in the current chat's artifact folder.",
    "parameters": {
        "type": "object",
        "properties": {
            "zarr": {"type": "string", "description": "Path to the zarr store in the chat sandbox"},
            "title": {"type": "string"},
            "variable": {"type": "string"},
            "style": {"type": "string", "enum": ["heatmap", "timeseries"]},
            "colormap": {"type": "string"},
        },
        "required": ["zarr", "title"],
    },
}


def get_builtin_tools(extra_params: dict) -> dict:
    from open_webui.utils.tools import get_async_tool_function_and_apply_extra_params

    def _tool(fn, spec):
        return {
            "toolkit_id": "builtin",
            "callable": get_async_tool_function_and_apply_extra_params(fn, extra_params),
            "spec": spec,
            "pydantic_model": None,
            "file_handler": False,
            "citation": False,
        }

    return {
        "create_automation": _tool(create_automation, CREATE_AUTOMATION_SPEC),
        "create_secret": _tool(create_secret, CREATE_SECRET_SPEC),
        "create_zarr_view": _tool(create_zarr_view, CREATE_ZARR_VIEW_SPEC),
    }
