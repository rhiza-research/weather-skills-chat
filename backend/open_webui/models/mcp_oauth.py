"""Storage for the MCP endpoint's OAuth authorization server.

Codes, tokens and pending authorization requests are stored only as the SHA-256 hex digest of the
value handed out. Each single-use value is consumed by one conditional UPDATE whose row count is
checked, so two processes presenting the same value see exactly one success.

Registered clients are public, so no client secret is stored.
"""

import hashlib
import logging
import time
import uuid
from typing import Callable, Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.internal.db import Base, JSONField, get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Index,
    Text,
    and_,
    exists,
    or_,
    update,
)
from sqlalchemy.exc import IntegrityError

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

# Kinds of row in the token table.
ACCESS = "access"
REFRESH = "refresh"


def digest(value: str) -> str:
    """The SHA-256 hex digest under which a code, token or request id is stored."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class McpOAuthClient(Base):
    __tablename__ = "mcp_oauth_client"

    client_id = Column(Text, primary_key=True)
    # The registered metadata.
    client_info = Column(JSONField, nullable=False)
    created_at = Column(BigInteger, nullable=False)


class McpOAuthAuthorization(Base):
    """An authorization request waiting for the user's decision on the consent page."""

    __tablename__ = "mcp_oauth_authorization"
    __table_args__ = (
        Index("ix_mcp_oauth_authorization_client_id", "client_id"),
        Index("ix_mcp_oauth_authorization_expires_at", "expires_at"),
    )

    request_hash = Column(Text, primary_key=True)
    client_id = Column(Text, nullable=False)
    redirect_uri = Column(Text, nullable=False)
    redirect_uri_provided_explicitly = Column(Boolean, nullable=False)
    state = Column(Text, nullable=True)
    code_challenge = Column(Text, nullable=False)
    scopes = Column(JSONField, nullable=False)
    resource = Column(Text, nullable=False)
    # Set when the consent page is shown to a signed-in user. The decision must come from the same
    # user and carry the form value whose digest is stored here.
    user_id = Column(Text, nullable=True)
    form_hash = Column(Text, nullable=True)
    expires_at = Column(BigInteger, nullable=False)
    consumed_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)


class McpOAuthCode(Base):
    __tablename__ = "mcp_oauth_code"
    __table_args__ = (
        Index("ix_mcp_oauth_code_client_id", "client_id"),
        Index("ix_mcp_oauth_code_expires_at", "expires_at"),
    )

    code_hash = Column(Text, primary_key=True)
    client_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    redirect_uri = Column(Text, nullable=False)
    redirect_uri_provided_explicitly = Column(Boolean, nullable=False)
    code_challenge = Column(Text, nullable=False)
    scopes = Column(JSONField, nullable=False)
    resource = Column(Text, nullable=False)
    expires_at = Column(BigInteger, nullable=False)
    used_at = Column(BigInteger, nullable=True)
    # The grant of the tokens issued for this code. Set when the code is exchanged.
    grant_id = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)


class McpOAuthToken(Base):
    """An access or refresh token. Tokens issued from one code share a grant_id."""

    __tablename__ = "mcp_oauth_token"
    __table_args__ = (
        Index("ix_mcp_oauth_token_grant_id", "grant_id"),
        Index("ix_mcp_oauth_token_client_id", "client_id"),
        Index("ix_mcp_oauth_token_expires_at", "expires_at"),
    )

    token_hash = Column(Text, primary_key=True)
    kind = Column(Text, nullable=False)
    grant_id = Column(Text, nullable=False)
    client_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    scopes = Column(JSONField, nullable=False)
    resource = Column(Text, nullable=False)
    expires_at = Column(BigInteger, nullable=False)
    revoked_at = Column(BigInteger, nullable=True)
    # Set on a refresh token when a refresh replaced it, with revoked_at. Not set by revocation.
    rotated_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)


class AuthorizationRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_hash: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    state: Optional[str] = None
    code_challenge: str
    scopes: list[str]
    resource: str
    user_id: Optional[str] = None
    form_hash: Optional[str] = None
    expires_at: int


class CodeRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code_hash: str
    client_id: str
    user_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    scopes: list[str]
    resource: str
    expires_at: int


class TokenRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token_hash: str
    kind: str
    grant_id: str
    client_id: str
    user_id: str
    scopes: list[str]
    resource: str
    expires_at: int


class IssuedTokens(BaseModel):
    """Raw values handed to the client once. Only their digests are stored."""

    access_token: str
    refresh_token: str
    access_expires_at: int
    scopes: list[str]


class ClientExistsError(Exception):
    """A client with this client_id is already registered."""


class McpOAuthTable:
    """Queries for the authorization server. Callers pass raw values; digests are computed here.

    `session_factory` is the context manager that yields a session. It defaults to the
    application's database.
    """

    def __init__(self, session_factory: Callable = get_db):
        self._session = session_factory

    # Clients

    def insert_client(self, client_id: str, client_info: dict) -> None:
        """Insert a client. Raises ClientExistsError when the client_id is taken; never replaces."""
        with self._session() as db:
            db.add(
                McpOAuthClient(
                    client_id=client_id,
                    client_info=client_info,
                    created_at=int(time.time()),
                )
            )
            try:
                db.commit()
            except IntegrityError as error:
                db.rollback()
                raise ClientExistsError(client_id) from error

    def get_client(self, client_id: str) -> Optional[dict]:
        """The client's stored metadata, or None."""
        with self._session() as db:
            row = db.query(McpOAuthClient).filter_by(client_id=client_id).first()
            return dict(row.client_info) if row else None

    # Pending authorization requests

    def insert_authorization(
        self,
        request_id: str,
        *,
        client_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        state: Optional[str],
        code_challenge: str,
        scopes: list[str],
        resource: str,
        expires_at: int,
    ) -> None:
        with self._session() as db:
            db.add(
                McpOAuthAuthorization(
                    request_hash=digest(request_id),
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                    state=state,
                    code_challenge=code_challenge,
                    scopes=scopes,
                    resource=resource,
                    expires_at=expires_at,
                    created_at=int(time.time()),
                )
            )
            db.commit()

    def get_authorization(self, request_id: str) -> Optional[AuthorizationRecord]:
        """The pending request, or None when unknown, expired or already decided."""
        now = int(time.time())
        with self._session() as db:
            row = (
                db.query(McpOAuthAuthorization)
                .filter(
                    McpOAuthAuthorization.request_hash == digest(request_id),
                    McpOAuthAuthorization.consumed_at.is_(None),
                    McpOAuthAuthorization.expires_at > now,
                )
                .first()
            )
            return AuthorizationRecord.model_validate(row) if row else None

    def bind_authorization(self, request_id: str, user_id: str, form_value: str) -> bool:
        """Record which user was shown the consent page and the digest of its form value.

        The first user to view the page is bound to the request. A later view by another user
        changes nothing and returns False; a later view by the same user issues a new form value.
        """
        now = int(time.time())
        with self._session() as db:
            result = db.execute(
                update(McpOAuthAuthorization)
                .where(
                    McpOAuthAuthorization.request_hash == digest(request_id),
                    McpOAuthAuthorization.consumed_at.is_(None),
                    McpOAuthAuthorization.expires_at > now,
                    or_(
                        McpOAuthAuthorization.user_id.is_(None),
                        McpOAuthAuthorization.user_id == user_id,
                    ),
                )
                .values(user_id=user_id, form_hash=digest(form_value))
            )
            db.commit()
            return result.rowcount == 1

    def consume_authorization(self, request_id: str, user_id: str, form_value: str) -> bool:
        """Mark the request decided. True for exactly one caller, and only for the bound user."""
        now = int(time.time())
        with self._session() as db:
            result = db.execute(
                update(McpOAuthAuthorization)
                .where(
                    McpOAuthAuthorization.request_hash == digest(request_id),
                    McpOAuthAuthorization.consumed_at.is_(None),
                    McpOAuthAuthorization.expires_at > now,
                    McpOAuthAuthorization.user_id == user_id,
                    McpOAuthAuthorization.form_hash == digest(form_value),
                )
                .values(consumed_at=now)
            )
            db.commit()
            return result.rowcount == 1

    # Codes

    def insert_code(
        self,
        code: str,
        *,
        client_id: str,
        user_id: str,
        redirect_uri: str,
        redirect_uri_provided_explicitly: bool,
        code_challenge: str,
        scopes: list[str],
        resource: str,
        expires_at: int,
    ) -> None:
        with self._session() as db:
            db.add(
                McpOAuthCode(
                    code_hash=digest(code),
                    client_id=client_id,
                    user_id=user_id,
                    redirect_uri=redirect_uri,
                    redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
                    code_challenge=code_challenge,
                    scopes=scopes,
                    resource=resource,
                    expires_at=expires_at,
                    created_at=int(time.time()),
                )
            )
            db.commit()

    def get_code(self, code: str) -> Optional[CodeRecord]:
        """The code, or None when unknown, expired or already used."""
        now = int(time.time())
        with self._session() as db:
            row = (
                db.query(McpOAuthCode)
                .filter(
                    McpOAuthCode.code_hash == digest(code),
                    McpOAuthCode.used_at.is_(None),
                    McpOAuthCode.expires_at > now,
                )
                .first()
            )
            return CodeRecord.model_validate(row) if row else None

    def exchange_code(
        self,
        code: str,
        *,
        client_id: str,
        new_access: str,
        new_refresh: str,
        access_expires_at: int,
        refresh_expires_at: int,
    ) -> Optional[IssuedTokens]:
        """Consume the code and store the tokens issued for it, in one transaction.

        Returns None unless this call's UPDATE marked the code used.
        """
        now = int(time.time())
        grant_id = str(uuid.uuid4())
        with self._session() as db:
            result = db.execute(
                update(McpOAuthCode)
                .where(
                    McpOAuthCode.code_hash == digest(code),
                    McpOAuthCode.client_id == client_id,
                    McpOAuthCode.used_at.is_(None),
                    McpOAuthCode.expires_at > now,
                )
                .values(used_at=now, grant_id=grant_id)
            )
            if result.rowcount != 1:
                db.rollback()
                self.revoke_reused_code(code)
                return None
            row = db.query(McpOAuthCode).filter_by(code_hash=digest(code)).first()
            self._add_token_pair(
                db,
                grant_id=grant_id,
                client_id=row.client_id,
                user_id=row.user_id,
                scopes=list(row.scopes),
                resource=row.resource,
                new_access=new_access,
                new_refresh=new_refresh,
                access_expires_at=access_expires_at,
                refresh_expires_at=refresh_expires_at,
                now=now,
            )
            db.commit()
            return IssuedTokens(
                access_token=new_access,
                refresh_token=new_refresh,
                access_expires_at=access_expires_at,
                scopes=list(row.scopes),
            )

    # Tokens

    @staticmethod
    def _add_token_pair(
        db,
        *,
        grant_id: str,
        client_id: str,
        user_id: str,
        scopes: list[str],
        resource: str,
        new_access: str,
        new_refresh: str,
        access_expires_at: int,
        refresh_expires_at: int,
        now: int,
    ) -> None:
        for kind, value, expires_at in (
            (ACCESS, new_access, access_expires_at),
            (REFRESH, new_refresh, refresh_expires_at),
        ):
            db.add(
                McpOAuthToken(
                    token_hash=digest(value),
                    kind=kind,
                    grant_id=grant_id,
                    client_id=client_id,
                    user_id=user_id,
                    scopes=scopes,
                    resource=resource,
                    expires_at=expires_at,
                    created_at=now,
                )
            )

    def insert_token(
        self,
        value: str,
        *,
        kind: str,
        grant_id: str,
        client_id: str,
        user_id: str,
        scopes: list[str],
        resource: str,
        expires_at: int,
    ) -> None:
        with self._session() as db:
            db.add(
                McpOAuthToken(
                    token_hash=digest(value),
                    kind=kind,
                    grant_id=grant_id,
                    client_id=client_id,
                    user_id=user_id,
                    scopes=scopes,
                    resource=resource,
                    expires_at=expires_at,
                    created_at=int(time.time()),
                )
            )
            db.commit()

    def get_token(self, value: str, kind: str) -> Optional[TokenRecord]:
        """The token, or None when unknown, of another kind, expired or revoked."""
        now = int(time.time())
        with self._session() as db:
            row = (
                db.query(McpOAuthToken)
                .filter(
                    McpOAuthToken.token_hash == digest(value),
                    McpOAuthToken.kind == kind,
                    McpOAuthToken.revoked_at.is_(None),
                    McpOAuthToken.expires_at > now,
                )
                .first()
            )
            return TokenRecord.model_validate(row) if row else None

    def rotate_refresh(
        self,
        value: str,
        *,
        client_id: str,
        scopes: list[str],
        new_access: str,
        new_refresh: str,
        access_expires_at: int,
        refresh_expires_at: int,
        grace_seconds: int = 0,
    ) -> Optional[IssuedTokens]:
        """Revoke the refresh token and store its replacements, in one transaction.

        The replacements carry `scopes`, which the token endpoint has checked are a subset of the
        presented token's.

        A token rotated at most `grace_seconds` ago, whose grant still has a live refresh token,
        is a retry after a lost response or a refresh that raced another. In the same transaction
        every live token of the grant (the tokens issued since that rotation) is revoked and a new
        pair is added, so one refresh chain stays live per grant and the grant is not revoked. Any
        other rotated or revoked token revokes its grant and returns None.
        """
        now = int(time.time())
        with self._session() as db:
            result = db.execute(
                update(McpOAuthToken)
                .where(
                    McpOAuthToken.token_hash == digest(value),
                    McpOAuthToken.kind == REFRESH,
                    McpOAuthToken.client_id == client_id,
                    McpOAuthToken.revoked_at.is_(None),
                    McpOAuthToken.expires_at > now,
                )
                .values(revoked_at=now, rotated_at=now)
            )
            if result.rowcount != 1 and not self._replace_chain_in_grace(
                db, value, client_id=client_id, grace_seconds=grace_seconds, now=now
            ):
                db.rollback()
                self.revoke_reused_refresh(value)
                return None
            row = db.query(McpOAuthToken).filter_by(token_hash=digest(value)).first()
            self._add_token_pair(
                db,
                grant_id=row.grant_id,
                client_id=row.client_id,
                user_id=row.user_id,
                scopes=list(scopes),
                resource=row.resource,
                new_access=new_access,
                new_refresh=new_refresh,
                access_expires_at=access_expires_at,
                refresh_expires_at=refresh_expires_at,
                now=now,
            )
            db.commit()
            return IssuedTokens(
                access_token=new_access,
                refresh_token=new_refresh,
                access_expires_at=access_expires_at,
                scopes=list(scopes),
            )

    @staticmethod
    def _grace_row(db, value: str, grace_seconds: int, now: int):
        """The refresh token row when rotation (not revocation) replaced it within the window."""
        if grace_seconds <= 0:
            return None
        return (
            db.query(McpOAuthToken)
            .filter(
                McpOAuthToken.token_hash == digest(value),
                McpOAuthToken.kind == REFRESH,
                McpOAuthToken.rotated_at.is_not(None),
                McpOAuthToken.rotated_at >= now - grace_seconds,
                McpOAuthToken.expires_at > now,
            )
            .first()
        )

    def _replace_chain_in_grace(
        self, db, value: str, *, client_id: str, grace_seconds: int, now: int
    ) -> bool:
        """Revoke the grant's live tokens when `value` is in its grace window. Caller commits.

        Returns False, changing nothing, when the token is not in grace, belongs to another
        client, or its grant has no live refresh token (it was revoked).

        The replaced refresh tokens get the presented token's rotated_at, so a client that raced
        and received one of them can still present it until the same window ends; that is handled
        here again, and one refresh chain stays live.
        """
        row = self._grace_row(db, value, grace_seconds, now)
        if row is None or row.client_id != client_id:
            return False
        live_refresh = db.execute(
            update(McpOAuthToken)
            .where(
                McpOAuthToken.grant_id == row.grant_id,
                McpOAuthToken.kind == REFRESH,
                McpOAuthToken.revoked_at.is_(None),
                McpOAuthToken.expires_at > now,
            )
            .values(revoked_at=now, rotated_at=row.rotated_at)
        )
        if live_refresh.rowcount == 0:
            return False
        db.execute(
            update(McpOAuthToken)
            .where(
                McpOAuthToken.grant_id == row.grant_id,
                McpOAuthToken.kind == ACCESS,
                McpOAuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return True

    # Rounds of revocation per grant. A token pair committed by a concurrent rotation after the
    # first UPDATE's snapshot is caught by a later round.
    REVOKE_ROUNDS = 3

    @classmethod
    def _revoke_grant_id(cls, db, grant_id: str) -> int:
        revoked = 0
        for _ in range(cls.REVOKE_ROUNDS):
            result = db.execute(
                update(McpOAuthToken)
                .where(
                    McpOAuthToken.grant_id == grant_id,
                    McpOAuthToken.revoked_at.is_(None),
                )
                .values(revoked_at=int(time.time()))
            )
            db.commit()
            revoked += result.rowcount
            if result.rowcount == 0:
                break
        return revoked

    def revoke_grant(self, value: str) -> int:
        """Revoke every token sharing a grant with this token. Returns the rows revoked."""
        with self._session() as db:
            row = db.query(McpOAuthToken).filter_by(token_hash=digest(value)).first()
            if row is None:
                return 0
            return self._revoke_grant_id(db, row.grant_id)

    def revoke_reused_code(self, code: str) -> int:
        """When this code was already exchanged, revoke every token issued from it.

        A code presented after its exchange may be a stolen copy (RFC 6749 §4.1.2). Returns the
        rows revoked; 0 for an unknown or never-exchanged code.
        """
        with self._session() as db:
            row = (
                db.query(McpOAuthCode)
                .filter(
                    McpOAuthCode.code_hash == digest(code),
                    McpOAuthCode.used_at.is_not(None),
                    McpOAuthCode.grant_id.is_not(None),
                )
                .first()
            )
            if row is None:
                return 0
            return self._revoke_grant_id(db, row.grant_id)

    def refresh_in_grace(self, value: str, grace_seconds: int) -> Optional[TokenRecord]:
        """The refresh token, when it was rotated at most `grace_seconds` ago and is still usable.

        Rotation sets the token's rotated_at and adds a live refresh token to the same grant.
        Revocation sets only revoked_at, so a token replaced by a grace retry or revoked through
        /revoke is never in grace, and a grant revoked through /revoke or by reuse has no live
        refresh token left. rotate_refresh checks the same conditions again in its transaction.
        """
        now = int(time.time())
        with self._session() as db:
            row = self._grace_row(db, value, grace_seconds, now)
            if row is None:
                return None
            live_successor = (
                db.query(McpOAuthToken)
                .filter(
                    McpOAuthToken.grant_id == row.grant_id,
                    McpOAuthToken.kind == REFRESH,
                    McpOAuthToken.revoked_at.is_(None),
                    McpOAuthToken.expires_at > now,
                )
                .first()
            )
            return TokenRecord.model_validate(row) if live_successor else None

    def revoke_reused_refresh(self, value: str) -> int:
        """When this refresh token was already rotated or revoked, revoke its whole grant.

        A rotated refresh token presented again may be a stolen copy (RFC 9700 §4.14.2). Returns
        the rows revoked; 0 for an unknown or still-live token.
        """
        with self._session() as db:
            row = (
                db.query(McpOAuthToken)
                .filter(
                    McpOAuthToken.token_hash == digest(value),
                    McpOAuthToken.kind == REFRESH,
                    McpOAuthToken.revoked_at.is_not(None),
                )
                .first()
            )
            if row is None:
                return 0
            return self._revoke_grant_id(db, row.grant_id)

    # Retention

    def purge(self, *, now: int, idle_client_seconds: int) -> dict[str, int]:
        """Delete rows that can no longer be used. Returns the rows deleted per table.

        - Pending requests: expired or decided.
        - Codes: expired. A used code is kept until it expires, so presenting it again still
          revokes the tokens issued for it.
        - Access tokens: expired or revoked.
        - Refresh tokens: expired. A rotated or revoked refresh token is kept until it expires, so
          presenting it again still revokes its grant.
        - Registered clients: created more than `idle_client_seconds` ago, with no live token and
          no live code or pending request.
        """
        idle_before = now - idle_client_seconds
        with self._session() as db:
            deleted = {
                "authorizations": db.query(McpOAuthAuthorization)
                .filter(
                    or_(
                        McpOAuthAuthorization.expires_at <= now,
                        McpOAuthAuthorization.consumed_at.is_not(None),
                    )
                )
                .delete(synchronize_session=False),
                "codes": db.query(McpOAuthCode)
                .filter(McpOAuthCode.expires_at <= now)
                .delete(synchronize_session=False),
                "tokens": db.query(McpOAuthToken)
                .filter(
                    or_(
                        McpOAuthToken.expires_at <= now,
                        and_(
                            McpOAuthToken.kind == ACCESS,
                            McpOAuthToken.revoked_at.is_not(None),
                        ),
                    )
                )
                .delete(synchronize_session=False),
            }
            live_token = exists().where(
                McpOAuthToken.client_id == McpOAuthClient.client_id,
                McpOAuthToken.revoked_at.is_(None),
                McpOAuthToken.expires_at > now,
            )
            live_code = exists().where(
                McpOAuthCode.client_id == McpOAuthClient.client_id,
                McpOAuthCode.expires_at > now,
            )
            live_request = exists().where(
                McpOAuthAuthorization.client_id == McpOAuthClient.client_id,
                McpOAuthAuthorization.expires_at > now,
            )
            deleted["clients"] = (
                db.query(McpOAuthClient)
                .filter(
                    McpOAuthClient.created_at <= idle_before,
                    ~live_token,
                    ~live_code,
                    ~live_request,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
            return deleted


McpOAuth = McpOAuthTable()
