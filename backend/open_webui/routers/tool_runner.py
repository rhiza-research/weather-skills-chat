import logging

from fastapi import APIRouter, Depends, HTTPException, status

from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS, tool_runner_enabled
from open_webui.models.chats import Chats
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import can_read_chat

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


def _readable(chat_id: str, user):
    # Owner, organization and visibility only; the full chat can be megabytes.
    chat = Chats.get_chat_access_row(chat_id)
    if not can_read_chat(user, chat):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return chat


def _status_body(status_body: dict, *, started: bool = False) -> dict:
    from open_webui.utils.skill_k8s_sandbox import public_runner_state

    state = public_runner_state(status_body.get("state"))
    if started and state == "paused":
        state = "starting"
    body = {**status_body, "enabled": True, "state": state}
    return body


@router.get("/{id}/tool-runner")
async def get_tool_runner(id: str, user=Depends(get_verified_user)):
    if not tool_runner_enabled():
        return {"enabled": False, "state": "off"}
    _readable(id, user)
    from open_webui.utils.chat_realtime import schedule_runner_metrics
    from open_webui.utils.skill_k8s_sandbox import runner_status

    try:
        schedule_runner_metrics(id)
        return _status_body(await runner_status(id))
    except Exception as exc:
        log.info("tool runner status failed for %s: %s", id, exc)
        return {"enabled": True, "state": "paused", "error": str(exc)}


@router.post("/{id}/tool-runner")
async def start_tool_runner(id: str, user=Depends(get_verified_user)):
    if not tool_runner_enabled():
        return {"enabled": False, "state": "off"}
    _readable(id, user)
    from open_webui.utils.chat_realtime import emit_chat_runner, schedule_runner_metrics
    from open_webui.utils.skill_k8s_sandbox import runner_status, start_runner

    try:
        start_runner(id)
        schedule_runner_metrics(id)
        body = _status_body(await runner_status(id), started=True)
        await emit_chat_runner(id, {"state": body["state"], "metrics": None})
        return body
    except Exception as exc:
        log.info("tool runner start failed for %s: %s", id, exc)
        return {"enabled": True, "state": "starting", "error": str(exc)}
