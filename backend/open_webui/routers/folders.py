import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
import mimetypes


from open_webui.models.folders import (
    FolderForm,
    FolderModel,
    Folders,
)
from open_webui.models.chats import Chats
from open_webui.models.organizations import VISIBILITY_ORGANIZATION
from open_webui.models.users import Users

from open_webui.config import UPLOAD_DIR
from open_webui.env import SRC_LOG_LEVELS
from open_webui.constants import ERROR_MESSAGES


from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, Request
from fastapi.responses import FileResponse, StreamingResponse


from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.access_control import has_permission
from open_webui.utils.organizations import (
    get_active_organization_id,
    is_member,
    resolve_visibility,
)


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


router = APIRouter()


def _can_read_folder(folder: Optional[FolderModel], user) -> bool:
    if folder is None:
        return False
    if folder.user_id == user.id:
        return True
    return folder.visibility == "organization" and is_member(
        folder.organization_id, user.id
    )


def _require_folder(folder_id: str, user) -> FolderModel:
    folder = Folders.get_folder_by_id(folder_id)
    if not _can_read_folder(folder, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return folder


def _owner_names(user_ids: list[str]) -> dict[str, str]:
    ids = [uid for uid in user_ids if uid]
    if not ids:
        return {}
    users = Users.get_users_by_user_ids(ids)
    return {u.id: u.name for u in users}


def _chat_item(chat, names: dict[str, str]) -> dict:
    return {
        "id": chat.id,
        "title": chat.title,
        "user_id": chat.user_id,
        "visibility": chat.visibility,
        "owner_name": names.get(chat.user_id) or "Unknown user",
    }


def _folder_chat_items_by_folder(folders, user) -> dict[str, list[dict]]:
    """Chats for every folder: one query per visibility, then one owner lookup."""
    private_ids = []
    organization_ids = []
    for folder in folders:
        if folder.visibility == VISIBILITY_ORGANIZATION:
            organization_ids.append(folder.id)
        else:
            private_ids.append(folder.id)
    chats = []
    if private_ids:
        chats.extend(Chats.get_chats_in_folders(private_ids, user.id, "private"))
    if organization_ids:
        chats.extend(
            Chats.get_chats_in_folders(
                organization_ids, user.id, VISIBILITY_ORGANIZATION
            )
        )
    names = _owner_names([chat.user_id for chat in chats])
    by_folder: dict[str, list[dict]] = {}
    for chat in chats:
        by_folder.setdefault(chat.folder_id, []).append(_chat_item(chat, names))
    return by_folder


def _sibling_name_taken(folder: FolderModel, name: str, parent_id: Optional[str]) -> bool:
    existing = Folders.get_folder_by_parent_visibility_and_name(
        parent_id,
        name,
        folder.visibility,
        folder.user_id,
        folder.organization_id,
    )
    return existing is not None and existing.id != folder.id


############################
# Get Folders
############################


@router.get("/", response_model=list[FolderModel])
async def get_folders(
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    folders = Folders.get_folders_by_user_id(user.id, organization_id=organization_id)
    chats_by_folder = _folder_chat_items_by_folder(folders, user)

    return [
        {
            **folder.model_dump(),
            "items": {"chats": chats_by_folder.get(folder.id, [])},
        }
        for folder in folders
    ]


############################
# Create Folder
############################


@router.post("/")
def create_folder(
    form_data: FolderForm,
    user=Depends(get_verified_user),
    organization_id: str = Depends(get_active_organization_id),
):
    visibility = resolve_visibility(
        organization_id, getattr(form_data, "visibility", None)
    )
    folder = Folders.get_folder_by_parent_visibility_and_name(
        None, form_data.name, visibility, user.id, organization_id
    )

    if folder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Folder already exists"),
        )

    try:
        folder = Folders.insert_new_folder(
            user.id,
            form_data.name,
            organization_id=organization_id,
            visibility=visibility,
        )
        return folder
    except Exception as e:
        log.exception(e)
        log.error("Error creating folder")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating folder"),
        )


############################
# Get Folders By Id
############################


@router.get("/{id}", response_model=Optional[FolderModel])
async def get_folder_by_id(id: str, user=Depends(get_verified_user)):
    return _require_folder(id, user)


############################
# Update Folder Name By Id
############################


@router.post("/{id}/update")
async def update_folder_name_by_id(
    id: str, form_data: FolderForm, user=Depends(get_verified_user)
):
    folder = _require_folder(id, user)
    if folder:
        if _sibling_name_taken(folder, form_data.name, folder.parent_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Folder already exists"),
            )

        try:
            folder = Folders.update_folder_name_by_id_and_user_id(
                id, user.id, form_data.name
            )

            return folder
        except Exception as e:
            log.exception(e)
            log.error(f"Error updating folder: {id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating folder"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update Folder Parent Id By Id
############################


class FolderParentIdForm(BaseModel):
    parent_id: Optional[str] = None


@router.post("/{id}/update/parent")
async def update_folder_parent_id_by_id(
    id: str, form_data: FolderParentIdForm, user=Depends(get_verified_user)
):
    folder = _require_folder(id, user)
    if folder:
        if form_data.parent_id:
            parent = _require_folder(form_data.parent_id, user)
            if parent.visibility != folder.visibility or (
                parent.visibility == "organization"
                and parent.organization_id != folder.organization_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT(
                        "Folders can only be moved within the same chat section."
                    ),
                )
            if parent.id == folder.id or any(
                child.id == parent.id for child in Folders.descendant_folders(folder)
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT("A folder cannot contain itself."),
                )

        if _sibling_name_taken(folder, folder.name, form_data.parent_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Folder already exists"),
            )

        try:
            folder = Folders.update_folder_parent_id_by_id_and_user_id(
                id, user.id, form_data.parent_id
            )
            return folder
        except Exception as e:
            log.exception(e)
            log.error(f"Error updating folder: {id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating folder"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update Folder Is Expanded By Id
############################


class FolderIsExpandedForm(BaseModel):
    is_expanded: bool


@router.post("/{id}/update/expanded")
async def update_folder_is_expanded_by_id(
    id: str, form_data: FolderIsExpandedForm, user=Depends(get_verified_user)
):
    folder = _require_folder(id, user)
    if folder:
        try:
            folder = Folders.update_folder_is_expanded_by_id_and_user_id(
                id, user.id, form_data.is_expanded
            )
            return folder
        except Exception as e:
            log.exception(e)
            log.error(f"Error updating folder: {id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error updating folder"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Delete Folder By Id
############################


@router.delete("/{id}")
async def delete_folder_by_id(
    request: Request, id: str, user=Depends(get_verified_user)
):
    folder = _require_folder(id, user)

    # Private folders delete the owner's chats. Team folders only remove the
    # grouping, so they do not require permission to delete chats.
    if folder.visibility != "organization":
        chat_delete_permission = has_permission(
            user.id, "chat.delete", request.app.state.config.USER_PERMISSIONS
        )
        if user.role != "admin" and not chat_delete_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    if folder:
        try:
            result = Folders.delete_folder_by_id_and_user_id(id, user.id)
            if result:
                return result
            else:
                raise Exception("Error deleting folder")
        except Exception as e:
            log.exception(e)
            log.error(f"Error deleting folder: {id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT("Error deleting folder"),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
