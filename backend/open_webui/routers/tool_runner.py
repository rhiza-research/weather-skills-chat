import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from open_webui.env import SRC_LOG_LEVELS, tool_runner_enabled
from open_webui.utils.auth import get_verified_user
from open_webui.utils.organizations import require_chat_read, require_chat_write

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


def _status_body(status_body: dict, *, started: bool = False) -> dict:
    from open_webui.utils.skill_k8s_sandbox import public_runner_state

    from open_webui.utils.skill_k8s_sandbox import runner_size_public

    state = public_runner_state(status_body.get("state"))
    if started and state == "paused":
        state = "starting"
    body = {
        **status_body,
        "enabled": True,
        "state": state,
        "size": runner_size_public(status_body.get("chat_id")),
    }
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
        await _warm_catalog()
        return _status_body({**await runner_status(id), "chat_id": id})
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
        await _warm_catalog()
        body = _status_body({**await runner_status(id), "chat_id": id}, started=True)
        await emit_chat_runner(
            id, {"state": body["state"], "metrics": None, "size": body["size"]}
        )
        return body
    except Exception as exc:
        log.info("tool runner start failed for %s: %s", id, exc)
        return {"enabled": True, "state": "starting", "error": str(exc)}


async def _warm_catalog() -> None:
    from open_webui.utils.skill_k8s_sandbox import runner_catalog

    try:
        await runner_catalog()
    except Exception:
        log.debug("runner sizes unavailable", exc_info=True)


@router.get("/{id}/tool-runner/sizes")
async def get_tool_runner_sizes(id: str, user=Depends(get_verified_user)):
    """The sizes this chat can switch to, and the one it is on."""
    if not tool_runner_enabled():
        return {"enabled": False, "sizes": [], "current": None}
    chat = await asyncio.to_thread(require_chat_read, id, user)
    from open_webui.utils.skill_k8s_sandbox import (
        default_runner_type,
        effective_runner_type,
        runner_catalog,
        runner_types_for_org,
    )

    catalog = await runner_catalog()
    allowed = await runner_types_for_org(chat.organization_id)
    return {
        "enabled": True,
        "sizes": [t.public() for t in allowed],
        "current": effective_runner_type(id, catalog).type,
        "default": default_runner_type(catalog).type,
    }


class RunnerSizeForm(BaseModel):
    size: str


@router.post("/{id}/tool-runner/size")
async def set_tool_runner_size(
    id: str, form_data: RunnerSizeForm, user=Depends(get_verified_user)
):
    """Switch the chat to a size. The user choosing it is the approval."""
    if not tool_runner_enabled():
        return {"enabled": False, "state": "off"}
    chat = await asyncio.to_thread(require_chat_write, id, user)
    from open_webui.utils.chat_realtime import emit_chat_runner, schedule_runner_metrics
    from open_webui.utils.runner_types import find
    from open_webui.utils.skill_k8s_sandbox import (
        runner_catalog,
        runner_status,
        runner_types_for_org,
        start_runner,
        switch_runner_type,
    )

    catalog = await runner_catalog()
    rtype = find(await runner_types_for_org(chat.organization_id), form_data.size)
    if rtype is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This chat cannot use that tool runner size.",
        )
    switch_runner_type(id, rtype, catalog)
    try:
        start_runner(id)
        schedule_runner_metrics(id)
        body = _status_body({**await runner_status(id), "chat_id": id}, started=True)
        await emit_chat_runner(
            id, {"state": body["state"], "metrics": None, "size": body["size"]}
        )
        return body
    except Exception as exc:
        log.info("tool runner size switch failed for %s: %s", id, exc)
        return {"enabled": True, "state": "starting", "size": rtype.public(), "error": str(exc)}
