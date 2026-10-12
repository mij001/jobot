"""topjobs.lk – lists every open vacancy of a functional area on one page."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "topjobs.lk"
BASE = "https://www.topjobs.lk"
LIST_URL = BASE + "/applicant/vacancybyfunctionalarea.jsp?FA={code}"
AD_URL = (BASE + "/employer/JobAdvertismentServlet?ac={ac}&jc={jc}&ec={ec}"
          "&pg=applicant/vacancybyfunctionalarea.jsp")

_ALERT_RE = re.compile(r"createAlert\('\d+','(\w+)','(\d+)','(\w+)'")
_COUNT_RE = re.compile(r"\s*\(\s*\d+\s*\)\s*$")


def _iso(text: str) -> str:
    text = " ".join(text.split())
    try:
        return datetime.strptime(text, "%a %b %d %Y").date().isoformat()
    except ValueError:
        return text


def parse(html: str, category: str = "") -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for tr in soup.select("tr[onclick*=createAlert]"):
        m = _ALERT_RE.search(tr.get("onclick", ""))
        tds = tr.find_all("td", recursive=False)
        if not m or len(tds) < 6:
            continue
        ac, jc, ec = m.groups()
        title_el = tds[2].find("h2")
        company_el = tds[2].find("h1")
        title = _COUNT_RE.sub("", title_el.get_text(" ", strip=True)) if title_el else ""
        if not title:
            continue
        jobs.append(Job(
            source=NAME,
            source_id=jc.lstrip("0") or jc,
            title=" ".join(title.split()),
            url=AD_URL.format(ac=ac, jc=jc, ec=ec),
            company=company_el.get_text(" ", strip=True) if company_el else "",
            description=tds[3].get_text(" ", strip=True).replace("\xa0", " ").strip(),
            category=category,
            posted=_iso(tds[4].get_text()),
            closing=_iso(tds[5].get_text()),
            location=tds[6].get_text(" ", strip=True) if len(tds) > 6 else "",
        ))
    return jobs


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    jobs: list[Job] = []
    for code in opts.get("categories") or ["MAE"]:
        resp = http.get(LIST_URL.format(code=code))
        resp.encoding = "utf-8"  # header says ISO-8859-1, the page itself is UTF-8
        jobs.extend(parse(resp.text, category=f"topjobs:{code}"))
    return jobs
