import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_db
from open_webui.env import SRC_LOG_LEVELS

from open_webui.models.users import Users, UserResponse


from pydantic import BaseModel, ConfigDict

from sqlalchemy import or_, and_, func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy import BigInteger, Column, Text, JSON, Boolean
from sqlalchemy.orm import aliased


from open_webui.utils.access_control import has_access


log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Models DB Schema
####################


# ModelParams is a model for the data stored in the params field of the Model table
class ModelParams(BaseModel):
    model_config = ConfigDict(extra="allow")
    pass


# ModelMeta is a model for the data stored in the meta field of the Model table
class ModelMeta(BaseModel):
    profile_image_url: Optional[str] = "/static/favicon.png"

    description: Optional[str] = None
    """
        User-facing description of the model.
    """

    capabilities: Optional[dict] = None

    model_config = ConfigDict(extra="allow")

    pass


class Model(Base):
    __tablename__ = "model"

    id = Column(Text, primary_key=True)
    """
        The model's id as used in the API. If set to an existing model, it will override the model.
    """
    user_id = Column(Text)

    base_model_id = Column(Text, nullable=True)
    """
        An optional pointer to the actual model that should be used when proxying requests.
    """

    name = Column(Text)
    """
        The human-readable display name of the model.
    """

    params = Column(JSONField)
    """
        Holds a JSON encoded blob of parameters, see `ModelParams`.
    """

    meta = Column(JSONField)
    """
        Holds a JSON encoded blob of metadata, see `ModelMeta`.
    """

    access_control = Column(JSON, nullable=True)  # Controls data access levels.
    # Defines access control rules for this entry.
    # - `None`: Public access, available to all users with the "user" role.
    # - `{}`: Private access, restricted exclusively to the owner.
    # - Custom permissions: Specific access control for reading and writing;
    #   Can specify group or user-level restrictions:
    #   {
    #      "read": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      },
    #      "write": {
    #          "group_ids": ["group_id1", "group_id2"],
    #          "user_ids":  ["user_id1", "user_id2"]
    #      }
    #   }

    is_active = Column(Boolean, default=True)

    organization_id = Column(Text, nullable=False)
    visibility = Column(Text, nullable=False, default="organization")
    enabled_by_default = Column(Boolean, nullable=False, default=True)

    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


class ModelModel(BaseModel):
    id: str
    user_id: str
    base_model_id: Optional[str] = None

    name: str
    params: ModelParams
    meta: ModelMeta

    access_control: Optional[dict] = None

    is_active: bool
    organization_id: Optional[str] = None
    visibility: str = "organization"
    enabled_by_default: bool = True
    enabled: Optional[bool] = None
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True)


####################
# Forms
####################


class ModelUserResponse(ModelModel):
    user: Optional[UserResponse] = None


class ModelResponse(ModelModel):
    pass


class ModelForm(BaseModel):
    id: str
    base_model_id: Optional[str] = None
    name: str
    meta: ModelMeta
    params: ModelParams
    access_control: Optional[dict] = None
    is_active: bool = True
    enabled_by_default: bool = True
    organization_id: Optional[str] = None
    visibility: Optional[str] = None


class ModelsTable:
    def insert_new_model(
        self, form_data: ModelForm, user_id: str
    ) -> Optional[ModelModel]:
        model = ModelModel(
            **{
                **form_data.model_dump(exclude={"enabled"}),
                "user_id": user_id,
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }
        )
        try:
            with get_db() as db:
                result = Model(
                    **{
                        **model.model_dump(exclude={"enabled", "user"}),
                    }
                )
                db.add(result)
                db.commit()
                db.refresh(result)

                if result:
                    return ModelModel.model_validate(result)
                else:
                    return None
        except Exception as e:
            log.exception(f"Failed to insert a new model: {e}")
            return None

    def get_all_models(self) -> list[ModelModel]:
        with get_db() as db:
            return [ModelModel.model_validate(model) for model in db.query(Model).all()]

    def get_models(self) -> list[ModelUserResponse]:
        with get_db() as db:
            models = []
            for model in db.query(Model).filter(Model.base_model_id != None).all():
                user = Users.get_user_by_id(model.user_id)
                models.append(
                    ModelUserResponse.model_validate(
                        {
                            **ModelModel.model_validate(model).model_dump(),
                            "user": user.model_dump() if user else None,
                        }
                    )
                )
            return models

    def list_for_organization(
        self, organization_id: str, *, enabled_only: bool = False
    ) -> list[ModelUserResponse]:
        """Catalog chat models visible to one org, including each owner's row.

        ``enabled_only`` keeps models the org can actually use in chat.
        Otherwise the list includes public models that are turned off, so the
        workspace page can turn them back on. One query either way.
        """
        from open_webui.models.org_catalog import RESOURCE_MODEL, OrgCatalogOverride
        from open_webui.models.organizations import PLATFORM_ORG_ID, VISIBILITY_PUBLIC
        from open_webui.models.users import User

        override = aliased(OrgCatalogOverride)
        public = Model.visibility == VISIBILITY_PUBLIC
        private_here = and_(
            Model.visibility != VISIBILITY_PUBLIC,
            Model.organization_id == organization_id,
        )
        active = or_(Model.is_active.is_(True), Model.is_active.is_(None))
        if organization_id == PLATFORM_ORG_ID:
            visible = or_(public, private_here)
        else:
            visible = or_(and_(public, active), private_here)

        enabled = or_(
            private_here,
            and_(
                public,
                or_(
                    override.enabled.is_(True),
                    and_(
                        override.enabled.is_(None),
                        Model.enabled_by_default.is_(True),
                    ),
                ),
            ),
        )

        with get_db() as db:
            query = (
                db.query(Model, User, override.enabled.label("override_enabled"))
                .outerjoin(User, User.id == Model.user_id)
                .outerjoin(
                    override,
                    and_(
                        override.organization_id == organization_id,
                        override.resource_type == RESOURCE_MODEL,
                        override.resource_id == Model.id,
                    ),
                )
                .filter(Model.base_model_id.isnot(None))
                .filter(visible)
            )
            if enabled_only:
                query = query.filter(active).filter(enabled)

            models = []
            for model, user, override_enabled in query.all():
                data = ModelModel.model_validate(model).model_dump()
                if model.visibility == VISIBILITY_PUBLIC:
                    data["enabled"] = (
                        bool(model.enabled_by_default)
                        if override_enabled is None
                        else bool(override_enabled)
                    )
                else:
                    data["enabled"] = True
                data["user"] = (
                    {
                        "id": user.id,
                        "name": user.name,
                        "email": user.email,
                        "role": user.role,
                        "profile_image_url": user.profile_image_url,
                    }
                    if user
                    else None
                )
                models.append(ModelUserResponse.model_validate(data))
            return models

    def get_base_models(self) -> list[ModelModel]:
        with get_db() as db:
            return [
                ModelModel.model_validate(model)
                for model in db.query(Model).filter(Model.base_model_id == None).all()
            ]

    def get_models_by_user_id(
        self, user_id: str, permission: str = "write"
    ) -> list[ModelUserResponse]:
        models = self.get_models()
        return [
            model
            for model in models
            if model.user_id == user_id
            or has_access(user_id, permission, model.access_control)
        ]

    def get_model_by_id(self, id: str) -> Optional[ModelModel]:
        try:
            with get_db() as db:
                model = db.get(Model, id)
                return ModelModel.model_validate(model)
        except Exception:
            return None

    def toggle_model_by_id(self, id: str) -> Optional[ModelModel]:
        with get_db() as db:
            try:
                is_active = db.query(Model).filter_by(id=id).first().is_active

                db.query(Model).filter_by(id=id).update(
                    {
                        "is_active": not is_active,
                        "updated_at": int(time.time()),
                    }
                )
                db.commit()

                return self.get_model_by_id(id)
            except Exception:
                return None

    def set_enabled_by_default(
        self, id: str, enabled_by_default: bool
    ) -> Optional[ModelModel]:
        with get_db() as db:
            try:
                db.query(Model).filter_by(id=id).update(
                    {
                        "enabled_by_default": bool(enabled_by_default),
                        "updated_at": int(time.time()),
                    }
                )
                db.commit()
                return self.get_model_by_id(id)
            except Exception:
                return None

    def update_model_by_id(self, id: str, model: ModelForm) -> Optional[ModelModel]:
        try:
            with get_db() as db:
                # update only the fields that are present in the model
                result = (
                    db.query(Model)
                    .filter_by(id=id)
                    .update(model.model_dump(exclude={"id", "enabled", "user"}))
                )
                db.commit()

                model = db.get(Model, id)
                db.refresh(model)
                return ModelModel.model_validate(model)
        except Exception as e:
            log.exception(f"Failed to update the model by id {id}: {e}")
            return None

    def delete_model_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Model).filter_by(id=id).delete()
                db.commit()

                return True
        except Exception:
            return False

    def delete_all_models(self) -> bool:
        try:
            with get_db() as db:
                db.query(Model).delete()
                db.commit()

                return True
        except Exception:
            return False


Models = ModelsTable()
