import logging
import time
import uuid
from contextlib import nullcontext
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, JSONField, get_db
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import BigInteger, Boolean, Column, Text, UniqueConstraint

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class SkillPack(Base):
    __tablename__ = "skill_pack"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "git_url", "git_ref", name="uq_skill_pack_org_git_url_ref"
        ),
    )

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text, nullable=False)
    organization_id = Column(Text, nullable=False)
    visibility = Column(Text, nullable=False, default="private")
    name = Column(Text, nullable=False)
    git_url = Column(Text, nullable=False)
    git_ref = Column(Text, nullable=False)
    commit_sha = Column(Text, nullable=True)
    local_path = Column(Text, nullable=False)
    meta = Column(JSONField, nullable=True)
    access_control = Column(JSONField, nullable=True)
    enabled_by_default = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class SkillSummary(BaseModel):
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    tool_id: Optional[str] = None
    skill_dir: Optional[str] = None
    relative_path: Optional[str] = None
    # Effective enable state after catalog annotation; stored meta also
    # keeps this as a legacy alias of enabled_by_default.
    enabled: bool = True
    is_active: bool = True
    enabled_by_default: bool = True

    @model_validator(mode="before")
    @classmethod
    def inherit_legacy_enabled(cls, data):
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "enabled_by_default" not in out and "enabled" in out:
            out["enabled_by_default"] = bool(out["enabled"])
        return out


class SkillPackModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    organization_id: Optional[str] = None
    visibility: str = "private"
    name: str
    git_url: str
    git_ref: str
    commit_sha: Optional[str] = None
    local_path: str
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
    enabled_by_default: bool = True
    is_active: bool = True
    enabled: Optional[bool] = None
    created_at: int
    updated_at: int
    skills: list[SkillSummary] = Field(default_factory=list)


class SkillPackInstallForm(BaseModel):
    git_url: str
    ref: str = "main"
    enabled_by_default: bool = True


class SkillPackUpdateForm(BaseModel):
    ref: Optional[str] = None


class SkillPackAccessForm(BaseModel):
    access_control: Optional[dict] = None


class SkillPackSkillEnabledForm(BaseModel):
    enabled: bool


class SkillPackTable:
    def insert(
        self,
        user_id: str,
        *,
        name: str,
        git_url: str,
        git_ref: str,
        commit_sha: str,
        local_path: str,
        meta: Optional[dict] = None,
        access_control: Optional[dict] = None,
        organization_id: Optional[str] = None,
        visibility: Optional[str] = None,
        enabled_by_default: bool = True,
        is_active: bool = True,
        db=None,
    ) -> Optional[SkillPackModel]:
        now = int(time.time())
        organization_id = organization_id or user_id
        visibility = visibility or "organization"
        owns = db is None
        with get_db() if owns else nullcontext(db) as session:
            row = SkillPack(
                id=str(uuid.uuid4()),
                user_id=user_id,
                organization_id=organization_id,
                visibility=visibility,
                name=name,
                git_url=git_url,
                git_ref=git_ref,
                commit_sha=commit_sha,
                local_path=local_path,
                meta=meta or {},
                # Skill use is catalog membership plus the org enablement
                # toggle, not this field. None is stored as NULL.
                access_control=access_control,
                enabled_by_default=enabled_by_default,
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            if owns:
                session.commit()
                session.refresh(row)
            else:
                session.flush()
            return self._to_model(row)

    def get_by_id(self, pack_id: str) -> Optional[SkillPackModel]:
        with get_db() as db:
            row = db.get(SkillPack, pack_id)
            return self._to_model(row) if row else None

    def get_by_url_ref(self, git_url: str, git_ref: str) -> Optional[SkillPackModel]:
        with get_db() as db:
            row = (
                db.query(SkillPack)
                .filter_by(git_url=git_url, git_ref=git_ref)
                .first()
            )
            return self._to_model(row) if row else None

    def get_by_org_url_ref(
        self, organization_id: str, git_url: str, git_ref: str
    ) -> Optional[SkillPackModel]:
        with get_db() as db:
            row = (
                db.query(SkillPack)
                .filter_by(
                    organization_id=organization_id, git_url=git_url, git_ref=git_ref
                )
                .first()
            )
            return self._to_model(row) if row else None

    def get_by_user_url_ref(
        self, user_id: str, git_url: str, git_ref: str
    ) -> Optional[SkillPackModel]:
        return self.get_by_org_url_ref(user_id, git_url, git_ref)

    def get_all(self) -> list[SkillPackModel]:
        with get_db() as db:
            rows = db.query(SkillPack).order_by(SkillPack.updated_at.desc()).all()
            return [self._to_model(row) for row in rows]

    def update(
        self, pack_id: str, data: dict[str, Any], db=None
    ) -> Optional[SkillPackModel]:
        owns = db is None
        with get_db() if owns else nullcontext(db) as session:
            row = session.get(SkillPack, pack_id)
            if not row:
                return None
            # Use ORM setattr so JSONField bind processors run (needed for
            # access_control=None / Public). Query.update() can skip them.
            for key, value in data.items():
                setattr(row, key, value)
            row.updated_at = int(time.time())
            session.add(row)
            if owns:
                session.commit()
                session.refresh(row)
            else:
                session.flush()
            return self._to_model(row)

    def toggle_active(self, pack_id: str) -> Optional[SkillPackModel]:
        pack = self.get_by_id(pack_id)
        if not pack:
            return None
        return self.update(
            pack_id, {"is_active": not bool(getattr(pack, "is_active", True))}
        )

    def set_enabled_by_default(
        self, pack_id: str, enabled_by_default: bool
    ) -> Optional[SkillPackModel]:
        return self.update(pack_id, {"enabled_by_default": bool(enabled_by_default)})

    def delete(self, pack_id: str) -> bool:
        with get_db() as db:
            db.query(SkillPack).filter_by(id=pack_id).delete()
            db.commit()
            return True

    def _to_model(self, row: SkillPack) -> SkillPackModel:
        meta = row.meta or {}
        skills_raw = meta.get("skills") or []
        skills = [SkillSummary.model_validate(s) for s in skills_raw]
        return SkillPackModel(
            id=row.id,
            user_id=row.user_id,
            organization_id=row.organization_id,
            visibility=row.visibility or "private",
            name=row.name,
            git_url=row.git_url,
            git_ref=row.git_ref,
            commit_sha=row.commit_sha,
            local_path=row.local_path,
            meta=meta,
            access_control=row.access_control,
            enabled_by_default=bool(getattr(row, "enabled_by_default", True)),
            is_active=getattr(row, "is_active", True) is not False,
            created_at=row.created_at or 0,
            updated_at=row.updated_at or 0,
            skills=skills,
        )


SkillPacks = SkillPackTable()
