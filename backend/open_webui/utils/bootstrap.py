import logging
import os

from open_webui.models.auths import Auths
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
        role="admin",
    )
    if user:
        log.info("Bootstrapped admin user %s", email)
    else:
        log.error("Failed to bootstrap admin user %s", email)
