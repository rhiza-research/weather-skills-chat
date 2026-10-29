import logging
from typing import Optional

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.automations import (
    AutomationForm,
    AutomationModel,
    AutomationRunModel,
    AutomationRuns,
    Automations,
    AutomationUpdateForm,
    AutomationUserStates,
)
from open_webui.models.chats import Chats
from open_webui.utils.auth import get_verified_user
from open_webui.utils.automation_runner import execute_automation
from open_webui.utils.automation_scheduler import (
    remove_automation_job,
    sync_automation_job,
)
from open_webui.utils.schedule import parse_schedule
from open_webui.utils.task_image import TASK_IMAGE_MIME
from open_webui.utils.organizations import (
    can_manage_automation,
    can_view_automation,
    get_active_organization_id,
    is_member,
    is_personal_org,
    resolve_visibility,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


MAX_TIMEOUT_MINUTES = 24 * 60


def _check_timeout(minutes: Optional[int]) -> None:
    if minutes is not None and not 1 <= minutes <= MAX_TIMEOUT_MINUTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The time limit must be between 1 minute and 24 hours.",
        )


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


class AutomationListItem(AutomationModel):
    last_run: Optional[AutomationRunModel] = None
    # The viewer's own: shown in their sidebar, and the last run they opened.
    pinned: bool = True
    seen_run_id: Optional[str] = None


class PinForm(BaseModel):
    pinned: bool


class SeenForm(BaseModel):
    run_id: str


@router.get("/", response_model=list[AutomationListItem])
def list_automations(
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    automations = Automations.get_automations_for_user(user.id, organization_id)
    ids = [a.id for a in automations]
    last_runs = AutomationRuns.get_latest_runs(ids)
    states = AutomationUserStates.get_states(user.id, ids)
    items = []
    for automation in automations:
        state = states.get(automation.id)
        items.append(
            AutomationListItem(
                **automation.model_dump(),
                last_run=last_runs.get(automation.id),
                pinned=state.pinned if state else True,
                seen_run_id=state.seen_run_id if state else None,
            )
        )
    return items


def _viewable(id: str, user) -> None:
    if not can_view_automation(user, Automations.get_automation_by_id(id)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )


@router.get("/{id}/image")
def get_task_image(id: str, user=Depends(get_verified_user)):
    _viewable(id, user)
    data = Automations.get_image(id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    # Pages ask with ?v=<image_updated_at>, so a new picture is a new URL.
    return Response(
        content=data,
        media_type=TASK_IMAGE_MIME,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.delete("/{id}/image", response_model=bool)
def delete_task_image(id: str, user=Depends(get_verified_user)):
    if not can_manage_automation(user, Automations.get_automation_by_id(id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    Automations.set_image(id, None)
    return True


@router.post("/{id}/pin", response_model=bool)
def set_pinned(id: str, form_data: PinForm, user=Depends(get_verified_user)):
    _viewable(id, user)
    AutomationUserStates.set_state(user.id, id, pinned=form_data.pinned)
    return True


@router.post("/{id}/seen", response_model=bool)
def mark_seen(id: str, form_data: SeenForm, user=Depends(get_verified_user)):
    _viewable(id, user)
    AutomationUserStates.set_state(user.id, id, seen_run_id=form_data.run_id)
    return True


@router.post("/", response_model=AutomationModel)
async def create_automation(
    form_data: AutomationForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    form_data.cron = _normalize_form_cron(form_data.cron)
    _check_timeout(form_data.timeout_minutes)
    form_data.organization_id = form_data.organization_id or organization_id
    if not is_member(form_data.organization_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    form_data.visibility = resolve_visibility(
        form_data.organization_id, form_data.visibility
    )
    if form_data.visibility == "organization" and is_personal_org(
        form_data.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot share automations in the personal organization",
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
    _check_timeout(form_data.timeout_minutes)
    if form_data.organization_id and not is_member(form_data.organization_id, user.id):
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
    except HTTPException:
        raise
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
