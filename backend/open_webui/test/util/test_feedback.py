"""In-app feedback is emailed to the help address with Reply-To set to the user."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

import open_webui.routers.users as users_router
from open_webui.utils import invite_email

USER = SimpleNamespace(id="u1", name="Sam", email="sam@example.com")


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=MagicMock()))
    )


class FeedbackRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_sends_to_help_address_only(self):
        deliver = MagicMock()
        with (
            patch("open_webui.env.WEBUI_HELP_EMAIL", "help@example.org"),
            patch.object(invite_email, "deliver_feedback", deliver),
        ):
            await users_router.send_feedback(
                _request(),
                users_router.FeedbackForm(
                    subject="Plot\r\nBcc: x@evil.test",
                    description=" It broke ",
                    chat_id="c-1",
                ),
                user=USER,
            )
        args = deliver.call_args.args
        self.assertEqual(
            args[1:],
            (
                "help@example.org",
                "Sam",
                "sam@example.com",
                "Plot Bcc: x@evil.test",
                "It broke",
                "c-1",
            ),
        )

    async def test_blank_fields_are_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await users_router.send_feedback(
                _request(),
                users_router.FeedbackForm(subject="  ", description="x"),
                user=USER,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_send_failure_is_a_plain_503(self):
        with patch.object(
            invite_email,
            "deliver_feedback",
            side_effect=invite_email.InviteEmailError("missing EMAIL_TOOL_SMTP_HOST"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await users_router.send_feedback(
                    _request(),
                    users_router.FeedbackForm(subject="Hi", description="x"),
                    user=USER,
                )
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, users_router.FEEDBACK_FAILED)

    def test_form_limits(self):
        with self.assertRaises(ValidationError):
            users_router.FeedbackForm(subject="Hi", description="x" * 5001)
        with self.assertRaises(ValidationError):
            users_router.FeedbackForm(subject="x" * 201, description="x")
        with self.assertRaises(ValidationError):
            users_router.FeedbackForm(subject="Hi", description="x", chat_id="../admin")


class DeliverFeedbackTest(unittest.TestCase):
    def _config(self, **overrides):
        values = dict(
            EMAIL_TOOL_SMTP_HOST="smtp.example.org",
            EMAIL_TOOL_SMTP_USERNAME="NAME",
            EMAIL_TOOL_SMTP_PASSWORD="NAME",
            EMAIL_TOOL_FROM_EMAIL="app@example.org",
            WEBUI_URL="https://chat.example.org/",
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_email_has_details_and_replies_to_user(self):
        send = MagicMock(return_value=(True, "sent"))
        with patch.object(invite_email, "_send_app_email", send):
            invite_email.deliver_feedback(
                self._config(),
                "help@example.org",
                "Sam",
                "sam@example.com",
                "Plot failed",
                "<b>broke</b>",
                "c-1",
            )
        _, reply_to, to, subject, body, html_body, _ = send.call_args.args
        self.assertEqual(reply_to, "sam@example.com")
        self.assertEqual(to, ["help@example.org"])
        self.assertEqual(subject, "Plot failed")
        self.assertIn("Name: Sam", body)
        self.assertIn("Email: sam@example.com", body)
        self.assertIn("Chat: https://chat.example.org/c/c-1", body)
        self.assertRegex(body, r"Time: \d{4}-\d\d-\d\d \d\d:\d\d UTC")
        self.assertIn("&lt;b&gt;broke&lt;/b&gt;", html_body)

    def test_missing_smtp_raises(self):
        with self.assertRaises(invite_email.InviteEmailError):
            invite_email.deliver_feedback(
                self._config(EMAIL_TOOL_SMTP_HOST=""),
                "help@example.org",
                "Sam",
                "sam@example.com",
                "Hi",
                "x",
            )

    def test_send_error_raises(self):
        with patch.object(
            invite_email, "_send_app_email", return_value=(False, "refused")
        ):
            with self.assertRaises(invite_email.InviteEmailError):
                invite_email.deliver_feedback(
                    self._config(),
                    "help@example.org",
                    "Sam",
                    "sam@example.com",
                    "Hi",
                    "x",
                )


if __name__ == "__main__":
    unittest.main()


class FeedbackLinkPromptTest(unittest.TestCase):
    def test_example_link_is_a_valid_prefilled_feedback_link(self):
        import re
        from urllib.parse import parse_qs

        from open_webui.utils.payload import FEEDBACK_LINK_PROMPT

        hrefs = re.findall(r"\]\((#feedback[^)\s]*)\)", FEEDBACK_LINK_PROMPT)
        self.assertIn("#feedback", hrefs)
        prefilled = [h for h in hrefs if h.startswith("#feedback?")]
        self.assertEqual(len(prefilled), 1)
        query = parse_qs(prefilled[0][len("#feedback?") :])
        self.assertEqual(
            query["description"],
            [
                "I asked for a rainfall map of Kenya. "
                'The CHIRPS fetch failed with "HTTP 503".'
            ],
        )
