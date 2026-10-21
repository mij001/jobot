"""Watches employers' own careers pages (e.g. CEB, SLT-Mobitel) for vacancy links.

Each page in config.yaml (sources.company_pages.pages) is fetched, and every
link whose text looks like a vacancy becomes a job. Give a page a `subfield`
to tag everything found there (useful when the link only says "Technician"),
otherwise the normal keyword matching decides. This works for any page that
lists vacancies – a university's vacancies page, a job board's search results –
and a page that turns out to be an RSS/Atom feed is read as one. A page with
`pages: 3` is read for ?page=1..3 (`page_param` renames the parameter).

Pages are visited only if the site's robots.txt allows it (`respect_robots`).
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import Config
from ..http import Http
from ..models import Job
from ..robots import RobotsCache
from ..swarm import gather
from . import rss

NAME = "Company pages"

# Link text (or URL) must look like a vacancy …
_JOBLIKE = re.compile(
    r"\b(vacanc\w*|recruit\w*|engineers?|officers?|technicians?|technical|assistants?|managers?|"
    r"interns?|internships?|trainees?|apprentices?|operators?|executives?|supervisors?|"
    r"superintendents?|post of|positions?|lecturers?|instructors?|professors?|demonstrators?|"
    r"researchers?|walk-?in|calling applications)\b|\.pdf\b",
    re.IGNORECASE,
)
# … and not be site furniture.
_NOISE = re.compile(r"^(apply( now)?|read more|more|details|view|download|login|register|home|careers?)$",
                    re.IGNORECASE)


def parse(html: str, page: dict) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    name, url = page.get("name") or page["url"], page["url"]
    jobs, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        href = urljoin(url, a["href"])
        if not (6 <= len(text) <= 160) or _NOISE.match(text) or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        if not _JOBLIKE.search(text) and not _JOBLIKE.search(a["href"]):
            continue
        key = (text.lower(), href)
        if key in seen:
            continue
        seen.add(key)
        jobs.append(Job(
            source=name,
            source_id=hashlib.sha1(f"{text}|{href}".encode()).hexdigest()[:16],
            title=text,
            url=href,
            company=page.get("company") or name,
            category=page.get("category", ""),
            subfields=[page["subfield"]] if page.get("subfield") else [],
        ))
    return jobs


def _is_feed(text: str) -> bool:
    head = text[:1500].lower()
    return "<rss" in head or "<feed" in head or ("<?xml" in head and ("<channel" in text[:4000] or "<entry" in text[:4000]))


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    pages = [p for p in opts.get("pages") or [] if p.get("url")]
    robots = RobotsCache() if opts.get("respect_robots", True) else None

    def one(conn: Http, page: dict) -> list[Job]:
        if robots is not None and robots.allows(conn, page["url"]) is False:
            raise RuntimeError("its robots.txt asks automated visitors to stay away")
        name, jobs = page.get("name") or page["url"], []
        for n in range(1, int(page.get("pages", 1)) + 1):
            params = {page.get("page_param") or "page": n} if n > 1 else None
            text = conn.get(page["url"], params=params).text
            batch = rss.parse(text, name) if _is_feed(text) else parse(text, page)
            jobs.extend(batch)
            if not batch:
                break
        return jobs

    # `one` is a closure over the shared robots cache; pages are read a few at a time on separate connections
    return gather(http, pages, one, workers=int(opts.get("workers", 4)), label=lambda p: p.get("name") or p["url"])
