import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from open_webui.env import BYPASS_MODEL_ACCESS_CONTROL, SRC_LOG_LEVELS
from open_webui.models.automations import AutomationRuns, Automations
from open_webui.models.chats import ChatForm, Chats
from open_webui.models.users import Users
from open_webui.tasks import create_task, get_task
from open_webui.utils.chat import generate_chat_completion as chat_completion_handler
from open_webui.utils.middleware import process_chat_payload, process_chat_response
from open_webui.utils.models import check_model_access, get_all_models

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


def _new_message(role: str, content: str, model: Optional[str] = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "parentId": None,
        "childrenIds": [],
        "role": role,
        "content": content,
        "timestamp": int(time.time()),
        **({"model": model} if role == "assistant" else {}),
    }


async def _notify_chat_created(user_ids: list[str], chat_id: str, title: str) -> None:
    """Tell connected clients to refresh their chat list (automation-created chats)."""
    try:
        from open_webui.socket.main import USER_POOL, sio

        payload = {
            "chat_id": chat_id,
            "message_id": None,
            "data": {
                "type": "chat:list",
                "data": {"id": chat_id, "title": title},
            },
        }
        seen = set()
        for user_id in user_ids:
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            for sid in list(USER_POOL.get(user_id, []) or []):
                await sio.emit("chat-events", payload, to=sid)
    except Exception:
        log.exception("Failed to notify clients of new automation chat")


def _accessible_tool_ids(user) -> list[str]:
    """Tool/skill IDs the user can read (chat default / automation fallback).

    Skills with manifest.enabled=false are omitted from defaults; chat can still
    send those IDs explicitly.
    """
    from open_webui.models.tools import Tools
    from open_webui.utils.access_control import user_owns_or_has_access

    ids: list[str] = []
    for tool in Tools.get_tools():
        if not user_owns_or_has_access(
            user.id, tool.user_id, tool.access_control, "read", user.role
        ):
            continue
        manifest = (tool.meta.manifest if tool.meta else None) or {}
        if manifest.get("kind") == "skill" and manifest.get("enabled") is False:
            continue
        ids.append(tool.id)
    return ids


def _resolve_tool_ids(automation, model: Optional[dict], user=None) -> Optional[list[str]]:
    if automation.tool_ids is not None:
        return list(automation.tool_ids)
    # Default: every tool/skill the owner can access (skill versions resolved later).
    if user is not None:
        ids = _accessible_tool_ids(user)
        return ids or None
    # Legacy: fall back to the model's stored tool list if present.
    if model:
        tool_ids = (model.get("info") or {}).get("meta", {}).get("toolIds")
        if isinstance(tool_ids, list) and tool_ids:
            return [str(t) for t in tool_ids if t]
    return None


async def _stream_automation_chat(
    request,
    *,
    run_id: str,
    chat_id: str,
    assistant_id: str,
    user,
    model: dict,
    model_id: str,
    prompt: str,
    tool_ids: Optional[list[str]],
    features: dict,
) -> None:
    """Run the chat middleware + streaming tool loop for an automation chat."""
    form_data = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "tool_ids": tool_ids,
        "features": features,
        "params": {"function_calling": "native"},
        "chat_id": chat_id,
        "id": assistant_id,
        # Fake session so process_chat_response takes the streaming path;
        # events still fan out to the user's real socket sessions via USER_POOL.
        "session_id": f"automation:{run_id}",
    }

    metadata = {
        "user_id": user.id,
        "chat_id": form_data.pop("chat_id", None),
        "message_id": form_data.pop("id", None),
        "session_id": form_data.pop("session_id", None),
        "tool_ids": form_data.get("tool_ids", None),
        "tool_servers": None,
        "files": None,
        "features": form_data.get("features", None),
        "variables": None,
        "model": model,
        "direct": False,
        "function_calling": "native",
        "headless": True,
    }
    request.state.metadata = metadata
    form_data["metadata"] = metadata

    form_data, metadata, events = await process_chat_payload(
        request, form_data, user, metadata, model
    )

    response = await chat_completion_handler(request, form_data, user)
    result = await process_chat_response(
        request, response, form_data, user, metadata, model, events, None
    )

    # Streaming path schedules the tool loop as a background task — wait for it.
    if isinstance(result, dict) and result.get("task_id"):
        task = get_task(result["task_id"])
        if task is not None:
            await task

    Chats.upsert_message_to_chat_by_id_and_message_id(
        chat_id,
        assistant_id,
        {"done": True},
    )


async def execute_automation(
    request, automation_id: str, triggered_by: str, *, wait: bool = True
):
    """Create an automation chat and run it like /api/chat/completions (streaming).

    When wait=False (manual "Run now"), returns immediately with chat_id so the
    client can open the chat and receive live socket stream events.
    """
    automation = Automations.get_automation_by_id(automation_id)
    if not automation:
        raise ValueError("Automation not found")

    owner_id = automation.user_id
    if triggered_by and triggered_by != "schedule":
        owner_id = triggered_by

    user = Users.get_user_by_id(owner_id)
    if not user:
        raise ValueError("Automation owner not found")

    if not request.app.state.MODELS:
        await get_all_models(request, user=user)

    model_id = automation.model
    if not model_id or model_id not in request.app.state.MODELS:
        raise ValueError(f"Model not found: {model_id}")

    model = request.app.state.MODELS[model_id]

    if not BYPASS_MODEL_ACCESS_CONTROL and user.role == "user":
        check_model_access(user, model)

    run = AutomationRuns.insert_run(
        automation.id, status="running", triggered_by=triggered_by
    )
    title = f"{automation.name} — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    user_message = _new_message("user", automation.prompt)
    assistant = _new_message("assistant", "", automation.model)
    assistant["parentId"] = user_message["id"]
    user_message["childrenIds"] = [assistant["id"]]
    history = {
        "messages": {
            user_message["id"]: user_message,
            assistant["id"]: assistant,
        },
        "currentId": assistant["id"],
    }
    chat_blob = {
        "title": title,
        "models": [automation.model] if automation.model else [],
        "history": history,
        "messages": [user_message, assistant],
    }

    try:
        chat = Chats.insert_new_chat(
            owner_id,
            ChatForm(chat=chat_blob, team_id=automation.team_id),
        )
        if not chat:
            raise ValueError("Failed to create chat")
        run = AutomationRuns.update_run(run.id, chat_id=chat.id)

        notify_ids = [owner_id]
        if automation.team_id:
            try:
                from open_webui.models.teams import Teams

                notify_ids.extend(
                    m.user_id for m in (Teams.get_members(automation.team_id) or [])
                )
            except Exception:
                log.exception("Failed to resolve team members for chat notify")
        await _notify_chat_created(notify_ids, chat.id, title)

        tool_ids = _resolve_tool_ids(automation, model, user)
        features = automation.features if isinstance(automation.features, dict) else {}

        async def _complete():
            try:
                await _stream_automation_chat(
                    request,
                    run_id=run.id,
                    chat_id=chat.id,
                    assistant_id=assistant["id"],
                    user=user,
                    model=model,
                    model_id=model_id,
                    prompt=automation.prompt,
                    tool_ids=tool_ids,
                    features=features,
                )
                AutomationRuns.update_run(run.id, status="success", finished=True)
            except Exception as e:
                log.exception("Automation run failed")
                AutomationRuns.update_run(
                    run.id, status="error", error=str(e), finished=True
                )
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    chat.id,
                    assistant["id"],
                    {
                        "done": True,
                        "error": {"content": str(e)},
                    },
                )
                if wait:
                    raise

        if wait:
            await _complete()
            return AutomationRuns.get_run_by_id(run.id)

        create_task(_complete(), id=chat.id)
        return run
    except Exception as e:
        log.exception("Automation run failed")
        AutomationRuns.update_run(run.id, status="error", error=str(e), finished=True)
        raise
