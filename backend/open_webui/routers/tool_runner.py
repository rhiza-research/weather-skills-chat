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
    chat = Chats.get_chat_by_id(chat_id)
    if not can_read_chat(user, chat):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return chat


@router.get("/{id}/tool-runner")
async def get_tool_runner(id: str, user=Depends(get_verified_user)):
    if not tool_runner_enabled():
        return {"enabled": False, "state": "off"}
    _readable(id, user)
    from open_webui.utils.chat_realtime import schedule_runner_metrics
    from open_webui.utils.skill_k8s_sandbox import runner_status, start_runner

    try:
        start_runner(id)
        schedule_runner_metrics(id)
        status_body = await runner_status(id)
        status_body["enabled"] = True
        return status_body
    except Exception as exc:
        log.info("tool runner start failed for %s: %s", id, exc)
        return {"enabled": True, "state": "starting", "error": str(exc)}
