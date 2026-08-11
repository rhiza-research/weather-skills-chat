import logging
from fastapi import APIRouter, Depends, HTTPException, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.teams import (
    TeamForm,
    TeamMemberAddForm,
    TeamMemberRoleForm,
    TeamModel,
    Teams,
    TeamUpdateForm,
)
from open_webui.models.users import Users
from open_webui.utils.auth import get_verified_user
from open_webui.utils.teams import is_team_admin, is_team_member

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


def _team_with_members(team: TeamModel, user_id: str) -> TeamModel:
    team.members = Teams.get_members(team.id)
    member = Teams.get_member(team.id, user_id)
    team.role = member.role if member else None
    return team


@router.get("/", response_model=list[TeamModel])
async def get_teams(user=Depends(get_verified_user)):
    if user.role == "admin":
        teams = Teams.get_all_teams()
        for team in teams:
            member = Teams.get_member(team.id, user.id)
            team.role = member.role if member else "admin"
        return teams
    return Teams.get_teams_by_user_id(user.id)


@router.post("/", response_model=TeamModel)
async def create_team(form_data: TeamForm, user=Depends(get_verified_user)):
    try:
        team = Teams.insert_new_team(user.id, form_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating team"),
        )
    return _team_with_members(team, user.id)


@router.get("/{id}", response_model=TeamModel)
async def get_team(id: str, user=Depends(get_verified_user)):
    team = Teams.get_team_by_id(id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if user.role != "admin" and not is_team_member(id, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return _team_with_members(team, user.id)


@router.post("/{id}/update", response_model=TeamModel)
async def update_team(
    id: str, form_data: TeamUpdateForm, user=Depends(get_verified_user)
):
    team = Teams.get_team_by_id(id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if not is_team_admin(id, user.id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    try:
        team = Teams.update_team(id, form_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error updating team"),
        )
    return _team_with_members(team, user.id)


@router.post("/{id}/members", response_model=TeamModel)
async def add_team_member(
    id: str, form_data: TeamMemberAddForm, user=Depends(get_verified_user)
):
    team = Teams.get_team_by_id(id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if not is_team_admin(id, user.id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if not Users.get_user_by_id(form_data.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.USER_NOT_FOUND
        )
    try:
        Teams.add_member(id, form_data.user_id, form_data.role)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _team_with_members(Teams.get_team_by_id(id), user.id)


@router.post("/{id}/members/{user_id}", response_model=TeamModel)
async def update_team_member_role(
    id: str,
    user_id: str,
    form_data: TeamMemberRoleForm,
    user=Depends(get_verified_user),
):
    if not is_team_admin(id, user.id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    try:
        member = Teams.update_member_role(id, user_id, form_data.role)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return _team_with_members(Teams.get_team_by_id(id), user.id)


@router.delete("/{id}/members/{user_id}", response_model=TeamModel)
async def remove_team_member(
    id: str, user_id: str, user=Depends(get_verified_user)
):
    if not is_team_admin(id, user.id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    try:
        removed = Teams.remove_member(id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return _team_with_members(Teams.get_team_by_id(id), user.id)


@router.delete("/{id}", response_model=bool)
async def delete_team(id: str, user=Depends(get_verified_user)):
    team = Teams.get_team_by_id(id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if not is_team_admin(id, user.id, user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return Teams.delete_team(id)
