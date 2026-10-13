"""TechJobs.lk – engineering/technical vacancies. The homepage shows the latest
vacancies; the listing page loads more through a small form endpoint."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "TechJobs.lk"
HOME = "https://techjobs.lk/"
FETCH = "https://techjobs.lk/Jobs_home/fetch"


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def parse(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: dict[str, Job] = {}
    for a in soup.select('a[href*="vacancy_id="]'):
        title = _text(a)
        href = a["href"].strip()
        vid = (parse_qs(urlparse(href).query).get("vacancy_id") or [""])[0]
        if not title or not vid or vid in jobs:
            continue
        box = a.find_parent(class_="inomation") or a.find_parent("div")
        info = [_text(li) for li in box.select("ul.info li")] if box else []
        jobs[vid] = Job(
            source=NAME,
            source_id=vid,
            title=title,
            url=href,
            company=_text(box.find("h5")) if box else "",
            location=info[0] if info else "",
        )
    return list(jobs.values())


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    jobs = {j.source_id: j for j in parse(http.get(HOME).text)}
    # The listing endpoint answers with more cards when it has any.
    limit, pages = 20, int(opts.get("max_pages", 3))
    for page in range(pages):
        form = {"limit": limit, "start": page * limit, "job_type_id": "", "occupation_cat_id": "",
                "industry_cat_id": "", "search_name": ""}
        try:
            text = http.post(FETCH, data=form, headers={"X-Requested-With": "XMLHttpRequest",
                                                        "Referer": HOME + "vacancies"}).text
        except Exception:
            break  # the homepage results are still worth keeping
        batch = parse(text)
        if not batch:
            break
        for job in batch:
            jobs.setdefault(job.source_id, job)
    return list(jobs.values())
