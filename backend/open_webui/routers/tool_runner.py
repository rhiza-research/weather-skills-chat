import asyncio
import logging

from fastapi import APIRouter, Depends

from open_webui.env import SRC_LOG_LEVELS, tool_runner_enabled
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import require_chat_read

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


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
    await asyncio.to_thread(require_chat_read, id, user)
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
    await asyncio.to_thread(require_chat_read, id, user)
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
