"""Opens each promising job's own page and reads the full advert.

List pages often show nothing but a title (topjobs, LankaJobs, TechJobs …),
and many Sri Lankan adverts are just a poster image or a PDF. For each
promising new job this module opens the posting, takes the advert's text,
reads posters with OCR (Tesseract) and PDF adverts with pdftotext, and
optionally asks the AI to read posters OCR can't. Results are cached in
data/postings_cache.json so each advert is only read once.

What it adds to a job: the advert text (appended to `description`, so the
sub-field, experience and qualification filters see it), how it was read
(`read_via`), the apply-to e-mail (`contact`), the closing date when the site
didn't give one, and a one-line `requirements` summary.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import ocr
from .config import Config
from .filters import is_excluded, keyword_pattern, matching_keywords, qualification_text, years_required
from .http import Http
from .models import Job
from .sources.ikman import extract_initial_data
from .swarm import parallel_map

log = logging.getLogger(__name__)

THIN = 300  # list text shorter than this: a "maybe" worth opening
FULL = 600  # list text this long already holds the advert; don't open it
TEXT_ENOUGH = 300  # page text this long: no need to OCR the images too
MAX_IMAGES = 3
MAX_BYTES = 8_000_000
CACHE_TEXT = 2000  # characters of advert text kept in the cache
CACHE_DAYS = 3  # forget adverts no longer listed for this many days
BLOCKED = (403, 429, 999)  # stop opening that site's pages for the rest of the run

Vision = Callable[[bytes, str], str]


@dataclass
class Posting:
    text: str = ""
    via: list[str] = field(default_factory=list)  # "page", "poster", "pdf", "ai"
    images: list[str] = field(default_factory=list)
    pdfs: list[str] = field(default_factory=list)


@dataclass
class ReadStats:
    opened: int = 0
    cached: int = 0
    posters: int = 0
    pdfs: int = 0
    ai: int = 0
    failed: int = 0
    left: int = 0  # over the per-run limit; read next time

    @property
    def summary(self) -> str:
        if not (self.opened or self.cached or self.failed):
            return ""
        how = [f"{n} {w}" for n, w in ((self.posters, "posters via OCR"), (self.pdfs, "PDFs"),
                                       (self.ai, "by AI")) if n]
        text = f"Adverts read: {self.opened} opened" + (f" ({', '.join(how)})" if how else "")
        if self.cached:
            text += f", {self.cached} from earlier runs"
        if self.failed:
            text += f", {self.failed} failed"
        if self.left:
            text += f", {self.left} left for next run"
        return text

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("opened", "cached", "posters", "pdfs", "ai", "failed", "left")}


# -- text helpers --------------------------------------------------------------

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)


def normalise(text: str) -> str:
    """NFKC (turns 𝐁𝐨𝐥𝐝 "fancy" letters into plain ones), tidy whitespace, drop OCR noise lines."""
    text = unicodedata.normalize("NFKC", text or "").translate(_ZERO_WIDTH)
    lines = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if sum(c.isalnum() for c in line) >= 2:
            lines.append(line)
    return "\n".join(lines)


def useful(text: str) -> bool:
    """Did OCR get real words out of the image (not just a logo or noise)?"""
    return len(re.findall(r"[A-Za-z]{3,}", text)) >= 15


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_SITE_DOMAINS = ("topjobs.lk", "ikman.lk", "lankajobs.lk", "itpro.lk", "techjobs.lk", "gazette.lk",
                 "findmyjob.lk", "xpress.jobs", "rooster.jobs", "observerjobs.lk", "example.com")


def find_email(text: str) -> str:
    for email in _EMAIL_RE.findall(text):
        domain = email.rsplit("@", 1)[1].lower()
        if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            continue
        if any(domain == d or domain.endswith("." + d) for d in _SITE_DOMAINS):
            continue
        return email.rstrip(".")
    return ""


_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_CLOSING_RE = re.compile(
    r"(?:closing\s+date|deadline|last\s+date|on\s+or\s+before|apply\s+before|"
    r"(?:should|must)\s+reach[^.\n]{0,60}?(?:before|by))"
    r"[^0-9A-Za-z]{0,6}(?:is\s+|of\s+applications?\s*[:\-–]?\s*)?(.{0,40})",
    re.IGNORECASE,
)


def parse_date(text: str) -> str:
    """'30.10.2026', '2026-10-30', '30th October 2026', 'October 30, 2026' -> ISO."""
    s = text.strip()
    if m := re.match(r"(20\d\d)[./-](\d{1,2})[./-](\d{1,2})", s):
        y, mo, d = m.groups()
    elif m := re.match(r"(\d{1,2})[./-](\d{1,2})[./-](20\d\d)\b", s):
        d, mo, y = m.groups()  # Sri Lankan adverts write day/month/year
    elif m := re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3})[a-z]*\.?,?\s+(20\d\d)", s, re.I):
        d, mon, y = m.groups()
        mo = _MONTHS.get(mon.lower())
    elif m := re.match(r"([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)", s, re.I):
        mon, d, y = m.groups()
        mo = _MONTHS.get(mon.lower())
    else:
        return ""
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except (TypeError, ValueError):
        return ""


def find_closing(text: str) -> str:
    for m in _CLOSING_RE.finditer(text):
        if iso := parse_date(m.group(1)):
            return iso
    return ""


# Bullets and OCR'd bullets ("¢ BSc", "e Degree", "‘+ Diploma") at the start of a line.
_BULLET = re.compile(r"^(?:[^\w(]+|[eo©]\s+(?=[A-Z]))+")
_SPLIT_RE = re.compile(r"\n|[•●▪◦✓✔➢➤►■□◆❖]|(?<=[a-z0-9)])\.\s+(?=[A-Z])")


def requirement_summary(text: str, cfg: Config) -> str:
    """Up to two snippets of the advert saying what qualification / experience it wants:
    the qualifications you've ticked first, then experience, then the rest."""
    quals = [q for q in cfg.qualifications if q.keywords]
    years_rank = max((i for i, q in enumerate(quals) if q.enabled), default=0) + 0.5
    candidates: list[tuple[float, int, str]] = []
    for pos, part in enumerate(_SPLIT_RE.split(text)):
        line = _BULLET.sub("", " ".join(part.split())).rstrip(" -–*:>|~.,;")
        if len(line) < 15:
            continue
        cleaned = qualification_text(line)
        ranks = [i for i, q in enumerate(quals) if matching_keywords(q.keywords, cleaned)]
        if ranks:
            rank: float = min(ranks)
            keywords = quals[min(ranks)].keywords
        elif years_required(line) is not None:
            rank, keywords = years_rank, []
        else:
            continue
        candidates.append((rank, pos, _snippet(line, keywords)))
    best = sorted(sorted(candidates)[:2], key=lambda c: c[1])
    return " · ".join(c[2] for c in best)


def _snippet(line: str, keywords: list[str], width: int = 140) -> str:
    """A long paragraph (or a poster OCR'd into one line) cut down to the part that matters."""
    if len(line) <= width:
        return line
    starts = [m.start() for k in keywords if (m := keyword_pattern(k).search(line))]
    if not starts and (m := re.search(r"\d+\s*\+?\s*(?:years?|yrs?)", line, re.I)):
        starts = [max(0, m.start() - 40)]
    start = max(0, min(starts, default=0) - 25)  # keep a few words of lead-in
    if start:
        start = line.rfind(" ", 0, start) + 1
    cut = line[start:start + width]
    if start + width < len(line):
        cut = cut[:cut.rfind(" ")].rstrip(" ,;:") + "…"
    return ("…" if start else "") + cut


# -- site readers: html -> (text, image urls, pdf urls) ---------------------------

_NOT_POSTER = re.compile(r"icon|avatar|company_logo|emoji|sprite|badge|whatsapp|facebook|"
                         r"twitter|linkedin|_small\.|\.gif|\.svg|data:", re.IGNORECASE)


def _images(box, base: str) -> list[str]:
    out = []
    for img in box.select("img"):
        src = (img.get("data-src") or img.get("data-lazy-src") or img.get("src") or "").strip()
        if not src or _NOT_POSTER.search(src):
            continue
        try:
            if int(img.get("width", 999)) < 200 and int(img.get("height", 999)) < 200:
                continue
        except ValueError:
            pass
        url = urljoin(base, src)
        if url not in out:
            out.append(url)
    return out


def _pdfs(box, base: str) -> list[str]:
    links = [urljoin(base, a["href"]) for a in box.select("a[href]") if a["href"].lower().split("?")[0].endswith(".pdf")]
    # Gazette.lk & co. link Sinhala (-S), Tamil (-T) and English (-E) versions: English first.
    english = [u for u in links if re.search(r"[-_]e(?:ng(?:lish)?)?\.pdf$", u.split("?")[0], re.I)]
    others = [u for u in links if u not in english and not re.search(r"[-_](?:s|t|si|ta|sin|tam)\.pdf$", u.split("?")[0], re.I)]
    return list(dict.fromkeys(english + others))


def _text(box) -> str:
    for junk in box.select("script, style, noscript, form, nav, footer, button, iframe, svg"):
        junk.decompose()
    return box.get_text("\n", strip=True)


def _read_box(box, base: str) -> tuple[str, list[str], list[str]]:
    if box is None:
        return "", [], []
    images, pdfs = _images(box, base), _pdfs(box, base)
    return _text(box), images, pdfs


def read_topjobs(html: str, url: str):
    return _read_box(BeautifulSoup(html, "html.parser").select_one("#remark"), url)


def read_ikman(html: str, url: str):
    ad = extract_initial_data(html)["adDetail"]["data"]["ad"]
    lines = [ad.get("description") or ""]
    for prop in ad.get("properties") or []:
        if prop.get("label") and prop.get("value"):
            lines.append(f"{prop['label']}: {prop['value']}")
    images = [m["src"] + "/1200/1200/fitted.jpg" for m in (ad.get("images") or {}).get("meta", []) if m.get("src")]
    return "\n".join(lines), images, []


def read_lankajobs(html: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    sections = soup.select(".single-page-section")
    text = "\n".join(_text(s) for s in sections)
    images = [u for s in soup.select(".single-page-section") for u in _images(s, url)]
    return text, images, [u for s in sections for u in _pdfs(s, url)]


def read_itpro(html: str, url: str):
    return _read_box(BeautifulSoup(html, "html.parser").select_one("#job-description"), url)


def read_techjobs(html: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    images = [urljoin(url, i["src"]) for i in soup.select("img[src*='job_posters']")]
    text = "\n".join(_text(s) for s in soup.select(".single-post.job-details, .single-post.job-experience"))
    return text, list(dict.fromkeys(images)), []


def read_gazette(html: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one(".entry-content")
    if box is None:
        return "", [], []
    images = [u for u in _images(box, url) if "/wp-content/uploads/" in u]
    pdfs = _pdfs(box, url)
    return _text(box), images, pdfs


def read_linkedin(html: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one(".show-more-less-html__markup, .description__text")
    criteria = [" ".join(li.get_text(" ", strip=True).split()) for li in soup.select(".description__job-criteria-item")]
    text = _text(box) if box is not None else ""
    return "\n".join([text, *criteria]), [], []


def read_generic(html: str, url: str):
    soup = BeautifulSoup(html, "html.parser")
    for sel in ("[itemprop=description]", "#job-description", ".job-description", ".job-details",
                ".entry-content", "article", "main", "body"):
        box = soup.select_one(sel)
        if box is not None and (box.get_text(strip=True) or box.select("img")):
            return _read_box(box, url)
    return "", [], []


READERS = {
    "topjobs.lk": read_topjobs,
    "ikman.lk": read_ikman,
    "lankajobs.lk": read_lankajobs,
    "itpro.lk": read_itpro,
    "techjobs.lk": read_techjobs,
    "gazette.lk": read_gazette,
    "linkedin.com": read_linkedin,
}


def reader_for(url: str):
    host = urlparse(url).netloc.lower()
    for domain, reader in READERS.items():
        if host == domain or host.endswith("." + domain):
            return reader
    return read_generic


def page_url(url: str) -> str:
    """The URL to fetch: LinkedIn's public posting endpoint instead of the login-walled page."""
    if m := re.search(r"linkedin\.com/jobs/view/(?:[^/]*-)?(\d+)", url):
        return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}"
    return url


# -- reading one posting --------------------------------------------------------------

def _decode(resp) -> str:
    try:
        return resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return resp.text


def _download(http: Http, url: str) -> tuple[bytes, str]:
    resp = http.get(url)
    if len(resp.content) > MAX_BYTES:
        return b"", ""
    mime = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    return resp.content, mime


def read_posting(http: Http, url: str, read_posters: bool = True, vision: Vision | None = None) -> Posting:
    resp = http.get(page_url(url))
    mime = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    posting = Posting()
    if mime == "application/pdf" or url.lower().split("?")[0].endswith(".pdf"):
        posting.text = normalise(ocr.pdf_text(resp.content))
        posting.via.append("pdf")
        return posting
    if mime.startswith("image/"):
        text, posting.images, posting.pdfs = "", [url], []
    else:
        text, posting.images, posting.pdfs = reader_for(url)(_decode(resp), resp.url or url)
    parts = [normalise(text)]
    if parts[0]:
        posting.via.append("page")

    for pdf in posting.pdfs[:1]:
        try:
            data, _ = _download(http, pdf)
        except requests.RequestException as exc:
            log.debug("PDF %s: %s", pdf, exc)
            continue
        if found := normalise(ocr.pdf_text(data)):
            parts.append(found)
            posting.via.append("pdf")

    if read_posters and len("\n".join(parts)) < TEXT_ENOUGH:
        for image in posting.images[:MAX_IMAGES]:
            try:
                data, img_mime = _download(http, image)
            except requests.RequestException as exc:
                log.debug("image %s: %s", image, exc)
                continue
            found = normalise(ocr.image_text(data))
            if useful(found):
                parts.append(found)
                posting.via.append("poster")
            elif vision is not None and data and (found := normalise(vision(data, img_mime or "image/jpeg"))):
                parts.append(found)
                posting.via.append("ai")
    posting.text = "\n".join(p for p in parts if p)
    posting.via = list(dict.fromkeys(posting.via))
    return posting


# -- which jobs to open ----------------------------------------------------------------

def _maybe(job: Job, cfg: Config) -> bool:
    """A job the list page couldn't settle: technical-sounding title, little or no text."""
    if len(job.description) >= THIN or is_excluded(job, cfg):
        return False
    if not matching_keywords(cfg.description_match_titles, job.title):
        return False
    if matching_keywords(cfg.postings.skip_titles, job.title):
        return False
    title_levels = [lv for lv in cfg.levels if matching_keywords(lv.keywords, job.title)]
    return not title_levels or title_levels[-1].enabled


def pick(all_jobs: list[Job], matched: list[Job], is_new: Callable[[Job], bool], cfg: Config,
         skip: set[str] | frozenset[str] = frozenset()) -> list[Job]:
    """New matched jobs first (to check their qualification and details), then
    new 'maybes' – jobs with a technical title whose list entry was too thin
    to tell whether they're EEE at all. `skip` = uids the AI already turned down."""
    matched_uids = {j.uid for j in matched}
    matched_fps = {j.fingerprint for j in matched}
    first, maybes, seen = [], [], set()
    for job in all_jobs:
        if job.uid in seen or not is_new(job):
            continue
        seen.add(job.uid)
        if job.remote:
            continue  # the remote boards' APIs already gave the text, and their pages often refuse robots
        if job.uid in matched_uids:
            if len(job.description) < FULL:
                first.append(job)
        elif job.fingerprint not in matched_fps and job.uid not in skip and _maybe(job, cfg):
            maybes.append(job)
    return first + maybes


# -- cache -------------------------------------------------------------------------

class PostingCache:
    """data/postings_cache.json – {job uid: what was read}, one line per advert."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.entries: dict[str, dict] = {}
        if self.path.exists():
            try:
                self.entries = dict(json.loads(self.path.read_text(encoding="utf-8") or "{}"))
            except ValueError:
                log.warning("%s is damaged – starting a fresh postings cache", self.path)

    def get(self, uid: str) -> dict | None:
        return self.entries.get(uid)

    def put(self, uid: str, posting: Posting, today: date) -> dict:
        entry = {
            "read": today.isoformat(),
            "seen": today.isoformat(),
            "via": "+".join(posting.via),
            "text": posting.text[:CACHE_TEXT],
            "email": find_email(posting.text),
            "closing": find_closing(posting.text),
        }
        self.entries[uid] = entry
        return entry

    def touch(self, uid: str, today: date) -> None:
        if uid in self.entries:
            self.entries[uid]["seen"] = today.isoformat()

    def prune(self, today: date, keep_days: int = CACHE_DAYS) -> None:
        cutoff = (today - timedelta(days=keep_days)).isoformat()
        self.entries = {k: v for k, v in self.entries.items() if v.get("seen", "") >= cutoff}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = [f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)}"
                for k, v in sorted(self.entries.items())]
        self.path.write_text("{\n" + ",\n".join(rows) + "\n}\n", encoding="utf-8")


def apply(job: Job, entry: dict, cfg: Config) -> None:
    """Copy what was read from the advert onto the job."""
    text = entry.get("text") or ""
    if text and text[:200] not in job.description:
        job.description = f"{job.description}\n\n{text}".strip()
    job.read_via = entry.get("via") or ""
    job.contact = job.contact or entry.get("email") or ""
    job.closing = job.closing or entry.get("closing") or ""
    if text:
        job.requirements = requirement_summary(text, cfg)


def enrich(jobs: list[Job], cache: PostingCache, cfg: Config, today: date,
           http: Http | None = None, vision: Vision | None = None, max_seconds: float | None = None) -> ReadStats:
    """Read (or recall) the advert behind each job. At most postings.max_per_run new pages are opened per
    run, a few at a time (postings.workers, each on its own connection) and no longer than
    postings.max_seconds in all – what is left waits for the next run."""
    stats = ReadStats()
    http = http or Http(delay=1.0)
    blocked: set[str] = set()
    lock = threading.Lock()
    deadline = time.monotonic() + (cfg.postings.max_seconds if max_seconds is None else min(max_seconds, cfg.postings.max_seconds))
    fresh: list[Job] = []
    for job in jobs:
        if cache.get(job.uid) is None:
            if len(fresh) < cfg.postings.max_per_run:
                fresh.append(job)
            else:
                stats.left += 1
    if vision is not None:
        raw_vision = vision

        def vision(data, kind, _raw=raw_vision):  # the AI reader keeps a count, so one image at a time
            with lock:
                return _raw(data, kind)

    clone = getattr(http, "clone", None)

    def read(job: Job):
        host = urlparse(job.url).netloc
        with lock:
            if host in blocked or time.monotonic() > deadline:
                return None  # not tried: it waits for the next run
        try:
            return read_posting(clone() if clone else http, job.url, cfg.postings.read_posters, vision)
        except requests.HTTPError as exc:
            code = getattr(exc.response, "status_code", 0)
            if code in BLOCKED:
                with lock:
                    if host not in blocked:
                        log.info("%s refused to show an advert (HTTP %s); not opening more of its pages today", host, code)
                    blocked.add(host)
            return exc
        except Exception as exc:  # one odd page must not stop the run
            log.debug("reading %s failed: %s", job.url, exc, exc_info=True)
            return exc

    read_in_parallel = cfg.postings.workers > 1 and clone is not None
    results = dict(zip((j.uid for j in fresh),
                       [r for r, _ in parallel_map(read, fresh, workers=cfg.postings.workers if read_in_parallel else 1)],
                       strict=True))
    if time.monotonic() > deadline and any(r is None for r in results.values()):
        log.info("Reading adverts stopped after %d s; the rest waits for the next run", cfg.postings.max_seconds)

    for job in jobs:
        entry = cache.get(job.uid)
        if entry is None:
            if job.uid not in results:
                continue  # over the per-run limit (already counted as left)
            posting = results[job.uid]
            if posting is None:
                stats.left += 1
                continue
            if isinstance(posting, Exception):
                stats.failed += 1
                continue
            entry = cache.put(job.uid, posting, today)
            stats.opened += 1
            stats.posters += "poster" in posting.via
            stats.pdfs += "pdf" in posting.via
            stats.ai += "ai" in posting.via
            log.debug("read %-50.50s via %s (%d chars)", job.title, entry["via"] or "-", len(posting.text))
        else:
            stats.cached += 1
        cache.touch(job.uid, today)
        apply(job, entry, cfg)
    return stats
