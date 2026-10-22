"""How jobs are ordered and grouped in each message (notify.order_by / group_by)."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .config import Config
from .models import Job

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_AGO = re.compile(r"(\d+)\s*(minute|min|hour|hr|day|week|month|year)s?", re.IGNORECASE)
_DAYS = {"minute": 0, "min": 0, "hour": 0, "hr": 0, "day": 1, "week": 7, "month": 30, "year": 365}


def to_date(text: str, today: date) -> date | None:
    """ISO dates, or relative ones like "13 hours" / "2 days ago" (ikman)."""
    text = (text or "").strip()
    if m := _ISO.match(text):
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    if m := _AGO.search(text):
        return today - timedelta(days=int(m[1]) * _DAYS[m[2].lower()])
    if text.lower() in ("today", "just now", "bump_up"):
        return today
    return None


def sort_jobs(jobs: list[Job], order_by: str, today: date) -> list[Job]:
    def newest(j: Job):
        d = to_date(j.posted, today)
        return (d is None, -(d.toordinal() if d else 0))

    if order_by == "newest":
        key = newest
    elif order_by == "closing_soon":
        def key(j: Job):
            d = to_date(j.closing, today)
            open_ = d is not None and d >= today
            return (not open_, d.toordinal() if open_ else 0)
    elif order_by == "company":
        def key(j: Job):
            return (not j.company, j.company.lower(), j.title.lower())
    elif order_by == "title":
        def key(j: Job):
            return j.title.lower()
    else:  # best_match
        def key(j: Job):
            return (j.ai_score is None, -(j.ai_score or 0), *newest(j))
    return sorted(jobs, key=key)


def group_jobs(jobs: list[Job], cfg: Config, today: date) -> list[tuple[str | None, list[Job]]]:
    """[(heading, jobs)] in a sensible order; heading is None when not grouping."""
    group_by, order_by = cfg.group_by, cfg.order_by
    buckets: dict[str, list[Job]] = {}
    labels: dict[str, str] = {}

    if group_by == "none":
        return [(None, sort_jobs(jobs, order_by, today))] if jobs else []

    if group_by == "level":
        order = [lv.key for lv in cfg.levels] + [""]
        labels = {lv.key: lv.label for lv in cfg.levels} | {"": "Level not stated"}
        for j in jobs:
            buckets.setdefault(j.level or "", []).append(j)
    elif group_by == "qualification":
        # Highest qualification the advert accepts: "Degree or Diploma" sits under Degree.
        order = [q.key for q in cfg.qualifications] + [""]
        labels = {q.key: q.label for q in cfg.qualifications} | {"": "Qualification not stated"}
        for j in jobs:
            buckets.setdefault(j.qualifications[0] if j.qualifications and not j.qual_guess else "", []).append(j)
    elif group_by == "subfield":
        order = [sf.key for sf in cfg.subfields] + [""]
        labels = {sf.key: sf.label for sf in cfg.subfields} | {"": "Other"}
        for j in jobs:
            buckets.setdefault(j.subfields[0] if j.subfields else "", []).append(j)
    else:  # site
        order = []
        for j in jobs:
            if j.source not in buckets:
                order.append(j.source)
            buckets.setdefault(j.source, []).append(j)
        labels = {k: k for k in order}

    return [(labels.get(k, k), sort_jobs(buckets[k], order_by, today)) for k in order if k in buckets]
