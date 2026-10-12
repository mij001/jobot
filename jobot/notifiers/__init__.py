"""Notification channels. Each is enabled by its environment variables."""

from __future__ import annotations

import os

from . import email, telegram

CHANNELS = {
    "telegram": telegram,
    "email": email,
}


def configured_channels(env: dict[str, str] | None = None) -> dict:
    env = dict(os.environ if env is None else env)
    return {name: mod for name, mod in CHANNELS.items() if mod.is_configured(env)}
