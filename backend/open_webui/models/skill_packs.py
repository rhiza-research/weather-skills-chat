import logging
import time
import uuid
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, JSONField, get_db
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, Column, Text, UniqueConstraint

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class SkillPack(Base):
    __tablename__ = "skill_pack"
    __table_args__ = (
        UniqueConstraint("git_url", "git_ref", name="uq_skill_pack_git_url_ref"),
    )

    id = Column(Text, unique=True, primary_key=True)
    user_id = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    git_url = Column(Text, nullable=False)
    git_ref = Column(Text, nullable=False)
    commit_sha = Column(Text, nullable=True)
    local_path = Column(Text, nullable=False)
    meta = Column(JSONField, nullable=True)
    access_control = Column(JSONField, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class SkillSummary(BaseModel):
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    tool_id: Optional[str] = None
    skill_dir: Optional[str] = None
    relative_path: Optional[str] = None


class SkillPackModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    git_url: str
    git_ref: str
    commit_sha: Optional[str] = None
    local_path: str
    meta: Optional[dict] = None
    access_control: Optional[dict] = None
    created_at: int
    updated_at: int
    skills: list[SkillSummary] = Field(default_factory=list)


class SkillPackInstallForm(BaseModel):
    git_url: str
    ref: str = "main"


class SkillPackUpdateForm(BaseModel):
    ref: Optional[str] = None


class SkillPackAccessForm(BaseModel):
    access_control: Optional[dict] = None


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
    ) -> Optional[SkillPackModel]:
        now = int(time.time())
        with get_db() as db:
            row = SkillPack(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=name,
                git_url=git_url,
                git_ref=git_ref,
                commit_sha=commit_sha,
                local_path=local_path,
                meta=meta or {},
                access_control={} if access_control is None else access_control,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
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

    def get_all(self) -> list[SkillPackModel]:
        with get_db() as db:
            rows = db.query(SkillPack).order_by(SkillPack.updated_at.desc()).all()
            return [self._to_model(row) for row in rows]

    def update(self, pack_id: str, data: dict[str, Any]) -> Optional[SkillPackModel]:
        with get_db() as db:
            db.query(SkillPack).filter_by(id=pack_id).update(
                {**data, "updated_at": int(time.time())}
            )
            db.commit()
            row = db.get(SkillPack, pack_id)
            return self._to_model(row) if row else None

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
            name=row.name,
            git_url=row.git_url,
            git_ref=row.git_ref,
            commit_sha=row.commit_sha,
            local_path=row.local_path,
            meta=meta,
            access_control=row.access_control,
            created_at=row.created_at or 0,
            updated_at=row.updated_at or 0,
            skills=skills,
        )


SkillPacks = SkillPackTable()
