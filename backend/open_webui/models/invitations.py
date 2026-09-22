import hashlib
import hmac
import logging
import secrets
import time
import uuid
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Float, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

INVITE_TTL_SECONDS = 7 * 24 * 60 * 60
KIND_PLATFORM = "platform"
KIND_ORGANIZATION = "organization"


class Invitation(Base):
    __tablename__ = "invitation"

    id = Column(Text, primary_key=True)
    email = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    organization_id = Column(Text, nullable=True)
    role = Column(Text, nullable=False)
    token_hash = Column(Text, nullable=False, unique=True)
    expires_at = Column(BigInteger, nullable=False)
    created_by = Column(Text, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    accepted_at = Column(BigInteger, nullable=True)
    monthly_limit_usd = Column(Float, nullable=True)


class InvitationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    kind: str
    organization_id: Optional[str] = None
    role: str
    expires_at: int
    created_by: str
    created_at: int
    accepted_at: Optional[int] = None
    monthly_limit_usd: Optional[float] = None

    @property
    def expired(self) -> bool:
        return self.accepted_at is None and self.expires_at < int(time.time())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


class InvitationTable:
    def issue(
        self,
        email: str,
        kind: str,
        created_by: str,
        role: str = "user",
        organization_id: Optional[str] = None,
        monthly_limit_usd: Optional[float] = 300,
    ) -> tuple[InvitationModel, str]:
        now = int(time.time())
        token = generate_token()
        token_hash = hash_token(token)
        expires_at = now + INVITE_TTL_SECONDS
        with get_db() as db:
            query = db.query(Invitation).filter(
                Invitation.email == email,
                Invitation.kind == kind,
                Invitation.accepted_at.is_(None),
            )
            if organization_id:
                query = query.filter(Invitation.organization_id == organization_id)
            else:
                query = query.filter(Invitation.organization_id.is_(None))
            existing = query.first()
            if existing:
                existing.token_hash = token_hash
                existing.expires_at = expires_at
                existing.created_by = created_by
                existing.role = role
                existing.monthly_limit_usd = monthly_limit_usd
                existing.created_at = now
                db.commit()
                db.refresh(existing)
                row = existing
            else:
                row = Invitation(
                    id=str(uuid.uuid4()),
                    email=email,
                    kind=kind,
                    organization_id=organization_id,
                    role=role,
                    monthly_limit_usd=monthly_limit_usd,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    created_by=created_by,
                    created_at=now,
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            return InvitationModel.model_validate(row), token

    def list_outstanding(
        self, kind: str, organization_id: Optional[str] = None
    ) -> list[InvitationModel]:
        with get_db() as db:
            query = db.query(Invitation).filter(
                Invitation.kind == kind,
                Invitation.accepted_at.is_(None),
            )
            if organization_id:
                query = query.filter(Invitation.organization_id == organization_id)
            else:
                query = query.filter(Invitation.organization_id.is_(None))
            rows = query.order_by(Invitation.created_at.desc()).all()
            return [InvitationModel.model_validate(row) for row in rows]

    def get_by_id(self, invitation_id: str) -> Optional[InvitationModel]:
        with get_db() as db:
            row = db.query(Invitation).filter_by(id=invitation_id).first()
            return InvitationModel.model_validate(row) if row else None

    def get_by_token(self, token: str) -> Optional[InvitationModel]:
        token_hash = hash_token(token or "")
        with get_db() as db:
            row = db.query(Invitation).filter_by(token_hash=token_hash).first()
            if not row or not token_matches(token, row.token_hash):
                return None
            return InvitationModel.model_validate(row)

    def resend(self, invitation_id: str, created_by: str) -> tuple[InvitationModel, str]:
        current = self.get_by_id(invitation_id)
        if not current or current.accepted_at is not None:
            raise ValueError(
                "Sorry, we couldn't find that invitation. It may have been canceled"
            )
        return self.issue(
            email=current.email,
            kind=current.kind,
            created_by=created_by,
            role=current.role,
            organization_id=current.organization_id,
            monthly_limit_usd=current.monthly_limit_usd,
        )

    def cancel(self, invitation_id: str) -> bool:
        with get_db() as db:
            row = db.query(Invitation).filter_by(id=invitation_id).first()
            if not row or row.accepted_at is not None:
                return False
            db.delete(row)
            db.commit()
            return True

    def mark_accepted(self, invitation_id: str) -> Optional[InvitationModel]:
        now = int(time.time())
        with get_db() as db:
            row = db.query(Invitation).filter_by(id=invitation_id).first()
            if not row:
                return None
            row.accepted_at = now
            db.commit()
            db.refresh(row)
            return InvitationModel.model_validate(row)


Invitations = InvitationTable()
