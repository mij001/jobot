"""ITPro.lk – Sri Lanka's IT job board. Its Hardware & Networking, Internship
and latest-jobs pages carry embedded, IoT, network and hardware roles."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "ITPro.lk"
BASE = "https://itpro.lk/"


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def parse(html: str, category: str = "") -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("article.job-card"):
        link = card.select_one("a[href]")
        title = _text(card.select_one(".jc-title"))
        if not link or not title:
            continue
        posted = card.select_one("time[datetime]")
        jobs.append(Job(
            source=NAME,
            source_id=card.get("id") or link["href"],
            title=title,
            url=link["href"],
            company=_text(card.select_one(".jc-company")),
            location=_text(card.select_one(".jc-company-info .la")),
            category=category.replace("-", " "),
            posted=(posted["datetime"][:10] if posted else ""),
            level_hint="internship" if category == "internship" else None,
        ))
    return jobs


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    jobs: dict[str, Job] = {}
    for category in opts.get("categories") or [""]:
        url = BASE + (f"jobs/{category}/" if category else "")
        for job in parse(http.get(url).text, category):
            jobs.setdefault(job.source_id, job)
    return list(jobs.values())
