import logging
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import BigInteger, Boolean, Column, Text, and_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

PLATFORM_ORG_ID = "platform"
ORG_KIND_PERSONAL = "personal"
ORG_KIND_WORKSPACE = "workspace"
ORG_KIND_PLATFORM = "platform"
ORG_ROLES = ("owner", "admin", "user")
ROLE_RANK = {"user": 1, "admin": 2, "owner": 3}
VISIBILITY_PRIVATE = "private"
VISIBILITY_ORGANIZATION = "organization"
VISIBILITY_PUBLIC = "public"


class Organization(Base):
    __tablename__ = "organization"

    id = Column(Text, unique=True, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    kind = Column(Text, nullable=False)
    created_by = Column(Text, nullable=False)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
    default_models = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    can_add_models = Column(Boolean, nullable=False, default=False)
    can_add_skills = Column(Boolean, nullable=False, default=False)
    can_add_knowledge = Column(Boolean, nullable=False, default=False)


class OrganizationMember(Base):
    __tablename__ = "organization_member"

    organization_id = Column(Text, primary_key=True)
    user_id = Column(Text, primary_key=True)
    role = Column(Text, nullable=False)
    created_at = Column(BigInteger)


class OrganizationMemberModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: str
    user_id: str
    role: str
    created_at: int
    name: Optional[str] = None
    email: Optional[str] = None
    profile_image_url: Optional[str] = None


class OrganizationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    kind: str
    created_by: str
    created_at: int
    updated_at: int
    role: Optional[str] = None
    members: Optional[list[OrganizationMemberModel]] = None
    default_models: Optional[str] = None
    active: bool = True
    can_add_models: bool = False
    can_add_skills: bool = False
    can_add_knowledge: bool = False


class OrganizationForm(BaseModel):
    name: str
    description: Optional[str] = None
    default_models: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Organization name cannot be empty")
        return v


class OrganizationUpdateForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_models: Optional[str] = None
    can_add_models: Optional[bool] = None
    can_add_skills: Optional[bool] = None
    can_add_knowledge: Optional[bool] = None


class OrganizationMemberAddForm(BaseModel):
    user_id: str
    role: str = "user"

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ORG_ROLES:
            raise ValueError("Role must be owner, admin, or user")
        return v


class OrganizationMemberRoleForm(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ORG_ROLES:
            raise ValueError("Role must be owner, admin, or user")
        return v


class OrganizationTable:
    def ensure_personal(self, user_id: str, name: str = "Personal") -> OrganizationModel:
        existing = self.get_organization_by_id(user_id)
        if existing:
            if not self.get_member(user_id, user_id):
                self.add_member(user_id, user_id, "owner")
            return existing
        now = int(time.time())
        with get_db() as db:
            org = Organization(
                id=user_id,
                name=name,
                description="",
                kind=ORG_KIND_PERSONAL,
                created_by=user_id,
                created_at=now,
                updated_at=now,
                active=True,
            )
            member = OrganizationMember(
                organization_id=user_id,
                user_id=user_id,
                role="owner",
                created_at=now,
            )
            db.add(org)
            db.add(member)
            db.commit()
            db.refresh(org)
            return OrganizationModel.model_validate(org)

    def ensure_platform(self, owner_user_id: Optional[str] = None) -> OrganizationModel:
        existing = self.get_organization_by_id(PLATFORM_ORG_ID)
        if existing:
            if owner_user_id and not self.get_member(PLATFORM_ORG_ID, owner_user_id):
                self.add_member(PLATFORM_ORG_ID, owner_user_id, "owner")
            self.adopt_legacy_admins()
            return existing
        now = int(time.time())
        created_by = owner_user_id or PLATFORM_ORG_ID
        with get_db() as db:
            org = Organization(
                id=PLATFORM_ORG_ID,
                name="Platform",
                description="Super-admin organization",
                kind=ORG_KIND_PLATFORM,
                created_by=created_by,
                created_at=now,
                updated_at=now,
                active=True,
            )
            db.add(org)
            if owner_user_id:
                db.add(
                    OrganizationMember(
                        organization_id=PLATFORM_ORG_ID,
                        user_id=owner_user_id,
                        role="owner",
                        created_at=now,
                    )
                )
            db.commit()
            db.refresh(org)
        self.adopt_legacy_admins()
        return OrganizationModel.model_validate(org)

    def insert_new_organization(
        self, user_id: str, form_data: OrganizationForm
    ) -> Optional[OrganizationModel]:
        now = int(time.time())
        org_id = str(uuid.uuid4())
        with get_db() as db:
            org = Organization(
                id=org_id,
                name=form_data.name,
                description=form_data.description or "",
                kind=ORG_KIND_WORKSPACE,
                created_by=user_id,
                created_at=now,
                updated_at=now,
                default_models=form_data.default_models,
                active=False,
            )
            member = OrganizationMember(
                organization_id=org_id,
                user_id=user_id,
                role="owner",
                created_at=now,
            )
            db.add(org)
            db.add(member)
            db.commit()
            db.refresh(org)
            return OrganizationModel.model_validate(org)

    def get_organization_by_id(self, organization_id: str) -> Optional[OrganizationModel]:
        with get_db() as db:
            org = db.query(Organization).filter_by(id=organization_id).first()
            return OrganizationModel.model_validate(org) if org else None

    def get_organizations_by_user_id(self, user_id: str) -> list[OrganizationModel]:
        self.ensure_personal(user_id)
        with get_db() as db:
            rows = (
                db.query(Organization, OrganizationMember.role)
                .join(
                    OrganizationMember,
                    Organization.id == OrganizationMember.organization_id,
                )
                .filter(
                    OrganizationMember.user_id == user_id,
                    Organization.active.is_(True),
                )
                .order_by(Organization.kind.asc(), Organization.name.asc())
                .all()
            )
            result = []
            for org, role in rows:
                model = OrganizationModel.model_validate(org)
                model.role = role
                result.append(model)
            return result

    def get_all_organizations(self) -> list[OrganizationModel]:
        with get_db() as db:
            return [
                OrganizationModel.model_validate(org)
                for org in db.query(Organization).order_by(Organization.name.asc()).all()
            ]

    def get_member(
        self, organization_id: str, user_id: str
    ) -> Optional[OrganizationMemberModel]:
        with get_db() as db:
            member = (
                db.query(OrganizationMember)
                .filter_by(organization_id=organization_id, user_id=user_id)
                .first()
            )
            return OrganizationMemberModel.model_validate(member) if member else None

    def get_members(self, organization_id: str) -> list[OrganizationMemberModel]:
        from open_webui.models.users import User

        with get_db() as db:
            rows = (
                db.query(OrganizationMember, User)
                .outerjoin(User, OrganizationMember.user_id == User.id)
                .filter(OrganizationMember.organization_id == organization_id)
                .order_by(OrganizationMember.created_at.asc())
                .all()
            )
            members = []
            for member, user in rows:
                model = OrganizationMemberModel.model_validate(member)
                if user:
                    model.name = user.name
                    model.email = user.email
                    model.profile_image_url = user.profile_image_url
                members.append(model)
            return members

    def count_role(self, organization_id: str, role: str) -> int:
        with get_db() as db:
            return (
                db.query(OrganizationMember)
                .filter(
                    and_(
                        OrganizationMember.organization_id == organization_id,
                        OrganizationMember.role == role,
                    )
                )
                .count()
            )

    def set_active(
        self, organization_id: str, active: bool
    ) -> Optional[OrganizationModel]:
        org = self.get_organization_by_id(organization_id)
        if not org:
            return None
        if org.kind in (ORG_KIND_PERSONAL, ORG_KIND_PLATFORM) and not active:
            raise ValueError("Cannot deactivate this organization")
        with get_db() as db:
            db.query(Organization).filter_by(id=organization_id).update(
                {"active": active, "updated_at": int(time.time())}
            )
            db.commit()
        return self.get_organization_by_id(organization_id)

    def update_organization(
        self, organization_id: str, form_data: OrganizationUpdateForm
    ) -> Optional[OrganizationModel]:
        updates = form_data.model_dump(exclude_none=True)
        if "name" in updates:
            updates["name"] = updates["name"].strip()
            if not updates["name"]:
                raise ValueError("Organization name cannot be empty")
        if not updates:
            return self.get_organization_by_id(organization_id)

        updates["updated_at"] = int(time.time())
        with get_db() as db:
            db.query(Organization).filter_by(id=organization_id).update(updates)
            db.commit()
        return self.get_organization_by_id(organization_id)

    def add_member(
        self, organization_id: str, user_id: str, role: str = "user"
    ) -> Optional[OrganizationMemberModel]:
        if role not in ORG_ROLES:
            raise ValueError("Role must be owner, admin, or user")
        org = self.get_organization_by_id(organization_id)
        if not org:
            raise ValueError("Organization not found")
        if org.kind == ORG_KIND_PERSONAL and not (
            user_id == organization_id and role == "owner"
        ):
            raise ValueError("Cannot add members to a personal organization")
        if org.kind == ORG_KIND_PLATFORM and role == "user":
            raise ValueError("Platform organization members must be owner or admin")
        existing = self.get_member(organization_id, user_id)
        if existing:
            return existing
        with get_db() as db:
            member = OrganizationMember(
                organization_id=organization_id,
                user_id=user_id,
                role=role,
                created_at=int(time.time()),
            )
            db.add(member)
            db.query(Organization).filter_by(id=organization_id).update(
                {"updated_at": int(time.time())}
            )
            db.commit()
            db.refresh(member)
        self.activate_if_pending(user_id)
        return OrganizationMemberModel.model_validate(member)

    def update_member_role(
        self, organization_id: str, user_id: str, role: str
    ) -> Optional[OrganizationMemberModel]:
        if role not in ORG_ROLES:
            raise ValueError("Role must be owner, admin, or user")
        org = self.get_organization_by_id(organization_id)
        if org and org.kind == ORG_KIND_PERSONAL:
            raise ValueError("Cannot change roles on a personal organization")
        if org and org.kind == ORG_KIND_PLATFORM and role == "user":
            raise ValueError("Platform organization members must be owner or admin")
        member = self.get_member(organization_id, user_id)
        if not member:
            return None
        if (
            member.role == "owner"
            and role != "owner"
            and self.count_role(organization_id, "owner") <= 1
        ):
            raise ValueError("Cannot demote the last owner")
        with get_db() as db:
            db.query(OrganizationMember).filter_by(
                organization_id=organization_id, user_id=user_id
            ).update({"role": role})
            db.query(Organization).filter_by(id=organization_id).update(
                {"updated_at": int(time.time())}
            )
            db.commit()
        return self.get_member(organization_id, user_id)

    def remove_member(self, organization_id: str, user_id: str) -> bool:
        org = self.get_organization_by_id(organization_id)
        if org and org.kind == ORG_KIND_PERSONAL:
            raise ValueError("Cannot remove the owner of a personal organization")
        member = self.get_member(organization_id, user_id)
        if not member:
            return False
        if member.role == "owner" and self.count_role(organization_id, "owner") <= 1:
            raise ValueError("Cannot remove the last owner")
        with get_db() as db:
            db.query(OrganizationMember).filter_by(
                organization_id=organization_id, user_id=user_id
            ).delete()
            db.query(Organization).filter_by(id=organization_id).update(
                {"updated_at": int(time.time())}
            )
            db.commit()
        return True

    def delete_organization(self, organization_id: str) -> bool:
        org = self.get_organization_by_id(organization_id)
        if not org:
            return False
        if org.kind in (ORG_KIND_PERSONAL, ORG_KIND_PLATFORM):
            raise ValueError("Cannot delete this organization")
        self._delete_organization_resources(organization_id)
        with get_db() as db:
            db.query(OrganizationMember).filter_by(
                organization_id=organization_id
            ).delete()
            deleted = db.query(Organization).filter_by(id=organization_id).delete()
            db.commit()
            return deleted > 0

    def _delete_organization_resources(self, organization_id: str) -> None:
        from open_webui.models.automations import Automation, AutomationRun
        from open_webui.models.chats import Chat
        from open_webui.models.folders import Folder
        from open_webui.models.knowledge import Knowledge
        from open_webui.models.models import Model
        from open_webui.models.org_catalog import OrgCatalogOverride
        from open_webui.models.secrets import Secret
        from open_webui.models.skill_packs import SkillPack

        with get_db() as db:
            chat_ids = [
                row[0]
                for row in db.query(Chat.id)
                .filter_by(organization_id=organization_id)
                .all()
            ]
            automation_ids = [
                row[0]
                for row in db.query(Automation.id)
                .filter_by(organization_id=organization_id)
                .all()
            ]
            if automation_ids:
                db.query(AutomationRun).filter(
                    AutomationRun.automation_id.in_(automation_ids)
                ).delete(synchronize_session=False)
            if chat_ids:
                db.query(Chat).filter(Chat.id.in_(chat_ids)).delete(
                    synchronize_session=False
                )
            db.query(Secret).filter_by(organization_id=organization_id).delete()
            db.query(Folder).filter_by(organization_id=organization_id).delete()
            db.query(SkillPack).filter_by(organization_id=organization_id).delete()
            db.query(Knowledge).filter_by(organization_id=organization_id).delete()
            db.query(Automation).filter_by(organization_id=organization_id).delete()
            db.query(Model).filter_by(organization_id=organization_id).delete()
            db.query(OrgCatalogOverride).filter_by(organization_id=organization_id).delete()
            db.commit()

    def delete_personal_org(self, user_id: str) -> bool:
        if self.get_organization_by_id(user_id):
            self._delete_organization_resources(user_id)
            with get_db() as db:
                db.query(OrganizationMember).filter_by(organization_id=user_id).delete()
                db.query(Organization).filter_by(id=user_id).delete()
                db.commit()
        return True

    def delete_private_workspace_resources(self, user_id: str) -> None:
        from open_webui.models.automations import Automation, AutomationRun
        from open_webui.models.chats import Chat, Chats
        from open_webui.models.folders import Folder
        from open_webui.models.knowledge import Knowledge
        from open_webui.models.secrets import Secret
        from open_webui.models.skill_packs import SkillPack

        Chats.delete_shared_chats_by_user_id(user_id)
        with get_db() as db:
            private_automation_ids = [
                row[0]
                for row in db.query(Automation.id)
                .filter_by(user_id=user_id, visibility="private")
                .all()
            ]
            if private_automation_ids:
                db.query(AutomationRun).filter(
                    AutomationRun.automation_id.in_(private_automation_ids)
                ).delete(synchronize_session=False)
            db.query(Chat).filter_by(user_id=user_id, visibility="private").delete()
            db.query(Secret).filter_by(user_id=user_id, visibility="private").delete()
            db.query(Folder).filter_by(user_id=user_id, visibility="private").delete()
            db.query(SkillPack).filter_by(user_id=user_id, visibility="private").delete()
            db.query(Knowledge).filter_by(
                user_id=user_id, visibility="private"
            ).delete()
            db.query(Automation).filter_by(
                user_id=user_id, visibility="private"
            ).delete()
            db.commit()

    def remove_user_from_all_organizations(self, user_id: str) -> bool:
        with get_db() as db:
            memberships = (
                db.query(OrganizationMember).filter_by(user_id=user_id).all()
            )
            for membership in memberships:
                org = (
                    db.query(Organization)
                    .filter_by(id=membership.organization_id)
                    .first()
                )
                if not org or org.kind == ORG_KIND_PERSONAL:
                    continue
                if membership.role == "owner":
                    owner_count = (
                        db.query(OrganizationMember)
                        .filter(
                            and_(
                                OrganizationMember.organization_id
                                == membership.organization_id,
                                OrganizationMember.role == "owner",
                            )
                        )
                        .count()
                    )
                    if owner_count <= 1:
                        other = (
                            db.query(OrganizationMember)
                            .filter(
                                and_(
                                    OrganizationMember.organization_id
                                    == membership.organization_id,
                                    OrganizationMember.user_id != user_id,
                                )
                            )
                            .first()
                        )
                        if other:
                            other.role = "owner"
            db.query(OrganizationMember).filter(
                and_(
                    OrganizationMember.user_id == user_id,
                    OrganizationMember.organization_id != user_id,
                )
            ).delete(synchronize_session=False)
            db.commit()
        return True

    def user_organization_ids(self, user_id: str) -> list[str]:
        with get_db() as db:
            return [
                row[0]
                for row in db.query(OrganizationMember.organization_id)
                .join(
                    Organization,
                    Organization.id == OrganizationMember.organization_id,
                )
                .filter(
                    OrganizationMember.user_id == user_id,
                    Organization.active.is_(True),
                )
                .all()
            ]

    def activate_if_pending(self, user_id: str) -> None:
        from open_webui.models.users import Users

        user = Users.get_user_by_id(user_id)
        if user and user.role == "pending":
            Users.update_user_role_by_id(user_id, "user")

    def adopt_legacy_admins(self) -> None:
        """Existing global admins become platform-org admins; role is no longer stored."""
        from open_webui.internal.db import get_db
        from open_webui.models.users import User

        with get_db() as db:
            admin_ids = [
                row[0] for row in db.query(User.id).filter(User.role == "admin").all()
            ]
        for user_id in admin_ids:
            if not self.get_member(PLATFORM_ORG_ID, user_id):
                try:
                    self.add_member(PLATFORM_ORG_ID, user_id, "admin")
                except ValueError:
                    continue


Organizations = OrganizationTable()
