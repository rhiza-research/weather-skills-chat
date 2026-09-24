import time
from types import SimpleNamespace
from unittest.mock import patch

from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


class TestInvitations(AbstractPostgresTest):
    BASE_PATH = "/api/v1"

    def setup_method(self):
        super().setup_method()
        from open_webui.models.auths import Auths
        from open_webui.models.invitations import Invitations, hash_token
        from open_webui.models.organizations import OrganizationForm, Organizations
        from open_webui.models.users import Users
        from open_webui.utils.auth import create_token, get_password_hash

        self.users = Users
        self.orgs = Organizations
        self.invitations = Invitations
        self.hash_token = hash_token
        self.create_token = create_token
        self.admin = Auths.insert_new_auth(
            email="admin@example.com",
            password=get_password_hash("admin-pass"),
            name="Admin",
            profile_image_url="/admin.png",
            role="admin",
        )
        self.orgs.ensure_platform(self.admin.id)
        self.org = self.orgs.insert_new_organization(
            self.admin.id,
            OrganizationForm(name="Field Team", description=""),
        )
        self.sent = {}

    def teardown_method(self):
        super().teardown_method()
        from open_webui.internal.db import Session
        from sqlalchemy import text

        Session.execute(text("TRUNCATE TABLE invitation"))
        Session.commit()

    def _smtp(self):
        def deliver(config, to, kind, token, organization_name="", expires_at=0, inviter_name=""):
            self.sent = {
                "to": to,
                "kind": kind,
                "token": token,
                "organization_name": organization_name,
                "expires_at": expires_at,
            }

        return patch.multiple(
            "open_webui.routers.invitations",
            smtp_is_configured=lambda config: "",
            deliver_invite_email=deliver,
        )

    def _auth(self, user):
        return {"Authorization": f"Bearer {self.create_token({'id': user.id})}"}

    def _invite_platform(self, email):
        with self._smtp(), mock_webui_user(id=self.admin.id, role="admin", email=self.admin.email):
            response = self.fast_api_client.post(
                self.create_url("/users/invitations"),
                json={"email": email},
            )
        return response

    def _invite_org(self, email):
        with self._smtp(), mock_webui_user(id=self.admin.id, role="admin", email=self.admin.email):
            response = self.fast_api_client.post(
                self.create_url(f"/organizations/{self.org.id}/invitations"),
                json={"email": email},
            )
        return response

    def _stored_hash(self, email):
        from open_webui.internal.db import get_db
        from open_webui.models.invitations import Invitation

        with get_db() as db:
            row = db.query(Invitation).filter_by(email=email).first()
            return None if row is None else row.token_hash

    def _expire(self, email):
        from open_webui.internal.db import get_db
        from open_webui.models.invitations import Invitation

        with get_db() as db:
            row = db.query(Invitation).filter_by(email=email).first()
            row.expires_at = int(time.time()) - 60
            db.commit()

    def test_platform_invite_stores_hash_and_rejects_existing_email(self):
        from open_webui.utils.auth import get_password_hash
        from open_webui.models.auths import Auths

        response = self._invite_platform("new-person@example.com")
        assert response.status_code == 200
        body = response.json()
        assert "token" not in body
        stored = self._stored_hash("new-person@example.com")
        assert stored == self.hash_token(self.sent["token"])
        assert stored != self.sent["token"]
        assert self.sent["kind"] == "platform"

        Auths.insert_new_auth(
            email="taken@example.com",
            password=get_password_hash("pass"),
            name="Taken",
            role="pending",
        )
        taken = self._invite_platform("taken@example.com")
        assert taken.status_code == 400
        assert self._stored_hash("taken@example.com") is None

    def test_cancel_invalidates_platform_and_org_invites(self):
        platform = self._invite_platform("cancel-platform@example.com")
        platform_token = self.sent["token"]
        org = self._invite_org("cancel-org@example.com")
        org_token = self.sent["token"]
        assert platform.status_code == 200
        assert org.status_code == 200

        with mock_webui_user(id=self.admin.id, role="admin", email=self.admin.email):
            canceled_platform = self.fast_api_client.delete(
                self.create_url(f"/users/invitations/{platform.json()['id']}")
            )
            canceled_org = self.fast_api_client.delete(
                self.create_url(
                    f"/organizations/{self.org.id}/invitations/{org.json()['id']}"
                )
            )
        assert canceled_platform.status_code == 200
        assert canceled_org.status_code == 200
        assert (
            self.fast_api_client.get(self.create_url(f"/invitations/{platform_token}")).status_code
            == 404
        )
        assert self.fast_api_client.get(self.create_url(f"/invitations/{org_token}")).status_code == 404
        created = self._invite_platform("later@example.com")
        assert created.status_code == 200
        token = self.sent["token"]
        self._expire("later@example.com")

        lookup = self.fast_api_client.get(self.create_url(f"/invitations/{token}"))
        assert lookup.status_code == 200
        assert lookup.json()["expired"] is True

        expired = self.fast_api_client.post(
            self.create_url(f"/invitations/{token}/accept"),
            json={"name": "Later", "password": "long-enough-password"},
        )
        assert expired.status_code == 400

        with self._smtp(), mock_webui_user(id=self.admin.id, role="admin", email=self.admin.email):
            resent = self.fast_api_client.post(
                self.create_url(f"/users/invitations/{created.json()['id']}/resend")
            )
        assert resent.status_code == 200
        assert self.sent["token"] != token
        old = self.fast_api_client.get(self.create_url(f"/invitations/{token}"))
        assert old.status_code == 404

        accepted = self.fast_api_client.post(
            self.create_url(f"/invitations/{self.sent['token']}/accept"),
            json={"name": "Later", "password": "long-enough-password"},
        )
        assert accepted.status_code == 200
        again = self.fast_api_client.post(
            self.create_url(f"/invitations/{self.sent['token']}/accept"),
            json={"name": "Later", "password": "long-enough-password"},
        )
        assert again.status_code == 400
        user = self.users.get_user_by_email("later@example.com")
        assert user.role == "user"

    def test_org_invite_waits_for_accept_and_rejects_wrong_session(self):
        from open_webui.models.auths import Auths
        from open_webui.utils.auth import get_password_hash

        member = Auths.insert_new_auth(
            email="member@example.com",
            password=get_password_hash("member-pass"),
            name="Member",
            role="user",
        )
        other = Auths.insert_new_auth(
            email="other@example.com",
            password=get_password_hash("other-pass"),
            name="Other",
            role="user",
        )
        created = self._invite_org("member@example.com")
        assert created.status_code == 200
        assert self.orgs.get_member(self.org.id, member.id) is None
        token = self.sent["token"]
        assert self._stored_hash("member@example.com") == self.hash_token(token)

        signed_out = self.fast_api_client.post(
            self.create_url(f"/invitations/{token}/accept"),
            json={},
        )
        assert signed_out.status_code == 401
        assert self.orgs.get_member(self.org.id, member.id) is None

        wrong = self.fast_api_client.post(
            self.create_url(f"/invitations/{token}/accept"),
            json={},
            headers=self._auth(other),
        )
        assert wrong.status_code == 409
        assert self.orgs.get_member(self.org.id, member.id) is None
        assert self.orgs.get_member(self.org.id, other.id) is None

        accepted = self.fast_api_client.post(
            self.create_url(f"/invitations/{token}/accept"),
            json={},
            headers=self._auth(member),
        )
        assert accepted.status_code == 200
        assert self.orgs.get_member(self.org.id, member.id) is not None
        assert self.orgs.get_member(self.org.id, member.id).role == "user"

        again = self._invite_org("member@example.com")
        assert again.status_code == 400

    def test_org_invite_creates_account_and_membership(self):
        created = self._invite_org("fresh@example.com")
        assert created.status_code == 200
        assert self.sent["organization_name"] == "Field Team"
        def fail_alert(*_args, **_kwargs):
            raise AssertionError("invite acceptance emailed admins")

        with patch("open_webui.utils.invite_email.deliver_signup_alert", fail_alert):
            accepted = self.fast_api_client.post(
                self.create_url(f"/invitations/{self.sent['token']}/accept"),
                json={"name": "Fresh", "password": "long-enough-password"},
            )
        assert accepted.status_code == 200
        user = self.users.get_user_by_email("fresh@example.com")
        assert user.role == "user"
        assert self.orgs.get_member(self.org.id, user.id).role == "user"

    def test_pending_signup_stays_pending_until_org_accept(self):
        from open_webui.models.auths import Auths
        from open_webui.utils.auth import get_password_hash

        pending = Auths.insert_new_auth(
            email="pending@example.com",
            password=get_password_hash("pending-pass"),
            name="Pending",
            role="pending",
        )
        created = self._invite_org("pending@example.com")
        assert created.status_code == 200
        assert self.users.get_user_by_id(pending.id).role == "pending"
        assert self.orgs.get_member(self.org.id, pending.id) is None

        accepted = self.fast_api_client.post(
            self.create_url(f"/invitations/{self.sent['token']}/accept"),
            json={},
            headers=self._auth(pending),
        )
        assert accepted.status_code == 200
        assert self.users.get_user_by_id(pending.id).role == "user"
        assert self.orgs.get_member(self.org.id, pending.id) is not None

    def test_platform_invite_as_admin_grants_platform_membership(self):
        with self._smtp(), mock_webui_user(
            id=self.admin.id, role="admin", email=self.admin.email
        ):
            created = self.fast_api_client.post(
                self.create_url("/users/invitations"),
                json={"email": "lead@example.com", "role": "admin"},
            )
        assert created.status_code == 200
        assert created.json()["role"] == "admin"
        accepted = self.fast_api_client.post(
            self.create_url(f"/invitations/{self.sent['token']}/accept"),
            json={"name": "Lead", "password": "long-enough-password"},
        )
        assert accepted.status_code == 200
        user = self.users.get_user_by_email("lead@example.com")
        assert user.role == "admin"
        member = self.orgs.get_member("platform", user.id)
        assert member is not None
        assert member.role == "admin"

    def test_org_invite_as_admin_sets_membership_role(self):
        with self._smtp(), mock_webui_user(
            id=self.admin.id, role="admin", email=self.admin.email
        ):
            created = self.fast_api_client.post(
                self.create_url(f"/organizations/{self.org.id}/invitations"),
                json={"email": "lead@example.com", "role": "admin"},
            )
        assert created.status_code == 200
        assert created.json()["role"] == "admin"
        accepted = self.fast_api_client.post(
            self.create_url(f"/invitations/{self.sent['token']}/accept"),
            json={"name": "Lead", "password": "long-enough-password"},
        )
        assert accepted.status_code == 200
        user = self.users.get_user_by_email("lead@example.com")
        assert user.role == "user"
        assert self.orgs.get_member(self.org.id, user.id).role == "admin"

    def test_signup_emails_platform_admins(self):
        sent = {}

        def fake_alert(config, admin_emails, name, email, description):
            sent["admins"] = list(admin_emails)
            sent["name"] = name
            sent["email"] = email
            sent["description"] = description

        with patch("open_webui.utils.invite_email.deliver_signup_alert", fake_alert):
            response = self.fast_api_client.post(
                "/api/v1/auths/signup",
                json={
                    "name": "New Person",
                    "email": "new-person@example.com",
                    "password": "long-enough-password",
                    "description": "I study seasonal rainfall.",
                },
            )
        assert response.status_code == 200
        assert sent["admins"] == [self.admin.email]
        assert sent["name"] == "New Person"
        assert sent["email"] == "new-person@example.com"
        assert sent["description"] == "I study seasonal rainfall."
        user = self.users.get_user_by_email("new-person@example.com")
        assert user.info["signup_description"] == "I study seasonal rainfall."

    def test_invite_rejects_unknown_role(self):
        with self._smtp(), mock_webui_user(
            id=self.admin.id, role="admin", email=self.admin.email
        ):
            created = self.fast_api_client.post(
                self.create_url("/users/invitations"),
                json={"email": "lead@example.com", "role": "owner"},
            )
        assert created.status_code == 400

    def test_invite_email_copy(self):
        from open_webui.utils.invite_email import deliver_invite_email

        calls = []

        def fake_send(*args, **kwargs):
            calls.append((args, kwargs))
            return True, ""

        config = SimpleNamespace(
            EMAIL_TOOL_SMTP_HOST="smtp.test",
            EMAIL_TOOL_SMTP_PORT=465,
            EMAIL_TOOL_SMTP_USERNAME="user",
            EMAIL_TOOL_SMTP_PASSWORD="pass",
            EMAIL_TOOL_SMTP_USE_TLS=True,
            EMAIL_TOOL_FROM_EMAIL="invite@example.com",
            WEBUI_URL="http://localhost:3000",
        )
        with patch("open_webui.utils.invite_email._send_via_smtp", fake_send):
            deliver_invite_email(
                config,
                "person@example.com",
                "platform",
                "raw-token",
                expires_at=1_800_000_000,
                inviter_name="Ada Lovelace",
            )
            deliver_invite_email(
                config,
                "person@example.com",
                "organization",
                "raw-token",
                organization_name="Field Team",
                expires_at=1_800_000_000,
                inviter_name="Ada Lovelace",
            )
            from open_webui.utils.invite_email import deliver_signup_alert

            deliver_signup_alert(
                config,
                ["admin@example.com"],
                "Ada Lovelace",
                "ada@example.com",
                "I forecast rainfall for East Africa.",
            )
            from open_webui.utils.invite_email import deliver_signup_approval

            deliver_signup_approval(
                config,
                "ada@example.com",
                "Grace Hopper",
                "info@rhizaresearch.org",
            )
        platform_subject, platform_body = calls[0][0][9], calls[0][0][10]
        org_subject, org_body = calls[1][0][9], calls[1][0][10]
        assert "create an account on Weather Skills" in platform_subject
        assert "Ada Lovelace has invited you to create an account on Weather Skills" in platform_body
        assert "http://localhost:3000/auth/invite?token=raw-token" in platform_body
        assert "Field Team" in org_subject
        assert (
            "Ada Lovelace has invited you to the Field Team organization on Weather Skills"
            in org_body
        )
        assert "already been added" not in org_body.lower()
        signup_subject, signup_body = calls[-2][0][9], calls[-2][0][10]
        assert signup_subject == "New signup on Weather Skills: Ada Lovelace"
        assert "Ada Lovelace" in signup_body
        assert "ada@example.com" in signup_body
        assert "I forecast rainfall for East Africa." in signup_body
        assert calls[-2][0][7] == "ada@example.com"
        assert calls[-2][0][8] == ["admin@example.com"]
        approval_subject, approval_body = calls[-1][0][9], calls[-1][0][10]
        assert approval_subject == "Welcome to Weather Skills"
        assert (
            "Welcome to Weather Skills! Grace Hopper approved your signup request."
            in approval_body
        )
        assert "You can now sign in at http://localhost:3000." in approval_body
        assert "info@rhizaresearch.org" in approval_body
        for _, kwargs in calls:
            assert 'src="cid:favicon"' in kwargs["html"]
            cid, data, subtype = kwargs["inline_images"][0]
            assert cid == "favicon"
            assert subtype == "png"
            assert data.startswith(b"\x89PNG")
