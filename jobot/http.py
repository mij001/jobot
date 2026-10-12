"""Shared HTTP session: browser-like headers, retries and a polite delay."""

from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
TIMEOUT = 30


class Http:
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def get(self, url: str, **kwargs) -> requests.Response:
        self._wait()
        resp = self.session.get(url, timeout=TIMEOUT, **kwargs)
        resp.raise_for_status()
        if "charset" not in resp.headers.get("Content-Type", "").lower():
            resp.encoding = "utf-8"  # requests would otherwise assume ISO-8859-1
        return resp

    def post(self, url: str, **kwargs) -> requests.Response:
        self._wait()
        resp = self.session.post(url, timeout=TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp
