"""Rooster (rooster.jobs) – JSON search API used by its Next.js front-end."""

from __future__ import annotations

import re

from ..config import Config
from ..http import Http
from ..models import Job
from ..swarm import gather

NAME = "Rooster"
API = "https://api.rooster.jobs/jobSearch/jobs/search"
JOB_URL = "https://rooster.jobs/jobs/{id}"
PAGE_SIZE = 100

_MARKDOWN = re.compile(r"[*_#>`]+")


def _salary(item: dict) -> str:
    lo, hi = item.get("min_salary"), item.get("max_salary")
    if not lo and not hi:
        return ""
    amount = f"{lo:,} - {hi:,}" if lo and hi else f"{lo or hi:,}"
    extra = " ".join(x for x in (item.get("salary_currency"), item.get("salary_frequency")) if x)
    return f"{amount} {extra}".strip()


def to_job(item: dict) -> Job:
    company = item.get("subsidiary_company_name") or item.get("company_name") or ""
    category = " / ".join(x for x in (item.get("class"), item.get("subclass"), item.get("department")) if x)
    return Job(
        source=NAME,
        source_id=str(item["id"]),
        title=" ".join((item.get("title") or "").split()),
        url=JOB_URL.format(id=item["id"]),
        company=company.strip(),
        location=(item.get("location") or "").strip(),
        description=_MARKDOWN.sub("", item.get("description") or ""),
        category=category,
        posted=(item.get("created_at") or "")[:10],
        salary=_salary(item),
        level_hint="internship" if (item.get("job_type") or "").lower() == "internship" else None,
    )


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    max_pages = int(opts.get("max_pages", 3))
    country = opts.get("country") or "Sri Lanka"

    def one(conn: Http, query: str) -> list[Job]:
        jobs: list[Job] = []
        for page in range(1, max_pages + 1):
            body = {
                "query": [query],
                "limit": PAGE_SIZE,
                "page": page,
                "filters": {"country": country},
            }
            data = (conn.post(API, json=body).json() or {}).get("body") or {}
            items = data.get("data") or []
            jobs.extend(to_job(item) for item in items)
            if page * PAGE_SIZE >= (data.get("count") or 0) or not items:
                break
        return jobs

    found = gather(http, opts.get("queries") or ["electrical"], one, workers=int(opts.get("workers", 3)),
                   label=lambda q: f"search {q!r}")
    return list({j.source_id: j for j in found}.values())  # the same job matches several searches
