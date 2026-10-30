from typing import Any, NamedTuple, Optional
from pathlib import Path
import asyncio
import json
import logging
import mimetypes
import os
import re
import time
from uuid import uuid4
import smtplib
from email.message import EmailMessage

from open_webui.models.automations import (
    DEFAULT_RUN_TIMEOUT_MINUTES,
    MAX_RUN_TIMEOUT_MINUTES,
    AutomationForm,
    AutomationRuns,
    Automations,
    AutomationUpdateForm,
)
from open_webui.models.chats import Chats
from open_webui.models.organizations import ORG_KIND_PERSONAL, Organizations
from open_webui.models.users import Users
from open_webui.utils.automation_scheduler import (
    remove_automation_job,
    sync_automation_job,
)
from open_webui.utils.schedule import parse_schedule, prompt_from_messages
from open_webui.utils.organizations import (
    can_manage_automation,
    can_read_chat,
    can_view_automation,
    can_write_chat,
    is_member,
    resolve_visibility,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
EMAIL_ATTACHMENTS_MAX_TOTAL_BYTES = 25 * 1024 * 1024
EMAIL_ATTACHMENTS_MAX_COUNT = 10
WEB_SEARCH_PAGE_CHAR_LIMIT = 8000


class ChatAccess(NamedTuple):
    user: Any
    chat: Any
    readable: bool
    writable: bool


def _load_chat_access(user_id: Optional[str], chat_id: Optional[str]) -> ChatAccess:
    """The user, the chat's access row, and whether the user may read or change it.

    The lookups, and the organization check for a user who is not the owner,
    are DB reads: call from a worker thread.
    """
    user = Users.get_user_by_id(user_id) if user_id else None
    chat = (
        Chats.get_chat_access_row(chat_id)
        if chat_id and chat_id != "local"
        else None
    )
    if user is None:
        return ChatAccess(None, chat, False, False)
    return ChatAccess(user, chat, can_read_chat(user, chat), can_write_chat(user, chat))


async def _chat_access(user_id: Optional[str], chat_id: Optional[str]) -> ChatAccess:
    """_load_chat_access for tools that stay async."""
    return await asyncio.to_thread(_load_chat_access, user_id, chat_id)


def _time_limit_problem(minutes: Optional[int]) -> Optional[str]:
    if minutes is not None and not 1 <= minutes <= MAX_RUN_TIMEOUT_MINUTES:
        return (
            f"The time limit must be between 1 and {MAX_RUN_TIMEOUT_MINUTES} "
            "minutes."
        )
    return None


# The tool arguments that set a task's feature flags, by the flag they set.
TASK_FEATURE_ARGS = {
    "web_search": "web_search",
    "code_interpreter": "code_interpreter",
    "read_files": "read_artifacts",
    "email": "email",
    "preferences": "preferences",
}

# Features an admin turns on for the app and users need permission for, as
# the task page and chat bar offer them.
_GATED_TASK_FEATURES = {
    "web_search": ("ENABLE_WEB_SEARCH", "Web search"),
    "code_interpreter": ("ENABLE_CODE_INTERPRETER", "Running code"),
}


def _apply_task_settings(
    form,
    user,
    organization_id: str,
    request,
    current_features: Optional[dict],
    model: Optional[str] = None,
    skills: Optional[list[str]] = None,
    shared: Optional[bool] = None,
    **features: Optional[bool],
) -> Optional[str]:
    """Set the passed settings on a task form, or say why one cannot be used.

    Checks them as the task page does. DB reads: call from a worker thread.
    """
    from open_webui.utils.access_control import has_permission
    from open_webui.utils.automation_runner import _accessible_tool_ids
    from open_webui.utils.models import check_model_access, remember_catalog_model
    from open_webui.utils.organizations import is_personal_org
    from open_webui.utils.tools import accessible_skill_records

    if model is not None:
        entry = remember_catalog_model(request, model) if request is not None else None
        try:
            if entry is None:
                raise ValueError(model)
            check_model_access(user, entry, organization_id)
        except Exception:
            return f"The model `{model}` is not available in this organization."
        form.model = model

    if skills is not None:
        known = {
            record["skill_name"]
            for record in accessible_skill_records(user, organization_id)
        } | set(_accessible_tool_ids(user, organization_id))
        unknown = [skill for skill in skills if skill not in known]
        if unknown:
            return (
                "These skills or tools are not available: "
                + ", ".join(f"`{skill}`" for skill in unknown)
                + ". list_available_tools with scope `all` lists the ones there are."
            )
        form.tool_ids = list(skills)

    chosen = {
        TASK_FEATURE_ARGS[arg]: value for arg, value in features.items() if value is not None
    }
    if chosen:
        config = _request_config(request)
        for feature, (setting, label) in _GATED_TASK_FEATURES.items():
            if not chosen.get(feature) or config is None:
                continue
            permitted = user.role == "admin" or has_permission(
                user.id, f"features.{feature}", getattr(config, "USER_PERMISSIONS", {})
            )
            if not getattr(config, setting, False) or not permitted:
                return f"{label} is not available to this user, so it cannot be turned on."
        form.features = {**(current_features or {}), **chosen}

    if shared is not None:
        if shared and is_personal_org(organization_id):
            return "A task in a personal organization cannot be shared."
        form.visibility = "organization" if shared else "private"
    return None


def _task_settings_args(**kwargs) -> dict:
    """The settings arguments to pass on, without the unset ones."""
    return {key: value for key, value in kwargs.items() if value is not None}


async def create_scheduled_task(
    name: str,
    schedule: str,
    prompt: Optional[str] = None,
    organization_id: Optional[str] = None,
    time_limit_minutes: Optional[int] = None,
    model: Optional[str] = None,
    skills: Optional[list[str]] = None,
    web_search: Optional[bool] = None,
    code_interpreter: Optional[bool] = None,
    read_files: Optional[bool] = None,
    email: Optional[bool] = None,
    preferences: Optional[bool] = None,
    shared: Optional[bool] = None,
    __user__: dict = {},
    __messages__: list = None,
    __metadata__: dict = None,
    __model__: dict = None,
    __request__=None,
) -> str:
    """Create a scheduled task from the current chat.

    Call this when the user asks to repeat the current task on a schedule,
    e.g. "do this again every day at noon".

    :param name: Short title for the scheduled task
    :param schedule: Cron (0 12 * * *) or a phrase like "every day at noon"
    :param prompt: Optional restatement of the task. If omitted, prior user turns are used.
    :param organization_id: Optional organization id. Defaults to the current chat's organization.
    :param time_limit_minutes: Optional limit on how long each run may take
    :param model: Optional model id. Defaults to this chat's model.
    :param skills: Optional skill names and tool ids. Defaults to this chat's.
    :param web_search: Optional; defaults to this chat's setting, as do the
        other switches
    :param shared: Optional; whether the organization shares the task
    """
    if problem := _time_limit_problem(time_limit_minutes):
        return problem
    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot create a scheduled task from a temporary chat. Save the chat first."

    cron = parse_schedule(schedule)
    if not cron:
        return (
            "I could not understand that schedule. "
            "Try cron like `0 12 * * *` or a phrase like `every day at noon`."
        )

    # The whole chat: the task reuses its model. DB reads, so in a thread.
    def load() -> tuple:
        user = Users.get_user_by_id(__user__.get("id"))
        if not user:
            return None, None, False
        chat = Chats.get_chat_by_id(chat_id)
        return user, chat, can_read_chat(user, chat)

    user, chat, readable = await asyncio.to_thread(load)
    if not user:
        return "User not found."
    if not readable:
        return "You do not have access to this chat."

    recipe = (prompt or "").strip() or prompt_from_messages(__messages__ or [])
    if not recipe:
        return "I need a task description to schedule. Please restate what should run."

    organization_id = organization_id if organization_id is not None else getattr(
        chat, "organization_id", user.id
    )
    if organization_id and not is_member(organization_id, user.id):
        return "You are not a member of that organization."

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

    form = AutomationForm(
        name=name.strip() or "Scheduled chat",
        prompt=recipe,
        model=model_id,
        cron=cron,
        enabled=True,
        organization_id=organization_id,
        visibility=getattr(chat, "visibility", "private"),
        source_chat_id=chat_id,
        tool_ids=tool_ids,
        features=features,
        timeout_minutes=time_limit_minutes,
    )
    # Anything passed replaces what was copied from the chat.
    problem = await asyncio.to_thread(
        _apply_task_settings,
        form,
        user,
        organization_id,
        __request__,
        features,
        **_task_settings_args(
            model=model,
            skills=skills,
            shared=shared,
            web_search=web_search,
            code_interpreter=code_interpreter,
            read_files=read_files,
            email=email,
            preferences=preferences,
        ),
    )
    if problem:
        return problem

    automation = Automations.insert_new_automation(user.id, form)
    if not automation:
        return "Failed to create the scheduled task."
    sync_automation_job(automation)
    scope = (
        f"organization `{organization_id}`"
        if organization_id != user.id
        else "your personal scheduled tasks"
    )
    tool_note = (
        f" Tools/skills captured: {len(tool_ids)}."
        if tool_ids
        else " Built-in tools only (no chat skills selected)."
    )
    return (
        f"Created scheduled task **{automation.name}** ({cron}) under {scope}."
        f"{tool_note} [Open scheduled tasks](/scheduled-tasks) to manage it."
    )


def _switch(description: str) -> dict:
    return {"type": "boolean", "description": description}


# Settings both create_scheduled_task and update_scheduled_task take, matching
# what the task page sets. Create defaults each one to the current chat's.
TASK_SETTING_PROPERTIES = {
    "model": {
        "type": "string",
        "description": "Model id to run the task with",
    },
    "skills": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Skill names and tool ids the task may use, replacing the current "
            "list; an empty list allows none. Each run uses the newest copy of a "
            "named skill."
        ),
    },
    "web_search": _switch("Allow the agent to search the web"),
    "code_interpreter": _switch("Allow the agent to write and run its own code"),
    "read_files": _switch(
        "Allow the agent to read the run's files. A run has no one to ask, so "
        "with this off it cannot read them."
    ),
    "email": _switch("Allow the agent to send email"),
    "preferences": _switch("Allow the agent to read and save preferences"),
    "shared": _switch(
        "Share the task with the organization; not possible in a personal one"
    ),
}


CREATE_SCHEDULED_TASK_SPEC = {
    "name": "create_scheduled_task",
    "description": (
        "Create a scheduled task from the current chat. It copies this chat's "
        "model, skills, and switches unless they are passed. "
        "Use when the user asks to repeat this task on a schedule "
        "(for example: 'do this again every day at noon'). "
        "Scheduled tasks run headless: no user is present to answer follow-up questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short title for the scheduled task",
            },
            "schedule": {
                "type": "string",
                "description": (
                    "Cron expression (0 12 * * *) or a phrase such as "
                    "'every weekday at 7am', 'mondays and thursdays at 6pm', "
                    "'every 2 hours', 'monthly on the 1st at 9am'"
                ),
            },
            "prompt": {
                "type": "string",
                "description": "Optional restatement of the task to replay",
            },
            "organization_id": {
                "type": "string",
                "description": "Optional organization id; defaults to the current chat's organization",
            },
            "time_limit_minutes": {
                "type": "integer",
                "description": (
                    f"How long each run may take, in minutes (1 to {MAX_RUN_TIMEOUT_MINUTES}). "
                    f"A run past it is stopped as an error. Defaults to {DEFAULT_RUN_TIMEOUT_MINUTES}."
                ),
            },
            **TASK_SETTING_PROPERTIES,
        },
        "required": ["name", "schedule"],
    },
}


TASK_PROMPT_PREVIEW_CHARS = 200


def _format_time(epoch: Optional[int]) -> str:
    if not epoch:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(epoch))


def _describe_task_tools(tool_ids: Optional[list[str]]) -> str:
    if tool_ids is None:
        return "every skill and tool the user can use"
    return ", ".join(tool_ids) or "none"


def _describe_task_features(features: Optional[dict]) -> str:
    features = features or {}
    on = [
        label
        for flag, label in (
            ("web_search", "web search"),
            ("code_interpreter", "running code"),
            ("read_artifacts", "read files"),
        )
        if features.get(flag)
    ]
    off = [
        f"{label} off"
        for flag, label in (("email", "email"), ("preferences", "preferences"))
        if features.get(flag) is False
    ]
    return "; ".join(part for part in (", ".join(on), ", ".join(off)) if part) or "none"


def _describe_task(automation, user_id: str, full: bool) -> str:
    runs = AutomationRuns.get_runs(automation.id, limit=1)
    last = runs[0] if runs else None
    last_run = "never run"
    if last:
        last_run = f"{last.status} at {_format_time(last.started_at)}"
        if last.summary:
            last_run += f": {last.summary}"
        if last.error:
            last_run += f": {last.error}"
    prompt = automation.prompt or ""
    if not full and len(prompt) > TASK_PROMPT_PREVIEW_CHARS:
        prompt = prompt[:TASK_PROMPT_PREVIEW_CHARS].rstrip() + "…"
    lines = [
        f"### {automation.name}",
        f"- id: `{automation.id}`",
        f"- schedule: `{automation.cron or 'none (runs only when someone presses Run)'}`"
        + ("" if automation.enabled else " (scheduled runs are off)"),
        f"- model: {automation.model or 'default'}",
        (
            f"- time limit: {automation.timeout_minutes} minutes"
            if automation.timeout_minutes
            else f"- time limit: {DEFAULT_RUN_TIMEOUT_MINUTES} minutes (default)"
        ),
        "- shared with the organization"
        if automation.visibility == "organization"
        else "- private",
    ]
    if automation.user_id != user_id:
        owner = Users.get_user_by_id(automation.user_id)
        lines.append(f"- owner: {owner.name if owner else automation.user_id}")
    lines.append(f"- skills and tools: {_describe_task_tools(automation.tool_ids)}")
    lines.append(f"- features: {_describe_task_features(automation.features)}")
    if automation.image_updated_at:
        lines.append("- has a picture")
    changed = f"- last changed: {_format_time(automation.updated_at)}"
    if automation.updated_by:
        changer = Users.get_user_by_id(automation.updated_by)
        changed += f" by {changer.name if changer else automation.updated_by}"
    lines.append(changed)
    lines.append(f"- last run: {last_run}")
    lines.append(f"- prompt: {prompt}")
    return "\n".join(lines)


async def list_scheduled_tasks(
    task_id: Optional[str] = None,
    __user__: dict = {},
    __metadata__: dict = None,
) -> str:
    """List the scheduled tasks in this chat's organization, or show one in full.

    :param task_id: Optional scheduled task id to show with its whole prompt
    """
    metadata = __metadata__ or {}
    user_id = __user__.get("id")

    def load() -> str:
        user = Users.get_user_by_id(user_id)
        if not user:
            return "User not found."
        if task_id:
            automation = Automations.get_automation_by_id(task_id)
            if not can_view_automation(user, automation):
                return "Scheduled task not found."
            return _describe_task(automation, user.id, full=True)
        organization_id = metadata.get("organization_id") or user.id
        automations = Automations.get_automations_for_user(user.id, organization_id)
        if not automations:
            return "There are no scheduled tasks in this organization."
        return "\n\n".join(_describe_task(a, user.id, full=False) for a in automations)

    return await asyncio.to_thread(load)


LIST_SCHEDULED_TASKS_SPEC = {
    "name": "list_scheduled_tasks",
    "description": (
        "List the scheduled tasks in this organization that the user can see, "
        "with each one's id, schedule, model, sharing, last run and its result, "
        "and the start of its prompt. Pass task_id to show one task's whole prompt."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Optional scheduled task id to show in full",
            },
        },
    },
}


def _managed_task(user_id: Optional[str], task_id: str):
    """(user, automation, error). DB reads: call from a worker thread."""
    user = Users.get_user_by_id(user_id) if user_id else None
    if not user:
        return None, None, "User not found."
    automation = Automations.get_automation_by_id(task_id)
    if not can_view_automation(user, automation):
        return user, None, "Scheduled task not found."
    if not can_manage_automation(user, automation):
        return user, automation, (
            "You cannot change this scheduled task. Only its owner, or an "
            "organization admin for a shared task, can."
        )
    return user, automation, None


async def update_scheduled_task(
    task_id: str,
    name: Optional[str] = None,
    schedule: Optional[str] = None,
    prompt: Optional[str] = None,
    organization_id: Optional[str] = None,
    time_limit_minutes: Optional[int] = None,
    model: Optional[str] = None,
    skills: Optional[list[str]] = None,
    web_search: Optional[bool] = None,
    code_interpreter: Optional[bool] = None,
    read_files: Optional[bool] = None,
    email: Optional[bool] = None,
    preferences: Optional[bool] = None,
    shared: Optional[bool] = None,
    enabled: Optional[bool] = None,
    remove_picture: Optional[bool] = None,
    __user__: dict = {},
    __request__=None,
) -> str:
    """Change any of a scheduled task's settings. Only the ones passed change.

    :param task_id: The scheduled task to change, from list_scheduled_tasks
    :param name: New short title
    :param schedule: New cron (0 12 * * *) or a phrase like "every day at noon"
    :param prompt: New task to run, in full
    :param organization_id: Organization id to move the scheduled task to
    :param time_limit_minutes: New limit on how long each run may take
    :param model: New model id
    :param skills: New skill names and tool ids, replacing the old ones
    :param web_search: Turn web search on or off, as for the other switches
    :param shared: Whether the organization shares the task
    :param enabled: Whether scheduled runs are on
    :param remove_picture: Remove the task's picture
    """
    form = AutomationUpdateForm()
    if enabled is not None:
        form.enabled = enabled
    if time_limit_minutes is not None:
        if problem := _time_limit_problem(time_limit_minutes):
            return problem
        form.timeout_minutes = time_limit_minutes
    if name is not None:
        if not name.strip():
            return "The name cannot be empty."
        form.name = name
    if schedule is not None:
        cron = parse_schedule(schedule)
        if not cron:
            return (
                "I could not understand that schedule. "
                "Try cron like `0 12 * * *` or a phrase like `every day at noon`."
            )
        form.cron = cron
    if prompt is not None:
        if not prompt.strip():
            return "The prompt cannot be empty."
        form.prompt = prompt

    def save() -> str:
        user, automation, error = _managed_task(__user__.get("id"), task_id)
        if error:
            return error
        if organization_id is not None and organization_id != automation.organization_id:
            if not is_member(organization_id, user.id):
                return "You are not a member of that organization."
            form.organization_id = organization_id
            # Sharing does not carry into a personal organization.
            form.visibility = resolve_visibility(organization_id, automation.visibility)
        problem = _apply_task_settings(
            form,
            user,
            form.organization_id or automation.organization_id,
            __request__,
            automation.features,
            **_task_settings_args(
                model=model,
                skills=skills,
                shared=shared,
                web_search=web_search,
                code_interpreter=code_interpreter,
                    read_files=read_files,
                email=email,
                preferences=preferences,
            ),
        )
        if problem:
            return problem
        if not form.model_fields_set and not remove_picture:
            return "Nothing to change. Pass the settings to change."
        if remove_picture:
            Automations.set_image(automation.id, None)
        updated = (
            Automations.update_automation(automation.id, form, updated_by=user.id)
            if form.model_fields_set
            else Automations.get_automation_by_id(automation.id)
        )
        if not updated:
            return "Failed to update the scheduled task."
        sync_automation_job(updated)
        return "Updated the scheduled task.\n\n" + _describe_task(
            updated, user.id, full=False
        )

    return await asyncio.to_thread(save)


UPDATE_SCHEDULED_TASK_SPEC = {
    "name": "update_scheduled_task",
    "description": (
        "Change any of an existing scheduled task's settings: the same ones "
        "create_scheduled_task takes, plus turning scheduled runs on or off and "
        "removing its picture. "
        "Get its id from list_scheduled_tasks. Only pass the fields to change. "
        "A new prompt replaces the old one, so pass the whole task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The scheduled task to change, from list_scheduled_tasks",
            },
            "name": {"type": "string", "description": "New short title"},
            "schedule": {
                "type": "string",
                "description": (
                    "New cron expression (0 12 * * *) or a phrase such as "
                    "'every weekday at 7am', 'mondays and thursdays at 6pm', "
                    "'every 2 hours', 'monthly on the 1st at 9am'"
                ),
            },
            "prompt": {
                "type": "string",
                "description": "New task to run, in full",
            },
            "organization_id": {
                "type": "string",
                "description": "Organization id to move the scheduled task to",
            },
            "time_limit_minutes": {
                "type": "integer",
                "description": (
                    f"How long each run may take, in minutes (1 to {MAX_RUN_TIMEOUT_MINUTES}). "
                    f"A run past it is stopped as an error. Tasks without one use {DEFAULT_RUN_TIMEOUT_MINUTES}."
                ),
            },
            **TASK_SETTING_PROPERTIES,
            "enabled": _switch("Turn the task's scheduled runs on or off"),
            "remove_picture": _switch("Remove the task's picture"),
        },
        "required": ["task_id"],
    },
}


async def delete_scheduled_task(task_id: str, __user__: dict = {}) -> str:
    """Delete a scheduled task, its schedule, and its run history.

    :param task_id: The scheduled task to delete, from list_scheduled_tasks
    """

    def delete() -> str:
        _user, automation, error = _managed_task(__user__.get("id"), task_id)
        if error:
            return error
        remove_automation_job(automation.id)
        if not Automations.delete_automation(automation.id):
            return "Failed to delete the scheduled task."
        return f"Deleted scheduled task **{automation.name}** and its run history."

    return await asyncio.to_thread(delete)


DELETE_SCHEDULED_TASK_SPEC = {
    "name": "delete_scheduled_task",
    "description": (
        "Delete a scheduled task, its schedule, and its run history. This cannot be "
        "undone. Only call it when the user asks to delete that scheduled task. "
        "Get its id from list_scheduled_tasks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The scheduled task to delete, from list_scheduled_tasks",
            },
        },
        "required": ["task_id"],
    },
}


TASK_RESULT_STATUSES = ("success", "failure")


def _task_picture(user_id: Optional[str], chat_id: Optional[str], path: str):
    """(thumbnail, None) for an image in the chat's files, or (None, why not).

    Reads files and the DB: call from a worker thread.
    """
    from open_webui.utils.artifacts import resolve_in_sandbox
    from open_webui.utils.task_image import task_image_thumbnail

    if not chat_id or not _load_chat_access(user_id, chat_id).readable:
        return None, "this run's chat files could not be read"
    rel = (path or "").strip().lstrip("/")
    try:
        target = resolve_in_sandbox(chat_id, rel)
    except Exception as e:
        return None, f"invalid path: {e}"
    if target.suffix.lower() not in DISPLAY_IMAGE_TYPES:
        return None, "use a .png, .jpg, .jpeg, .gif, or .webp image"
    data = wait_for_sandbox_image(target, target.suffix, timeout_s=DISPLAY_IMAGE_WAIT_S)
    if data is None:
        return None, f"`{rel}` was not found"
    if len(data) > DISPLAY_IMAGE_MAX_BYTES:
        return None, f"`{rel}` is too large"
    try:
        return task_image_thumbnail(data), None
    except Exception:
        return None, f"`{rel}` could not be read as an image"


async def report_task_result(
    status: str,
    summary: str,
    image: Optional[str] = None,
    __user__: dict = {},
    __metadata__: dict = None,
) -> str:
    """Report whether this scheduled task run did what it was asked.

    :param status: success or failure
    :param summary: One or two sentences on the result
    :param image: Optional path to an image in the chat's files to show for the task
    """
    from open_webui.utils.automation_runner import record_report

    metadata = __metadata__ or {}
    run_id = metadata.get("automation_run_id")
    if not run_id:
        return "There is no scheduled task run to report on."
    status = (status or "").strip().lower()
    if status not in TASK_RESULT_STATUSES:
        return "The status must be `success` or `failure`."
    summary = (summary or "").strip()
    if not summary:
        return "Give a short summary of the result."
    picture, problem = None, None
    if image:
        picture, problem = await asyncio.to_thread(
            _task_picture, __user__.get("id"), metadata.get("chat_id"), image
        )
    record_report(run_id, status, summary, picture)
    result = f"Recorded this run's result as {status}."
    if problem:
        result += f" The image was not used: {problem}."
    return result


REPORT_TASK_RESULT_SPEC = {
    "name": "report_task_result",
    "description": (
        "Report whether this scheduled task did what it was asked. Call it once, "
        "when the task is done: `success` if it did, `failure` if it could not, "
        "for example because data was missing or a step failed. The summary is "
        "shown to the user next to the run. A later call replaces an earlier one. "
        "If you never call it, the run's result is shown as unknown. Optionally "
        "pass `image`, a path to a PNG, JPEG, GIF, or WebP in the chat's files "
        "that best shows what this run produced, such as the map it made; it "
        "becomes the task's picture. When the run made or showed an image that "
        "represents its result, pass it, so the user can recognize the task at "
        "a glance. Leave it out to keep the current picture."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": list(TASK_RESULT_STATUSES),
                "description": "success or failure",
            },
            "summary": {
                "type": "string",
                "description": "One or two sentences on the result, for the user",
            },
            "image": {
                "type": "string",
                "description": (
                    "Optional relative path to an image in the chat's files to "
                    "show as the task's picture"
                ),
            },
        },
        "required": ["status", "summary"],
    },
}


async def secrets_page(name: str, __request__=None, **_ignored) -> str:
    """Return a secrets-page link with the name filled in. Never accept a value."""
    from open_webui.models.secrets import SECRET_NAME_RE
    from open_webui.utils.secrets import secrets_page_url

    cleaned = (name or "").strip()
    if not SECRET_NAME_RE.match(cleaned):
        return (
            "Secret name must start with a letter or underscore and contain only "
            "letters, digits, and underscores. Do not ask the user to paste the "
            "secret value into the chat."
        )
    config = getattr(getattr(__request__, "app", None), "state", None)
    config = getattr(config, "config", None)
    base = (getattr(config, "WEBUI_URL", "") or "") if config is not None else ""
    url = secrets_page_url(base, cleaned)
    return (
        f"Give the user this link and do not ask them to paste the secret here: {url} "
        f"The name `{cleaned}` is already filled in. They paste the value on that page."
    )


def _preference_actor(__user__, __metadata__):
    from open_webui.models.users import Users

    user_id = (__user__ or {}).get("id")
    user = Users.get_user_by_id(user_id) if user_id else None
    if not user:
        return None, None
    org_id = ((__metadata__ or {}).get("organization_id") or "").strip() or user.id
    return user, org_id


async def list_preferences(__user__=None, __metadata__=None, **_ignored) -> str:
    """List preferences the user can see in the active organization."""
    from open_webui.utils.preferences import list_preference_metadata

    user, org_id = _preference_actor(__user__, __metadata__)
    if not user:
        return "Cannot list preferences without an authenticated user."
    items = list_preference_metadata(user, org_id)
    if not items:
        return (
            "No preferences in this organization. If the user wants one saved, "
            "ask them first. Call create_preference only after they agree."
        )
    lines = ["Preferences in this organization:"]
    for item in items:
        scope = "organization" if item.get("visibility") == "organization" else "private"
        state = "enabled" if item.get("enabled") else "disabled"
        lines.append(f"- {item.get('title')} ({scope}, {state})")
        lines.append((item.get("content") or "").strip())
    lines.append(
        "To save a new preference, ask the user if they want it, then call "
        "create_preference only after they agree."
    )
    return "\n".join(lines)


async def create_preference(
    title: str,
    content: str,
    visibility: str = "private",
    __user__=None,
    __metadata__=None,
    **_ignored,
) -> str:
    """Create a preference after the user has agreed."""
    from open_webui.models.preferences import PreferenceForm, Preferences
    from open_webui.utils.organizations import (
        is_org_admin,
        is_personal_org,
        resolve_visibility,
    )

    user, org_id = _preference_actor(__user__, __metadata__)
    if not user:
        return "Cannot create a preference without an authenticated user."
    title = (title or "").strip()
    scope = resolve_visibility(org_id, (visibility or "private").strip() or "private")
    if scope == "organization":
        if is_personal_org(org_id):
            return "Cannot save an organization preference in the personal organization."
        if not is_org_admin(org_id, user.id):
            return (
                "Only an organization admin can save an organization preference. "
                "Ask the user if a private preference is what they want instead."
            )
        if Preferences.get_shared(org_id, (title or "").strip()):
            return "An organization preference with that title already exists."
    elif Preferences.get_private(org_id, user.id, (title or "").strip()):
        return "A private preference with that title already exists."
    try:
        preference = Preferences.insert(
            user.id,
            PreferenceForm(
                title=title,
                content=content,
                organization_id=org_id,
                visibility=scope,
                enabled=True,
            ),
        )
    except ValueError as exc:
        return str(exc)
    if not preference:
        return "Could not save that preference."
    return (
        f"Saved {scope} preference `{preference.title}`. It is enabled and will be "
        "included in chats for this organization."
    )


LIST_PREFERENCES_SPEC = {
    "name": "list_preferences",
    "description": (
        "Read the user's saved preferences for the current organization, including "
        "private preferences and organization preferences. Each has a title, text, "
        "and whether it is enabled. Enabled preferences are already added to the "
        "chat. To add one, ask the user if they want it saved, then call "
        "create_preference only after they agree."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


CREATE_PREFERENCE_SPEC = {
    "name": "create_preference",
    "description": (
        "Save a preference that will be appended to future chats. Ask the user "
        "whether they want this saved as a preference and wait until they agree "
        "before calling this tool. Do not create a preference they have not "
        "confirmed. Use visibility private unless they are an organization admin "
        "and they confirmed it should apply to the whole organization."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short name for the preference.",
            },
            "content": {
                "type": "string",
                "description": "The preference text to follow in later chats.",
            },
            "visibility": {
                "type": "string",
                "enum": ["private", "organization"],
                "description": (
                    "private applies to this user. organization applies to every "
                    "member and requires an organization admin who agreed to that."
                ),
            },
        },
        "required": ["title", "content"],
    },
}


SECRETS_PAGE_SPEC = {
    "name": "secrets_page",
    "description": (
        "Get a link to the user's secrets page with a secret name already filled in, "
        "so they can paste the value there. Never ask them to paste a secret into "
        "the chat, and do not accept or store a secret value."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Secret name to prefill, such as ECMWF_API_KEY. "
                    "Letters, digits, and underscores only. Do not include the secret value."
                ),
            }
        },
        "required": ["name"],
    },
}


def copy_intermediate_result(
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

    access = _load_chat_access(__user__.get("id"), chat_id)
    if not access.writable:
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

    from open_webui.utils.chat_realtime import schedule_artifacts

    schedule_artifacts(str(chat_id))

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


def create_folder(
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

    access = _load_chat_access(__user__.get("id"), chat_id)
    if not access.writable:
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


def list_artifacts(
    path: Optional[str] = None,
    depth: Optional[int] = None,
    provenance: bool = False,
    __user__: dict = {},
    __metadata__: dict = None,
) -> str:
    """List files and folders in the current chat artifact sandbox."""
    from open_webui.utils.artifacts import list_artifacts as _list, resolve_in_sandbox

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot list artifacts in a temporary chat."
    if depth is not None and depth < 1:
        return "depth must be at least 1."

    if not _load_chat_access(__user__.get("id"), chat_id).readable:
        return "You do not have access to this chat."

    prefix = (path or "").strip().lstrip("/")
    if prefix in (".",):
        prefix = ""
    if prefix:
        # None when prefix is a folder to list; otherwise the reply.
        def check_prefix() -> Optional[str]:
            try:
                target = resolve_in_sandbox(chat_id, prefix)
            except Exception as e:
                return f"Invalid path: {e}"
            if not target.exists():
                return f"Path not found: `{prefix}`"
            if not target.is_dir():
                return f"`{prefix}` (file, {target.stat().st_size} bytes)"
            return None

        reply = check_prefix()
        if reply is not None:
            return reply

    try:
        entries = _list(chat_id, path=prefix or None, depth=depth, provenance=provenance)
    except Exception as e:
        return f"Failed to list artifacts: {e}"

    if not entries:
        where = f" under `{prefix}`" if prefix else ""
        return f"No files in the chat artifact sandbox{where}."

    lines = [
        "Chat artifact sandbox contents"
        + (f" under `{prefix}`:" if prefix else ":")
    ]
    for item in entries:
        rel = item.get("path") or ""
        kind = item.get("kind") or ("directory" if item.get("is_dir") else "file")
        size = item.get("size")
        if kind in ("directory",) or item.get("is_dir"):
            note = ", not expanded" if item.get("truncated") else ""
            line = f"- `{rel}/` ({kind}{note})"
        elif size is not None:
            line = f"- `{rel}` ({kind}, {size} bytes)"
        else:
            line = f"- `{rel}` ({kind})"
        crumbs = item.get("provenance")
        if crumbs:
            line += " — made by: " + " → ".join(crumbs)
        lines.append(line)
    if any(item.get("truncated") for item in entries):
        lines.append(
            "Folders marked not expanded are deeper than `depth`; "
            "list one by passing it as `path`."
        )
    lines.append(
        "Paths are relative to the chat sandbox (skills cwd). "
        "Use these paths with other tools (e.g. skills, read_artifact, display_image, execute_code)."
    )
    return "\n".join(lines)


LIST_ARTIFACTS_SPEC = {
    "name": "list_artifacts",
    "description": (
        "List files and folders in the current chat artifact sandbox (skills working "
        "directory). Use when the user uploaded files, after skills write outputs, "
        "or to discover available paths before reading them with read_artifact "
        "or plotting/attaching them. "
        "Optionally pass a relative folder path to list only that subtree, a depth "
        "to limit how many folder levels are listed, and provenance to show which "
        "skills produced each image, HTML page and Zarr store."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Optional relative folder under the sandbox to list "
                    "(e.g. `intermediate_results` or `plots`). Omit for the full tree."
                ),
            },
            "depth": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Optional number of folder levels to list below `path` "
                    "(1 = only its direct contents). Omit to list every level."
                ),
            },
            "provenance": {
                "type": "boolean",
                "description": (
                    "Show the chain of skills that produced each image, HTML page "
                    "and Zarr store. Slower on large sandboxes. Defaults to false."
                ),
            },
        },
        "required": [],
    },
}


DISPLAY_IMAGE_MAX_BYTES = 8 * 1024 * 1024
DISPLAY_IMAGE_WAIT_S = 6.0
DISPLAY_IMAGE_POLL_S = 0.25
DISPLAY_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
}


def looks_like_display_image(data: bytes, suffix: str) -> bool:
    if not data:
        return False
    kind = (suffix or "").lower()
    if kind == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if kind in (".jpg", ".jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if kind == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if kind == ".webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    if kind == ".avif":
        return len(data) >= 12 and data[4:8] == b"ftyp" and b"avif" in data[8:16]
    return False


DISPLAY_HTML_SUFFIXES = {".html", ".htm"}
DISPLAY_HTML_HEAD_BYTES = 4096


def looks_like_display_html(head: bytes) -> bool:
    return b"<" in (head or b"")[:DISPLAY_HTML_HEAD_BYTES]


def refresh_sandbox_lookup(path: Path) -> None:
    """Bust FUSE/JuiceFS negative dentry cache so a just-written file is visible."""
    try:
        os.listdir(path.parent)
    except OSError:
        pass


def wait_for_sandbox_image(
    target: Path,
    suffix: str,
    *,
    timeout_s: float = DISPLAY_IMAGE_WAIT_S,
    interval_s: float = DISPLAY_IMAGE_POLL_S,
) -> Optional[bytes]:
    deadline = time.monotonic() + timeout_s
    while True:
        refresh_sandbox_lookup(target)
        try:
            if target.is_file():
                data = target.read_bytes()
                if looks_like_display_image(data, suffix):
                    return data
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval_s)


def wait_for_sandbox_html(
    target: Path,
    *,
    timeout_s: float = DISPLAY_IMAGE_WAIT_S,
    interval_s: float = DISPLAY_IMAGE_POLL_S,
) -> bool:
    """Wait until a just-written HTML file is there. Reads only its start: an
    embedded Plotly figure is several MB."""
    deadline = time.monotonic() + timeout_s
    while True:
        refresh_sandbox_lookup(target)
        try:
            if target.is_file():
                with target.open("rb") as f:
                    if looks_like_display_html(f.read(DISPLAY_HTML_HEAD_BYTES)):
                        return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)


def display_image(
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

    access = _load_chat_access(__user__.get("id"), chat_id)
    if not access.readable:
        return "You do not have access to this chat."

    rel = (path or "").strip().lstrip("/")
    if not rel:
        return "Provide a relative path to an image in the chat sandbox."

    try:
        target = resolve_in_sandbox(chat_id, rel)
    except Exception as e:
        return f"Invalid path: {e}"

    if target.suffix.lower() in DISPLAY_HTML_SUFFIXES:
        # Shown to the user in a sandboxed frame; nothing is sent to the model.
        if not wait_for_sandbox_html(
            target, timeout_s=DISPLAY_IMAGE_WAIT_S, interval_s=DISPLAY_IMAGE_POLL_S
        ):
            return f"File not found: `{rel}`"
        return (
            f"Showing `{rel}` to the user as an interactive page. You cannot see "
            "it; to look at a figure yourself, also save it as a PNG and use "
            "read_artifact."
        )

    mime = DISPLAY_IMAGE_TYPES.get(target.suffix.lower())
    if not mime:
        return (
            "Unsupported type. Use a .png, .jpg, .jpeg, .gif, or .webp image, or "
            f"an .html page (got `{target.suffix or 'no extension'}`)."
        )

    data = wait_for_sandbox_image(target, target.suffix)
    if data is None:
        return f"Image not found: `{rel}`"

    if len(data) > DISPLAY_IMAGE_MAX_BYTES:
        return (
            f"Image `{rel}` is too large to display inline "
            f"({len(data)} bytes; max {DISPLAY_IMAGE_MAX_BYTES})."
        )

    encoded = base64.b64encode(data).decode("ascii")
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
        "`intermediate_results/step.png`. It also shows an .html page, such as "
        "an interactive Plotly figure, in a sandboxed frame the user can zoom "
        "and hover; save Plotly figures with include_plotlyjs='cdn' so the "
        "file stays small. This call waits for other tools in "
        "the same turn, so you do not need `depends_on` when a skill just "
        "wrote the file. Show each image either with this tool or with a "
        "relative markdown link such as `![map](plots/map.png)` or "
        "`[map](plots/map.png)`. Do not do both for the same image. This "
        "shows the image to the user; it does not send it to you. To read "
        "an image yourself, use read_artifact."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to an image or .html file in the chat sandbox",
            },
        },
        "required": ["path"],
    },
}


async def _user_approved_artifact_read(rel: str, event_call) -> Optional[str]:
    """Ask the user to allow sending a sandbox file to the model.

    Returns None when approved, or a message to give the model when not.
    """
    if event_call is None:
        return (
            "Cannot ask the user to approve a file read in this session. "
            "The file was not sent."
        )
    try:
        result = await event_call(
            {
                "type": "confirmation",
                "data": {
                    "title": "Allow the model to read this file?",
                    "message": (
                        f"The model wants to read `{rel}` from this chat's files."
                    ),
                },
            }
        )
    except Exception:
        return (
            "Could not ask the user to approve reading that file. "
            "It was not sent."
        )
    if result is True:
        return None
    return "The user declined to let you read that file."


def _runner_size_text(rtype) -> str:
    parts = []
    if rtype.cpus:
        parts.append(f"{rtype.cpus:g} CPU cores")
    if rtype.memory_gib:
        parts.append(f"{rtype.memory_gib:g} GiB memory")
    return f"{rtype.display_name} ({', '.join(parts)})" if parts else rtype.display_name


async def _user_approved_runner(rtype, reason: str, event_call) -> Optional[str]:
    """Ask the user to allow a runner size that needs approval.

    Returns None when approved, or a message to give the model when not.
    """
    if event_call is None:
        return (
            "Cannot ask the user to approve a larger tool runner in this session. "
            "The runner was not changed."
        )
    minutes = max(1, round((rtype.idle_ttl_seconds or 600) / 60))
    lines = [f"The model wants a {_runner_size_text(rtype)} tool runner for this chat."]
    if reason:
        lines.append(f"Reason: {reason}")
    if rtype.description:
        lines.append(rtype.description)
    lines.append(
        f"Skills run on it until it has been idle for {minutes} minutes; then the "
        "chat goes back to the standard runner."
    )
    try:
        result = await event_call(
            {
                "type": "confirmation",
                "data": {
                    "title": f"Switch to a {rtype.display_name} tool runner?",
                    "message": "\n\n".join(lines),
                },
            }
        )
    except Exception:
        return (
            "Could not ask the user to approve a larger tool runner. "
            "The runner was not changed."
        )
    if result is True:
        return None
    return f"The user declined the {rtype.display_name} tool runner. The runner was not changed."


async def request_tool_runner(
    size: str,
    reason: str = "",
    __user__: dict = {},
    __metadata__: dict = None,
    __event_call__=None,
):
    """Switch this chat's tool runner to another size."""
    from open_webui.utils.chat_realtime import emit_chat_runner, schedule_runner_metrics
    from open_webui.utils.runner_types import find
    from open_webui.utils.skill_k8s_sandbox import (
        default_runner_type,
        effective_runner_type,
        runner_catalog,
        runner_size_public,
        runner_types_for_org,
        start_runner,
        switch_runner_type,
    )

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "A temporary chat has no tool runner. Save the chat first."
    access = await _chat_access(__user__.get("id"), chat_id)
    if not access.readable:
        return "You do not have access to this chat."

    catalog = await runner_catalog()
    allowed = await runner_types_for_org(metadata.get("organization_id"))
    names = ", ".join(f"`{t.type}`" for t in allowed)
    rtype = find(catalog, size)
    if rtype is None:
        return f"There is no `{size}` tool runner. Sizes this chat can use: {names}."
    if not any(t.name == rtype.name for t in allowed):
        return (
            f"This organization cannot use {rtype.display_name} tool runners. A "
            f"platform admin can allow them. Sizes this chat can use: {names}."
        )
    current = effective_runner_type(chat_id, catalog)
    if rtype.name == current.name:
        return f"This chat is already on the {_runner_size_text(rtype)} tool runner."

    # Going smaller never asks; a size marked as needing approval does.
    if rtype.requires_approval and rtype.order > current.order:
        if metadata.get("headless"):
            return (
                f"A scheduled task cannot ask for a {rtype.display_name} tool runner. "
                "Set the runner size on the task instead."
            )
        denied = await _user_approved_runner(rtype, (reason or "").strip(), __event_call__)
        if denied:
            return denied

    switch_runner_type(chat_id, rtype, catalog)
    # Start it now, so it boots while the reply goes on.
    start_runner(chat_id)
    schedule_runner_metrics(chat_id)
    try:
        await emit_chat_runner(
            chat_id,
            {"state": "starting", "metrics": None, "size": runner_size_public(chat_id)},
        )
    except Exception:
        log.debug("runner switch emit failed", exc_info=True)

    when = (
        "It keeps a runner ready, so it starts in seconds."
        if rtype.warm
        else "It can take a few minutes to start; the next skill waits for it."
    )
    back = ""
    if rtype.name != default_runner_type(catalog).name:
        minutes = max(1, round((rtype.idle_ttl_seconds or 600) / 60))
        back = (
            f" The chat goes back to {default_runner_type(catalog).display_name} "
            f"after the runner has been idle for {minutes} minutes."
        )
    return (
        f"Switched this chat to the {_runner_size_text(rtype)} tool runner. Skill "
        f"calls from now on run on it. {when} Calls already running finish on the "
        f"previous runner; files in the chat are shared by both.{back}"
    )


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} seconds ago"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} minutes ago"
    return f"{round(seconds / 3600, 1):g} hours ago"


async def get_tool_runner_info(
    __user__: dict = {},
    __metadata__: dict = None,
):
    """This chat's tool runner: size, limits, state, memory now, and the last skill's use."""
    from open_webui.utils.skill_k8s_sandbox import (
        default_runner_type,
        effective_runner_type,
        last_skill_usage,
        public_runner_state,
        runner_calls_running,
        runner_catalog,
        runner_metrics,
        runner_status,
        runner_types_for_org,
    )

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "A temporary chat has no tool runner. Save the chat first."
    access = await _chat_access(__user__.get("id"), chat_id)
    if not access.readable:
        return "You do not have access to this chat."

    catalog = await runner_catalog()
    current = effective_runner_type(chat_id, catalog)
    lines = [f"Tool runner size: {_runner_size_text(current)}."]
    try:
        state = public_runner_state((await runner_status(chat_id)).get("state"))
    except Exception:
        state = "unknown"
    lines.append(
        {
            "ready": "State: ready.",
            "starting": "State: starting; the next skill waits for it.",
            "degraded": "State: degraded; it is not answering or reports itself unhealthy.",
            "paused": "State: not running; the next skill starts one.",
        }.get(state, "State: unknown.")
    )
    if state == "ready":
        try:
            metrics = await runner_metrics(chat_id)
            used = metrics.get("memory_bytes")
            limit = metrics.get("memory_limit_bytes")
            if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit:
                lines.append(
                    f"Memory in use now: {used / 2**30:.1f} of {limit / 2**30:.0f} GiB "
                    f"({used / limit:.0%})."
                )
        except Exception:
            log.debug("runner metrics for get_tool_runner_info failed", exc_info=True)
    running = runner_calls_running(chat_id)
    if running:
        lines.append(f"Skills running now: {running}.")

    usage = last_skill_usage(chat_id)
    if usage:
        size = usage.get("rtype") or default_runner_type(catalog)
        run = usage.get("run_seconds") or 0
        cpu = usage.get("cpu_seconds") or 0
        text = (
            f"Most recent skill: `{usage.get('script')}` on the {size.display_name} "
            f"runner, finished {_ago(time.time() - usage.get('finished_at', time.time()))}. "
            f"Peak memory of its largest process: {usage.get('memory_mb', 0) / 1024:.1f} GiB. "
            f"CPU: {cpu:.0f} CPU-seconds over {run:.0f} seconds"
        )
        if run > 0:
            text += f" (about {cpu / run:.1f} cores on average)"
        lines.append(text + ".")
    else:
        lines.append("No skill has reported its resource use in this chat since the server started.")

    allowed = await runner_types_for_org(metadata.get("organization_id"))
    others = [t for t in allowed if t.name != current.name]
    if others:
        lines.append(
            "Other sizes this chat can use: "
            + "; ".join(
                _runner_size_text(t) + (" (needs the user's approval)" if t.requires_approval else "")
                for t in others
            )
            + ". Switch with request_tool_runner."
        )
    return "\n".join(lines)


GET_TOOL_RUNNER_INFO_SPEC = {
    "name": "get_tool_runner_info",
    "description": (
        "Show this chat's tool runner (where skills run): its size and CPU and "
        "memory limits, whether it is running, the memory it uses now, the "
        "peak memory and CPU of the most recent skill, and the other sizes "
        "this chat can switch to. Use it to judge whether work fits before "
        "starting it, or whether to switch sizes."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


REQUEST_TOOL_RUNNER_SPEC = {
    "name": "request_tool_runner",
    "description": (
        "Switch this chat's tool runner (where skills run) to another size. "
        "Use it when work needs more memory or CPU than the current runner, "
        "for example after a skill ran out of memory and the work cannot be "
        "split, and to switch back to a smaller size once heavy work is done. "
        "Call it by itself, before the skills that need the new size. Sizes "
        "that need approval ask the user first. The system prompt lists the "
        "sizes this chat can use."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "size": {
                "type": "string",
                "description": "The size to switch to, such as `medium` or `large`.",
            },
            "reason": {
                "type": "string",
                "description": (
                    "One sentence for the user on why this size is needed, "
                    "for example the region and period being processed."
                ),
            },
        },
        "required": ["size"],
    },
}


def _content_loader(request):
    from open_webui.retrieval.loaders.main import Loader

    config = request.app.state.config
    return Loader(
        engine=config.CONTENT_EXTRACTION_ENGINE,
        TIKA_SERVER_URL=config.TIKA_SERVER_URL,
        DOCLING_SERVER_URL=config.DOCLING_SERVER_URL,
        PDF_EXTRACT_IMAGES=config.PDF_EXTRACT_IMAGES,
        DOCUMENT_INTELLIGENCE_ENDPOINT=config.DOCUMENT_INTELLIGENCE_ENDPOINT,
        DOCUMENT_INTELLIGENCE_KEY=config.DOCUMENT_INTELLIGENCE_KEY,
        MISTRAL_OCR_API_KEY=config.MISTRAL_OCR_API_KEY,
    )


async def _insert_rag_for_file(
    request, user, file_item: dict, messages: list, model_id: Optional[str]
) -> str:
    from open_webui.utils.middleware import (
        chat_completion_files_handler,
        rag_context_string,
    )
    from open_webui.utils.misc import get_last_user_message
    from open_webui.utils.task import rag_template

    _, flags = await chat_completion_files_handler(
        request,
        {
            "model": model_id,
            "messages": messages or [],
            "metadata": {"files": [file_item]},
        },
        user,
    )
    context_string = rag_context_string(flags.get("sources") or [])
    if not context_string:
        return f"No extractable text in `{file_item.get('name')}`."
    prompt = get_last_user_message(messages or []) or ""
    template = getattr(request.app.state.config, "RAG_TEMPLATE", "")
    return rag_template(template, context_string, prompt)


async def _rag_from_artifact_file(
    request, user, rel: str, target: Path, messages: list, model_id: Optional[str]
) -> str:
    # Parsing the file and embedding it are slow and synchronous.
    file_item = await asyncio.to_thread(_artifact_file_item, request, user, rel, target)
    if isinstance(file_item, str):
        return file_item
    return await _insert_rag_for_file(request, user, file_item, messages, model_id)


def _artifact_file_item(request, user, rel: str, target: Path):
    """The parsed file as a RAG file item, or a message when it has no text."""
    from langchain_core.documents import Document

    from open_webui.routers.retrieval import save_docs_to_vector_db
    from open_webui.utils.misc import calculate_sha256_string

    mime, _ = mimetypes.guess_type(target.name)
    docs = _content_loader(request).load(target.name, mime, str(target))
    docs = [
        Document(
            page_content=doc.page_content,
            metadata={**(doc.metadata or {}), "name": rel, "source": rel},
        )
        for doc in docs
    ]
    text = " ".join(doc.page_content for doc in docs).strip()
    if not text:
        return f"No extractable text in `{rel}`."

    config = request.app.state.config
    if getattr(config, "BYPASS_EMBEDDING_AND_RETRIEVAL", False) or getattr(
        config, "RAG_FULL_CONTEXT", False
    ):
        file_item = {
            "type": "file",
            "name": rel,
            "context": "full",
            "file": {"data": {"content": text}},
        }
    else:
        digest = calculate_sha256_string(text)
        collection_name = f"sandbox-{digest[:16]}"
        try:
            save_docs_to_vector_db(
                request,
                docs=docs,
                collection_name=collection_name,
                metadata={"name": rel, "hash": digest},
                user=user,
            )
        except Exception:
            pass
        file_item = {
            "type": "file",
            "name": rel,
            "id": collection_name,
            "collection_name": collection_name,
        }
    return file_item


async def read_artifact(
    path: str,
    __user__: dict = {},
    __metadata__: dict = None,
    __event_call__=None,
    __request__=None,
    __messages__: list = None,
    __model__: dict = None,
):
    """Read a chat artifact from disk and send it to the model after approval."""
    from open_webui.utils.artifacts import classify_entry, resolve_in_sandbox

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot read artifacts in a temporary chat. Save the chat first."

    access = await _chat_access(__user__.get("id"), chat_id)
    user = access.user
    if not access.readable:
        return "You do not have access to this chat."

    rel = (path or "").strip().lstrip("/")
    if not rel:
        return "Provide a relative path to a file in the chat sandbox."

    # The file target, or why it cannot be read.
    def locate():
        try:
            target = resolve_in_sandbox(chat_id, rel)
        except Exception as e:
            return None, f"Invalid path: {e}"
        refresh_sandbox_lookup(target)
        if not target.exists():
            return None, f"Path not found: `{rel}`"
        kind = classify_entry(target)
        if kind == "zarr":
            return None, (
                f"`{rel}` is a Zarr store. Do not send it with read_artifact; "
                "use a skill to read or plot it."
            )
        if target.is_dir() or kind == "directory":
            return None, (
                f"`{rel}` is a folder. List it with list_artifacts, or pass a "
                "file path to read_artifact."
            )
        return target, None

    target, problem = await asyncio.to_thread(locate)
    if problem:
        return problem

    # The Read files switch: on reads without asking. Off asks the user in a
    # chat; a scheduled task has no one to ask, so off refuses.
    features = metadata.get("features") or {}
    if isinstance(features, dict) and features.get("read_artifacts"):
        allowed_note = f"Read files is on, so `{rel}` was read without asking."
    elif metadata.get("headless"):
        return (
            "Reading files is off for this scheduled task, so the file was not "
            "sent. Turn on Read files for the task to allow it."
        )
    else:
        denied = await _user_approved_artifact_read(rel, __event_call__)
        if denied:
            return denied
        allowed_note = f"The user approved reading `{rel}`."

    if DISPLAY_IMAGE_TYPES.get(target.suffix.lower()):
        shown = await asyncio.to_thread(
            display_image, path=rel, __user__=__user__, __metadata__=__metadata__
        )
        if isinstance(shown, list) and shown:
            shown = [
                (
                    f"{allowed_note} "
                    "The image is attached as a vision input after this tool result."
                ),
                *shown[1:],
            ]
        return shown

    if __request__ is None:
        return "Request context not available; the file was not sent."

    model_id = None
    if isinstance(__model__, dict):
        model_id = __model__.get("id")
    try:
        context = await _rag_from_artifact_file(
            __request__,
            user,
            rel,
            target,
            __messages__ or [],
            model_id,
        )
        return f"{allowed_note}\n\n{context}"
    except Exception as e:
        return f"Failed to read `{rel}`: {e}"


READ_ARTIFACT_SPEC = {
    "name": "read_artifact",
    "description": (
        "Read a file from the current chat artifact sandbox and send its "
        "contents to yourself. Files in the sandbox are not in your context "
        "until you call this. Unless Read files is turned on, the user must "
        "approve each read in a popup, and a scheduled task cannot read files. "
        "Images are sent as images; other files are indexed and matching "
        "text is inserted into context. Pass a relative path such as "
        "`photo.png` or `stations.csv`. Folders and Zarr stores cannot be "
        "read this way. "
        "This call waits for other tools in the same turn, so you do not "
        "need `depends_on` when a skill just wrote the file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to a file in the chat sandbox",
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


def _email_recipient_directory(user_id: str, _chat) -> dict:
    user = Users.get_user_by_id(user_id)
    self_info = None
    if user:
        email = (user.email or "").strip().lower()
        self_info = {
            "email": email if email and EMAIL_RE.match(email) else None,
            "name": (user.name or "").strip() or None,
        }

    org_ids = set(Organizations.user_organization_ids(user_id))

    organizations = []
    for org_id in sorted(org_ids):
        org = Organizations.get_organization_by_id(org_id)
        if not org or org.kind == ORG_KIND_PERSONAL:
            continue
        members = []
        for member in Organizations.get_members(org_id):
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
            organizations.append(
                {
                    "organization_id": org_id,
                    "organization_name": org.name,
                    "members": members,
                }
            )

    return {"self": self_info, "organizations": organizations}


def _allowed_email_recipients_for_user(user_id: str, chat) -> set[str]:
    directory = _email_recipient_directory(user_id, chat)
    allowed: set[str] = set()
    self_email = (directory.get("self") or {}).get("email")
    if self_email:
        allowed.add(self_email)
    for organization in directory.get("organizations") or []:
        for member in organization.get("members") or []:
            allowed.add(member["email"])
    return allowed


async def list_email_recipients(
    __user__: dict = {},
    __metadata__: dict = None,
    __request__=None,
) -> str:
    """Return the current user's email and organization member emails allowed for send_email."""
    metadata = __metadata__ or {}
    access = await _chat_access(__user__.get("id"), metadata.get("chat_id"))
    user, chat = access.user, access.chat
    if not user:
        return "User not found."
    directory = _email_recipient_directory(user.id, chat)

    lines: list[str] = []
    self_info = directory.get("self") or {}
    if self_info.get("email"):
        name = self_info.get("name") or "You"
        lines.append(f"Your email: `{self_info['email']}` ({name})")
    else:
        lines.append("Your account has no email address on file.")

    organizations = directory.get("organizations") or []
    member_lines: list[str] = []
    for organization in organizations:
        header = f"**{organization['organization_name']}**"
        org_members = []
        for member in organization.get("members") or []:
            if member.get("is_self"):
                continue
            label = member.get("name") or member["email"]
            role = member.get("role")
            role_suffix = f" ({role})" if role else ""
            org_members.append(f"- `{member['email']}` — {label}{role_suffix}")
        if org_members:
            member_lines.append(header)
            member_lines.extend(org_members)

    if member_lines:
        lines.append("")
        lines.append("Organization members (valid `send_email` recipients):")
        lines.extend(member_lines)
    else:
        lines.append("")
        lines.append("No organization member email addresses found.")

    lines.append("")
    lines.append(
        "Only your email and the emails of people in your organizations listed above may be used with `send_email`."
    )
    return "\n".join(lines)


LIST_EMAIL_RECIPIENTS_SPEC = {
    "name": "list_email_recipients",
    "description": (
        "List your email address and the email addresses of people in your organizations. "
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
    *,
    html: str | None = None,
    inline_images: list[tuple[str, bytes, str]] | None = None,
) -> tuple[bool, str]:
    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
        html_part = msg.get_payload()[-1]
        for cid, data, subtype in inline_images or []:
            content_id = cid if cid.startswith("<") else f"<{cid}>"
            html_part.add_related(
                data, maintype="image", subtype=subtype, cid=content_id
            )
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


def send_email(
    to: list[str] | str,
    subject: str,
    body: str,
    attachments: list[str] | str | None = None,
    __user__: dict = {},
    __metadata__: dict = None,
    __request__=None,
) -> str:
    """Send a restricted email (self and organization members only) via configured provider."""
    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if not chat_id or chat_id == "local":
        return "Cannot send email from a temporary chat. Save the chat first."
    if __request__ is None:
        return "Request context not available."

    access = _load_chat_access(__user__.get("id"), chat_id)
    user, chat = access.user, access.chat
    if not user:
        return "User not found."
    if not access.readable:
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
            f"members of your organizations: {', '.join(blocked)}"
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
    ok, detail = _send_via_smtp(
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
        "to the current user and members of the user's organizations. "
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
                    "Recipient email addresses. Must be your email or the email of someone in your organization."
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
    from open_webui.utils.access_control import user_owns_or_has_access
    from open_webui.utils.tools import accessible_skill_records

    metadata = __metadata__ or {}
    user = Users.get_user_by_id(__user__.get("id"))
    if not user:
        return "User not found."

    scope = (scope or "chat").strip().lower()
    if scope not in ("chat", "all"):
        scope = "chat"

    lines = []

    # The built-in tools this chat or run is offered.
    offered = get_builtin_tools({"__metadata__": metadata})
    lines.append("## Built-in tools")
    for name, description in (
        ("list_available_tools", "List tools/skills available in this chat, or all tools you can access."),
        ("create_scheduled_task", "Create a scheduled task from the current chat."),
        ("secrets_page", "Link to the secrets page with a secret name already filled in."),
        ("list_preferences", "Read saved preferences for this organization."),
        ("create_preference", "Save a preference after the user agrees. Ask them first."),
        ("copy_intermediate_result", "Copy a file/folder into or out of intermediate_results."),
        ("create_folder", "Create a folder in the chat artifact sandbox for organizing outputs."),
        ("list_artifacts", "List files/folders in the chat artifact sandbox."),
        ("read_artifact", "Ask the user for permission, then send a sandbox file to yourself."),
        ("get_tool_runner_info", "Show this chat's tool runner size, limits, memory now, and the last skill's peak use."),
        ("request_tool_runner", "Switch this chat's tool runner to a larger or smaller size."),
        ("list_email_recipients", "List your email and organization member emails allowed for send_email."),
        ("send_email", "Email results to yourself or people in your organizations; optional artifact sandbox attachments."),
        ("display_image", "Show a sandbox image inline, or link it with a relative markdown path. Do not do both."),
        ("execute_code", "Run Python in Pyodide. Can copy artifact files into /mnt and back out."),
    ):
        if name in offered:
            lines.append(_tool_summary_line(name, description, kind="builtin"))

    selected_ids = list(metadata.get("tool_ids") or [])
    catalog = Tools.get_tool_catalog()
    org_id = metadata.get("organization_id")
    skill_records = accessible_skill_records(
        user, organization_id=org_id, catalog=catalog
    )
    usable_skill_ids = {record["id"] for record in skill_records}
    all_tools = catalog

    def _visible(tool) -> bool:
        manifest = (tool.meta.manifest if tool.meta else None) or {}
        if manifest.get("kind") == "skill":
            return tool.id in usable_skill_ids
        return user_owns_or_has_access(
            user.id, tool.user_id, tool.access_control, "read", user.role
        )

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


def _check_code_artifacts(chat_id, input_paths, output_paths):
    """Normalized input and output paths, or why the inputs cannot be copied."""
    from open_webui.utils.artifacts import (
        EXECUTE_CODE_MAX_ARCHIVE_BYTES,
        normalize_sandbox_relpath,
        resolve_in_sandbox,
        sandbox_tree_size,
    )

    try:
        input_paths = [normalize_sandbox_relpath(p) for p in input_paths]
        output_paths = [normalize_sandbox_relpath(p) for p in output_paths]
        total = 0
        for rel in input_paths:
            target = resolve_in_sandbox(chat_id, rel)
            if not target.exists():
                return input_paths, output_paths, f"Artifact not found: {rel}"
            total += sandbox_tree_size(target)
            if total > EXECUTE_CODE_MAX_ARCHIVE_BYTES:
                return (
                    input_paths,
                    output_paths,
                    f"Input files exceed the {EXECUTE_CODE_MAX_ARCHIVE_BYTES} byte limit",
                )
    except ValueError as e:
        return input_paths, output_paths, str(e)
    return input_paths, output_paths, None


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
        access = await _chat_access((__user__ or {}).get("id"), chat_id)
        if output_paths:
            if not access.writable:
                return json.dumps(
                    {"error": "You do not have write access to this chat."}
                )
        elif not access.readable:
            return json.dumps({"error": "You do not have access to this chat."})

        # Sizing the inputs walks every file on JuiceFS.
        input_paths, output_paths, problem = await asyncio.to_thread(
            _check_code_artifacts, chat_id, input_paths, output_paths
        )
        if problem:
            return json.dumps({"error": problem})

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

        stdout = await asyncio.to_thread(_rewrite_png_data_uris, output.get("stdout") or "")
        result = await asyncio.to_thread(_rewrite_png_data_uris, output.get("result") or "")
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


def _request_config(request):
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    return getattr(state, "config", None)


def web_search_tool_description(request) -> str:
    from open_webui.config import DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION

    config = _request_config(request)
    configured = ""
    if config is not None:
        configured = getattr(config, "WEB_SEARCH_TOOL_DESCRIPTION", "") or ""
    configured = str(configured).strip()
    return configured or DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION


def web_search_tool_spec(description: str) -> dict:
    return {
        "name": "web_search",
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Specific search queries. Each query returns up to the "
                        "configured number of pages."
                    ),
                }
            },
            "required": ["queries"],
        },
    }


def _as_query_list(queries) -> list[str]:
    if isinstance(queries, str):
        text = queries.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                queries = parsed
            else:
                queries = [text]
        else:
            queries = [text] if text else []
    if not isinstance(queries, (list, tuple)):
        raise ValueError("queries must be a list of strings")
    out = []
    for item in queries:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _config_positive_int(config, name: str, default: int) -> int:
    try:
        value = int(getattr(config, name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _clip_page_content(content: str) -> tuple[str, bool]:
    if len(content) <= WEB_SEARCH_PAGE_CHAR_LIMIT:
        return content, False
    return content[:WEB_SEARCH_PAGE_CHAR_LIMIT], True


async def web_search(
    queries,
    __request__=None,
    __event_emitter__=None,
    **_ignored,
) -> str:
    """Search the web for each query and return the relevant pages."""
    if __request__ is None:
        return json.dumps({"error": "Request context not available"})

    try:
        query_list = _as_query_list(queries)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    if not query_list:
        return json.dumps({"error": "Provide at least one search query."})

    config = _request_config(__request__)
    engine = getattr(config, "WEB_SEARCH_ENGINE", "") if config is not None else ""
    if not engine:
        return json.dumps({"error": "Web search engine is not configured."})

    from starlette.concurrency import run_in_threadpool

    from open_webui.retrieval.web.utils import get_web_loader
    from open_webui.routers.retrieval import search_web

    async def emit(data: dict):
        if __event_emitter__ is None:
            return
        await __event_emitter__({"type": "status", "data": data})

    result_count = _config_positive_int(config, "WEB_SEARCH_RESULT_COUNT", 3)
    concurrency = _config_positive_int(config, "WEB_SEARCH_CONCURRENT_REQUESTS", 10)
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(query: str) -> dict:
        async with semaphore:
            await asyncio.sleep(0)
            await emit(
                {
                    "action": "web_search",
                    "description": 'Searching "{{searchQuery}}"',
                    "query": query,
                    "done": False,
                }
            )
            try:
                web_results = await run_in_threadpool(
                    search_web, __request__, engine, query
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("web_search failed for %s", query)
                return {"query": query, "error": str(e), "pages": []}

            hits = [result for result in web_results if result.link][:result_count]
            by_link = {result.link: result for result in hits}
            page_urls = list(by_link)
            pages = []
            if page_urls:
                try:
                    loader = get_web_loader(
                        page_urls,
                        verify_ssl=getattr(
                            config, "ENABLE_WEB_LOADER_SSL_VERIFICATION", True
                        ),
                        requests_per_second=concurrency,
                        trust_env=getattr(config, "WEB_SEARCH_TRUST_ENV", False),
                    )
                    docs = await loader.aload()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.exception("web_search page load failed for %s", query)
                    return {
                        "query": query,
                        "error": str(e),
                        "pages": [
                            {
                                "title": result.title or "",
                                "url": result.link,
                                "snippet": result.snippet or "",
                                "content": "",
                            }
                            for result in hits
                        ],
                    }

                for doc in docs:
                    if len(pages) >= result_count:
                        break
                    metadata = doc.metadata or {}
                    url = metadata.get("source") or ""
                    hit = by_link.get(url)
                    content, truncated = _clip_page_content(doc.page_content or "")
                    page = {
                        "title": metadata.get("title")
                        or (hit.title if hit else "")
                        or "",
                        "url": url,
                        "snippet": (hit.snippet if hit else "") or "",
                        "content": content,
                    }
                    if truncated:
                        page["truncated"] = True
                    pages.append(page)

            return {"query": query, "pages": pages}

    try:
        results = list(await asyncio.gather(*(run_one(query) for query in query_list)))
    except asyncio.CancelledError:
        await emit(
            {
                "action": "web_search",
                "description": "Cancelled",
                "done": True,
            }
        )
        raise

    urls = [
        page["url"]
        for result in results
        for page in result.get("pages") or []
        if page.get("url")
    ]
    if urls:
        await emit(
            {
                "action": "web_search",
                "description": "Searched {{count}} sites",
                "urls": urls,
                "done": True,
            }
        )
    else:
        await emit(
            {
                "action": "web_search",
                "description": "No search results found",
                "done": True,
                "error": True,
            }
        )

    return json.dumps({"results": results}, ensure_ascii=False)


# Built-in tools a chat or scheduled task can turn off, by feature name. Each
# group is on unless its feature is false, so older chats and tasks keep it.
BUILTIN_TOOL_GROUPS = {
    "email": ("list_email_recipients", "send_email"),
    "scheduled_tasks": (
        "create_scheduled_task",
        "list_scheduled_tasks",
        "update_scheduled_task",
        "delete_scheduled_task",
    ),
    "preferences": ("list_preferences", "create_preference"),
}


def _turned_off_builtins(metadata: dict) -> set[str]:
    features = metadata.get("features") or {}
    if not isinstance(features, dict):
        return set()
    return {
        name
        for group, names in BUILTIN_TOOL_GROUPS.items()
        if features.get(group) is False
        for name in names
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
        "secrets_page": _tool(secrets_page, SECRETS_PAGE_SPEC),
        "list_preferences": _tool(list_preferences, LIST_PREFERENCES_SPEC),
        "create_preference": _tool(create_preference, CREATE_PREFERENCE_SPEC),
        "copy_intermediate_result": _tool(
            copy_intermediate_result, COPY_INTERMEDIATE_RESULT_SPEC
        ),
        "create_folder": _tool(create_folder, CREATE_FOLDER_SPEC),
        "list_artifacts": _tool(list_artifacts, LIST_ARTIFACTS_SPEC),
        "read_artifact": _tool(read_artifact, READ_ARTIFACT_SPEC),
        "display_image": _tool(display_image, DISPLAY_IMAGE_SPEC),
        "list_email_recipients": _tool(
            list_email_recipients, LIST_EMAIL_RECIPIENTS_SPEC
        ),
        "send_email": _tool(send_email, SEND_EMAIL_SPEC),
    }
    metadata = extra_params.get("__metadata__") or {}
    # A scheduled run has no one present to ask, so it cannot change scheduled
    # tasks. It reports its own result instead.
    if metadata.get("headless"):
        tools["report_task_result"] = _tool(report_task_result, REPORT_TASK_RESULT_SPEC)
    else:
        tools.update(
            {
                "create_scheduled_task": _tool(
                    create_scheduled_task, CREATE_SCHEDULED_TASK_SPEC
                ),
                "list_scheduled_tasks": _tool(
                    list_scheduled_tasks, LIST_SCHEDULED_TASKS_SPEC
                ),
                "update_scheduled_task": _tool(
                    update_scheduled_task, UPDATE_SCHEDULED_TASK_SPEC
                ),
                "delete_scheduled_task": _tool(
                    delete_scheduled_task, DELETE_SCHEDULED_TASK_SPEC
                ),
            }
        )
    from open_webui.env import tool_runner_enabled

    chat_id = metadata.get("chat_id")
    if tool_runner_enabled() and chat_id and chat_id != "local":
        tools["request_tool_runner"] = _tool(request_tool_runner, REQUEST_TOOL_RUNNER_SPEC)
        tools["get_tool_runner_info"] = _tool(get_tool_runner_info, GET_TOOL_RUNNER_INFO_SPEC)
    for name in _turned_off_builtins(metadata):
        tools.pop(name, None)
    features = metadata.get("features") or {}
    if isinstance(features, dict) and features.get("code_interpreter"):
        tools["execute_code"] = _tool(execute_code, EXECUTE_CODE_SPEC)
    if isinstance(features, dict) and features.get("web_search"):
        request = extra_params.get("__request__")
        config = _request_config(request)
        admin_enabled = (
            True
            if config is None
            else bool(getattr(config, "ENABLE_WEB_SEARCH", False))
        )
        if admin_enabled:
            tools["web_search"] = _tool(
                web_search,
                web_search_tool_spec(web_search_tool_description(request)),
            )
    return tools
