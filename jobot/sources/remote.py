"""Fully remote jobs you can do from Sri Lanka, from the open remote-job feeds and APIs.

Remote job boards list thousands of jobs, but most are open only to people in the US or Europe. Every
job here is checked against where the employer says candidates may live (`open_to_sri_lanka`): only
"worldwide / anywhere / APAC / Asia / Sri Lanka" jobs, or ones with no restriction at all, are kept,
and those with a time-zone requirement that Sri Lanka can't meet are dropped. The kept jobs are marked
remote, and then go through your usual sub-field / level / qualification settings.

Providers (all free, public, and asking for a link back to them – the job links point to the source site):
Remotive, Remote OK, We Work Remotely, Jobicy, Himalayas, Working Nomads. Choose with `providers:`.
"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from ..config import Config
from ..http import Http
from ..models import Job
from ..swarm import gather

NAME = "Remote jobs"

# What an EEE person can do remotely – also the search words for the providers that have a search.
DEFAULT_QUERIES = ["embedded", "firmware", "electrical engineer", "electronics engineer", "hardware engineer", "PCB",
                   "FPGA", "power systems", "controls engineer", "automation engineer", "IoT", "RF engineer",
                   "telecommunications", "network engineer", "solar", "test engineer", "mechatronics", "robotics"]

_TAGS = re.compile(r"<[^>]+>")
# Words that mean "candidates may live anywhere, Sri Lanka included". "Asia" counts, "Southeast / East Asia" doesn't.
_WORLD = re.compile(
    r"\b(?:worldwide|world[\s-]?wide|anywhere|global(?:ly)?|international|any (?:country|location)|all countries|everywhere|"
    r"apac|asia[\s-]pacific|south asia|sri\s?lanka)\b|(?<!east )(?<!east-)(?<!central )(?<!west )\basia\b", re.I)
_BOUND = re.compile(r"\banywhere (?:in|within) (?!(?:the )?world\b)", re.I)  # "Anywhere in India" is a restriction
_ZONE = re.compile(r"\btime\s?zones?\b|\boverlap\b|\b(?:cet|cest|est|edt|cst|cdt|pst|pdt|eet|bst|gmt|utc)\b|"
                   r"\b(?:us|u\.s\.|eu|uk|european|american|north american)\s+(?:time|hours|business hours)\b", re.I)
_SL_ZONE = re.compile(r"\b(?:ist|gmt\s*\+\s*5|utc\s*\+\s*5|asia|apac)\b", re.I)


def open_to_sri_lanka(where: str, empty_ok: bool = False) -> bool:
    """Can someone living in Sri Lanka take a job whose location restriction reads `where`?"""
    text = " ".join(html.unescape(where or "").split())
    if not text:
        return empty_ok
    if re.search(r"sri\s?lanka", text, re.I):
        return True
    if _BOUND.search(text) or not _WORLD.search(text):
        return False
    # "Worldwide, but must overlap US hours" is not open to Sri Lanka's time zone
    return not _ZONE.search(text) or bool(_SL_ZONE.search(text))


def _plain(text, limit: int = 600) -> str:
    if isinstance(text, list):
        text = ", ".join(str(t) for t in text)
    elif isinstance(text, str) and text.startswith("[") and text.endswith("]"):
        text = text.strip("[]").replace("'", "").replace('"', "")
    return " ".join(html.unescape(_TAGS.sub(" ", str(text or ""))).split())[:limit]


def _iso(value) -> str:
    if value in (None, "", "None"):
        return ""
    try:
        if str(value).isdigit():
            return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
        return str(value)[:10]
    except (ValueError, OSError):
        return ""


def _salary(lo, hi, currency="", period="") -> str:
    def clean(x) -> str:
        try:
            n = int(float(x))
        except (TypeError, ValueError):
            return ""
        return f"{n:,}" if n > 0 else ""

    amount = " - ".join(p for p in (clean(lo), clean(hi)) if p)
    if not amount:
        return ""
    return " ".join(x for x in (amount, str(currency or ""), str(period or "")) if x and x != "None")


def _job(source: str, ident: str, title: str, url: str, company: str, where: str, **kw) -> Job | None:
    if not title or not url:
        return None
    job = Job(source=source, source_id=str(ident or hashlib.sha1(url.encode()).hexdigest()[:16]), title=" ".join(title.split()),
              url=url.strip(), company=" ".join((company or "").split()), location=where, remote=True, **kw)
    return job


# -- providers: each returns jobs whose `location` is still the raw "who may apply" text -------------------------------------

def remotive(conn: Http, opts: dict) -> list[Job]:
    """Remotive's free API returns the 10 newest jobs per call and asks for at most about 4 visits a day."""
    out: list[Job] = []
    for call in opts.get("remotive_calls") or [{"category": "engineering"}, {"search": "embedded"}]:
        data = conn.get("https://remotive.com/api/remote-jobs", params=dict(call)).json()
        for it in data.get("jobs") or []:
            j = _job("Remotive", it.get("id"), it.get("title"), it.get("url"), it.get("company_name"),
                     it.get("candidate_required_location") or "", description=_plain(it.get("description")),
                     category=it.get("category") or "", posted=_iso(it.get("publication_date")), salary=it.get("salary") or "")
            if j:
                out.append(j)
    return out


def remoteok(conn: Http, opts: dict) -> list[Job]:
    data = conn.get("https://remoteok.com/api").json()
    out = []
    for it in data:
        if not isinstance(it, dict) or not it.get("position"):
            continue  # the first element is the legal notice
        where = it.get("location") or "Worldwide"  # Remote OK names a place only when the job is restricted
        j = _job("Remote OK", it.get("id"), it.get("position"), it.get("url"), it.get("company"), where,
                 description=_plain(it.get("description")), category=", ".join(it.get("tags") or [])[:80],
                 posted=_iso(it.get("date")), salary=_salary(it.get("salary_min"), it.get("salary_max"), "USD", "a year"))
        if j:
            out.append(j)
    return out


def weworkremotely(conn: Http, opts: dict) -> list[Job]:
    root = ET.fromstring(conn.get("https://weworkremotely.com/remote-jobs.rss").text)
    out = []
    for it in root.iter("item"):
        region = (it.findtext("region") or "").strip()
        full_title = (it.findtext("title") or "").strip()
        company, _, title = full_title.partition(": ")
        try:
            posted = parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            posted = ""
        j = _job("We Work Remotely", it.findtext("guid") or it.findtext("link"), title or full_title, it.findtext("link") or "",
                 company if title else "", region, description=_plain(it.findtext("description")),
                 category=(it.findtext("category") or "").strip(), posted=posted)
        if j:
            out.append(j)
    return out


def jobicy(conn: Http, opts: dict) -> list[Job]:
    calls = [{"geo": "anywhere", "count": 100}, {"geo": "apac", "count": 100}] + \
            [{"tag": q, "count": 50} for q in (opts.get("jobicy_tags") or ["embedded", "firmware", "electrical", "hardware", "pcb", "fpga"])]
    out: list[Job] = []
    for call in calls:
        data = conn.get("https://jobicy.com/api/v2/remote-jobs", params=call).json()
        for it in data.get("jobs") or []:
            geo = it.get("jobGeo") or ""
            j = _job("Jobicy", it.get("id"), it.get("jobTitle"), it.get("url"), it.get("companyName"), geo,
                     description=_plain(it.get("jobExcerpt")), category=_plain(it.get("jobIndustry")),
                     posted=_iso(it.get("pubDate")), salary=_salary(it.get("salaryMin"), it.get("salaryMax"),
                                                                    it.get("salaryCurrency"), it.get("salaryPeriod")))
            if j:
                out.append(j)
    return out


def himalayas(conn: Http, opts: dict) -> list[Job]:
    out: list[Job] = []
    for query in opts.get("queries") or DEFAULT_QUERIES:
        data = conn.get("https://himalayas.app/jobs/api/search", params={"q": query}).json()
        for it in data.get("jobs") or []:
            places = it.get("locationRestrictions") or []
            if isinstance(places, str):
                places = [p.strip(" '\"") for p in places.strip("[]").split(",") if p.strip(" '\"")]
            zones = it.get("timezoneRestrictions") or []
            if isinstance(zones, str):
                zones = [float(z) for z in re.findall(r"-?\d+(?:\.\d+)?", zones)]
            if zones and not any(5 <= float(z) <= 6 for z in zones):
                continue  # asks for time zones Sri Lanka isn't in
            where = ", ".join(map(str, places)) or "Worldwide"  # no restriction listed: open to everyone
            j = _job("Himalayas", it.get("guid") or it.get("applicationLink"), it.get("title"), it.get("applicationLink") or it.get("guid"),
                     it.get("companyName"), where, description=_plain(it.get("excerpt")),
                     category=", ".join(it.get("parentCategories") or []) if isinstance(it.get("parentCategories"), list) else "",
                     posted=_iso(it.get("pubDate")), salary=_salary(it.get("minSalary"), it.get("maxSalary"), it.get("currency"), it.get("salaryPeriod")))
            if j:
                out.append(j)
    return out


def workingnomads(conn: Http, opts: dict) -> list[Job]:
    out = []
    for it in conn.get("https://www.workingnomads.com/api/exposed_jobs/").json():
        j = _job("Working Nomads", it.get("url"), it.get("title"), it.get("url"), it.get("company_name"), it.get("location") or "",
                 description=_plain(it.get("description")), category=it.get("category_name") or "", posted=_iso(it.get("pub_date")))
        if j:
            out.append(j)
    return out


PROVIDERS = {"remotive": remotive, "remoteok": remoteok, "weworkremotely": weworkremotely, "jobicy": jobicy,
             "himalayas": himalayas, "workingnomads": workingnomads}


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    names = [n for n in (opts.get("providers") or list(PROVIDERS)) if n in PROVIDERS]
    extra = [str(x) for x in opts.get("open_to") or []]  # more words that mean "open to Sri Lanka"

    def one(conn: Http, name: str) -> list[Job]:
        kept = []
        for job in PROVIDERS[name](conn, opts):
            if open_to_sri_lanka(job.location) or (extra and any(w.lower() in job.location.lower() for w in extra)):
                job.location = f"Remote – {job.location}" if job.location != "Worldwide" else "Remote – open worldwide"
                kept.append(job)
        return kept

    found = gather(http, names, one, workers=int(opts.get("workers", 3)), label=lambda n: n)
    return list({j.fingerprint: j for j in found}.values())  # the same job is often on several boards
