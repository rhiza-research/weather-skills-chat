import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import BigInteger, Boolean, Column, Text, and_, or_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

MAX_PREFERENCE_TITLE_CHARS = 200
MAX_PREFERENCE_CONTENT_BYTES = 16 * 1024


class Preference(Base):
    __tablename__ = "preference"

    id = Column(Text, unique=True, primary_key=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    organization_id = Column(Text, nullable=False)
    visibility = Column(Text, nullable=False, default="private")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class PreferenceModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    user_id: str
    organization_id: str
    visibility: str = "private"
    enabled: bool = True
    created_at: int
    updated_at: int
    can_manage: Optional[bool] = None


class PreferenceForm(BaseModel):
    title: str
    content: str
    organization_id: Optional[str] = None
    visibility: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Title cannot be empty")
        if len(v) > MAX_PREFERENCE_TITLE_CHARS:
            raise ValueError("Title is too long")
        return v

    @field_validator("content")
    @classmethod
    def valid_content(cls, v: str) -> str:
        if v is None or not str(v).strip():
            raise ValueError("Preference text cannot be empty")
        if len(str(v).encode("utf-8")) > MAX_PREFERENCE_CONTENT_BYTES:
            raise ValueError("Preference text is too large")
        return str(v)


class PreferenceUpdateForm(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    visibility: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty")
        if len(v) > MAX_PREFERENCE_TITLE_CHARS:
            raise ValueError("Title is too long")
        return v

    @field_validator("content")
    @classmethod
    def valid_content(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not str(v).strip():
            raise ValueError("Preference text cannot be empty")
        if len(str(v).encode("utf-8")) > MAX_PREFERENCE_CONTENT_BYTES:
            raise ValueError("Preference text is too large")
        return str(v)


def _to_model(row: Preference) -> PreferenceModel:
    return PreferenceModel.model_validate(row)


class PreferenceTable:
    def insert(self, user_id: str, form: PreferenceForm) -> Optional[PreferenceModel]:
        now = int(time.time())
        organization_id = form.organization_id or user_id
        visibility = form.visibility or "private"
        if organization_id == user_id:
            visibility = "private"
        with get_db() as db:
            row = Preference(
                id=str(uuid.uuid4()),
                title=form.title,
                content=form.content,
                user_id=user_id,
                organization_id=organization_id,
                visibility=visibility,
                enabled=True if form.enabled is None else bool(form.enabled),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _to_model(row)

    def get_by_id(self, id: str) -> Optional[Preference]:
        with get_db() as db:
            return db.query(Preference).filter_by(id=id).first()

    def get_private(
        self, organization_id: str, user_id: str, title: str
    ) -> Optional[Preference]:
        with get_db() as db:
            return (
                db.query(Preference)
                .filter_by(
                    organization_id=organization_id,
                    user_id=user_id,
                    title=title,
                    visibility="private",
                )
                .first()
            )

    def get_shared(self, organization_id: str, title: str) -> Optional[Preference]:
        with get_db() as db:
            return (
                db.query(Preference)
                .filter_by(
                    organization_id=organization_id,
                    title=title,
                    visibility="organization",
                )
                .first()
            )

    def list_for_org(self, organization_id: str, user_id: str) -> list[PreferenceModel]:
        with get_db() as db:
            rows = (
                db.query(Preference)
                .filter(
                    Preference.organization_id == organization_id,
                    or_(
                        Preference.visibility == "organization",
                        and_(
                            Preference.visibility == "private",
                            Preference.user_id == user_id,
                        ),
                    ),
                )
                .order_by(Preference.title.asc())
                .all()
            )
            return [_to_model(row) for row in rows]

    def update(self, id: str, form: PreferenceUpdateForm) -> Optional[PreferenceModel]:
        with get_db() as db:
            row = db.query(Preference).filter_by(id=id).first()
            if not row:
                return None
            if form.title is not None:
                row.title = form.title
            if form.content is not None:
                row.content = form.content
            if form.visibility is not None:
                row.visibility = form.visibility
            if form.enabled is not None:
                row.enabled = bool(form.enabled)
            row.updated_at = int(time.time())
            db.commit()
            db.refresh(row)
            return _to_model(row)

    def delete(self, id: str) -> bool:
        with get_db() as db:
            deleted = db.query(Preference).filter_by(id=id).delete()
            db.commit()
            return deleted > 0


Preferences = PreferenceTable()
