"""LankaJobs (lankajobs.lk) – government, private and foreign vacancies."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "LankaJobs"
BASE = "https://lankajobs.lk/"
PAGE_SIZE = 24

_PAGE_RE = re.compile(r"CurrentPage=(\d+)")


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def _iso(text: str) -> str:
    try:  # the site writes month/day/year
        return datetime.strptime(text.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return text.strip()


def parse(html: str) -> tuple[list[Job], int]:
    """Jobs on one listing page, and the highest page number linked from it."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("a.task-listing[href]"):
        href = card["href"]
        heads = [_text(h) for h in card.select("h3.job-listing-title")]
        company = heads[0] if heads else ""
        title = _text(card.select_one("#en_jobs_v")) or _text(card.select_one("#si_jobs_v")) or (
            heads[1] if len(heads) > 1 else "")
        if not title:
            continue
        dates = {}
        for offer in card.select(".task-offers"):
            label, value = offer.find("span"), offer.find("strong")
            if label and value:
                dates[_text(label).rstrip(":").lower()] = _text(value)
        tags = [_text(t) for t in card.select(".task-tags span")]
        location = tags[1] if len(tags) > 1 and tags[1].lower() != "none" else ""
        kind = _text(card.select_one(".dashboard-status-button"))
        jobs.append(Job(
            source=NAME,
            source_id=href.rstrip("/").rsplit("/", 1)[-1],
            title=title,
            url=urljoin(BASE, href),
            company=company,
            location=location,
            category=kind,
            posted=_iso(dates.get("published date", "")),
            closing=_iso(dates.get("closing date", "")),
        ))
    pages = [int(n) for n in _PAGE_RE.findall(html)]
    return jobs, max(pages or [1])


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    max_pages = int(opts.get("max_pages", 8))
    jobs: list[Job] = []
    page, last = 1, 1
    while page <= min(last, max_pages):
        params = {"Keywords": "", "Location": "", "Category": opts.get("category", ""),
                  "JobType": "", "Sort": "NEWEST", "CurrentPage": page}
        batch, last = parse(http.get(BASE, params=params).text)
        if not batch:
            break
        jobs.extend(batch)
        page += 1
    return jobs
