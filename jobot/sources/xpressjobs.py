"""XpressJobs (xpress.jobs) – uses the JSON API behind its React front-end."""

from __future__ import annotations

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "XpressJobs"
API = "https://xpress.jobs/api/jobs/searchJobs"
FILTERS_API = "https://xpress.jobs/api/jobs/searchFilterOptions"
JOB_URL = "https://xpress.jobs/jobs/view/{id}"
PAGE_SIZE = 100


def to_job(item: dict, category: str = "", level_hint: str | None = None) -> Job:
    closing = (item.get("expiryDateOnWebsite") or "")[:10]
    return Job(
        source=NAME,
        source_id=str(item["jobId"]),
        title=" ".join((item.get("jobTitle") or "").split()),
        url=JOB_URL.format(id=item["jobId"]),
        company=(item.get("organizationName") or "").strip(),
        location=(item.get("locations") or "").strip(),
        description=(item.get("overview") or "").strip(),
        category=category,
        closing=closing,
        level_hint=level_hint,
    )


def _search(http: Http, sectors: str, career_level: int | None, max_pages: int) -> list[dict]:
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "page": page,
            "pageSize": PAGE_SIZE,
            "sectors": sectors,
            "sortBy": "SortedCreateDate DESC",
            "byCVLess": "false",
            "byWalkIn": "false",
        }
        if career_level is not None:
            params["careerLevels"] = career_level
        batch = http.get(API, params=params).json()
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        total = batch[0].get("recordCount") or 0
        if page * PAGE_SIZE >= total:
            break
    return items


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    sector_ids = [int(s) for s in opts.get("sectors") or [24]]
    max_pages = int(opts.get("max_pages", 10))
    level_map = {int(k): str(v) for k, v in (opts.get("career_levels") or {}).items()}

    names: dict[int, str] = {}
    try:
        for s in http.get(FILTERS_API).json().get("sectors", []):
            names[s["sectorId"]] = s["sectorName"]
    except Exception:  # sector names are only a matching hint
        pass

    # The listing doesn't say which career level a job has, so ask once per
    # level (all sectors together) to learn it.
    all_sectors = ",".join(str(s) for s in sector_ids)
    hints: dict[int, str] = {}
    for level_id, level_key in level_map.items():
        for item in _search(http, all_sectors, level_id, max_pages):
            hints.setdefault(item["jobId"], level_key)

    jobs = []
    for sector in sector_ids:
        for item in _search(http, str(sector), None, max_pages):
            jobs.append(to_job(item, category=names.get(sector, ""), level_hint=hints.get(item["jobId"])))
    return jobs
