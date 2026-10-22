"""LinkedIn – the public (logged-out) job search fragment endpoint.

LinkedIn rate-limits anonymous traffic, so this source may sometimes return
HTTP 429. Other sources keep working when that happens.
"""

from __future__ import annotations

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "LinkedIn"
API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
JOB_URL = "https://www.linkedin.com/jobs/view/{id}/"
PAGE_SIZE = 10

log = logging.getLogger(__name__)
_URN_RE = re.compile(r"jobPosting:(\d+)")
_ID_IN_URL_RE = re.compile(r"-(\d{6,})(?:[/?]|$)")


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def parse(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select(".base-card, .job-search-card"):
        link = card if card.name == "a" else card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        href = link.get("href", "") if link else ""
        m = _URN_RE.search(card.get("data-entity-urn", "")) or _ID_IN_URL_RE.search(href)
        if not m:
            continue
        job_id = m.group(1)
        title = _text(card.select_one(".base-search-card__title")) or _text(link)
        if not title:
            continue
        time_el = card.select_one("time")
        jobs.append(Job(
            source=NAME,
            source_id=job_id,
            title=title,
            url=JOB_URL.format(id=job_id),
            company=_text(card.select_one(".base-search-card__subtitle")),
            location=_text(card.select_one(".job-search-card__location")),
            posted=(time_el.get("datetime") or _text(time_el)) if time_el else "",
        ))
    return jobs


def experience_filter(opts: dict, cfg: Config) -> str:
    """LinkedIn f_E codes for the enabled levels ("" = no filter)."""
    if len(cfg.enabled_levels) == len(cfg.levels):
        return ""
    codes_by_level = opts.get("experience_codes") or {}
    codes: set[int] = set()
    for lv in cfg.enabled_levels:
        codes.update(int(c) for c in codes_by_level.get(lv.key, []))
    return ",".join(str(c) for c in sorted(codes))


def _get(http: Http, params: dict, retry_wait: float) -> str:
    """GET one results page; when LinkedIn says "slow down", wait once and retry."""
    try:
        return http.get(API, params=params).text
    except requests.HTTPError as exc:
        if not _is_rate_limited(exc) or retry_wait <= 0:
            raise
        log.info("LinkedIn asked us to slow down; waiting %ds", retry_wait)
        time.sleep(retry_wait)
        return http.get(API, params=params).text


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    """With `remote: true` only LinkedIn's fully-remote jobs are asked for (its "On-site / Remote" filter),
    and only those whose listed place is open to Sri Lanka are kept and marked remote.

    `keywords` are searches for EEE job titles (one page each). `broad_keywords` are generic titles that name no field
    ("associate engineer", "technical officer"): LinkedIn lists many real EEE vacancies only under those, so they get
    `broad_pages` pages each, asked last (a rate-limit stops the loop) and left to the title-less triage to sort out."""
    from .remote import open_to_sri_lanka
    remote = bool(opts.get("remote"))
    days = int(opts.get("posted_within_days", 7))
    max_pages = int(opts.get("max_pages", 1))
    retry_wait = float(opts.get("retry_wait_seconds", 60))
    f_e = experience_filter(opts, cfg)
    jobs: dict[str, Job] = {}
    errors: list[Exception] = []
    searches = [(k, max_pages) for k in opts.get("keywords") or ["electrical engineer"]]
    searches += [(k, int(opts.get("broad_pages", 2))) for k in opts.get("broad_keywords") or []]
    for keyword, pages in searches:
        for page in range(pages):
            params = {
                "keywords": keyword,
                "location": opts.get("location") or "Sri Lanka",
                "f_TPR": f"r{days * 86400}",
                "start": page * PAGE_SIZE,
            }
            if f_e:
                params["f_E"] = f_e
            if remote:
                params["f_WT"] = "2"  # LinkedIn's work-type code for remote
            try:
                batch = parse(_get(http, params, retry_wait))
            except requests.RequestException as exc:
                errors.append(exc)
                log.warning("LinkedIn %r page %d failed: %s", keyword, page + 1, exc)
                break
            for job in batch:
                if remote:
                    if not open_to_sri_lanka(job.location):
                        continue
                    job.remote, job.location = True, f"Remote – {job.location}"
                jobs.setdefault(job.source_id, job)
            if len(batch) < PAGE_SIZE:
                break
        if errors and _is_rate_limited(errors[-1]):
            break  # further requests would just be rejected too
    if errors and not jobs:
        raise errors[0]
    return list(jobs.values())


def _is_rate_limited(exc: Exception) -> bool:
    resp = getattr(exc, "response", None)
    return resp is not None and resp.status_code in (429, 999)
