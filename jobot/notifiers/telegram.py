"""Telegram bot notifications (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)."""

from __future__ import annotations

import time

import requests

from ..report import Report

API = "https://api.telegram.org/bot{token}/sendMessage"


def is_configured(env: dict[str, str]) -> bool:
    return bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"))


def send(report: Report, env: dict[str, str]) -> None:
    url = API.format(token=env["TELEGRAM_BOT_TOKEN"])
    # Several chat ids may be given, comma-separated.
    chat_ids = [c.strip() for c in env["TELEGRAM_CHAT_ID"].split(",") if c.strip()]
    for chat_id in chat_ids:
        for text in report.telegram_messages():
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 429:  # flood control: wait as told, retry once
                time.sleep(int(resp.json().get("parameters", {}).get("retry_after", 5)) + 1)
                resp = requests.post(url, json=payload, timeout=30)
            if not resp.ok:
                # Don't echo the URL: it contains the bot token.
                raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text[:300]}")
            time.sleep(1)
