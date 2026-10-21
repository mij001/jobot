"""Shared HTTP session: browser-like headers, retries and a polite delay.

Each job site gets its own `Http` (and each parallel worker a `clone()` of it), so
the delay between requests is kept per site while different sites are fetched
at the same time.
"""

from __future__ import annotations

import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
TIMEOUT = (10, 30)  # connect, read – a site that doesn't answer is given up on quickly


class SourceTimeout(TimeoutError):
    """The site used up the time it was given for this run."""


class Http:
    def __init__(self, delay: float = 1.0, timeout: tuple[float, float] = TIMEOUT, retries: int = 2,
                 deadline: float | None = None, warnings: list[str] | None = None):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.deadline = deadline  # time.monotonic() value after which no more requests are made
        self.warnings: list[str] = warnings if warnings is not None else []  # problems that didn't stop the site
        self._last = 0.0
        self._lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        retry = Retry(
            total=retries,
            connect=retries,
            read=1,  # a read that timed out once is worth one more try, not three
            backoff_factor=1,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def clone(self) -> Http:
        """Another connection to the same site for a parallel worker (same delay, deadline and notes)."""
        return Http(self.delay, self.timeout, self.retries, self.deadline, self.warnings)

    def note(self, message: str) -> None:
        """Record a problem that didn't stop the site from being read (shown as a warning)."""
        self.warnings.append(message)

    def _wait(self) -> None:
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise SourceTimeout("gave up: the site took too long this run")
        with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self._last = time.monotonic()

    def get(self, url: str, **kwargs) -> requests.Response:
        self._wait()
        resp = self.session.get(url, timeout=kwargs.pop("timeout", self.timeout), **kwargs)
        resp.raise_for_status()
        if "charset" not in resp.headers.get("Content-Type", "").lower():
            resp.encoding = "utf-8"  # requests would otherwise assume ISO-8859-1
        return resp

    def post(self, url: str, **kwargs) -> requests.Response:
        self._wait()
        resp = self.session.post(url, timeout=kwargs.pop("timeout", self.timeout), **kwargs)
        resp.raise_for_status()
        return resp
