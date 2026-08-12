from typing import Optional
from pathlib import Path

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


async def copy_intermediate_result(
    path: str,
    direction: str,
    destination: Optional[str] = None,
    __user__: dict = {},
    __metadata__: dict = None,
) -> str:
    """Copy a file or folder between the chat sandbox and intermediate_results."""
    from open_webui.utils.artifacts import copy_intermediate_result as _copy

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot copy intermediate results in a temporary chat."

    user = Users.get_user_by_id(__user__.get("id"))
    chat = Chats.get_chat_by_id(chat_id)
    if not can_write_chat(user, chat):
        return "You do not have write access to this chat."

    try:
        result = _copy(
            chat_id,
            path=path,
            direction=direction,
            destination=destination,
        )
    except Exception as e:
        return f"Copy failed: {e}"

    arrow = "→"
    action = (
        "into intermediate_results"
        if result["direction"] == "in"
        else "out of intermediate_results"
    )
    return (
        f"Copied {result['kind']} {action}: "
        f"`{result['source']}` {arrow} `{result['destination']}`."
    )


COPY_INTERMEDIATE_RESULT_SPEC = {
    "name": "copy_intermediate_result",
    "description": (
        "Copy a file or folder between the chat sandbox and intermediate_results. "
        "Use direction=in to stash a sandbox path under intermediate_results "
        "(not shown to the user). Use direction=out to promote something from "
        "intermediate_results into the user-visible sandbox. Paths are relative; "
        "do not include intermediate_results/ in path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative path to copy. For direction=in, path is under the "
                    "sandbox root. For direction=out, path is under intermediate_results."
                ),
            },
            "direction": {
                "type": "string",
                "enum": ["in", "out"],
                "description": (
                    "in = sandbox → intermediate_results; "
                    "out = intermediate_results → sandbox"
                ),
            },
            "destination": {
                "type": "string",
                "description": (
                    "Optional destination relative path within the target area. "
                    "Defaults to the source basename."
                ),
            },
        },
        "required": ["path", "direction"],
    },
}


DISPLAY_IMAGE_MAX_BYTES = 8 * 1024 * 1024
DISPLAY_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


async def display_image(
    path: str,
    __user__: dict = {},
    __metadata__: dict = None,
):
    """Load a sandbox image and return it for inline display in the chat."""
    import base64

    from open_webui.utils.artifacts import INTERMEDIATE_RESULTS_DIRNAME, resolve_in_sandbox

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot display an image in a temporary chat."

    user = Users.get_user_by_id(__user__.get("id"))
    chat = Chats.get_chat_by_id(chat_id)
    if not can_read_chat(user, chat):
        return "You do not have access to this chat."

    rel = (path or "").strip().lstrip("/")
    if not rel:
        return "Provide a relative path to an image in the chat sandbox."

    try:
        target = resolve_in_sandbox(chat_id, rel)
    except Exception as e:
        return f"Invalid path: {e}"

    if not target.is_file():
        return f"Image not found: `{rel}`"

    mime = DISPLAY_IMAGE_TYPES.get(target.suffix.lower())
    if not mime:
        return (
            "Unsupported image type. Use a .png, .jpg, .jpeg, .gif, or .webp "
            f"file (got `{target.suffix or 'no extension'}`)."
        )

    size = target.stat().st_size
    if size > DISPLAY_IMAGE_MAX_BYTES:
        return (
            f"Image `{rel}` is too large to display inline "
            f"({size} bytes; max {DISPLAY_IMAGE_MAX_BYTES})."
        )

    encoded = base64.b64encode(target.read_bytes()).decode("ascii")
    data_url = f"data:{mime};base64,{encoded}"
    note = f"Showing `{rel}`."
    if INTERMEDIATE_RESULTS_DIRNAME in Path(rel).parts:
        note = f"Showing `{rel}` (from intermediate_results)."
    return [note, data_url]


DISPLAY_IMAGE_SPEC = {
    "name": "display_image",
    "description": (
        "Display a PNG (or jpeg/gif/webp) from the current chat sandbox inline "
        "in the chat. Pass a relative path such as `plot.png` or "
        "`intermediate_results/step.png`. Use after a skill writes an image "
        "you want the user to see in the conversation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to an image file in the chat sandbox",
            },
        },
        "required": ["path"],
    },
}


def _tool_summary_line(name: str, description: str = "", kind: str = "tool", tool_id: str = "") -> str:
    desc = (description or "").strip().split("\n")[0].strip()
    if len(desc) > 160:
        desc = desc[:157] + "..."
    bits = [f"- `{name}`"]
    if kind and kind != "tool":
        bits.append(f"[{kind}]")
    if tool_id and tool_id != name:
        bits.append(f"(id: {tool_id})")
    if desc:
        bits.append(f"— {desc}")
    return " ".join(bits)


async def list_available_tools(
    scope: str = "chat",
    __user__: dict = {},
    __metadata__: dict = None,
) -> str:
    """List tools and skills available to the model for this chat (or all the user can access).

    Call this when the user asks what tools/skills are available, or before choosing
    which skill to run.
    """
    from open_webui.models.tools import Tools
    from open_webui.utils.access_control import has_access

    metadata = __metadata__ or {}
    user = Users.get_user_by_id(__user__.get("id"))
    if not user:
        return "User not found."

    scope = (scope or "chat").strip().lower()
    if scope not in ("chat", "all"):
        scope = "chat"

    lines = []

    # Builtins are always on for every chat turn.
    lines.append("## Built-in tools (always available)")
    lines.append(
        _tool_summary_line(
            "list_available_tools",
            "List tools/skills available in this chat, or all tools you can access.",
            kind="builtin",
        )
    )
    lines.append(
        _tool_summary_line(
            "create_automation",
            "Create a scheduled automation from the current chat.",
            kind="builtin",
        )
    )
    lines.append(
        _tool_summary_line(
            "create_secret",
            "Encrypt and store a credential for later {{secret:NAME}} use.",
            kind="builtin",
        )
    )
    lines.append(
        _tool_summary_line(
            "create_zarr_view",
            "Create a zarr view JSON in the chat artifact folder.",
            kind="builtin",
        )
    )
    lines.append(
        _tool_summary_line(
            "copy_intermediate_result",
            "Copy a file/folder into or out of intermediate_results.",
            kind="builtin",
        )
    )
    lines.append(
        _tool_summary_line(
            "display_image",
            "Show a sandbox PNG/JPEG/GIF/WebP inline in the chat.",
            kind="builtin",
        )
    )

    selected_ids = list(metadata.get("tool_ids") or [])
    all_tools = Tools.get_tools()

    def _visible(tool) -> bool:
        if user.role == "admin" or tool.user_id == user.id:
            return True
        return has_access(user.id, "read", tool.access_control)

    if scope == "chat":
        lines.append("")
        lines.append("## Enabled for this chat")
        if not selected_ids:
            lines.append(
                "(None selected.) Enable tools/skills in the chat tools menu, "
                "or ask with scope=`all` to see everything you can access."
            )
        else:
            by_id = {t.id: t for t in all_tools}
            for tid in selected_ids:
                tool = by_id.get(tid)
                if not tool:
                    lines.append(f"- `{tid}` (missing or unloaded)")
                    continue
                if not _visible(tool):
                    continue
                manifest = (tool.meta.manifest if tool.meta else None) or {}
                kind = "skill" if manifest.get("kind") == "skill" else "tool"
                # Prefer callable names from specs
                if tool.specs:
                    for spec in tool.specs:
                        lines.append(
                            _tool_summary_line(
                                spec.get("name") or tid,
                                spec.get("description")
                                or (tool.meta.description if tool.meta else "")
                                or "",
                                kind=kind,
                                tool_id=tid,
                            )
                        )
                else:
                    lines.append(
                        _tool_summary_line(
                            tool.name or tid,
                            (tool.meta.description if tool.meta else "") or "",
                            kind=kind,
                            tool_id=tid,
                        )
                    )
    else:
        lines.append("")
        lines.append("## All tools/skills you can access")
        accessible = [t for t in all_tools if _visible(t)]
        if not accessible:
            lines.append("(No workspace tools or skills.)")
        else:
            skills = [
                t
                for t in accessible
                if ((t.meta.manifest if t.meta else None) or {}).get("kind") == "skill"
            ]
            plain = [
                t
                for t in accessible
                if ((t.meta.manifest if t.meta else None) or {}).get("kind") != "skill"
            ]
            if plain:
                lines.append("### Tools")
                for tool in plain:
                    desc = (tool.meta.description if tool.meta else "") or ""
                    if tool.specs:
                        for spec in tool.specs:
                            lines.append(
                                _tool_summary_line(
                                    spec.get("name") or tool.id,
                                    spec.get("description") or desc,
                                    kind="tool",
                                    tool_id=tool.id,
                                )
                            )
                    else:
                        lines.append(
                            _tool_summary_line(tool.name or tool.id, desc, tool_id=tool.id)
                        )
            if skills:
                lines.append("### Skills")
                for tool in skills:
                    desc = (tool.meta.description if tool.meta else "") or ""
                    if tool.specs:
                        for spec in tool.specs:
                            lines.append(
                                _tool_summary_line(
                                    spec.get("name") or tool.id,
                                    spec.get("description") or desc,
                                    kind="skill",
                                    tool_id=tool.id,
                                )
                            )
                    else:
                        lines.append(
                            _tool_summary_line(
                                tool.name or tool.id, desc, kind="skill", tool_id=tool.id
                            )
                        )
            enabled = set(selected_ids)
            not_enabled = [t.id for t in accessible if t.id not in enabled]
            if not_enabled:
                lines.append("")
                lines.append(
                    f"Note: {len(not_enabled)} accessible tool(s)/skill(s) are not enabled "
                    "for this chat. Enable them in the tools menu to call them."
                )

    return "\n".join(lines)


LIST_AVAILABLE_TOOLS_SPEC = {
    "name": "list_available_tools",
    "description": (
        "List tools and skills available to you. Use when the user asks what tools "
        "or skills you have, what you can do, or which skill to use. "
        "Default scope is this chat's enabled tools; use scope=all for everything "
        "the user can access (including skills not yet enabled in this chat)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["chat", "all"],
                "description": (
                    "chat = tools/skills enabled for this chat turn (default). "
                    "all = every tool/skill the user can access."
                ),
            },
        },
        "required": [],
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
        "list_available_tools": _tool(list_available_tools, LIST_AVAILABLE_TOOLS_SPEC),
        "create_automation": _tool(create_automation, CREATE_AUTOMATION_SPEC),
        "create_secret": _tool(create_secret, CREATE_SECRET_SPEC),
        "create_zarr_view": _tool(create_zarr_view, CREATE_ZARR_VIEW_SPEC),
        "copy_intermediate_result": _tool(
            copy_intermediate_result, COPY_INTERMEDIATE_RESULT_SPEC
        ),
        "display_image": _tool(display_image, DISPLAY_IMAGE_SPEC),
    }
