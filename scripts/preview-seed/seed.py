"""Sample accounts and a workspace for a local stack. See wiki/Development.md.

Runs inside the stack's container, after the app has started and created the
bootstrap admin, with the app's own models:

    docker exec -i -w /app/backend CONTAINER python - < scripts/preview-seed/seed.py

Running it again does nothing.
"""

from open_webui.models.auths import Auths
from open_webui.models.organizations import OrganizationForm, Organizations
from open_webui.models.users import Users
from open_webui.utils.auth import get_password_hash

PASSWORD = "preview"
ADMIN_EMAIL = "admin@example.com"

admin = Users.get_user_by_email(ADMIN_EMAIL)
assert admin, f"{ADMIN_EMAIL} is missing: start the stack with BOOTSTRAP_ADMIN_EMAIL set"
if Users.get_user_by_email("researcher@example.com"):
    print("Accounts already seeded")
    raise SystemExit


def user(email, name, role):
    auth = Auths.insert_new_auth(
        email=email, password=get_password_hash(PASSWORD), name=name, role=role
    )
    Organizations.ensure_personal(auth.id)
    return auth


researcher = user("researcher@example.com", "Researcher", "user")
user("pending@example.com", "Pending Person", "pending")

org = Organizations.insert_new_organization(
    admin.id, OrganizationForm(name="Demo Org", description="Sample workspace")
)
Organizations.set_active(org.id, True)
Organizations.add_member(org.id, researcher.id, "user")
print("Seeded 3 accounts and Demo Org")
