import datetime
import html
from pathlib import Path

from open_webui.utils.builtin_tools import _send_via_smtp

_FAVICON_PATH = Path(__file__).resolve().parents[1] / "static" / "favicon-96x96.png"


def _send_app_email(
    config,
    reply_to: str | None,
    to: list[str],
    subject: str,
    body: str,
    html_body: str,
    favicon: bytes | None,
) -> tuple[bool, str]:
    """Send from the app's sender address; replies go to ``reply_to`` or the sender."""
    from_email = (getattr(config, "EMAIL_TOOL_FROM_EMAIL", "") or "").strip()
    return _send_via_smtp(
        (getattr(config, "EMAIL_TOOL_SMTP_HOST", "") or "").strip(),
        int(getattr(config, "EMAIL_TOOL_SMTP_PORT", 465) or 465),
        (getattr(config, "EMAIL_TOOL_SMTP_USERNAME", "") or "").strip(),
        (getattr(config, "EMAIL_TOOL_SMTP_PASSWORD", "") or "").strip(),
        bool(getattr(config, "EMAIL_TOOL_SMTP_USE_TLS", True)),
        "Weather Skills",
        from_email,
        reply_to or from_email,
        to,
        subject,
        body,
        html=html_body,
        inline_images=[("favicon", favicon, "png")] if favicon else None,
    )


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


_INVITE_ASSISTANCE = (
    "Please reply to this email or send a message to help@weather-skills.org "
    "if you need assistance."
)


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
        f"<p>{html.escape(_INVITE_ASSISTANCE)}</p>"
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
    else:
        subject = f"Invitation to create an account on {app_name}"
        lead = f"{inviter} has invited you to create an account on {app_name}."
        link_label = "Open this link to create your account"
    body = (
        f"{lead}\n\n{link_label}:\n{link}\n\n"
        f"This invitation expires on {expiry}.\n\n{_INVITE_ASSISTANCE}"
    )
    favicon = _favicon_png()
    html_body = _invite_html(lead, link_label, link, expiry, show_icon=favicon is not None)

    ok, err = _send_app_email(
        config, None, [to], subject, body, html_body, favicon
    )
    if not ok:
        raise InviteEmailError(
            f"Invitation saved, but the email could not be sent. Use Resend. ({err})",
            saved=True,
        )


def deliver_signup_alert(
    config,
    admin_emails: list[str],
    name: str,
    email: str,
    description: str,
) -> None:
    missing = smtp_is_configured(config)
    if missing:
        raise InviteEmailError(missing, saved=False)

    recipients = []
    seen = set()
    for raw in admin_emails:
        addr = (raw or "").strip().lower()
        if addr and addr not in seen:
            seen.add(addr)
            recipients.append(addr)
    if not recipients:
        return

    app_name = "Weather Skills"
    person = (name or "").strip() or email
    subject = f"New signup on {app_name}: {person}"
    body = (
        f"{person} signed up for {app_name}.\n\n"
        f"Name: {person}\n"
        f"Email: {email}\n\n"
        f"Description:\n{description}"
    )
    base = (getattr(config, "WEBUI_URL", "") or "").rstrip("/")
    admin_url = f"{base}/admin/users" if base else ""
    if admin_url:
        body = f"{body}\n\nReview users:\n{admin_url}"
    favicon = _favicon_png()
    html_body = (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#1c1917;font-size:16px;line-height:1.5;">'
        + (
            '<img src="cid:favicon" width="48" height="48" alt="Weather Skills" '
            'style="border-radius:12px;display:block;margin:0 0 16px;" />'
            if favicon
            else ""
        )
        + f"<p><strong>{html.escape(person)}</strong> signed up for {html.escape(app_name)}.</p>"
        + "<p>"
        + f"Name: {html.escape(person)}<br>"
        + f"Email: {html.escape(email)}"
        + "</p>"
        + f"<p>Description:</p><p>{html.escape(description)}</p>"
        + (
            f'<p><a href="{html.escape(admin_url, quote=True)}">Review users</a></p>'
            if admin_url
            else ""
        )
        + "</div>"
    )

    ok, err = _send_app_email(
        config, email, recipients, subject, body, html_body, favicon
    )
    if not ok:
        raise InviteEmailError(f"Signup alert could not be sent. ({err})", saved=False)


def deliver_signup_approval(
    config,
    to: str,
    approver_name: str,
    help_email: str,
) -> None:
    missing = smtp_is_configured(config)
    if missing:
        raise InviteEmailError(missing, saved=False)
    recipient = (to or "").strip().lower()
    if not recipient:
        return

    app_name = "Weather Skills"
    approver = (approver_name or "").strip() or "An administrator"
    help_addr = (help_email or "").strip()
    base = (getattr(config, "WEBUI_URL", "") or "").rstrip("/")
    sign_in = base or app_name
    subject = f"Welcome to {app_name}"
    body = (
        f"Welcome to {app_name}! {approver} approved your signup request. "
        f"You can now sign in at {sign_in}. "
        f"If you have further questions, please reach out to {help_addr}."
    )
    favicon = _favicon_png()
    sign_in_html = (
        f'<a href="{html.escape(base, quote=True)}">{html.escape(base)}</a>'
        if base
        else html.escape(app_name)
    )
    html_body = (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#1c1917;font-size:16px;line-height:1.5;">'
        + (
            '<img src="cid:favicon" width="48" height="48" alt="Weather Skills" '
            'style="border-radius:12px;display:block;margin:0 0 16px;" />'
            if favicon
            else ""
        )
        + "<p>"
        + f"Welcome to {html.escape(app_name)}! {html.escape(approver)} approved your signup request. "
        + f"You can now sign in at {sign_in_html}. "
        + f"If you have further questions, please reach out to {html.escape(help_addr)}."
        + "</p></div>"
    )

    ok, err = _send_app_email(
        config, help_addr or from_email, [recipient], subject, body, html_body, favicon
    )
    if not ok:
        raise InviteEmailError(f"Signup approval could not be sent. ({err})", saved=False)


def deliver_credit_request(
    config,
    admin_emails: list[str],
    requester_name: str,
    requester_email: str,
    organization_name: str,
    limit_label: str,
    used: float,
    limit: float | None,
    requested: float | None,
    reason: str,
    review_path: str,
) -> None:
    """Email the admins who can raise a limit that a user asked for more credits."""
    missing = smtp_is_configured(config)
    if missing:
        raise InviteEmailError(missing, saved=False)
    if not admin_emails:
        raise InviteEmailError("No admin can receive this request.", saved=False)

    app_name = "Weather Skills"
    person = (requester_name or "").strip() or requester_email
    used_text = f"{used:.2f}"
    limit_text = f"{limit:.2f}" if limit is not None else "none"
    requested_text = f"{requested:.2f}" if requested is not None else "not specified"
    subject = f"Credit increase request for {organization_name} on {app_name}"
    lead = f"{person} asked for more credits in the {organization_name} organization."
    details = [
        ("Name", person),
        ("Email", requester_email),
        ("Organization", organization_name),
        ("Limit reached", limit_label),
        ("Used this month", f"{used_text} of {limit_text} credits"),
        ("Additional credits requested", requested_text),
    ]
    base = (getattr(config, "WEBUI_URL", "") or "").rstrip("/")
    review_url = f"{base}{review_path}" if base else ""

    body = lead + "\n\n" + "\n".join(f"{k}: {v}" for k, v in details)
    body += f"\n\nReason:\n{reason}"
    if review_url:
        body += f"\n\nChange the limit:\n{review_url}"

    favicon = _favicon_png()
    html_body = (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#1c1917;font-size:16px;line-height:1.5;">'
        + (
            '<img src="cid:favicon" width="48" height="48" alt="Weather Skills" '
            'style="border-radius:12px;display:block;margin:0 0 16px;" />'
            if favicon
            else ""
        )
        + f"<p>{html.escape(lead)}</p>"
        + "<p>"
        + "<br>".join(f"{html.escape(k)}: {html.escape(v)}" for k, v in details)
        + "</p>"
        + f'<p>Reason:</p><p style="white-space:pre-wrap;">{html.escape(reason)}</p>'
        + (
            f'<p><a href="{html.escape(review_url, quote=True)}">Change the limit</a></p>'
            if review_url
            else ""
        )
        + "</div>"
    )

    ok, err = _send_app_email(
        config, requester_email, admin_emails, subject, body, html_body, favicon
    )
    if not ok:
        raise InviteEmailError(
            f"The request could not be sent. ({err})", saved=False
        )
