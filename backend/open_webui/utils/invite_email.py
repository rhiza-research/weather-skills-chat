import datetime
import html
from pathlib import Path

from open_webui.utils.builtin_tools import _send_via_smtp

_FAVICON_PATH = Path(__file__).resolve().parents[1] / "static" / "favicon-96x96.png"


class InviteEmailError(Exception):
    def __init__(self, message: str, saved: bool = False):
        super().__init__(message)
        self.saved = saved


def smtp_is_configured(config) -> str:
    host = (getattr(config, "EMAIL_TOOL_SMTP_HOST", "") or "").strip()
    username = (getattr(config, "EMAIL_TOOL_SMTP_USERNAME", "") or "").strip()
    password = (getattr(config, "EMAIL_TOOL_SMTP_PASSWORD", "") or "").strip()
    from_email = (getattr(config, "EMAIL_TOOL_FROM_EMAIL", "") or "").strip()
    missing = []
    if not host:
        missing.append("EMAIL_TOOL_SMTP_HOST")
    if not username:
        missing.append("EMAIL_TOOL_SMTP_USERNAME")
    if not password:
        missing.append("EMAIL_TOOL_SMTP_PASSWORD")
    if not from_email:
        missing.append("EMAIL_TOOL_FROM_EMAIL")
    if missing:
        return f"Email delivery is not configured (missing {', '.join(missing)})."
    return ""


def invite_link(config, token: str) -> str:
    base = (getattr(config, "WEBUI_URL", "") or "").rstrip("/")
    return f"{base}/auth/invite?token={token}"


def _favicon_png() -> bytes | None:
    if not _FAVICON_PATH.is_file():
        return None
    return _FAVICON_PATH.read_bytes()


def _invite_html(lead: str, link_label: str, link: str, expiry: str, show_icon: bool) -> str:
    icon = ""
    if show_icon:
        icon = (
            '<img src="cid:favicon" width="48" height="48" alt="Weather Skills" '
            'style="border-radius:12px;display:block;margin:0 0 16px;" />'
        )
    safe_link = html.escape(link, quote=True)
    return (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#1c1917;font-size:16px;line-height:1.5;">'
        f"{icon}"
        f"<p>{html.escape(lead)}</p>"
        f'<p><a href="{safe_link}">{html.escape(link_label)}</a></p>'
        f'<p style="color:#57534e;font-size:14px;">This invitation expires on {html.escape(expiry)}.</p>'
        f'<p style="color:#a8a29e;font-size:12px;">{safe_link}</p>'
        "</div>"
    )


def deliver_invite_email(
    config,
    to: str,
    kind: str,
    token: str,
    organization_name: str = "",
    expires_at: int = 0,
    inviter_name: str = "",
) -> None:
    missing = smtp_is_configured(config)
    if missing:
        raise InviteEmailError(missing, saved=False)

    app_name = "Weather Skills"
    link = invite_link(config, token)
    expiry = datetime.datetime.fromtimestamp(
        expires_at, datetime.timezone.utc
    ).strftime("%B %d, %Y")
    inviter = (inviter_name or "").strip() or "Someone"
    if kind == "organization":
        subject = f"Invitation to the {organization_name} organization on {app_name}"
        lead = f"{inviter} has invited you to the {organization_name} organization on {app_name}."
        link_label = "Open this link to accept the invitation"
        body = f"{lead}\n\n{link_label}:\n{link}\n\nThis invitation expires on {expiry}."
    else:
        subject = f"Invitation to create an account on {app_name}"
        lead = f"{inviter} has invited you to create an account on {app_name}."
        link_label = "Open this link to create your account"
        body = f"{lead}\n\n{link_label}:\n{link}\n\nThis invitation expires on {expiry}."
    favicon = _favicon_png()
    html_body = _invite_html(lead, link_label, link, expiry, show_icon=favicon is not None)

    host = (getattr(config, "EMAIL_TOOL_SMTP_HOST", "") or "").strip()
    port = int(getattr(config, "EMAIL_TOOL_SMTP_PORT", 465) or 465)
    username = (getattr(config, "EMAIL_TOOL_SMTP_USERNAME", "") or "").strip()
    password = (getattr(config, "EMAIL_TOOL_SMTP_PASSWORD", "") or "").strip()
    use_tls = bool(getattr(config, "EMAIL_TOOL_SMTP_USE_TLS", True))
    from_email = (getattr(config, "EMAIL_TOOL_FROM_EMAIL", "") or "").strip()
    ok, err = _send_via_smtp(
        host,
        port,
        username,
        password,
        use_tls,
        app_name,
        from_email,
        from_email,
        [to],
        subject,
        body,
        html=html_body,
        inline_images=[("favicon", favicon, "png")] if favicon else None,
    )
    if not ok:
        raise InviteEmailError(
            f"Invitation saved, but the email could not be sent. Use Resend. ({err})",
            saved=True,
        )
