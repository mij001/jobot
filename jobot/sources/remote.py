"""Fully remote jobs you can do from Sri Lanka, from the open remote-job feeds and APIs.

Remote job boards list thousands of jobs, but most are open only to people in the US or Europe. Every
job here is checked against where the employer says candidates may live (`open_to_sri_lanka`): only
"worldwide / anywhere / APAC / Asia / Sri Lanka" jobs, or ones with no restriction at all, are kept,
and those with a time-zone requirement that Sri Lanka can't meet are dropped. The kept jobs are marked
remote, and then go through your usual sub-field / level / qualification settings.

A job whose text names no place at all ("Remote") is "unsure": the AI reads the advert and settles it
(see triage.vet_remote); without an AI key it is kept with a note to check.

Providers (all free and public; the job links point to the source site, as most of them ask):
Remotive, Remote OK (front page and by tag), We Work Remotely, Jobicy, Himalayas, Working Nomads,
Jobspresso, NoDesk, Hacker News "Who is hiring", and employers' own job boards on Greenhouse, Lever
and Ashby (`boards:`). Choose with `providers:`.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

from ..config import Config
from ..http import Http
from ..models import Job
from ..swarm import gather

log = logging.getLogger(__name__)

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
# Places that, named without a "worldwide"-type word, mean the job is limited to them.
_PLACES = re.compile(
    r"\b(?:usa?|u\.s\.a?|united states|americas?|north america|canada|canadian|mexico|latam|latin america|south america|brazil|"
    r"argentina|colombia|chile|peru|europe|european|eu|emea|uk|u\.k\.|united kingdom|britain|england|scotland|ireland|"
    r"germany|france|spain|portugal|italy|netherlands|belgium|switzerland|austria|poland|romania|bulgaria|ukraine|czech(?:ia)?|"
    r"hungary|greece|turkey|sweden|norway|denmark|finland|baltics|nordics?|australia|new zealand|oceania|anz|india|pakistan|"
    r"bangladesh|nepal|singapore|malaysia|indonesia|philippines|vietnam|thailand|japan|korea|china|hong kong|taiwan|israel|uae|"
    r"dubai|saudi(?: arabia)?|middle east|mena|africa|nigeria|kenya|south africa|egypt|ghana|london|new york|san francisco|"
    r"toronto|berlin|sydney)\b", re.I)


def eligibility(where: str, empty: str = "unsure") -> str:
    """Plain-text check of a job's "who may apply" text for someone living in Sri Lanka:
    "open" (worldwide / anywhere / APAC / Asia / Sri Lanka, no incompatible time zone), "closed" (limited to
    other places or time zones) or "unsure" (names no place – the AI reads the advert). `empty` is what an
    empty text means for a given board."""
    text = " ".join(html.unescape(where or "").split())
    if not text:
        return empty
    if re.search(r"sri\s?lanka", text, re.I):
        return "open"
    if _BOUND.search(text):
        return "closed"
    if _WORLD.search(text):
        return "open" if not _ZONE.search(text) or _SL_ZONE.search(text) else "closed"
    if _ZONE.search(text):  # a time-zone requirement and no "anywhere": Sri Lanka's zone isn't what they mean
        return "closed"
    return "closed" if _PLACES.search(text) else "unsure"


def open_to_sri_lanka(where: str, empty_ok: bool = False) -> bool:
    """True only when the plain-text check says "open" (`eligibility`)."""
    return eligibility(where, "open" if empty_ok else "closed") == "open"


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
# (a provider that knows an empty text means "no restriction" fills in "Worldwide" itself)

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


def _remoteok_items(data) -> list[Job]:
    out = []
    for it in data if isinstance(data, list) else []:
        if not isinstance(it, dict) or not it.get("position"):
            continue  # the first element is the legal notice
        where = it.get("location") or "Worldwide"  # Remote OK names a place only when the job is restricted
        j = _job("Remote OK", it.get("id"), it.get("position"), it.get("url"), it.get("company"), where,
                 description=_plain(it.get("description")), category=", ".join(it.get("tags") or [])[:80],
                 posted=_iso(it.get("date")), salary=_salary(it.get("salary_min"), it.get("salary_max"), "USD", "a year"))
        if j:
            out.append(j)
    return out


def remoteok(conn: Http, opts: dict) -> list[Job]:
    """The front page plus the jobs under each hardware-ish tag (the front page alone is only the newest ~100)."""
    out = _remoteok_items(conn.get("https://remoteok.com/api").json())
    for tag in opts.get("remoteok_tags") or ["hardware", "electronics", "embedded", "iot", "robotics", "firmware", "electrical",
                                              "telecom", "network", "energy", "engineer"]:
        out.extend(_remoteok_items(conn.get("https://remoteok.com/api", params={"tag": tag}).json()))
    return list({j.source_id: j for j in out}.values())


def weworkremotely(conn: Http, opts: dict) -> list[Job]:
    root = _xml(conn.get("https://weworkremotely.com/remote-jobs.rss").text)
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
    tags = opts.get("jobicy_tags") or ["embedded", "firmware", "electrical", "hardware", "pcb", "fpga", "iot", "robotics",
                                       "electronics", "telecom", "network"]
    calls = [{"geo": "anywhere", "count": 100}, {"geo": "apac", "count": 100}] + [{"tag": q, "count": 50} for q in tags]
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
    return list({j.source_id: j for j in out}.values())


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


_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


def _xml(text: str) -> ET.Element:
    """Parse a feed, tolerating HTML entities (&rsquo; &nbsp; …) that plain XML doesn't define."""
    def fix(m: re.Match) -> str:
        return m.group(0) if m.group(1) in _XML_ENTITIES else html.unescape(m.group(0))

    return ET.fromstring(re.sub(r"&([A-Za-z][A-Za-z0-9]*);", fix, text))


def jobspresso(conn: Http, opts: dict) -> list[Job]:
    """Jobspresso's job feed: the "creator" line reads "Company<br>⚲ Where"."""
    root = _xml(conn.get("https://jobspresso.co/", params={"feed": "job_feed"}).text)
    out = []
    for it in root.iter("item"):
        creator = it.findtext("{http://purl.org/dc/elements/1.1/}creator") or ""
        company, _, where = re.sub(r"<br\s*/?>", "|", creator).partition("⚲")
        company = _plain(company.replace("|", " "))
        try:
            posted = parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            posted = ""
        j = _job("Jobspresso", it.findtext("link"), _plain(it.findtext("title")), it.findtext("link") or "", company, _plain(where),
                 description=_plain(it.findtext("description")), posted=posted)
        if j:
            out.append(j)
    return out


def nodesk(conn: Http, opts: dict) -> list[Job]:
    """NoDesk's feed names no place ("Title at Company"), so what it lists is judged by the AI."""
    root = _xml(conn.get("https://nodesk.co/remote-jobs/index.xml").text)
    out = []
    for it in root.iter("item"):
        title, _, company = _plain(it.findtext("title")).rpartition(" at ")
        j = _job("NoDesk", it.findtext("guid") or it.findtext("link"), title, it.findtext("link") or "", company, "",
                 description=_plain(it.findtext("description")))
        if j:
            out.append(j)
    return out


_HN_ROLE = re.compile(r"engineer|developer|designer|architect|scientist|manager|lead|technician|researcher|analyst|specialist|"
                      r"administrator|consultant|programmer|intern", re.I)


def _hn_advert(link: str, raw: str, posted: str) -> Job | None:
    """One "Who is hiring?" comment, which starts "Company | Role | Place | REMOTE …"; None if it isn't a remote advert."""
    paras = [p for p in re.split(r"<p>|<br\s*/?>", html.unescape(raw)) if _plain(p)]
    if not paras:
        return None
    header = _plain(paras[0], 300)
    parts = [p.strip() for p in header.split("|")]
    if len(parts) < 3 or not re.search(r"\bremote\b", header, re.I):
        return None  # not an advert, or not remote
    role = next((p for p in parts[1:] if _HN_ROLE.search(p)), parts[1])
    where = " | ".join(p for p in parts[1:] if p is not role)
    return _job("HN Who is hiring", link, role, link, parts[0], where, description=_plain(" ".join(paras[1:]), 700), posted=posted)


def _hn_comments(conn: Http, count: int) -> list[tuple[str, str, str]]:
    """(link, comment HTML, date) of the newest "Who is hiring?" thread's top-level comments, from the Algolia HN API."""
    base = "https://hn.algolia.com/api/v1/search_by_date"
    stories = conn.get(base, params={"tags": "story,author_whoishiring", "hitsPerPage": 6}).json().get("hits") or []
    story = next((h for h in stories if str(h.get("title", "")).lower().startswith("ask hn: who is hiring")), None)
    if story is None:
        return []
    hits = conn.get(base, params={"tags": f"comment,story_{story['objectID']}", "query": "remote",
                                  "hitsPerPage": min(1000, count * 4)}).json().get("hits") or []
    return [(f"https://news.ycombinator.com/item?id={h['objectID']}", h.get("comment_text") or "", str(h.get("created_at") or "")[:10])
            for h in hits if str(h.get("parent_id")) == str(story["objectID"])][:count]


def _hn_feed(conn: Http, count: int) -> list[tuple[str, str, str]]:
    """The same from hnrss.org (a fallback: its server sometimes refuses GitHub's)."""
    root = ET.fromstring(conn.get("https://hnrss.org/whoishiring/jobs", params={"count": count}).text)
    out = []
    for it in root.iter("item"):
        try:
            posted = parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            posted = ""
        out.append((it.findtext("link") or "", it.findtext("description") or "", posted))
    return out


def hn_hiring(conn: Http, opts: dict) -> list[Job]:
    """Hacker News "Who is hiring?": every top-level comment of the month's thread is an advert."""
    count = int(opts.get("hn_count", 100))
    try:
        comments = _hn_comments(conn, count)
    except Exception as exc:  # Algolia down or changed: try the RSS mirror before giving up
        log.info("HN Who is hiring: Algolia failed (%s), trying hnrss.org", type(exc).__name__)
        comments = _hn_feed(conn, count)
    return [j for link, raw, posted in comments if (j := _hn_advert(link, raw, posted))]


def boards(conn: Http, opts: dict) -> list[Job]:
    """Employers' own job boards on Greenhouse, Lever and Ashby (public JSON), remote jobs only."""
    out: list[Job] = []
    for b in opts.get("boards") or []:
        ats, slug, name = str(b.get("ats", "")).lower(), str(b.get("slug", "")), b.get("name") or str(b.get("slug", ""))
        if not slug:
            continue
        try:
            if ats == "greenhouse":
                for it in conn.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs").json().get("jobs") or []:
                    where = (it.get("location") or {}).get("name") or ""
                    if "remote" in where.lower():
                        j = _job(name, it.get("id"), it.get("title"), it.get("absolute_url"), name, where, posted=_iso(it.get("first_published")))
                        out.append(j) if j else None
            elif ats == "lever":
                for it in conn.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json", "limit": 200}).json() or []:
                    where = (it.get("categories") or {}).get("location") or ""
                    if str(it.get("workplaceType") or "").lower() == "remote" or "remote" in where.lower():
                        j = _job(name, it.get("id"), it.get("text"), it.get("hostedUrl"), name, where or it.get("country") or "",
                                 description=_plain(it.get("descriptionPlain")), posted=_iso(int(it.get("createdAt") or 0) // 1000))
                        out.append(j) if j else None
            elif ats == "ashby":
                for it in conn.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").json().get("jobs") or []:
                    where = it.get("location") or ""
                    if str(it.get("workplaceType") or "").lower() == "remote" or (it.get("isRemote") and "hybrid" not in str(it.get("workplaceType") or "").lower()):
                        j = _job(name, it.get("id"), it.get("title"), it.get("jobUrl"), name, where,
                                 description=_plain(it.get("descriptionPlain")), posted=_iso(it.get("publishedAt")))
                        out.append(j) if j else None
            else:
                conn.note(f"{name}: unknown job board type {ats!r}")
        except Exception as exc:  # one employer's board being down must not hide the others
            conn.note(f"{name}: {type(exc).__name__}: {str(exc)[:60]}")
    return out


PROVIDERS = {"remotive": remotive, "remoteok": remoteok, "weworkremotely": weworkremotely, "jobicy": jobicy,
             "himalayas": himalayas, "workingnomads": workingnomads, "jobspresso": jobspresso, "nodesk": nodesk,
             "hn_hiring": hn_hiring, "boards": boards}


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    names = [n for n in (opts.get("providers") or list(PROVIDERS)) if n in PROVIDERS]
    extra = [str(x).lower() for x in opts.get("open_to") or []]  # more words that mean "open to Sri Lanka"

    def one(conn: Http, name: str) -> list[Job]:
        kept = []
        for job in PROVIDERS[name](conn, opts):
            state = eligibility(job.location)
            if extra and any(w in job.location.lower() for w in extra):
                state = "open"
            if state == "closed":
                continue
            job.remote_rule = state
            if state == "open":
                job.location = "Remote – open worldwide" if job.location == "Worldwide" else f"Remote – {job.location}"
            else:
                job.location = f"Remote – {job.location}" if job.location else "Remote – place not stated"
            kept.append(job)
        return kept

    found = gather(http, names, one, workers=int(opts.get("workers", 4)), label=lambda n: n)
    return list({j.fingerprint: j for j in found}.values())  # the same job is often on several boards
