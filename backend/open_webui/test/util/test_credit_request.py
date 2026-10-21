"""Credit increase requests go to the admins who can raise the limit reached."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import open_webui.routers.usage as usage_router
from open_webui.models.organizations import PLATFORM_ORG_ID
from open_webui.models.usage import UsageMeModel
from open_webui.utils import invite_email


def _usage(**overrides):
    values = dict(
        organization_id="org-1",
        organization_name="Rain Team",
        period="2026-10",
        cost_usd=40.0,
        org_cost_usd=300.0,
        org_limit_usd=300.0,
    )
    values.update(overrides)
    return UsageMeModel(**values)


def _admins(by_org):
    return lambda organization_id, exclude="": list(by_org.get(organization_id, []))


class CreditRequestRouteTest(unittest.IsolatedAsyncioTestCase):
    async def _submit(self, usage, admins, credits=50.0, reason="Running a seasonal outlook"):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=MagicMock())))
        user = SimpleNamespace(id="u1", name="Sam", email="sam@example.com")
        deliver = MagicMock()
        with (
            patch.object(usage_router, "usage_snapshot", return_value=usage),
            patch.object(usage_router, "admin_emails", side_effect=_admins(admins)),
            patch.object(usage_router, "deliver_credit_request", deliver),
        ):
            await usage_router.request_credit_increase(
                request,
                usage_router.CreditRequestForm(credits=credits, reason=reason),
                user=user,
                organization_id="org-1",
            )
        return deliver.call_args.args

    async def test_organization_limit_goes_to_platform_admins(self):
        args = await self._submit(
            _usage(),
            {PLATFORM_ORG_ID: ["ops@example.com"], "org-1": ["lead@example.com"]},
        )
        self.assertEqual(args[1], ["ops@example.com"])
        self.assertEqual(args[5], "Organization limit")
        self.assertEqual((args[6], args[7]), (300.0, 300.0))
        self.assertEqual(args[8], 50.0)
        self.assertEqual(args[10], "/admin/users")

    async def test_member_limit_goes_to_organization_admins(self):
        args = await self._submit(
            _usage(org_cost_usd=120.0, user_limit_usd=40.0),
            {PLATFORM_ORG_ID: ["ops@example.com"], "org-1": ["lead@example.com"]},
        )
        self.assertEqual(args[1], ["lead@example.com"])
        self.assertEqual(args[5], "Member limit")
        self.assertEqual((args[6], args[7]), (40.0, 40.0))
        self.assertEqual(args[10], "/organization/membership")

    async def test_member_limit_without_other_admins_goes_to_platform(self):
        args = await self._submit(
            _usage(org_cost_usd=120.0, user_limit_usd=40.0),
            {PLATFORM_ORG_ID: ["ops@example.com"]},
        )
        self.assertEqual(args[1], ["ops@example.com"])
        self.assertEqual(args[5], "Member limit")
        self.assertEqual(args[10], "/admin/users")

    async def test_send_failure_is_a_plain_message(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=MagicMock())))
        user = SimpleNamespace(id="u1", name="Sam", email="sam@example.com")
        with (
            patch.object(usage_router, "usage_snapshot", return_value=_usage()),
            patch.object(usage_router, "admin_emails", return_value=["ops@example.com"]),
            patch.object(
                usage_router,
                "deliver_credit_request",
                side_effect=invite_email.InviteEmailError("missing EMAIL_TOOL_SMTP_HOST"),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await usage_router.request_credit_increase(
                    request,
                    usage_router.CreditRequestForm(reason="More runs"),
                    user=user,
                    organization_id="org-1",
                )
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, usage_router.CREDIT_REQUEST_FAILED)

    def test_reason_is_required(self):
        with self.assertRaises(ValueError):
            usage_router.CreditRequestForm(reason="")


class CreditRequestEmailTest(unittest.TestCase):
    def test_email_names_request_and_links_to_limit(self):
        config = SimpleNamespace(
            EMAIL_TOOL_SMTP_HOST="smtp.example.com",
            EMAIL_TOOL_SMTP_USERNAME="NAME",
            EMAIL_TOOL_SMTP_PASSWORD="NAME",
            EMAIL_TOOL_FROM_EMAIL="noreply@example.com",
            WEBUI_URL="https://chat.example.com/",
        )
        send = MagicMock(return_value=(True, ""))
        with patch.object(invite_email, "_send_app_email", send):
            invite_email.deliver_credit_request(
                config,
                ["ops@example.com"],
                "Sam",
                "sam@example.com",
                "Rain Team",
                "Organization limit",
                300.0,
                300.0,
                None,
                "Need <more> runs",
                "/admin/users",
            )
        _, reply_to, to, subject, body, html_body, _ = send.call_args.args
        self.assertEqual(reply_to, "sam@example.com")
        self.assertEqual(to, ["ops@example.com"])
        self.assertIn("Rain Team", subject)
        self.assertIn("300.00 of 300.00 credits", body)
        self.assertIn("not specified", body)
        self.assertIn("https://chat.example.com/admin/users", body)
        self.assertIn("Need &lt;more&gt; runs", html_body)

    def test_unconfigured_mail_is_an_error(self):
        with self.assertRaises(invite_email.InviteEmailError):
            invite_email.deliver_credit_request(
                SimpleNamespace(),
                ["ops@example.com"],
                "Sam",
                "sam@example.com",
                "Rain Team",
                "Organization limit",
                1.0,
                1.0,
                None,
                "x",
                "/admin/users",
            )


class AdminEmailsTest(unittest.TestCase):
    def test_owners_and_admins_without_excluded_or_duplicates(self):
        from open_webui.utils import organizations

        members = [
            SimpleNamespace(role="owner", email="Lead@example.com"),
            SimpleNamespace(role="admin", email="lead@example.com"),
            SimpleNamespace(role="admin", email="sam@example.com"),
            SimpleNamespace(role="user", email="member@example.com"),
            SimpleNamespace(role="admin", email=None),
        ]
        with patch.object(
            organizations.Organizations, "get_members", return_value=members
        ):
            self.assertEqual(
                organizations.admin_emails("org-1", exclude="Sam@example.com"),
                ["lead@example.com"],
            )


if __name__ == "__main__":
    unittest.main()
