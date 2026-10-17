"""Outgoing email: Resend API, Brevo API, or plain SMTP. Falls back to the server log."""
import html
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

import httpx

from backend import settings

log = logging.getLogger("synapse.mail")


def provider():
    if settings.RESEND_API_KEY and settings.MAIL_FROM:
        return "resend"
    if settings.BREVO_API_KEY and settings.MAIL_FROM:
        return "brevo"
    if settings.SMTP_HOST and settings.MAIL_FROM:
        return "smtp"
    return None


def email_enabled():
    return provider() is not None


def _send_resend(to, subject, text, body_html):
    response = httpx.post(
        "https://api.resend.com/emails",
        timeout=20,
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        json={"from": settings.MAIL_FROM, "to": [to], "subject": subject, "text": text, "html": body_html},
    )
    response.raise_for_status()


def _send_brevo(to, subject, text, body_html):
    name, address = parseaddr(settings.MAIL_FROM)
    sender = {"email": address}
    if name:
        sender["name"] = name
    response = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        timeout=20,
        headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"},
        json={
            "sender": sender,
            "to": [{"email": to}],
            "subject": subject,
            "textContent": text,
            "htmlContent": body_html,
        },
    )
    response.raise_for_status()


def _send_smtp(to, subject, text, body_html):
    message = EmailMessage()
    message["From"] = settings.MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(body_html, subtype="html")
    context = ssl.create_default_context()
    if settings.SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20, context=context)
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
    with server:
        if settings.SMTP_PORT != 465:
            server.starttls(context=context)
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(message)


def send_email(to, subject, text, body_html):
    """Send one email. Never raises; returns True when a provider accepted it."""
    kind = provider()
    if kind is None:
        log.warning("Email is not configured; the message was not sent.")
        return False
    try:
        {"resend": _send_resend, "brevo": _send_brevo, "smtp": _send_smtp}[kind](to, subject, text, body_html)
        return True
    except Exception as error:  # delivery problems must not break the request
        log.error("Could not send email via %s (%s).", kind, type(error).__name__)
        return False


def reset_email(username, link):
    minutes = settings.RESET_TTL // 60
    text = (
        f"Hi {username},\n\n"
        "Someone asked to reset the password for your Synapse account. "
        f"Open this link within {minutes} minutes to choose a new one:\n\n{link}\n\n"
        "If this wasn't you, ignore this email. Your password stays the same.\n\n- Synapse"
    )
    safe_name = html.escape(username)
    safe_link = html.escape(link, quote=True)
    body = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#e9ece7;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#e9ece7;padding:32px 12px;">
<tr><td align="center">
<table role="presentation" width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;background:#fbfcfa;border-radius:14px;overflow:hidden;font-family:Helvetica,Arial,sans-serif;color:#141922;">
<tr><td style="background:#0f1a3a;padding:22px 28px;">
<span style="display:inline-block;width:26px;height:26px;border-radius:7px;background:#3e63ff;color:#fff;font-weight:700;text-align:center;line-height:26px;font-size:15px;">S</span>
<span style="color:#fff;font-size:18px;font-weight:700;letter-spacing:-0.3px;vertical-align:middle;margin-left:8px;">Synapse</span>
</td></tr>
<tr><td style="padding:30px 28px 8px;">
<h1 style="margin:0 0 12px;font-size:22px;line-height:1.25;letter-spacing:-0.4px;">Reset your password</h1>
<p style="margin:0 0 22px;font-size:15px;line-height:1.6;color:#3b4252;">Hi {safe_name}, someone asked to reset the password for your Synapse account. This link works for {minutes} minutes.</p>
<a href="{safe_link}" style="display:inline-block;background:#2748ff;color:#ffffff;text-decoration:none;font-weight:600;font-size:15px;padding:13px 22px;border-radius:10px;">Choose a new password</a>
<p style="margin:24px 0 6px;font-size:13px;line-height:1.5;color:#6a7284;">Button not working? Paste this address into your browser:</p>
<p style="margin:0 0 22px;font-size:13px;line-height:1.5;word-break:break-all;"><a href="{safe_link}" style="color:#2748ff;">{safe_link}</a></p>
</td></tr>
<tr><td style="padding:0 28px 28px;">
<p style="margin:0;padding-top:16px;border-top:1px solid #dfe3dc;font-size:13px;line-height:1.5;color:#6a7284;">If this wasn't you, ignore this email. Your password stays the same.</p>
</td></tr>
</table>
</td></tr></table>
</body></html>"""
    return "Reset your Synapse password", text, body


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
