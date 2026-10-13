"""Watches employers' own careers pages (e.g. CEB, SLT-Mobitel) for vacancy links.

Each page in config.yaml (sources.company_pages.pages) is fetched, and every
link whose text looks like a vacancy becomes a job. Give a page a `subfield`
to tag everything found there (useful when the link only says "Technician"),
otherwise the normal keyword matching decides.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "Company pages"

# Link text (or URL) must look like a vacancy …
_JOBLIKE = re.compile(
    r"\b(vacanc\w*|recruit\w*|engineers?|officers?|technicians?|technical|assistants?|managers?|"
    r"interns?|internships?|trainees?|apprentices?|operators?|executives?|supervisors?|"
    r"superintendents?|post of|positions?)\b|\.pdf\b",
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


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    jobs: list[Job] = []
    errors = []
    for page in opts.get("pages") or []:
        if not page.get("url"):
            continue
        try:
            jobs.extend(parse(http.get(page["url"]).text, page))
        except Exception as exc:  # one broken page mustn't hide the others
            errors.append(f"{page.get('name') or page['url']}: {exc}")
    if errors and not jobs:
        raise RuntimeError("; ".join(errors))
    return jobs
