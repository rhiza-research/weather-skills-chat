from typing import Optional
from pathlib import Path
import asyncio
import json
import logging
import mimetypes
import os
import re
from uuid import uuid4
import smtplib
from email.message import EmailMessage

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

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
EMAIL_ATTACHMENTS_MAX_TOTAL_BYTES = 25 * 1024 * 1024
EMAIL_ATTACHMENTS_MAX_COUNT = 10


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

    # Capture the same tools/features enabled on this chat request so
    # scheduled runs replay with the same skill/tool set.
    tool_ids = metadata.get("tool_ids")
    if isinstance(tool_ids, list):
        tool_ids = [str(t) for t in tool_ids if t]
    else:
        tool_ids = None
    features = metadata.get("features")
    if features is not None and not isinstance(features, dict):
        features = None

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
            tool_ids=tool_ids,
            features=features,
        ),
    )
    if not automation:
        return "Failed to create the automation."
    sync_automation_job(automation)
    scope = f"team `{scope_team_id}`" if scope_team_id else "your private automations"
    tool_note = (
        f" Tools/skills captured: {len(tool_ids)}."
        if tool_ids
        else " Built-in tools only (no chat skills selected)."
    )
    return (
        f"Created automation **{automation.name}** ({cron}) under {scope}."
        f"{tool_note} Open /automations to manage it."
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
        "Copy a file or folder between the chat sandbox root area and the "
        "intermediate_results folder (useful scratch space for skill pipelines). "
        "Use direction=in to move a sandbox path under intermediate_results. "
        "Use direction=out to promote something from intermediate_results back "
        "to the sandbox root area. Paths are relative; do not include "
        "intermediate_results/ in path."
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


async def create_folder(
    path: str,
    __user__: dict = {},
    __metadata__: dict = None,
) -> str:
    """Create a folder (and parents) in the current chat artifact sandbox."""
    from open_webui.utils.artifacts import create_folder as _mkdir

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot create folders in a temporary chat."

    user = Users.get_user_by_id(__user__.get("id"))
    chat = Chats.get_chat_by_id(chat_id)
    if not can_write_chat(user, chat):
        return "You do not have write access to this chat."

    try:
        result = _mkdir(chat_id, path)
    except Exception as e:
        return f"Create folder failed: {e}"

    if result.get("existed"):
        return f"Folder already exists: `{result['path']}`."
    return f"Created folder: `{result['path']}`."


CREATE_FOLDER_SPEC = {
    "name": "create_folder",
    "description": (
        "Create a folder (including parent folders) in the current chat artifact "
        "sandbox so skill outputs can be organized. Pass a relative path such as "
        "`plots/weekly` or `intermediate_results/scratch/run1`. Idempotent: if the "
        "folder already exists, succeeds without error."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative folder path under the chat sandbox "
                    "(e.g. `plots`, `runs/2024-01`, `intermediate_results/tmp`)."
                ),
            },
        },
        "required": ["path"],
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


def _as_email_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = [value]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        raise ValueError("Email recipients must be a string or list of strings")
    emails = []
    for item in parts:
        email = str(item).strip().lower()
        if email:
            emails.append(email)
    return sorted(set(emails))


def _validate_emails(emails: list[str]) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    bad: list[str] = []
    for email in emails:
        if EMAIL_RE.match(email):
            ok.append(email)
        else:
            bad.append(email)
    return ok, bad


def _email_recipient_directory(user_id: str, chat) -> dict:
    user = Users.get_user_by_id(user_id)
    self_info = None
    if user:
        email = (user.email or "").strip().lower()
        self_info = {
            "email": email if email and EMAIL_RE.match(email) else None,
            "name": (user.name or "").strip() or None,
        }

    team_ids = set(Teams.user_team_ids(user_id))
    chat_team_id = getattr(chat, "team_id", None) if chat else None
    if chat_team_id:
        team_ids.add(chat_team_id)

    teams = []
    for team_id in sorted(team_ids):
        team = Teams.get_team_by_id(team_id)
        if not team:
            continue
        members = []
        for member in Teams.get_members(team_id):
            email = (member.email or "").strip().lower()
            if not email or not EMAIL_RE.match(email):
                continue
            members.append(
                {
                    "email": email,
                    "name": (member.name or "").strip() or None,
                    "role": member.role,
                    "is_self": member.user_id == user_id,
                }
            )
        if members:
            teams.append(
                {
                    "team_id": team_id,
                    "team_name": team.name,
                    "members": members,
                }
            )

    return {"self": self_info, "teams": teams}


def _allowed_email_recipients_for_user(user_id: str, chat) -> set[str]:
    directory = _email_recipient_directory(user_id, chat)
    allowed: set[str] = set()
    self_email = (directory.get("self") or {}).get("email")
    if self_email:
        allowed.add(self_email)
    for team in directory.get("teams") or []:
        for member in team.get("members") or []:
            allowed.add(member["email"])
    return allowed


async def list_email_recipients(
    __user__: dict = {},
    __metadata__: dict = None,
    __request__=None,
) -> str:
    """Return the current user's email and teammate emails allowed for send_email."""
    user = Users.get_user_by_id(__user__.get("id"))
    if not user:
        return "User not found."

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    chat = (
        Chats.get_chat_by_id(chat_id) if chat_id and chat_id != "local" else None
    )
    directory = _email_recipient_directory(user.id, chat)

    lines: list[str] = []
    self_info = directory.get("self") or {}
    if self_info.get("email"):
        name = self_info.get("name") or "You"
        lines.append(f"Your email: `{self_info['email']}` ({name})")
    else:
        lines.append("Your account has no email address on file.")

    teams = directory.get("teams") or []
    teammate_lines: list[str] = []
    for team in teams:
        team_header = f"**{team['team_name']}**"
        team_members = []
        for member in team.get("members") or []:
            if member.get("is_self"):
                continue
            label = member.get("name") or member["email"]
            role = member.get("role")
            role_suffix = f" ({role})" if role else ""
            team_members.append(f"- `{member['email']}` — {label}{role_suffix}")
        if team_members:
            teammate_lines.append(team_header)
            teammate_lines.extend(team_members)

    if teammate_lines:
        lines.append("")
        lines.append("Teammate emails (valid `send_email` recipients):")
        lines.extend(teammate_lines)
    else:
        lines.append("")
        lines.append("No teammate email addresses found.")

    lines.append("")
    lines.append(
        "Only your email and teammate emails listed above may be used with `send_email`."
    )
    return "\n".join(lines)


LIST_EMAIL_RECIPIENTS_SPEC = {
    "name": "list_email_recipients",
    "description": (
        "List your email address and the email addresses of your teammates. "
        "Use before send_email to look up valid recipient addresses."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def _ensure_chat_share_link(chat_id: str, base_url: str) -> str:
    chat = Chats.get_chat_by_id(chat_id)
    if not chat:
        return ""
    share_id = getattr(chat, "share_id", None)
    if not share_id:
        shared = Chats.insert_shared_chat_by_chat_id(chat_id)
        share_id = getattr(shared, "id", None) if shared else None
    base = (base_url or "").rstrip("/")
    if not (base and share_id):
        return ""
    return f"{base}/s/{share_id}"


def _attachment_filename(rel: str, *, is_archive: bool = False) -> str:
    path = Path(rel.rstrip("/"))
    if is_archive:
        base = path.name or "artifact"
        return f"{base}.zip"
    return path.as_posix().replace("/", "_")


def _guess_attachment_mime(filename: str) -> tuple[str, str]:
    if filename.endswith(".zip"):
        return "application", "zip"
    mime, _ = mimetypes.guess_type(filename)
    if mime and "/" in mime:
        maintype, subtype = mime.split("/", 1)
        return maintype, subtype
    return "application", "octet-stream"


def _load_email_attachments(
    chat_id: str, paths: list[str]
) -> tuple[list[tuple[str, bytes, str, str]], list[str]]:
    """Load sandbox files/directories as email attachments.

    Returns (attachments, notes) where each attachment is
    (filename, data, maintype, subtype).
    """
    from open_webui.utils.artifacts import (
        normalize_sandbox_relpath,
        pack_sandbox_zip,
        resolve_in_sandbox,
        sandbox_tree_size,
    )

    if len(paths) > EMAIL_ATTACHMENTS_MAX_COUNT:
        raise ValueError(
            f"At most {EMAIL_ATTACHMENTS_MAX_COUNT} attachments are allowed."
        )

    attachments: list[tuple[str, bytes, str, str]] = []
    notes: list[str] = []
    seen_names: set[str] = set()
    total = 0

    for raw in paths:
        rel = normalize_sandbox_relpath(raw)
        target = resolve_in_sandbox(chat_id, rel)
        if not target.exists():
            raise FileNotFoundError(f"Attachment not found: `{rel}`")

        if target.is_dir():
            size = sandbox_tree_size(target)
            if size > EMAIL_ATTACHMENT_MAX_BYTES:
                raise ValueError(
                    f"`{rel}` is too large to attach "
                    f"({size} bytes; max {EMAIL_ATTACHMENT_MAX_BYTES})."
                )
            data = pack_sandbox_zip(chat_id, [rel])
            filename = _attachment_filename(rel, is_archive=True)
        else:
            size = target.stat().st_size
            if size > EMAIL_ATTACHMENT_MAX_BYTES:
                raise ValueError(
                    f"`{rel}` is too large to attach "
                    f"({size} bytes; max {EMAIL_ATTACHMENT_MAX_BYTES})."
                )
            data = target.read_bytes()
            filename = _attachment_filename(rel)

        if filename in seen_names:
            raise ValueError(f"Duplicate attachment filename: `{filename}`")
        seen_names.add(filename)

        total += len(data)
        if total > EMAIL_ATTACHMENTS_MAX_TOTAL_BYTES:
            raise ValueError(
                "Total attachment size exceeds "
                f"{EMAIL_ATTACHMENTS_MAX_TOTAL_BYTES} bytes."
            )

        maintype, subtype = _guess_attachment_mime(filename)
        attachments.append((filename, data, maintype, subtype))
        notes.append(f"`{rel}` as `{filename}`")

    return attachments, notes


def _send_via_smtp(
    host: str,
    port: int,
    username: str,
    password: str,
    use_tls: bool,
    sender_name: str,
    sender_email: str,
    reply_to: str,
    to: list[str],
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes, str, str]] | None = None,
) -> tuple[bool, str]:
    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to
    msg.set_content(body)
    for filename, data, maintype, subtype in attachments or []:
        msg.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )
    try:
        if use_tls:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls()
                if username:
                    smtp.login(username, password)
                smtp.send_message(msg)
        return True, "sent"
    except Exception as e:
        return False, str(e)


async def send_email(
    to: list[str] | str,
    subject: str,
    body: str,
    attachments: list[str] | str | None = None,
    __user__: dict = {},
    __metadata__: dict = None,
    __request__=None,
) -> str:
    """Send a restricted email (self + teammates only) via configured provider."""
    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot send email from a temporary chat. Save the chat first."
    if __request__ is None:
        return "Request context not available."

    user = Users.get_user_by_id(__user__.get("id"))
    if not user:
        return "User not found."
    chat = Chats.get_chat_by_id(chat_id)
    if not can_read_chat(user, chat):
        return "You do not have access to this chat."

    try:
        recipients = _as_email_list(to)
    except ValueError as e:
        return str(e)
    if not recipients:
        return "Provide at least one recipient email."
    valid, invalid = _validate_emails(recipients)
    if invalid:
        return f"Invalid recipient email(s): {', '.join(invalid)}"

    allowed = _allowed_email_recipients_for_user(user.id, chat)
    blocked = [email for email in valid if email not in allowed]
    if blocked:
        return (
            "These recipients are not allowed. You can only email yourself or "
            f"members of one of your teams: {', '.join(blocked)}"
        )

    config = __request__.app.state.config
    smtp_host = (getattr(config, "EMAIL_TOOL_SMTP_HOST", "") or "").strip()
    smtp_port = int(getattr(config, "EMAIL_TOOL_SMTP_PORT", 465) or 465)
    smtp_user = (getattr(config, "EMAIL_TOOL_SMTP_USERNAME", "") or "").strip()
    smtp_password = (getattr(config, "EMAIL_TOOL_SMTP_PASSWORD", "") or "").strip()
    smtp_use_tls = bool(getattr(config, "EMAIL_TOOL_SMTP_USE_TLS", True))
    from_email = (getattr(config, "EMAIL_TOOL_FROM_EMAIL", "") or "").strip()
    if not smtp_host:
        return "Email delivery is not configured (missing EMAIL_TOOL_SMTP_HOST)."
    if not smtp_user:
        return "Email delivery is not configured (missing EMAIL_TOOL_SMTP_USERNAME)."
    if not smtp_password:
        return "Email delivery is not configured (missing EMAIL_TOOL_SMTP_PASSWORD)."
    if not from_email:
        return "Email delivery is not configured (missing EMAIL_TOOL_FROM_EMAIL)."

    share_link = _ensure_chat_share_link(chat_id, getattr(config, "WEBUI_URL", ""))
    footer = (
        "\n\n---\n"
        f"This email was generated from Weather Skills Chat by user {user.email}. "
        f"Share link: {share_link or '(share link unavailable)'}"
    )
    full_body = f"{(body or '').rstrip()}{footer}"

    try:
        attachment_paths = _as_path_list(attachments)
    except ValueError as e:
        return str(e)
    try:
        loaded_attachments, attachment_notes = _load_email_attachments(
            chat_id, attachment_paths
        )
    except (ValueError, FileNotFoundError) as e:
        return str(e)

    sender_name = f"Weather Skills Chat ({(user.name or user.email).strip()})"
    ok, detail = await asyncio.to_thread(
        _send_via_smtp,
        host=smtp_host,
        port=smtp_port,
        username=smtp_user,
        password=smtp_password,
        use_tls=smtp_use_tls,
        sender_name=sender_name,
        sender_email=from_email,
        reply_to=user.email,
        to=valid,
        subject=(subject or "").strip() or "Weather Skills Chat update",
        body=full_body,
        attachments=loaded_attachments,
    )
    if not ok:
        return f"Email send failed: {detail}"
    result = (
        f"Email sent to {', '.join(valid)} with reply-to `{user.email}` "
        f"and from `{sender_name} <{from_email}>`."
    )
    if attachment_notes:
        result += f" Attachments: {', '.join(attachment_notes)}."
    return result


SEND_EMAIL_SPEC = {
    "name": "send_email",
    "description": (
        "Send an email via configured SMTP. Recipients are restricted "
        "to the current user and members of one of the user's teams. "
        "Call list_email_recipients first to look up valid addresses. "
        "Optional attachments are read from the chat artifact sandbox."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Recipient email addresses. Must be your email or a teammate's email."
                ),
            },
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {
                "type": "string",
                "description": (
                    "Plain-text email body. A footer with sender and share link is added automatically."
                ),
            },
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional relative paths to files or folders in the chat "
                    "artifact sandbox (e.g. `plots/map.png`, "
                    "`imerg_kenya_weekly/imerg_kenya_weekly_totals.png`). "
                    "Folders and Zarr stores are attached as `.zip` archives."
                ),
            },
        },
        "required": ["to", "subject", "body"],
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
    from open_webui.utils.skill_version import resolve_tool_ids_by_skill_version
    from open_webui.utils.tools import accessible_skill_records

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
            "create_folder",
            "Create a folder in the chat artifact sandbox for organizing outputs.",
            kind="builtin",
        )
    )
    lines.append(
        _tool_summary_line(
            "list_email_recipients",
            "List your email and teammate emails allowed for send_email.",
            kind="builtin",
        )
    )
    lines.append(
        _tool_summary_line(
            "send_email",
            "Email results to yourself or teammates; optional artifact sandbox attachments.",
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
    features = metadata.get("features") or {}
    if isinstance(features, dict) and features.get("code_interpreter"):
        lines.append(
            _tool_summary_line(
                "execute_code",
                "Run Python in Pyodide. Can copy artifact files into /mnt and back out.",
                kind="builtin",
            )
        )

    selected_ids = list(metadata.get("tool_ids") or [])
    if selected_ids:
        selected_ids = resolve_tool_ids_by_skill_version(
            selected_ids, accessible_skill_records(user)
        )
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


log = logging.getLogger(__name__)


def _rewrite_png_data_uris(text: str) -> str:
    if not isinstance(text, str) or "data:image/png;base64" not in text:
        return text
    import base64

    from open_webui.config import CACHE_DIR

    lines = text.split("\n")
    for idx, line in enumerate(lines):
        if "data:image/png;base64" not in line:
            continue
        try:
            image_id = str(uuid4())
            os.makedirs(os.path.join(CACHE_DIR, "images"), exist_ok=True)
            image_path = os.path.join(CACHE_DIR, f"images/{image_id}.png")
            with open(image_path, "wb") as handle:
                handle.write(base64.b64decode(line.split(",", 1)[1]))
            lines[idx] = f"![Output Image {idx}](/cache/images/{image_id}.png)"
        except Exception:
            log.exception("Failed to persist interpreter image")
    return "\n".join(lines)


def _as_path_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = [value]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        raise ValueError("Paths must be a list of relative artifact paths")
    paths = []
    for item in parts:
        text = str(item).strip()
        if text:
            paths.append(text)
    return paths


async def execute_code(
    code: str,
    inputs: Optional[list[str]] = None,
    outputs: Optional[list[str]] = None,
    __request__=None,
    __event_call__=None,
    __metadata__: dict = None,
    __user__: dict = {},
) -> str:
    """Run Python in the browser Pyodide sandbox (or Jupyter) and return output.

    Optional ``inputs`` are copied from the chat artifact sandbox into Pyodide
    at ``/mnt/<path>`` before execution. Optional ``outputs`` are copied from
    ``/mnt/<path>`` back into the artifact sandbox afterwards.
    """
    if __request__ is None:
        return json.dumps({"error": "Request context not available"})

    engine = getattr(
        __request__.app.state.config, "CODE_INTERPRETER_ENGINE", "pyodide"
    )
    metadata = __metadata__ or {}

    try:
        input_paths = _as_path_list(inputs)
        output_paths = _as_path_list(outputs)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    chat_id = metadata.get("chat_id")
    if (input_paths or output_paths) and (not chat_id or chat_id == "local"):
        return json.dumps(
            {
                "error": (
                    "Cannot copy artifact files in a temporary chat. "
                    "Save the chat first."
                )
            }
        )

    if input_paths or output_paths:
        user = Users.get_user_by_id((__user__ or {}).get("id"))
        chat = Chats.get_chat_by_id(chat_id) if chat_id else None
        if output_paths:
            if not can_write_chat(user, chat):
                return json.dumps(
                    {"error": "You do not have write access to this chat."}
                )
        elif not can_read_chat(user, chat):
            return json.dumps({"error": "You do not have access to this chat."})

        try:
            from open_webui.utils.artifacts import (
                EXECUTE_CODE_MAX_ARCHIVE_BYTES,
                normalize_sandbox_relpath,
                resolve_in_sandbox,
                sandbox_tree_size,
            )

            input_paths = [normalize_sandbox_relpath(p) for p in input_paths]
            output_paths = [normalize_sandbox_relpath(p) for p in output_paths]
            total = 0
            for rel in input_paths:
                target = resolve_in_sandbox(chat_id, rel)
                if not target.exists():
                    return json.dumps({"error": f"Artifact not found: {rel}"})
                total += sandbox_tree_size(target)
                if total > EXECUTE_CODE_MAX_ARCHIVE_BYTES:
                    return json.dumps(
                        {
                            "error": (
                                "Input files exceed the "
                                f"{EXECUTE_CODE_MAX_ARCHIVE_BYTES} byte limit"
                            )
                        }
                    )
        except ValueError as e:
            return json.dumps({"error": str(e)})

    try:
        if engine == "pyodide":
            if __event_call__ is None:
                return json.dumps(
                    {
                        "error": (
                            "Pyodide needs a live browser session. "
                            "Reload the page and try again."
                        )
                    }
                )
            output = await __event_call__(
                {
                    "type": "execute:python",
                    "data": {
                        "id": str(uuid4()),
                        "code": code,
                        "session_id": metadata.get("session_id"),
                        "chat_id": chat_id,
                        "inputs": input_paths,
                        "outputs": output_paths,
                    },
                }
            )
        elif engine == "jupyter":
            if input_paths or output_paths:
                return json.dumps(
                    {
                        "error": (
                            "Copying artifact files into execute_code is only "
                            "supported with the Pyodide engine."
                        )
                    }
                )
            from open_webui.utils.code_interpreter import execute_code_jupyter

            config = __request__.app.state.config
            auth = getattr(config, "CODE_INTERPRETER_JUPYTER_AUTH", "")
            output = await execute_code_jupyter(
                getattr(config, "CODE_INTERPRETER_JUPYTER_URL", ""),
                code,
                (
                    getattr(config, "CODE_INTERPRETER_JUPYTER_AUTH_TOKEN", None)
                    if auth == "token"
                    else None
                ),
                (
                    getattr(config, "CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD", None)
                    if auth == "password"
                    else None
                ),
                getattr(config, "CODE_INTERPRETER_JUPYTER_TIMEOUT", 60),
            )
        else:
            return json.dumps(
                {"error": f"Unknown code interpreter engine: {engine}"}
            )

        if not isinstance(output, dict):
            return json.dumps(
                {
                    "status": "success" if output else "error",
                    "result": str(output) if output else "",
                }
            )

        if output.get("error") and not output.get("stdout") and not output.get("result"):
            return json.dumps(
                {
                    "status": "error",
                    "stderr": output.get("error"),
                    "stdout": "",
                    "result": "",
                }
            )

        stdout = _rewrite_png_data_uris(output.get("stdout") or "")
        result = _rewrite_png_data_uris(output.get("result") or "")
        stderr = output.get("stderr") or ""
        payload = {
            "status": "error" if stderr else "success",
            "stdout": stdout,
            "stderr": stderr,
            "result": result,
        }
        if input_paths:
            payload["inputs"] = input_paths
        copied = output.get("copied_outputs") or output.get("written")
        if copied:
            payload["outputs"] = copied
        missing = output.get("missing_outputs") or []
        if missing:
            payload["outputs_missing"] = missing
        return json.dumps(payload, ensure_ascii=False)
    except Exception as e:
        log.exception("execute_code failed")
        return json.dumps({"error": str(e)})


EXECUTE_CODE_SPEC = {
    "name": "execute_code",
    "description": (
        "Execute Python in a sandboxed in-browser interpreter (Pyodide) and "
        "return stdout, stderr, and the result. Optional inputs are copied "
        "from this chat's artifact sandbox into `/mnt/<path>` before the code "
        "runs; optional outputs are copied from `/mnt/<path>` back into the "
        "artifact sandbox afterwards (files or zarr folders). The working "
        "directory is `/mnt`. Packages are limited to what Pyodide/micropip "
        "can install (numpy, pandas, xarray, matplotlib, and similar)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python source to run. Read inputs from `/mnt/<path>`. "
                    "Write anything that should be saved back under `/mnt/` "
                    "and list those paths in outputs. Print values you need "
                    "to see. Do not write or append weather-skills provenance "
                    "metadata (such as `weather_skills_history*` or "
                    "`rhiza_history*`) into output files."
                ),
            },
            "inputs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Artifact-sandbox relative paths to copy into Pyodide at "
                    "`/mnt/<path>` before execution (files or directories, "
                    "including zarr stores)."
                ),
            },
            "outputs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Paths relative to `/mnt` to copy back into the artifact "
                    "sandbox after execution, using the same relative path."
                ),
            },
        },
        "required": ["code"],
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

    tools = {
        "list_available_tools": _tool(list_available_tools, LIST_AVAILABLE_TOOLS_SPEC),
        "create_automation": _tool(create_automation, CREATE_AUTOMATION_SPEC),
        "create_secret": _tool(create_secret, CREATE_SECRET_SPEC),
        "create_zarr_view": _tool(create_zarr_view, CREATE_ZARR_VIEW_SPEC),
        "copy_intermediate_result": _tool(
            copy_intermediate_result, COPY_INTERMEDIATE_RESULT_SPEC
        ),
        "create_folder": _tool(create_folder, CREATE_FOLDER_SPEC),
        "display_image": _tool(display_image, DISPLAY_IMAGE_SPEC),
        "list_email_recipients": _tool(
            list_email_recipients, LIST_EMAIL_RECIPIENTS_SPEC
        ),
        "send_email": _tool(send_email, SEND_EMAIL_SPEC),
    }
    features = (extra_params.get("__metadata__") or {}).get("features") or {}
    if isinstance(features, dict) and features.get("code_interpreter"):
        tools["execute_code"] = _tool(execute_code, EXECUTE_CODE_SPEC)
    return tools
