"""ikman.lk jobs – listing data is embedded in the page as window.initialData."""

from __future__ import annotations

import json

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "ikman.lk"
LIST_URL = "https://ikman.lk/en/ads/sri-lanka/{category}"
AD_URL = "https://ikman.lk/en/ad/{slug}"
_MARKER = "window.initialData ="


def extract_initial_data(html: str) -> dict:
    start = html.find(_MARKER)
    if start < 0:
        raise ValueError("ikman page layout changed: window.initialData not found")
    end = html.find("</script>", start)
    raw = html[start + len(_MARKER): end].strip().rstrip(";")
    return json.loads(raw)


def parse(html: str, category: str = "") -> tuple[list[Job], int]:
    """Return the jobs on the page and the total number of pages."""
    data = extract_initial_data(html)["serp"]["ads"]["data"]
    hint = "internship" if "intern" in category else None
    jobs = []
    for ad in data.get("ads", []):
        if not ad.get("isJobAd"):
            continue
        job_info = ad["isJobAd"] if isinstance(ad["isJobAd"], dict) else {}
        jobs.append(Job(
            source=NAME,
            source_id=ad.get("id") or ad["slug"],
            title=" ".join((ad.get("title") or "").split()),
            url=AD_URL.format(slug=ad["slug"]),
            company=(ad.get("details") or "").strip(),
            location=(ad.get("location") or "").strip(),
            salary=(ad.get("price") or "").strip(),
            category=(ad.get("category") or {}).get("name", ""),
            posted=ad.get("lastBumpUpDate") or "",
            closing=job_info.get("deadline") or "",
            level_hint=hint,
        ))
    pages = data.get("paginationData") or {}
    total, size = pages.get("total") or 0, pages.get("pageSize") or 25
    return jobs, max(1, -(-total // size))


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    max_pages = int(opts.get("max_pages", 4))
    jobs: list[Job] = []
    for category in opts.get("categories") or ["engineer-jobs"]:
        page = 1
        while page <= max_pages:
            html = http.get(LIST_URL.format(category=category), params={"page": page}).text
            batch, total_pages = parse(html, category)
            jobs.extend(batch)
            if page >= total_pages:
                break
            page += 1
    return jobs
