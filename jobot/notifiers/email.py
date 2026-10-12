"""E-mail digest over SMTP (SMTP_USERNAME + SMTP_PASSWORD + EMAIL_TO).

Defaults to Gmail (smtp.gmail.com:587). With Gmail, SMTP_PASSWORD must be an
"App password", not your normal password.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from ..report import Report


def is_configured(env: dict[str, str]) -> bool:
    return bool(env.get("SMTP_USERNAME") and env.get("SMTP_PASSWORD") and env.get("EMAIL_TO"))


def send(report: Report, env: dict[str, str]) -> None:
    host = env.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(env.get("SMTP_PORT") or 587)
    user = env["SMTP_USERNAME"]

    msg = EmailMessage()
    msg["Subject"] = report.title
    msg["From"] = env.get("EMAIL_FROM") or user
    msg["To"] = env["EMAIL_TO"]
    msg.set_content(report.email_text())
    msg.add_alternative(report.email_html(), subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as smtp:
            smtp.login(user, env["SMTP_PASSWORD"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.starttls(context=context)
            smtp.login(user, env["SMTP_PASSWORD"])
            smtp.send_message(msg)
