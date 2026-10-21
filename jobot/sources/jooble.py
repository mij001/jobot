"""Jooble – a job search engine that gathers adverts from many Sri Lankan sites, through its official free API.

Off by default. Get a free key at https://jooble.org/api/about and store it as the JOOBLE_API_KEY secret.
"""

from __future__ import annotations

import hashlib
import re

from ..config import Config
from ..http import Http
from ..models import Job
from ..swarm import gather

NAME = "Jooble"
API = "https://jooble.org/api/{key}"
_TAGS = re.compile(r"<[^>]+>")


def missing(env: dict[str, str]) -> str | None:
    return None if env.get("JOOBLE_API_KEY") else "needs the JOOBLE_API_KEY secret (a free key from jooble.org/api/about)"


def _plain(text: str | None) -> str:
    return " ".join(_TAGS.sub(" ", text or "").replace("&nbsp;", " ").split())


def to_job(item: dict) -> Job | None:
    link = (item.get("link") or "").strip()
    title = _plain(item.get("title"))
    if not link or not title:
        return None
    return Job(
        source=NAME,
        source_id=str(item.get("id") or hashlib.sha1(link.encode()).hexdigest()[:16]),
        title=title,
        url=link,
        company=_plain(item.get("company")),
        location=_plain(item.get("location")),
        description=_plain(item.get("snippet")),
        category=_plain(item.get("source")),
        posted=str(item.get("updated") or "")[:10],
        salary=_plain(item.get("salary")),
    )


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    env = opts.get("_env") or {}
    if problem := missing(env):
        raise RuntimeError(problem)
    url = API.format(key=env["JOOBLE_API_KEY"])
    max_pages = int(opts.get("max_pages", 2))

    def one(conn: Http, query: str) -> list[Job]:
        jobs: list[Job] = []
        for page in range(1, max_pages + 1):
            body = {"keywords": query, "location": opts.get("location") or "Sri Lanka", "page": str(page)}
            items = (conn.post(url, json=body).json() or {}).get("jobs") or []
            jobs.extend(j for j in map(to_job, items) if j)
            if len(items) < 10:
                break
        return jobs

    found = gather(http, opts.get("queries") or ["electrical engineer"], one, workers=int(opts.get("workers", 2)),
                   label=lambda q: f"search {q!r}")
    return list({j.source_id: j for j in found}.values())
