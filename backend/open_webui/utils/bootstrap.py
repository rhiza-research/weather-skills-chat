import logging
import os
import time
from typing import Optional

from pydantic import ConfigDict
from sqlalchemy.exc import IntegrityError

from open_webui.config import env_json
from open_webui.internal.db import get_db
from open_webui.models.auths import Auths
from open_webui.models.models import Model, ModelForm
from open_webui.models.organizations import PLATFORM_ORG_ID, VISIBILITY_PUBLIC
from open_webui.models.skill_packs import SkillPackInstallForm, SkillPacks
from open_webui.models.users import Users
from open_webui.utils.auth import get_password_hash
from open_webui.utils.misc import validate_email_format

log = logging.getLogger(__name__)


def bootstrap_admin_user() -> None:
    """Create the initial admin account when bootstrap env vars are set and no users exist."""
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    name = os.environ.get("BOOTSTRAP_ADMIN_NAME", "admin").strip() or "admin"

    if not email or not password:
        return

    if Users.get_num_users() != 0:
        return

    if not validate_email_format(email):
        log.error("BOOTSTRAP_ADMIN_EMAIL is invalid: %s", email)
        return

    if len(password.encode("utf-8")) > 72:
        log.error("BOOTSTRAP_ADMIN_PASSWORD exceeds bcrypt length limit")
        return

    hashed = get_password_hash(password)
    user = Auths.insert_new_auth(
        email,
        hashed,
        name,
        profile_image_url="/user.png",
        role="user",
    )
    if user:
        from open_webui.models.organizations import Organizations

        Organizations.ensure_personal(user.id)
        Organizations.ensure_platform(user.id)
        log.info("Bootstrapped admin user %s", email)
    else:
        log.error("Failed to bootstrap admin user %s", email)


class SkillPackEntry(SkillPackInstallForm):
    model_config = ConfigDict(extra="forbid")


class CatalogModelEntry(ModelForm):
    model_config = ConfigDict(extra="forbid")


def provision_from_env(app_tools: dict) -> None:
    """Apply SKILL_PACKS, CATALOG_MODELS and BOOTSTRAP_ADMIN_API_KEY.

    A container started from environment variables alone must be ready to
    use once it serves requests, so every failure raises and stops startup
    rather than leaving a partly provisioned app running. Everything is
    checked before anything is written.
    """
    packs = _read_packs()
    models = _read_models()
    api_key = _read_api_key()

    if not packs and not models and api_key is None:
        return

    owner = _platform_owner()

    if api_key is not None and owner.api_key != api_key:
        if not Users.update_user_api_key_by_id(owner.id, api_key):
            raise RuntimeError(
                "Could not set BOOTSTRAP_ADMIN_API_KEY on the BOOTSTRAP_ADMIN_EMAIL "
                "account; another account may already use that key"
            )

    for pack, url, ref in packs:
        _install_pack(pack, url, ref, owner.id, app_tools)

    for model in models:
        _put_model(model, owner.id)


def _read_packs() -> list[tuple[SkillPackEntry, str, str]]:
    from open_webui.utils.skills import validate_public_git_url

    entries = env_json(
        "SKILL_PACKS",
        [],
        list[SkillPackEntry],
        'a JSON array of objects, each with a string "git_url" and optional '
        '"ref" and "enabled_by_default"',
    )
    packs = []
    seen = set()
    for raw in entries:
        entry = SkillPackEntry.model_validate(raw)
        ref = entry.ref.strip()
        if not ref:
            raise ValueError(f"SKILL_PACKS: {entry.git_url} has an empty ref")
        try:
            url = validate_public_git_url(entry.git_url)
        except Exception as e:
            raise ValueError(f"SKILL_PACKS: {entry.git_url}: {e}") from e
        if (url, ref) in seen:
            raise ValueError(f"SKILL_PACKS lists {url} @ {ref} more than once")
        seen.add((url, ref))
        packs.append((entry, url, ref))
    return packs


def _read_models() -> list[CatalogModelEntry]:
    entries = env_json(
        "CATALOG_MODELS",
        [],
        list[CatalogModelEntry],
        "a JSON array of model objects",
    )
    models = []
    seen = set()
    for raw in entries:
        model = CatalogModelEntry.model_validate(raw)
        if not model.id.strip():
            raise ValueError("CATALOG_MODELS has a model with an empty id")
        if model.id in seen:
            raise ValueError(f"CATALOG_MODELS lists model {model.id} more than once")
        seen.add(model.id)
        for field, required in (
            ("organization_id", PLATFORM_ORG_ID),
            ("visibility", VISIBILITY_PUBLIC),
        ):
            given = getattr(model, field)
            if given is not None and given != required:
                raise ValueError(
                    f"CATALOG_MODELS: model {model.id} sets {field} to {given!r}; "
                    f"catalog models are always {required!r}"
                )
        models.append(model)
    return models


def _read_api_key() -> Optional[str]:
    from open_webui.config import ENABLE_API_KEY

    api_key = os.environ.get("BOOTSTRAP_ADMIN_API_KEY")
    if api_key is None:
        return None
    if (
        not api_key.startswith("sk-")
        or api_key == "sk-"
        or any(c.isspace() for c in api_key)
    ):
        raise ValueError(
            "BOOTSTRAP_ADMIN_API_KEY must be sk- followed by more characters, "
            "with no whitespace"
        )
    if not ENABLE_API_KEY.value:
        raise ValueError(
            "BOOTSTRAP_ADMIN_API_KEY is set but ENABLE_API_KEY is off, so the key "
            "could not be used"
        )
    return api_key


def _platform_owner():
    from open_webui.models.organizations import Organizations

    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    owner = Users.get_user_by_email(email) if email else None
    if owner is None:
        raise RuntimeError(
            "An account with the BOOTSTRAP_ADMIN_EMAIL address is required when "
            "SKILL_PACKS, CATALOG_MODELS or BOOTSTRAP_ADMIN_API_KEY is set"
        )
    member = Organizations.get_member(PLATFORM_ORG_ID, owner.id)
    if member is None or member.role not in ("owner", "admin"):
        raise RuntimeError(
            "The BOOTSTRAP_ADMIN_EMAIL account must be an owner or admin of the "
            "platform organization to own SKILL_PACKS and CATALOG_MODELS items "
            "and BOOTSTRAP_ADMIN_API_KEY"
        )
    return owner


def _install_pack(
    entry: SkillPackEntry, url: str, ref: str, owner_id: str, app_tools: dict
) -> None:
    from open_webui.utils.skills import install_skill_pack

    existing = SkillPacks.get_by_org_url_ref(PLATFORM_ORG_ID, url, ref)
    if existing is None:
        try:
            install_skill_pack(
                owner_id,
                url,
                ref,
                app_tools,
                organization_id=PLATFORM_ORG_ID,
                visibility=VISIBILITY_PUBLIC,
                enabled_by_default=entry.enabled_by_default,
            )
            log.info("Installed skill pack %s @ %s from SKILL_PACKS", url, ref)
            return
        except Exception as e:
            # Another app process starting at the same time may have installed
            # it first, which makes this insert fail on the unique key.
            existing = SkillPacks.get_by_org_url_ref(PLATFORM_ORG_ID, url, ref)
            if existing is None:
                raise RuntimeError(
                    f"SKILL_PACKS: installing {url} @ {ref} failed: {e}"
                ) from e
            _restore_pack_tree(existing, app_tools)

    if existing.enabled_by_default != entry.enabled_by_default:
        SkillPacks.set_enabled_by_default(existing.id, entry.enabled_by_default)


def _restore_pack_tree(pack, app_tools: dict) -> None:
    """Fetch the pack again if a failed install here removed its shared folder."""
    from pathlib import Path

    from open_webui.utils.skills import _pack_tree_present, update_skill_pack

    if _pack_tree_present(Path(pack.local_path)):
        return
    try:
        update_skill_pack(pack.id, app_tools)
    except Exception as e:
        raise RuntimeError(
            f"SKILL_PACKS: restoring {pack.git_url} @ {pack.git_ref} failed: {e}"
        ) from e


def _existing_model_row(db, model_id: str):
    return db.get(Model, model_id)


def _put_model(entry: CatalogModelEntry, owner_id: str) -> None:
    entry.organization_id = PLATFORM_ORG_ID
    entry.visibility = VISIBILITY_PUBLIC
    fields = entry.model_dump(exclude={"id"})

    for _ in range(2):
        with get_db() as db:
            now = int(time.time())
            row = _existing_model_row(db, entry.id)
            if row is None:
                db.add(
                    Model(
                        id=entry.id,
                        user_id=owner_id,
                        created_at=now,
                        updated_at=now,
                        **fields,
                    )
                )
            else:
                for name, value in fields.items():
                    setattr(row, name, value)
                row.user_id = owner_id
                row.updated_at = now
            try:
                db.commit()
            except IntegrityError:
                # Another app process inserted this id first; overwrite it.
                db.rollback()
                continue
        log.info("Saved catalog model %s from CATALOG_MODELS", entry.id)
        return
    raise RuntimeError(f"CATALOG_MODELS: saving model {entry.id} failed")
