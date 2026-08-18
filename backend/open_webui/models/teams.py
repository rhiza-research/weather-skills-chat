import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import BigInteger, Column, Text, and_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

TEAM_ROLES = ("admin", "member")


class Team(Base):
    __tablename__ = "team"

    id = Column(Text, unique=True, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(Text, nullable=False)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
    default_models = Column(Text, nullable=True)


class TeamMember(Base):
    __tablename__ = "team_member"

    team_id = Column(Text, primary_key=True)
    user_id = Column(Text, primary_key=True)
    role = Column(Text, nullable=False)
    created_at = Column(BigInteger)


class TeamMemberModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    team_id: str
    user_id: str
    role: str
    created_at: int
    name: Optional[str] = None
    email: Optional[str] = None
    profile_image_url: Optional[str] = None


class TeamModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    created_by: str
    created_at: int
    updated_at: int
    role: Optional[str] = None
    members: Optional[list[TeamMemberModel]] = None
    default_models: Optional[str] = None


class TeamForm(BaseModel):
    name: str
    description: Optional[str] = None
    default_models: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Team name cannot be empty")
        return v


class TeamUpdateForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_models: Optional[str] = None


class TeamMemberAddForm(BaseModel):
    user_id: str
    role: str = "member"

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in TEAM_ROLES:
            raise ValueError("Role must be admin or member")
        return v


class TeamMemberRoleForm(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in TEAM_ROLES:
            raise ValueError("Role must be admin or member")
        return v


class TeamTable:
    def insert_new_team(self, user_id: str, form_data: TeamForm) -> Optional[TeamModel]:
        now = int(time.time())
        team_id = str(uuid.uuid4())
        with get_db() as db:
            team = Team(
                id=team_id,
                name=form_data.name,
                description=form_data.description or "",
                created_by=user_id,
                created_at=now,
                updated_at=now,
                default_models=form_data.default_models,
            )
            member = TeamMember(
                team_id=team_id,
                user_id=user_id,
                role="admin",
                created_at=now,
            )
            db.add(team)
            db.add(member)
            db.commit()
            db.refresh(team)
            return TeamModel.model_validate(team)

    def get_team_by_id(self, team_id: str) -> Optional[TeamModel]:
        with get_db() as db:
            team = db.query(Team).filter_by(id=team_id).first()
            return TeamModel.model_validate(team) if team else None

    def get_teams_by_user_id(self, user_id: str) -> list[TeamModel]:
        with get_db() as db:
            rows = (
                db.query(Team, TeamMember.role)
                .join(TeamMember, Team.id == TeamMember.team_id)
                .filter(TeamMember.user_id == user_id)
                .order_by(Team.name.asc())
                .all()
            )
            result = []
            for team, role in rows:
                model = TeamModel.model_validate(team)
                model.role = role
                result.append(model)
            return result

    def get_all_teams(self) -> list[TeamModel]:
        with get_db() as db:
            return [
                TeamModel.model_validate(team)
                for team in db.query(Team).order_by(Team.name.asc()).all()
            ]

    def get_member(self, team_id: str, user_id: str) -> Optional[TeamMemberModel]:
        with get_db() as db:
            member = (
                db.query(TeamMember)
                .filter_by(team_id=team_id, user_id=user_id)
                .first()
            )
            return TeamMemberModel.model_validate(member) if member else None

    def get_members(self, team_id: str) -> list[TeamMemberModel]:
        from open_webui.models.users import User

        with get_db() as db:
            rows = (
                db.query(TeamMember, User)
                .outerjoin(User, TeamMember.user_id == User.id)
                .filter(TeamMember.team_id == team_id)
                .order_by(TeamMember.created_at.asc())
                .all()
            )
            members = []
            for member, user in rows:
                model = TeamMemberModel.model_validate(member)
                if user:
                    model.name = user.name
                    model.email = user.email
                    model.profile_image_url = user.profile_image_url
                members.append(model)
            return members

    def count_admins(self, team_id: str) -> int:
        with get_db() as db:
            return (
                db.query(TeamMember)
                .filter(
                    and_(TeamMember.team_id == team_id, TeamMember.role == "admin")
                )
                .count()
            )

    def update_team(
        self, team_id: str, form_data: TeamUpdateForm
    ) -> Optional[TeamModel]:
        updates = form_data.model_dump(exclude_none=True)
        if "name" in updates:
            updates["name"] = updates["name"].strip()
            if not updates["name"]:
                raise ValueError("Team name cannot be empty")
        if not updates:
            return self.get_team_by_id(team_id)

        updates["updated_at"] = int(time.time())
        with get_db() as db:
            db.query(Team).filter_by(id=team_id).update(updates)
            db.commit()
        return self.get_team_by_id(team_id)

    def add_member(
        self, team_id: str, user_id: str, role: str = "member"
    ) -> Optional[TeamMemberModel]:
        if role not in TEAM_ROLES:
            raise ValueError("Role must be admin or member")
        existing = self.get_member(team_id, user_id)
        if existing:
            return existing
        with get_db() as db:
            member = TeamMember(
                team_id=team_id,
                user_id=user_id,
                role=role,
                created_at=int(time.time()),
            )
            db.add(member)
            db.query(Team).filter_by(id=team_id).update(
                {"updated_at": int(time.time())}
            )
            db.commit()
            db.refresh(member)
            return TeamMemberModel.model_validate(member)

    def update_member_role(
        self, team_id: str, user_id: str, role: str
    ) -> Optional[TeamMemberModel]:
        if role not in TEAM_ROLES:
            raise ValueError("Role must be admin or member")
        member = self.get_member(team_id, user_id)
        if not member:
            return None
        if member.role == "admin" and role != "admin" and self.count_admins(team_id) <= 1:
            raise ValueError("Cannot demote the last team admin")
        with get_db() as db:
            db.query(TeamMember).filter_by(team_id=team_id, user_id=user_id).update(
                {"role": role}
            )
            db.query(Team).filter_by(id=team_id).update(
                {"updated_at": int(time.time())}
            )
            db.commit()
        return self.get_member(team_id, user_id)

    def remove_member(self, team_id: str, user_id: str) -> bool:
        member = self.get_member(team_id, user_id)
        if not member:
            return False
        if member.role == "admin" and self.count_admins(team_id) <= 1:
            raise ValueError("Cannot remove the last team admin")
        with get_db() as db:
            db.query(TeamMember).filter_by(team_id=team_id, user_id=user_id).delete()
            db.query(Team).filter_by(id=team_id).update(
                {"updated_at": int(time.time())}
            )
            db.commit()
        return True

    def delete_team(self, team_id: str) -> bool:
        with get_db() as db:
            db.query(TeamMember).filter_by(team_id=team_id).delete()
            deleted = db.query(Team).filter_by(id=team_id).delete()
            db.commit()
            return deleted > 0

    def remove_user_from_all_teams(self, user_id: str) -> bool:
        with get_db() as db:
            memberships = db.query(TeamMember).filter_by(user_id=user_id).all()
            for membership in memberships:
                if membership.role == "admin":
                    admin_count = (
                        db.query(TeamMember)
                        .filter(
                            and_(
                                TeamMember.team_id == membership.team_id,
                                TeamMember.role == "admin",
                            )
                        )
                        .count()
                    )
                    if admin_count <= 1:
                        # Promote another member if possible so the team survives.
                        other = (
                            db.query(TeamMember)
                            .filter(
                                and_(
                                    TeamMember.team_id == membership.team_id,
                                    TeamMember.user_id != user_id,
                                )
                            )
                            .first()
                        )
                        if other:
                            other.role = "admin"
            db.query(TeamMember).filter_by(user_id=user_id).delete()
            db.commit()
            return True

    def user_team_ids(self, user_id: str) -> list[str]:
        with get_db() as db:
            return [
                row[0]
                for row in db.query(TeamMember.team_id)
                .filter_by(user_id=user_id)
                .all()
            ]


Teams = TeamTable()
