"""Job statistics: one record per run in data/stats.json, plus a CSV log of
every new job (data/jobs_log.csv) that opens straight in Excel / Sheets."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path

from .config import Config
from .filters import classify_level, is_excluded, level_allowed, match_subfields
from .models import Job
from .report import SourceResult

MAX_RUNS = 400
MAX_LOG_ROWS = 5000
LOG_FIELDS = ["date", "status", "site", "title", "company", "location", "subfields", "level",
              "ai_score", "ai_reason", "closing", "url"]


def open_jobs_by_subfield(jobs: list[Job], cfg: Config) -> tuple[Counter, Counter]:
    """How many currently open jobs match each sub-field – switched on or not –
    and how many matching jobs your experience-level filter drops."""
    everything = replace(cfg, subfields=[replace(s, enabled=True) for s in cfg.subfields])
    by_subfield: Counter = Counter()
    level_filtered: Counter = Counter()
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
    return by_subfield, level_filtered


def run_record(day: date, sources: list[SourceResult], scanned: list[Job], matched: list[Job],
               new: list[Job], shown: list[Job], cfg: Config, ai_result=None) -> dict:
    by_subfield, level_filtered = open_jobs_by_subfield(scanned, cfg)
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
        "new_by_site": dict(Counter(j.source for j in new)),
        "open_by_subfield": dict(by_subfield),
        "open_level_filtered": dict(level_filtered),
        "top_companies": companies.most_common(10),
        "ai": None,
    }
    if ai_result is not None:
        record["ai"] = {"checked": ai_result.scored, "hidden": ai_result.hidden, "error": ai_result.error}
    return record


class StatsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.runs: list[dict] = []
        self.suggestions: list[dict] = []
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            self.runs = list(data.get("runs", []))
            self.suggestions = list(data.get("suggestions", []))

    def add(self, record: dict) -> None:
        self.runs.append(record)
        self.runs = self.runs[-MAX_RUNS:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"runs": self.runs, "suggestions": self.suggestions}
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jobs_log(path: str | Path, day: date, new: list[Job], hidden_uids: set[str], cfg: Config) -> None:
    path = Path(path)
    rows: list[dict] = []
    if path.exists():
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    for job in new:
        rows.append({
            "date": day.isoformat(),
            "status": "hidden by AI" if job.uid in hidden_uids else "sent",
            "site": job.source,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "subfields": "; ".join(sf.label for k in job.subfields if (sf := cfg.subfield(k))),
            "level": (cfg.level(job.level).label if job.level and cfg.level(job.level) else "not stated"),
            "ai_score": "" if job.ai_score is None else job.ai_score,
            "ai_reason": job.ai_reason,
            "closing": job.closing,
            "url": job.url,
        })
    rows = rows[-MAX_LOG_ROWS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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
