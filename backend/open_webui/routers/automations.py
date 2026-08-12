import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.automations import (
    AutomationForm,
    AutomationModel,
    AutomationRunModel,
    AutomationRuns,
    Automations,
    AutomationUpdateForm,
)
from open_webui.models.chats import Chats
from open_webui.utils.auth import get_verified_user
from open_webui.utils.automation_runner import execute_automation
from open_webui.utils.automation_scheduler import (
    remove_automation_job,
    sync_automation_job,
)
from open_webui.utils.schedule import parse_schedule
from open_webui.utils.teams import (
    can_manage_automation,
    can_view_automation,
    is_team_member,
    user_team_ids,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


def _normalize_form_cron(cron: Optional[str]) -> Optional[str]:
    if cron is None or cron == "":
        return None
    parsed = parse_schedule(cron)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid schedule. Use cron or a phrase like 'every day at noon'.",
        )
    return parsed


@router.get("/", response_model=list[AutomationModel])
async def list_automations(user=Depends(get_verified_user)):
    return Automations.get_automations_for_user(user.id, user_team_ids(user.id))


@router.post("/", response_model=AutomationModel)
async def create_automation(form_data: AutomationForm, user=Depends(get_verified_user)):
    form_data.cron = _normalize_form_cron(form_data.cron)
    if form_data.team_id and not is_team_member(form_data.team_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    automation = Automations.insert_new_automation(user.id, form_data)
    if not automation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating automation"),
        )
    sync_automation_job(automation)
    return automation


@router.get("/{id}", response_model=AutomationModel)
async def get_automation(id: str, user=Depends(get_verified_user)):
    automation = Automations.get_automation_by_id(id)
    if not can_view_automation(user, automation):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return automation


@router.post("/{id}/update", response_model=AutomationModel)
async def update_automation(
    id: str, form_data: AutomationUpdateForm, user=Depends(get_verified_user)
):
    automation = Automations.get_automation_by_id(id)
    if not can_manage_automation(user, automation):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if form_data.cron is not None:
        form_data.cron = _normalize_form_cron(form_data.cron)
    if form_data.team_id and not is_team_member(form_data.team_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    automation = Automations.update_automation(id, form_data)
    if automation:
        sync_automation_job(automation)
    return automation


@router.delete("/{id}", response_model=bool)
async def delete_automation(id: str, user=Depends(get_verified_user)):
    automation = Automations.get_automation_by_id(id)
    if not can_manage_automation(user, automation):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    remove_automation_job(id)
    return Automations.delete_automation(id)


@router.post("/{id}/run", response_model=AutomationRunModel)
async def run_automation(request: Request, id: str, user=Depends(get_verified_user)):
    automation = Automations.get_automation_by_id(id)
    if not can_view_automation(user, automation):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    try:
        # Return as soon as the chat exists so the UI can open it and
        # receive live streaming socket events (same as a normal chat).
        return await execute_automation(request, id, user.id, wait=False)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


@router.get("/{id}/runs", response_model=list[AutomationRunModel])
async def list_runs(id: str, user=Depends(get_verified_user)):
    automation = Automations.get_automation_by_id(id)
    if not can_view_automation(user, automation):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    runs = AutomationRuns.get_runs(id)
    for run in runs:
        if run.chat_id:
            chat = Chats.get_chat_by_id(run.chat_id)
            if chat:
                run.chat_title = chat.title
    return runs
