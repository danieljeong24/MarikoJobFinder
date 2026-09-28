"""Send the digest by SMTP. Settings come only from environment variables."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

REQUIRED = ("JOB_WATCH_SMTP_HOST", "JOB_WATCH_SMTP_USER", "JOB_WATCH_SMTP_PASSWORD", "JOB_WATCH_SMTP_TO")


class EmailConfigError(Exception):
    pass


def send_digest(subject: str, body: str) -> None:
    env = os.environ
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise EmailConfigError(f"missing environment variable(s): {', '.join(missing)}")

    host = env["JOB_WATCH_SMTP_HOST"]
    use_ssl = env.get("JOB_WATCH_SMTP_SSL", "0").lower() in ("1", "true", "yes")
    port = int(env.get("JOB_WATCH_SMTP_PORT") or (465 if use_ssl else 587))
    user = env["JOB_WATCH_SMTP_USER"]
    sender = env.get("JOB_WATCH_SMTP_FROM") or user
    recipients = [r.strip() for r in env["JOB_WATCH_SMTP_TO"].split(",") if r.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            smtp.login(user, env["JOB_WATCH_SMTP_PASSWORD"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, env["JOB_WATCH_SMTP_PASSWORD"])
            smtp.send_message(msg)
