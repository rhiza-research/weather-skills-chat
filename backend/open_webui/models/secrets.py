import logging
import re
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from open_webui.utils.secret_crypto import decrypt_secret, encrypt_secret
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import BigInteger, Column, Integer, Text, and_, or_

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

SECRET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
MAX_SECRET_VALUE_BYTES = 16 * 1024


class Secret(Base):
    __tablename__ = "secret"

    id = Column(Text, unique=True, primary_key=True)
    name = Column(Text, nullable=False)
    ciphertext = Column(Text, nullable=False)
    nonce = Column(Text, nullable=False)
    key_version = Column(Integer, nullable=False, default=1)
    user_id = Column(Text, nullable=False)
    organization_id = Column(Text, nullable=False)
    visibility = Column(Text, nullable=False, default="private")
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class SecretModel(BaseModel):
    """Metadata only — never includes the plaintext value."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    user_id: str
    organization_id: str
    visibility: str = "private"
    created_at: int
    updated_at: int
    scope: Optional[str] = None
    organization_name: Optional[str] = None
    can_manage: Optional[bool] = None
    overridden: Optional[bool] = None


class SecretForm(BaseModel):
    name: str
    value: str
    organization_id: Optional[str] = None
    visibility: Optional[str] = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not SECRET_NAME_RE.match(v):
            raise ValueError(
                "Name must start with a letter or underscore and contain only letters, digits, and underscores"
            )
        return v

    @field_validator("value")
    @classmethod
    def value_not_empty(cls, v: str) -> str:
        if v is None or v == "":
            raise ValueError("Secret value cannot be empty")
        if len(v.encode("utf-8")) > MAX_SECRET_VALUE_BYTES:
            raise ValueError("Secret value is too large")
        return v


class SecretUpdateForm(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None
    visibility: Optional[str] = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not SECRET_NAME_RE.match(v):
            raise ValueError(
                "Name must start with a letter or underscore and contain only letters, digits, and underscores"
            )
        return v

    @field_validator("value")
    @classmethod
    def value_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v == "":
            raise ValueError("Secret value cannot be empty")
        if len(v.encode("utf-8")) > MAX_SECRET_VALUE_BYTES:
            raise ValueError("Secret value is too large")
        return v


def _to_model(row: Secret) -> SecretModel:
    return SecretModel.model_validate(row)


class SecretTable:
    def insert(self, user_id: str, form: SecretForm) -> Optional[SecretModel]:
        now = int(time.time())
        organization_id = form.organization_id or user_id
        visibility = form.visibility or "private"
        if organization_id == user_id:
            visibility = "private"
        ciphertext, nonce = encrypt_secret(
            form.value,
            name=form.name,
            user_id=user_id,
            organization_id=organization_id,
            visibility=visibility,
        )
        with get_db() as db:
            row = Secret(
                id=str(uuid.uuid4()),
                name=form.name,
                ciphertext=ciphertext,
                nonce=nonce,
                key_version=1,
                user_id=user_id,
                organization_id=organization_id,
                visibility=visibility,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return _to_model(row)

    def get_by_id(self, id: str) -> Optional[Secret]:
        with get_db() as db:
            return db.query(Secret).filter_by(id=id).first()

    def get_private(self, organization_id: str, user_id: str, name: str) -> Optional[Secret]:
        with get_db() as db:
            return (
                db.query(Secret)
                .filter_by(
                    organization_id=organization_id,
                    user_id=user_id,
                    name=name,
                    visibility="private",
                )
                .first()
            )

    def get_shared(self, organization_id: str, name: str) -> Optional[Secret]:
        with get_db() as db:
            return (
                db.query(Secret)
                .filter_by(
                    organization_id=organization_id,
                    name=name,
                    visibility="organization",
                )
                .first()
            )

    def list_for_org(self, organization_id: str, user_id: str) -> list[SecretModel]:
        with get_db() as db:
            rows = (
                db.query(Secret)
                .filter(
                    Secret.organization_id == organization_id,
                    or_(
                        Secret.visibility == "organization",
                        and_(
                            Secret.visibility == "private",
                            Secret.user_id == user_id,
                        ),
                    ),
                )
                .order_by(Secret.name.asc())
                .all()
            )
            return [_to_model(r) for r in rows]

    def update(self, id: str, form: SecretUpdateForm) -> Optional[SecretModel]:
        with get_db() as db:
            row = db.query(Secret).filter_by(id=id).first()
            if not row:
                return None
            name = form.name if form.name is not None else row.name
            visibility = form.visibility if form.visibility is not None else row.visibility
            if form.value is not None:
                ciphertext, nonce = encrypt_secret(
                    form.value,
                    name=name,
                    user_id=row.user_id,
                    organization_id=row.organization_id,
                    visibility=visibility,
                )
                row.ciphertext = ciphertext
                row.nonce = nonce
            elif name != row.name or visibility != row.visibility:
                plaintext = decrypt_secret(
                    row.ciphertext,
                    row.nonce,
                    name=row.name,
                    user_id=row.user_id,
                    organization_id=row.organization_id,
                    visibility=row.visibility,
                )
                ciphertext, nonce = encrypt_secret(
                    plaintext,
                    name=name,
                    user_id=row.user_id,
                    organization_id=row.organization_id,
                    visibility=visibility,
                )
                row.ciphertext = ciphertext
                row.nonce = nonce
            row.name = name
            row.visibility = visibility
            row.updated_at = int(time.time())
            db.commit()
            db.refresh(row)
            return _to_model(row)

    def delete(self, id: str) -> bool:
        with get_db() as db:
            deleted = db.query(Secret).filter_by(id=id).delete()
            db.commit()
            return deleted > 0

    def delete_private_by_user_id(self, user_id: str) -> None:
        with get_db() as db:
            db.query(Secret).filter_by(user_id=user_id, visibility="private").delete()
            db.commit()

    def decrypt(self, row: Secret) -> str:
        return decrypt_secret(
            row.ciphertext,
            row.nonce,
            name=row.name,
            user_id=row.user_id,
            organization_id=row.organization_id,
            visibility=row.visibility,
        )


Secrets = SecretTable()
