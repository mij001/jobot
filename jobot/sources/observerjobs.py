"""Observer Jobs (observerjobs.lk, Lake House) – many government vacancies.

The site is a Laravel/Inertia app: each page carries its data as JSON in the
`data-page` attribute, so no HTML scraping is needed.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "Observer Jobs"
LIST_URL = "https://www.observerjobs.lk/vacancies"
JOB_URL = "https://www.observerjobs.lk/vacancy/{id}/{slug}"

_PAGE_RE = re.compile(r'data-page="([^"]*)"')


def page_data(text: str) -> dict:
    m = _PAGE_RE.search(text)
    if not m:
        raise ValueError("Observer Jobs layout changed: data-page not found")
    return json.loads(html.unescape(m.group(1)))


def _iso(text: str) -> str:
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return text.strip()


def parse(text: str) -> tuple[list[Job], int]:
    """Jobs on one listing page, and the number of the last page."""
    results = page_data(text)["props"]["jobs"]
    jobs = []
    for item in results.get("data", []):
        company = item.get("company") or {}
        categories = [c.get("name", "") for c in item.get("categories") or []]
        if (item.get("type") or "").lower() == "internship":
            hint = "internship"
        else:
            hint = None
        salary = item.get("salary") or ""
        jobs.append(Job(
            source=NAME,
            source_id=str(item["id"]),
            title=" ".join((item.get("title") or "").split()),
            url=JOB_URL.format(id=item["id"], slug=item.get("slug") or "job"),
            company="" if company.get("is_name_withheld") else (company.get("name") or "").strip(),
            location=(item.get("location") or "").strip(),
            description=" ".join(x for x in (item.get("description"), item.get("years_experience"),
                                             item.get("minimum_qualification")) if x),
            category=" / ".join(categories),
            posted=_iso(item.get("created_at") or ""),
            closing=_iso(item.get("deadline") or ""),
            salary="" if salary in ("", "0") else str(salary),
            level_hint=hint,
        ))
    return jobs, int(results.get("last_page") or 1)


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    max_pages = int(opts.get("max_pages", 10))
    jobs: list[Job] = []
    page, last = 1, 1
    while page <= min(last, max_pages):
        batch, last = parse(http.get(LIST_URL, params={"page": page}).text)
        jobs.extend(batch)
        page += 1
    return jobs
