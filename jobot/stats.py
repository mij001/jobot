"""Job statistics: one record per run (kept in the encrypted history, see history.py)."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date

from .config import Config
from .filters import (classify_level, classify_qualifications, is_excluded, level_allowed, match_subfields,
                      qualification_allowed)
from .models import Job
from .report import SourceResult


def open_jobs_by_subfield(jobs: list[Job], cfg: Config) -> tuple[Counter, Counter, Counter]:
    """How many currently open jobs match each sub-field – switched on or not –
    and how many matching jobs your experience-level and qualification filters drop."""
    everything = replace(cfg, subfields=[replace(s, enabled=True) for s in cfg.subfields])
    by_subfield: Counter = Counter()
    level_filtered: Counter = Counter()
    qual_filtered: Counter = Counter()
    seen: set[str] = set()
    for job in jobs:
        if job.fingerprint in seen or is_excluded(job, cfg):
            continue
        seen.add(job.fingerprint)
        keys = match_subfields(job, everything)
        if not keys:
            continue
        by_subfield.update(keys)
        on = [k for k in keys if (sf := cfg.subfield(k)) and sf.enabled]
        level = classify_level(job, cfg)
        if on and not level_allowed(level, cfg):
            level_filtered[level or "unknown"] += 1
        elif on:
            quals = classify_qualifications(job, cfg)
            if not qualification_allowed(quals, cfg):
                qual_filtered[quals[0] if quals else "unknown"] += 1
    return by_subfield, level_filtered, qual_filtered


def run_record(day: date, sources: list[SourceResult], scanned: list[Job], matched: list[Job],
               new: list[Job], shown: list[Job], cfg: Config, ai_result=None, read_stats=None) -> dict:
    by_subfield, level_filtered, qual_filtered = open_jobs_by_subfield(scanned, cfg)
    companies = Counter(j.company.strip() for j in matched if j.company.strip())
    record = {
        "date": day.isoformat(),
        "sources": {
            r.name: ({"skipped": r.skipped} if r.skipped else {"error": r.error} if r.error else {"scanned": r.fetched})
            for r in sources
        },
        "scanned": len(scanned),
        "matched": len(matched),
        "new": len(new),
        "sent": len(shown),
        "new_by_subfield": dict(Counter(j.subfields[0] for j in new if j.subfields)),
        "new_by_level": dict(Counter(j.level or "unknown" for j in new)),
        "new_by_qualification": dict(Counter(j.qualifications[0] if j.qualifications else "unknown" for j in new)),
        "new_by_site": dict(Counter(j.source for j in new)),
        "open_by_subfield": dict(by_subfield),
        "open_level_filtered": dict(level_filtered),
        "open_qualification_filtered": dict(qual_filtered),
        "postings": read_stats.as_dict() if read_stats is not None else None,
        "top_companies": companies.most_common(10),
        "ai": None,
    }
    if ai_result is not None:
        record["ai"] = {"checked": ai_result.scored, "hidden": ai_result.hidden, "error": ai_result.error}
    return record


def week_summary(runs: list[dict], cfg: Config, today: date, days: int = 7) -> list[str]:
    """Plain-text lines summing up the last `days` days of runs."""
    recent = [r for r in runs if (today - date.fromisoformat(r["date"])).days < days]
    if not recent:
        return []
    new = sum(r.get("new", 0) for r in recent)
    sent = sum(r.get("sent", 0) for r in recent)
    subs: Counter = Counter()
    sites: Counter = Counter()
    for r in recent:
        subs.update(r.get("new_by_subfield", {}))
        sites.update(r.get("new_by_site", {}))
    label = lambda k: (cfg.subfield(k).label if cfg.subfield(k) else k)  # noqa: E731
    lines = [f"{new} new matching jobs in the last {days} days, {sent} sent to you."]
    if subs:
        lines.append("Most new jobs: " + ", ".join(f"{label(k)} ({n})" for k, n in subs.most_common(3)))
    if sites:
        lines.append("Best sites: " + ", ".join(f"{k} ({n})" for k, n in sites.most_common(3)))
    latest = recent[-1]
    if latest.get("top_companies"):
        lines.append("Hiring most: " + ", ".join(f"{c} ({n})" for c, n in latest["top_companies"][:3]))
    return lines
