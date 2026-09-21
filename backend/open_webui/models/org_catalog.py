from typing import Optional

from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Column, Text


class CatalogEnabledForm(BaseModel):
    enabled: bool


RESOURCE_MODEL = "model"
RESOURCE_SKILL = "skill_pack"
RESOURCE_SKILL_ITEM = "skill"
RESOURCE_KNOWLEDGE = "knowledge"


class OrgCatalogOverride(Base):
    __tablename__ = "org_catalog_override"

    organization_id = Column(Text, primary_key=True)
    resource_type = Column(Text, primary_key=True)
    resource_id = Column(Text, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)


class OrgCatalogOverrideModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: str
    resource_type: str
    resource_id: str
    enabled: bool


class OrgCatalogOverrideTable:
    def get(
        self, organization_id: str, resource_type: str, resource_id: str
    ) -> Optional[bool]:
        with get_db() as db:
            row = db.get(
                OrgCatalogOverride,
                (organization_id, resource_type, resource_id),
            )
            return None if row is None else bool(row.enabled)

    def set(
        self,
        organization_id: str,
        resource_type: str,
        resource_id: str,
        enabled: bool,
    ) -> bool:
        with get_db() as db:
            row = db.get(
                OrgCatalogOverride,
                (organization_id, resource_type, resource_id),
            )
            if row is None:
                db.add(
                    OrgCatalogOverride(
                        organization_id=organization_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        enabled=enabled,
                    )
                )
            else:
                row.enabled = enabled
            db.commit()
            return enabled

    def delete_for_resource(self, resource_type: str, resource_id: str) -> None:
        with get_db() as db:
            db.query(OrgCatalogOverride).filter_by(
                resource_type=resource_type, resource_id=resource_id
            ).delete()
            db.commit()

    def delete_for_organization(self, organization_id: str) -> None:
        with get_db() as db:
            db.query(OrgCatalogOverride).filter_by(
                organization_id=organization_id
            ).delete()
            db.commit()


OrgCatalogOverrides = OrgCatalogOverrideTable()
