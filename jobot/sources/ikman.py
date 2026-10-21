"""ikman.lk jobs – listing data is embedded in the page as window.initialData."""

from __future__ import annotations

import json

from ..config import Config
from ..http import Http
from ..models import Job
from ..swarm import gather

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
    """Job categories (a page at a time, newest first) plus keyword searches across *all* job ads – a
    search finds ads that were filed under the wrong category."""
    max_pages = int(opts.get("max_pages", 4))
    searches = [("category", c) for c in (opts.get("categories") or ["engineer-jobs"])]
    searches += [("query", q) for q in (opts.get("queries") or [])]
    search_pages = int(opts.get("query_pages", 2))

    def one(conn: Http, search: tuple[str, str]) -> list[Job]:
        kind, value = search
        limit = search_pages if kind == "query" else max_pages
        jobs: list[Job] = []
        for page in range(1, limit + 1):
            params = {"page": page}
            if kind == "query":
                params["query"] = value
            html = conn.get(LIST_URL.format(category="jobs" if kind == "query" else value), params=params).text
            batch, total_pages = parse(html, value)
            jobs.extend(batch)
            if page >= total_pages:
                break
        return jobs

    found = gather(http, searches, one, workers=int(opts.get("workers", 3)),
                   label=lambda s: f"search {s[1]!r}" if s[0] == "query" else s[1])
    return list({j.source_id: j for j in found}.values())  # the same ad turns up in several searches
