"""Good manners for sites that have no API: read robots.txt before visiting a page automatically."""

from __future__ import annotations

import threading
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from .http import USER_AGENT


class RobotsCache:
    """robots.txt per site, fetched once per run. A robots.txt that can't be read means "no rules"."""

    def __init__(self) -> None:
        self._rules: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def allows(self, http, url: str) -> bool | None:
        """True / False from the site's rules for our user agent; None when the site has none we could read."""
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            if host not in self._rules:
                self._rules[host] = self._read(http, host)
            rules = self._rules[host]
        return None if rules is None else rules.can_fetch(USER_AGENT, url)

    @staticmethod
    def _read(http, host: str) -> RobotFileParser | None:
        try:
            text = http.get(f"{host}/robots.txt", timeout=(6, 10)).text
        except (requests.RequestException, OSError):
            return None
        if "<html" in text[:300].lower():  # an error page, not rules
            return None
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return parser
