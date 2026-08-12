import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, JSONField, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, Text, or_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class Automation(Base):
    __tablename__ = "automation"

    id = Column(Text, unique=True, primary_key=True)
    name = Column(Text, nullable=False)
    prompt = Column(Text, nullable=False)
    model = Column(Text, nullable=True)
    cron = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    user_id = Column(Text, nullable=False)
    team_id = Column(Text, nullable=True)
    source_chat_id = Column(Text, nullable=True)
    tool_ids = Column(JSONField, nullable=True)
    features = Column(JSONField, nullable=True)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class AutomationRun(Base):
    __tablename__ = "automation_run"

    id = Column(Text, unique=True, primary_key=True)
    automation_id = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    error = Column(Text, nullable=True)
    started_at = Column(BigInteger)
    finished_at = Column(BigInteger)
    triggered_by = Column(Text, nullable=True)


class AutomationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prompt: str
    model: Optional[str] = None
    cron: Optional[str] = None
    enabled: bool = True
    user_id: str
    team_id: Optional[str] = None
    source_chat_id: Optional[str] = None
    tool_ids: Optional[list[str]] = None
    features: Optional[dict] = None
    created_at: int
    updated_at: int


class AutomationRunModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    automation_id: str
    chat_id: Optional[str] = None
    status: str
    error: Optional[str] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    triggered_by: Optional[str] = None
    chat_title: Optional[str] = None


class AutomationForm(BaseModel):
    name: str
    prompt: str
    model: Optional[str] = None
    cron: Optional[str] = None
    enabled: bool = True
    team_id: Optional[str] = None
    source_chat_id: Optional[str] = None
    tool_ids: Optional[list[str]] = None
    features: Optional[dict] = None


class AutomationUpdateForm(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    cron: Optional[str] = None
    enabled: Optional[bool] = None
    team_id: Optional[str] = None
    tool_ids: Optional[list[str]] = None
    features: Optional[dict] = None


class AutomationTable:
    def insert_new_automation(
        self, user_id: str, form_data: AutomationForm
    ) -> Optional[AutomationModel]:
        now = int(time.time())
        with get_db() as db:
            automation = Automation(
                id=str(uuid.uuid4()),
                name=form_data.name.strip(),
                prompt=form_data.prompt,
                model=form_data.model,
                cron=form_data.cron,
                enabled=form_data.enabled,
                user_id=user_id,
                team_id=form_data.team_id,
                source_chat_id=form_data.source_chat_id,
                tool_ids=form_data.tool_ids,
                features=form_data.features,
                created_at=now,
                updated_at=now,
            )
            db.add(automation)
            db.commit()
            db.refresh(automation)
            return AutomationModel.model_validate(automation)

    def get_automation_by_id(self, id: str) -> Optional[AutomationModel]:
        with get_db() as db:
            row = db.query(Automation).filter_by(id=id).first()
            return AutomationModel.model_validate(row) if row else None

    def get_automations_for_user(
        self, user_id: str, team_ids: Optional[list[str]] = None
    ) -> list[AutomationModel]:
        team_ids = team_ids or []
        with get_db() as db:
            conditions = [
                (Automation.user_id == user_id) & (Automation.team_id.is_(None))
            ]
            if team_ids:
                conditions.append(Automation.team_id.in_(team_ids))
            return [
                AutomationModel.model_validate(row)
                for row in db.query(Automation)
                .filter(or_(*conditions))
                .order_by(Automation.updated_at.desc())
                .all()
            ]

    def get_enabled_scheduled(self) -> list[AutomationModel]:
        with get_db() as db:
            return [
                AutomationModel.model_validate(row)
                for row in db.query(Automation)
                .filter(Automation.enabled == True, Automation.cron.isnot(None))  # noqa: E712
                .all()
            ]

    def update_automation(
        self, id: str, form_data: AutomationUpdateForm
    ) -> Optional[AutomationModel]:
        updates = form_data.model_dump(exclude_unset=True)
        if "name" in updates and updates["name"] is not None:
            updates["name"] = updates["name"].strip()
        updates["updated_at"] = int(time.time())
        with get_db() as db:
            db.query(Automation).filter_by(id=id).update(updates)
            db.commit()
        return self.get_automation_by_id(id)

    def delete_automation(self, id: str) -> bool:
        with get_db() as db:
            db.query(AutomationRun).filter_by(automation_id=id).delete()
            deleted = db.query(Automation).filter_by(id=id).delete()
            db.commit()
            return deleted > 0


class AutomationRunTable:
    def insert_run(
        self,
        automation_id: str,
        status: str = "running",
        chat_id: Optional[str] = None,
        triggered_by: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[AutomationRunModel]:
        now = int(time.time())
        with get_db() as db:
            run = AutomationRun(
                id=str(uuid.uuid4()),
                automation_id=automation_id,
                chat_id=chat_id,
                status=status,
                error=error,
                started_at=now,
                finished_at=None if status == "running" else now,
                triggered_by=triggered_by,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            return AutomationRunModel.model_validate(run)

    def get_run_by_id(self, id: str) -> Optional[AutomationRunModel]:
        with get_db() as db:
            row = db.query(AutomationRun).filter_by(id=id).first()
            return AutomationRunModel.model_validate(row) if row else None

    def update_run(
        self,
        id: str,
        status: Optional[str] = None,
        chat_id: Optional[str] = None,
        error: Optional[str] = None,
        finished: bool = False,
    ) -> Optional[AutomationRunModel]:
        updates = {}
        if status is not None:
            updates["status"] = status
        if chat_id is not None:
            updates["chat_id"] = chat_id
        if error is not None:
            updates["error"] = error
        if finished:
            updates["finished_at"] = int(time.time())
        with get_db() as db:
            if updates:
                db.query(AutomationRun).filter_by(id=id).update(updates)
                db.commit()
            row = db.query(AutomationRun).filter_by(id=id).first()
            return AutomationRunModel.model_validate(row) if row else None

    def get_runs(
        self, automation_id: str, skip: int = 0, limit: int = 50
    ) -> list[AutomationRunModel]:
        with get_db() as db:
            rows = (
                db.query(AutomationRun)
                .filter_by(automation_id=automation_id)
                .order_by(AutomationRun.started_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )
            return [AutomationRunModel.model_validate(row) for row in rows]

    def clear_chat_id(self, chat_id: str) -> None:
        with get_db() as db:
            db.query(AutomationRun).filter_by(chat_id=chat_id).update({"chat_id": None})
            db.commit()


Automations = AutomationTable()
AutomationRuns = AutomationRunTable()
