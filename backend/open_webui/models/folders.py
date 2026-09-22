import logging
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from open_webui.models.chats import Chats

from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Text, JSON, Boolean, or_
from open_webui.utils.access_control import get_permissions


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Folder DB Schema
####################


class Folder(Base):
    __tablename__ = "folder"
    id = Column(Text, primary_key=True)
    parent_id = Column(Text, nullable=True)
    user_id = Column(Text)
    organization_id = Column(Text, nullable=False)
    visibility = Column(Text, nullable=False, default="private")
    name = Column(Text)
    items = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    is_expanded = Column(Boolean, default=False)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class FolderModel(BaseModel):
    id: str
    parent_id: Optional[str] = None
    user_id: str
    organization_id: Optional[str] = None
    visibility: str = "private"
    name: str
    items: Optional[dict] = None
    meta: Optional[dict] = None
    is_expanded: bool = False
    created_at: int
    updated_at: int

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class FolderForm(BaseModel):
    name: str
    visibility: Optional[str] = None
    model_config = ConfigDict(extra="allow")


class FolderTable:
    def insert_new_folder(
        self,
        user_id: str,
        name: str,
        parent_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        visibility: str = "private",
    ) -> Optional[FolderModel]:
        organization_id = organization_id or user_id
        if organization_id == user_id or visibility != "organization":
            visibility = "private"
        with get_db() as db:
            id = str(uuid.uuid4())
            folder = FolderModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "organization_id": organization_id,
                    "visibility": visibility,
                    "name": name,
                    "parent_id": parent_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )
            try:
                result = Folder(**folder.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return FolderModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error inserting a new folder: {e}")
                return None

    def get_folder_by_id(self, id: str) -> Optional[FolderModel]:
        try:
            with get_db() as db:
                folder = db.get(Folder, id)
                if not folder:
                    return None
                return FolderModel.model_validate(folder)
        except Exception:
            return None

    def get_folder_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[FolderModel]:
        folder = self.get_folder_by_id(id)
        if folder and folder.user_id == user_id:
            return folder
        return None

    def get_folder_by_parent_visibility_and_name(
        self,
        parent_id: Optional[str],
        name: str,
        visibility: str,
        user_id: str,
        organization_id: str,
    ) -> Optional[FolderModel]:
        try:
            with get_db() as db:
                query = db.query(Folder).filter(
                    Folder.parent_id == parent_id,
                    Folder.name.ilike(name),
                    Folder.visibility == visibility,
                )
                if visibility == "organization":
                    query = query.filter(Folder.organization_id == organization_id)
                else:
                    query = query.filter(Folder.user_id == user_id)
                folder = query.first()
                if not folder:
                    return None
                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"get_folder_by_parent_visibility_and_name: {e}")
            return None

    def descendant_folders(self, folder: FolderModel) -> list[FolderModel]:
        """Child folders in the same scope (private owner, or shared team folder)."""
        found: list[FolderModel] = []
        with get_db() as db:
            stack = [folder.id]
            while stack:
                parent_id = stack.pop()
                query = db.query(Folder).filter(Folder.parent_id == parent_id)
                if folder.visibility == "organization":
                    query = query.filter(
                        Folder.visibility == "organization",
                        Folder.organization_id == folder.organization_id,
                    )
                else:
                    query = query.filter(
                        Folder.visibility == "private",
                        Folder.user_id == folder.user_id,
                    )
                for child in query.all():
                    model = FolderModel.model_validate(child)
                    found.append(model)
                    stack.append(model.id)
        return found

    def get_children_folders_by_id_and_user_id(
        self, id: str, user_id: str
    ) -> Optional[FolderModel]:
        try:
            with get_db() as db:
                folders = []

                def get_children(folder):
                    children = self.get_folders_by_parent_id_and_user_id(
                        folder.id, user_id
                    )
                    for child in children:
                        get_children(child)
                        folders.append(child)

                folder = db.query(Folder).filter_by(id=id, user_id=user_id).first()
                if not folder:
                    return None

                get_children(folder)
                return folders
        except Exception:
            return None

    def get_folders_by_user_id(
        self, user_id: str, organization_id: Optional[str] = None
    ) -> list[FolderModel]:
        organization_id = organization_id or user_id
        with get_db() as db:
            return [
                FolderModel.model_validate(folder)
                for folder in db.query(Folder)
                .filter(
                    Folder.organization_id == organization_id,
                    or_(
                        Folder.visibility == "organization",
                        Folder.user_id == user_id,
                    ),
                )
                .all()
            ]

    def get_folder_by_parent_id_and_user_id_and_name(
        self, parent_id: Optional[str], user_id: str, name: str
    ) -> Optional[FolderModel]:
        try:
            with get_db() as db:
                # Check if folder exists
                folder = (
                    db.query(Folder)
                    .filter_by(parent_id=parent_id, user_id=user_id)
                    .filter(Folder.name.ilike(name))
                    .first()
                )

                if not folder:
                    return None

                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"get_folder_by_parent_id_and_user_id_and_name: {e}")
            return None

    def get_folders_by_parent_id_and_user_id(
        self, parent_id: Optional[str], user_id: str
    ) -> list[FolderModel]:
        with get_db() as db:
            return [
                FolderModel.model_validate(folder)
                for folder in db.query(Folder)
                .filter_by(parent_id=parent_id, user_id=user_id)
                .all()
            ]

    def update_folder_parent_id_by_id_and_user_id(
        self,
        id: str,
        user_id: str,
        parent_id: str,
    ) -> Optional[FolderModel]:
        try:
            with get_db() as db:
                folder = db.query(Folder).filter_by(id=id).first()

                if not folder:
                    return None

                folder.parent_id = parent_id
                folder.updated_at = int(time.time())

                db.commit()

                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"update_folder: {e}")
            return

    def update_folder_name_by_id_and_user_id(
        self, id: str, user_id: str, name: str
    ) -> Optional[FolderModel]:
        try:
            with get_db() as db:
                folder = db.query(Folder).filter_by(id=id).first()

                if not folder:
                    return None

                existing_query = db.query(Folder).filter(
                    Folder.id != id,
                    Folder.name == name,
                    Folder.parent_id == folder.parent_id,
                    Folder.visibility == folder.visibility,
                )
                if folder.visibility == "organization":
                    existing_query = existing_query.filter(
                        Folder.organization_id == folder.organization_id
                    )
                else:
                    existing_query = existing_query.filter(Folder.user_id == folder.user_id)
                existing_folder = existing_query.first()

                if existing_folder:
                    return None

                folder.name = name
                folder.updated_at = int(time.time())

                db.commit()

                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"update_folder: {e}")
            return

    def update_folder_is_expanded_by_id_and_user_id(
        self, id: str, user_id: str, is_expanded: bool
    ) -> Optional[FolderModel]:
        try:
            with get_db() as db:
                folder = db.query(Folder).filter_by(id=id).first()

                if not folder:
                    return None

                folder.is_expanded = is_expanded
                folder.updated_at = int(time.time())

                db.commit()

                return FolderModel.model_validate(folder)
        except Exception as e:
            log.error(f"update_folder: {e}")
            return

    def delete_folder_by_id_and_user_id(
        self, id: str, user_id: str, delete_chats=True
    ) -> bool:
        try:
            folder = self.get_folder_by_id(id)
            if not folder:
                return False

            # Team folders are shared structure. Removing one puts chats back
            # in the team list instead of deleting other people's chats.
            remove_chats = delete_chats and folder.visibility != "organization"
            descendants = self.descendant_folders(folder)
            folder_ids = [folder.id, *[child.id for child in descendants]]

            if remove_chats:
                for folder_id in folder_ids:
                    Chats.delete_chats_by_user_id_and_folder_id(user_id, folder_id)
            else:
                Chats.clear_chat_folder_ids(folder_ids)

            with get_db() as db:
                db.query(Folder).filter(Folder.id.in_(folder_ids)).delete(
                    synchronize_session=False
                )
                db.commit()
                return True
        except Exception as e:
            log.error(f"delete_folder: {e}")
            return False


Folders = FolderTable()
