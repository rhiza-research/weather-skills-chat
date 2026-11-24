"""Text skills: markdown instructions a chat can switch on, with no tools.

Scoped like preferences: private to a user, or shared with an organization.
"""

import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import BigInteger, Boolean, Column, Text, and_, or_

MAX_TEXT_SKILL_TITLE_CHARS = 200
MAX_TEXT_SKILL_CONTENT_BYTES = 32 * 1024


class TextSkill(Base):
    __tablename__ = "text_skill"

    id = Column(Text, unique=True, primary_key=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    organization_id = Column(Text, nullable=False)
    visibility = Column(Text, nullable=False, default="private")
    enabled = Column(Boolean, nullable=False, default=True)
    enabled_by_default = Column(Boolean, nullable=False, default=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class TextSkillModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    user_id: str
    organization_id: str
    visibility: str = "private"
    enabled: bool = True
    enabled_by_default: bool = True
    created_at: int
    updated_at: int
    can_manage: Optional[bool] = None


def _valid_title(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    v = v.strip()
    if not v:
        raise ValueError("Title cannot be empty")
    if len(v) > MAX_TEXT_SKILL_TITLE_CHARS:
        raise ValueError("Title is too long")
    return v


def _valid_content(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if not str(v).strip():
        raise ValueError("Skill text cannot be empty")
    if len(str(v).encode("utf-8")) > MAX_TEXT_SKILL_CONTENT_BYTES:
        raise ValueError("Skill text is too large")
    return str(v)


class TextSkillUpdateForm(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    visibility: Optional[str] = None
    enabled: Optional[bool] = None
    enabled_by_default: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, v):
        return _valid_title(v)

    @field_validator("content")
    @classmethod
    def valid_content(cls, v):
        return _valid_content(v)


class TextSkillForm(TextSkillUpdateForm):
    title: str
    content: str
    organization_id: Optional[str] = None


class TextSkillTable:
    def insert(self, user_id: str, form: TextSkillForm) -> TextSkillModel:
        now = int(time.time())
        organization_id = form.organization_id or user_id
        visibility = form.visibility or "private"
        if organization_id == user_id:
            visibility = "private"
        with get_db() as db:
            row = TextSkill(
                id=str(uuid.uuid4()),
                title=form.title,
                content=form.content,
                user_id=user_id,
                organization_id=organization_id,
                visibility=visibility,
                enabled=form.enabled is not False,
                enabled_by_default=form.enabled_by_default is not False,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return TextSkillModel.model_validate(row)

    def get_by_id(self, id: str) -> Optional[TextSkill]:
        with get_db() as db:
            return db.query(TextSkill).filter_by(id=id).first()

    def get_by_title(
        self, organization_id: str, user_id: str, title: str, visibility: str
    ) -> Optional[TextSkill]:
        filters = dict(organization_id=organization_id, title=title, visibility=visibility)
        if visibility == "private":
            filters["user_id"] = user_id
        with get_db() as db:
            return db.query(TextSkill).filter_by(**filters).first()

    def list_for_org(self, organization_id: str, user_id: str) -> list[TextSkillModel]:
        with get_db() as db:
            rows = (
                db.query(TextSkill)
                .filter(
                    TextSkill.organization_id == organization_id,
                    or_(
                        TextSkill.visibility == "organization",
                        and_(
                            TextSkill.visibility == "private",
                            TextSkill.user_id == user_id,
                        ),
                    ),
                )
                .order_by(TextSkill.title.asc())
                .all()
            )
            return [TextSkillModel.model_validate(row) for row in rows]

    def update(self, id: str, form: TextSkillUpdateForm) -> Optional[TextSkillModel]:
        with get_db() as db:
            row = db.query(TextSkill).filter_by(id=id).first()
            if not row:
                return None
            for key, value in form.model_dump(exclude_none=True).items():
                setattr(row, key, value)
            row.updated_at = int(time.time())
            db.commit()
            db.refresh(row)
            return TextSkillModel.model_validate(row)

    def delete(self, id: str) -> bool:
        with get_db() as db:
            deleted = db.query(TextSkill).filter_by(id=id).delete()
            db.commit()
            return deleted > 0


TextSkills = TextSkillTable()
