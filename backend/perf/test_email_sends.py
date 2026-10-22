"""App emails (#12): invitations, signup alerts and role approvals.

These routes send the email with smtplib inside an async handler, so the SMTP
connection, TLS handshake, login and send all hold the event loop.
"""

import asyncio
import smtplib
import time
from unittest.mock import patch

from perf_harness import LoopProbe, check_budget, db_delay, record
from perf_harness.app_data import asgi_client, ensure_user, main_app

INVITES = 3
# Connect, TLS and EHLO to smtp.resend.com measured at 293 ms median from the
# staging pod; login and the message add a few ~55 ms round trips.
SMTP_SEND_S = 0.55


class _SMTP:
    def __init__(self, *args, **kwargs):
        time.sleep(SMTP_SEND_S)

    def __getattr__(self, name):
        return lambda *args, **kwargs: (250, b"ok")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_send_invitations(tmp_path):
    from open_webui.models.organizations import Organizations

    user = ensure_user()
    Organizations.ensure_platform(owner_user_id=user.id)
    app = main_app(user)
    config = app.state.config
    config.EMAIL_TOOL_SMTP_HOST = "smtp.test"
    config.EMAIL_TOOL_SMTP_PORT = 465
    config.EMAIL_TOOL_SMTP_USERNAME = "resend"
    config.EMAIL_TOOL_SMTP_PASSWORD = "test-password"
    config.EMAIL_TOOL_SMTP_USE_TLS = True
    config.EMAIL_TOOL_FROM_EMAIL = "help@example.com"
    config.WEBUI_URL = "https://chat.test"

    async def run():
        async with asgi_client(app) as client:
            async with LoopProbe() as probe:
                for i in range(INVITES):
                    response = await client.post(
                        "/api/v1/users/invitations",
                        json={"email": f"invitee-{time.time_ns()}-{i}@example.com"},
                    )
                    assert response.status_code == 200, response.text
        return probe.stats

    with patch.object(smtplib, "SMTP_SSL", _SMTP), patch.object(smtplib, "SMTP", _SMTP), db_delay():
        stats = asyncio.run(run())
    record(f"email: {INVITES} invitations sent", stats)
    check_budget(stats, max_lag_ms=50, pending="#12 SMTP on the loop")
