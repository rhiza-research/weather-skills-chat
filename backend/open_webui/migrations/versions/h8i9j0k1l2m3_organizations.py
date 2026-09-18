"""Replace teams with organizations; keep users; drop team data.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-09-16 00:00:00.000000

"""

import json
import time

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None

PLATFORM_ORG_ID = "platform"
RESOURCE_TABLES_WITH_TEAM = ("chat", "secret", "automation")
RESOURCE_TABLES = (
    "chat",
    "secret",
    "automation",
    "folder",
    "skill_pack",
    "knowledge",
)
ACL_TABLES = ("skill_pack", "knowledge", "model", "prompt", "tool", "file", "channel")


def _index_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {idx["name"] for idx in inspect(bind).get_indexes(table) if idx.get("name")}


def _drop_index_if_exists(name: str, table: str) -> None:
    # SQLite leftover indexes from a failed batch_alter survive inspect+drop_index.
    op.execute(text(f'DROP INDEX IF EXISTS "{name}"'))


def _create_index_if_missing(
    name: str, table: str, columns: list[str], unique: bool = False
) -> None:
    if name not in _index_names(table):
        op.create_index(name, table, columns, unique=unique)


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _row_exists(conn, sql: str, params: dict) -> bool:
    return conn.execute(text(sql), params).fetchone() is not None


def _rewrite_access_control(value):
    if value is None:
        return None
    as_text = isinstance(value, str)
    if as_text:
        raw = value.strip()
        if not raw:
            return value
        try:
            data = json.loads(raw)
        except Exception:
            return value
    else:
        data = value
    if not isinstance(data, dict):
        return value
    changed = False
    for section_name in ("read", "write"):
        section = data.get(section_name)
        if not isinstance(section, dict):
            continue
        if "team_ids" in section:
            section.pop("team_ids", None)
            changed = True
        if "organization_ids" not in section:
            section["organization_ids"] = []
            changed = True
        else:
            section["organization_ids"] = []
            changed = True
    if not changed:
        return value
    return json.dumps(data) if as_text else data


def _reencrypt_team_secrets(conn) -> None:
    if not _table_exists("secret") or "team_id" not in _column_names("secret"):
        return
    rows = conn.execute(
        text(
            "SELECT id, name, ciphertext, nonce, user_id, team_id FROM secret "
            "WHERE team_id IS NOT NULL"
        )
    ).fetchall()
    if not rows:
        return
    try:
        from open_webui.utils.secret_crypto import decrypt_secret, encrypt_secret
    except Exception:
        for row in rows:
            conn.execute(text("DELETE FROM secret WHERE id = :id"), {"id": row[0]})
        return
    for row in rows:
        secret_id, name, ciphertext, nonce, user_id, team_id = row
        try:
            plaintext = decrypt_secret(
                ciphertext, nonce, name=name, user_id=user_id, team_id=team_id
            )
            new_ct, new_nonce = encrypt_secret(
                plaintext,
                name=name,
                user_id=user_id,
                organization_id=user_id,
                visibility="private",
            )
            conn.execute(
                text(
                    "UPDATE secret SET ciphertext = :ct, nonce = :nonce, "
                    "team_id = NULL WHERE id = :id"
                ),
                {"ct": new_ct, "nonce": new_nonce, "id": secret_id},
            )
        except Exception:
            conn.execute(text("DELETE FROM secret WHERE id = :id"), {"id": secret_id})


def upgrade():
    conn = op.get_bind()
    now = int(time.time())

    if not _table_exists("organization"):
        op.create_table(
            "organization",
            sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("created_by", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
            sa.Column("updated_at", sa.BigInteger(), nullable=True),
            sa.Column("default_models", sa.Text(), nullable=True),
        )
    _create_index_if_missing("ix_organization_kind", "organization", ["kind"])

    if not _table_exists("organization_member"):
        op.create_table(
            "organization_member",
            sa.Column("organization_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=True),
            sa.PrimaryKeyConstraint("organization_id", "user_id"),
        )
    _create_index_if_missing(
        "ix_organization_member_user_id", "organization_member", ["user_id"]
    )

    users = conn.execute(
        text("SELECT id, role, created_at FROM user ORDER BY created_at ASC")
    ).fetchall()
    for user_id, _role, created_at in users:
        created = created_at or now
        if not _row_exists(
            conn, "SELECT 1 FROM organization WHERE id = :id", {"id": user_id}
        ):
            conn.execute(
                text(
                    "INSERT INTO organization (id, name, description, kind, created_by, "
                    "created_at, updated_at) VALUES (:id, :name, :description, :kind, "
                    ":created_by, :created_at, :updated_at)"
                ),
                {
                    "id": user_id,
                    "name": "Personal",
                    "description": "",
                    "kind": "personal",
                    "created_by": user_id,
                    "created_at": created,
                    "updated_at": now,
                },
            )
        if not _row_exists(
            conn,
            "SELECT 1 FROM organization_member WHERE organization_id = :organization_id "
            "AND user_id = :user_id",
            {"organization_id": user_id, "user_id": user_id},
        ):
            conn.execute(
                text(
                    "INSERT INTO organization_member (organization_id, user_id, role, created_at) "
                    "VALUES (:organization_id, :user_id, :role, :created_at)"
                ),
                {
                    "organization_id": user_id,
                    "user_id": user_id,
                    "role": "owner",
                    "created_at": created,
                },
            )

    platform_owner = next((row[0] for row in users if row[1] == "admin"), None)
    if not _row_exists(
        conn, "SELECT 1 FROM organization WHERE id = :id", {"id": PLATFORM_ORG_ID}
    ):
        conn.execute(
            text(
                "INSERT INTO organization (id, name, description, kind, created_by, "
                "created_at, updated_at) VALUES (:id, :name, :description, :kind, "
                ":created_by, :created_at, :updated_at)"
            ),
            {
                "id": PLATFORM_ORG_ID,
                "name": "Platform",
                "description": "Super-admin organization",
                "kind": "platform",
                "created_by": platform_owner or PLATFORM_ORG_ID,
                "created_at": now,
                "updated_at": now,
            },
        )
    first_admin = True
    for user_id, role, created_at in users:
        if role != "admin":
            continue
        if not _row_exists(
            conn,
            "SELECT 1 FROM organization_member WHERE organization_id = :organization_id "
            "AND user_id = :user_id",
            {"organization_id": PLATFORM_ORG_ID, "user_id": user_id},
        ):
            conn.execute(
                text(
                    "INSERT INTO organization_member (organization_id, user_id, role, created_at) "
                    "VALUES (:organization_id, :user_id, :role, :created_at)"
                ),
                {
                    "organization_id": PLATFORM_ORG_ID,
                    "user_id": user_id,
                    "role": "owner" if first_admin else "admin",
                    "created_at": created_at or now,
                },
            )
        first_admin = False

    _reencrypt_team_secrets(conn)

    for table in RESOURCE_TABLES:
        if not _table_exists(table):
            continue
        columns = _column_names(table)
        with op.batch_alter_table(table) as batch:
            if "organization_id" not in columns:
                batch.add_column(sa.Column("organization_id", sa.Text(), nullable=True))
            if "visibility" not in columns:
                batch.add_column(sa.Column("visibility", sa.Text(), nullable=True))

        conn.execute(text(f"DELETE FROM {table} WHERE user_id IS NULL"))
        conn.execute(
            text(
                f"UPDATE {table} SET organization_id = user_id, visibility = 'private' "
                f"WHERE organization_id IS NULL"
            )
        )
        conn.execute(
            text(f"DELETE FROM {table} WHERE organization_id IS NULL")
        )

        _drop_index_if_exists(f"ix_{table}_team_id", table)
        if table == "secret":
            _drop_index_if_exists("uq_secret_personal_name", table)
            _drop_index_if_exists("uq_secret_team_name", table)
        with op.batch_alter_table(table) as batch:
            batch.alter_column("organization_id", existing_type=sa.Text(), nullable=False)
            batch.alter_column("visibility", existing_type=sa.Text(), nullable=False)
            if table in RESOURCE_TABLES_WITH_TEAM and "team_id" in _column_names(table):
                batch.drop_column("team_id")
        _create_index_if_missing(f"ix_{table}_organization_id", table, ["organization_id"])

    if _table_exists("secret"):
        op.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_secret_private_name "
                "ON secret (organization_id, user_id, name) WHERE visibility = 'private'"
            )
        )
        op.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_secret_org_name "
                "ON secret (organization_id, name) WHERE visibility = 'organization'"
            )
        )

    if _table_exists("skill_pack"):
        _drop_index_if_exists("uq_skill_pack_user_git_url_ref", "skill_pack")
        _create_index_if_missing(
            "uq_skill_pack_org_git_url_ref",
            "skill_pack",
            ["organization_id", "git_url", "git_ref"],
            unique=True,
        )

    for table in ACL_TABLES:
        if not _table_exists(table) or "access_control" not in _column_names(table):
            continue
        rows = conn.execute(
            text(f"SELECT id, access_control FROM {table} WHERE access_control IS NOT NULL")
        ).fetchall()
        for row_id, acl in rows:
            rewritten = _rewrite_access_control(acl)
            if rewritten == acl:
                continue
            conn.execute(
                text(f"UPDATE {table} SET access_control = :acl WHERE id = :id"),
                {"acl": rewritten, "id": row_id},
            )

    if _table_exists("team_member"):
        op.drop_table("team_member")
    if _table_exists("team"):
        op.drop_table("team")


def downgrade():
    op.create_table(
        "team",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
        sa.Column("default_models", sa.Text(), nullable=True),
    )
    op.create_table(
        "team_member",
        sa.Column("team_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("team_id", "user_id"),
    )
    op.create_index("ix_team_member_user_id", "team_member", ["user_id"])

    for table in RESOURCE_TABLES:
        if not _table_exists(table):
            continue
        _drop_index_if_exists(f"ix_{table}_organization_id", table)
        with op.batch_alter_table(table) as batch:
            if table in RESOURCE_TABLES_WITH_TEAM:
                batch.add_column(sa.Column("team_id", sa.Text(), nullable=True))
            batch.drop_column("visibility")
            batch.drop_column("organization_id")
        if table in RESOURCE_TABLES_WITH_TEAM:
            op.create_index(f"ix_{table}_team_id", table, ["team_id"])

    if _table_exists("skill_pack"):
        _drop_index_if_exists("uq_skill_pack_org_git_url_ref", "skill_pack")
        op.create_index(
            "uq_skill_pack_user_git_url_ref",
            "skill_pack",
            ["user_id", "git_url", "git_ref"],
            unique=True,
        )

    op.drop_table("organization_member")
    op.drop_table("organization")
