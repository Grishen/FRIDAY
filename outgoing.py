"""Outgoing message helpers: email + Slack.

Email (SMTP, stdlib only):

- ``JARVIS_SMTP_HOST``  (e.g. smtp.gmail.com)
- ``JARVIS_SMTP_PORT``  (default 587)
- ``JARVIS_SMTP_USER``  (login)
- ``JARVIS_SMTP_PASS``  (app password / token)
- ``JARVIS_EMAIL_FROM`` (display from address; defaults to SMTP_USER)
- ``JARVIS_EMAIL_TO_DEFAULT`` (default recipient for "email myself")

Slack (incoming webhook):

- ``JARVIS_SLACK_WEBHOOK`` — full webhook URL from Slack admin.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional


# ---------- email ----------

def _smtp_configured() -> bool:
    return all(
        os.environ.get(k, "").strip()
        for k in ("JARVIS_SMTP_HOST", "JARVIS_SMTP_USER", "JARVIS_SMTP_PASS")
    )


def send_email(
    *,
    subject: str,
    body: str,
    to: Optional[str] = None,
    sender: Optional[str] = None,
) -> str:
    """Send a plaintext email via configured SMTP server."""
    if not _smtp_configured():
        return (
            "Email is not configured. Set JARVIS_SMTP_HOST, JARVIS_SMTP_USER, "
            "JARVIS_SMTP_PASS (and optionally JARVIS_EMAIL_FROM)."
        )
    subject = (subject or "").strip() or "(no subject)"
    body = (body or "").strip()
    if not body:
        return "Refusing to send empty email body."

    host = os.environ["JARVIS_SMTP_HOST"].strip()
    try:
        port = int(os.environ.get("JARVIS_SMTP_PORT", "587"))
    except ValueError:
        port = 587
    user = os.environ["JARVIS_SMTP_USER"].strip()
    pw = os.environ["JARVIS_SMTP_PASS"]
    from_addr = (sender or os.environ.get("JARVIS_EMAIL_FROM", "").strip() or user)
    to_addr = (
        (to or "").strip()
        or os.environ.get("JARVIS_EMAIL_TO_DEFAULT", "").strip()
        or from_addr
    )
    if not to_addr:
        return "No recipient available (set JARVIS_EMAIL_TO_DEFAULT or pass `to`)."

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as srv:
                srv.login(user, pw)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as srv:
                srv.ehlo()
                try:
                    srv.starttls(context=ssl.create_default_context())
                    srv.ehlo()
                except smtplib.SMTPException:
                    pass
                srv.login(user, pw)
                srv.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        return f"Email send failed: {exc}"
    return f"Email sent to {to_addr}: {subject}"


def email_myself(body: str, *, subject: Optional[str] = None) -> str:
    """Convenience: send to JARVIS_EMAIL_TO_DEFAULT (falls back to SMTP user)."""
    return send_email(
        subject=(subject or "Note from Jarvis").strip(),
        body=body or "",
        to=None,
    )


# ---------- Slack ----------

def slack_configured() -> bool:
    return bool(os.environ.get("JARVIS_SLACK_WEBHOOK", "").strip())


def slack_post(text: str, *, username: str = "Jarvis") -> str:
    """Post a message to a configured Slack incoming webhook."""
    if not slack_configured():
        return (
            "Slack is not configured. Set JARVIS_SLACK_WEBHOOK to an incoming-webhook URL."
        )
    body = (text or "").strip()
    if not body:
        return "Refusing to post empty Slack message."
    try:
        import requests
    except ImportError:
        return "The 'requests' package is required for Slack posting."
    try:
        resp = requests.post(
            os.environ["JARVIS_SLACK_WEBHOOK"].strip(),
            json={"text": body, "username": username},
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        return f"Slack post failed: {exc}"
    if 200 <= resp.status_code < 300:
        return "Posted to Slack."
    return f"Slack returned HTTP {resp.status_code}: {resp.text[:200]}"


__all__ = [
    "email_myself",
    "send_email",
    "slack_configured",
    "slack_post",
]
