"""Job statistics: one record per run (kept in the encrypted history, see history.py)."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date

from .config import Config
from .filters import (classify_level, is_excluded, level_allowed, match_subfields, qualification_allowed,
                      qualifications_with_source)
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
            quals, guessed = qualifications_with_source(job, cfg)
            if not qualification_allowed(quals, cfg, guessed):
                qual_filtered[quals[0] if quals else "unknown"] += 1
    return by_subfield, level_filtered, qual_filtered


def near_misses(jobs: list[Job], cfg: Config, limit: int = 8) -> list[tuple[Job, str]]:
    """Open jobs your own settings dropped although they match an EEE sub-field, each with the reason –
    so a switched-off sub-field or level can never hide postings without you knowing."""
    everything = replace(cfg, subfields=[replace(s, enabled=True) for s in cfg.subfields])
    out: list[tuple[Job, str]] = []
    seen: set[str] = set()
    for job in jobs:
        if job.fingerprint in seen or is_excluded(job, cfg):
            continue
        seen.add(job.fingerprint)
        keys = match_subfields(job, everything)
        if not keys:
            continue
        on = [k for k in keys if (sf := cfg.subfield(k)) and sf.enabled]
        if not on:
            labels = ", ".join(sf.label for k in keys[:2] if (sf := cfg.subfield(k)))
            out.append((job, f"{labels} is switched off"))
            continue
        level = classify_level(job, cfg)
        if not level_allowed(level, cfg):
            lv = cfg.level(level)
            out.append((job, f"{lv.label if lv else 'that'} level is switched off"))
            continue
        quals, guessed = qualifications_with_source(job, cfg)
        if not qualification_allowed(quals, cfg, guessed):
            q = cfg.qualification(quals[0]) if quals else None
            out.append((job, f"asks for {q.short.lower() if q else 'other'} level qualifications, which you've switched off"))
    out.sort(key=lambda pair: pair[0].posted if len(pair[0].posted) == 10 and pair[0].posted[:2] == "20" else "", reverse=True)
    return out[:limit]


def run_record(day: date, sources: list[SourceResult], scanned: list[Job], matched: list[Job],
               new: list[Job], shown: list[Job], cfg: Config, ai_result=None, read_stats=None) -> dict:
    by_subfield, level_filtered, qual_filtered = open_jobs_by_subfield(scanned, cfg)
    companies = Counter(j.company.strip() for j in matched if j.company.strip())
    record = {
        "date": day.isoformat(),
        "sources": {
            r.name: ({"skipped": r.skipped} if r.skipped else {"error": r.error} if r.error else
                     {"scanned": r.fetched, **({"partial": r.warnings[:3]} if r.warnings else {})})
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


def _source_state(st: dict | None) -> str:
    return "none" if not st else "ok" if "scanned" in st else "error" if "error" in st else "skipped"


def status_signature(record: dict) -> dict[str, str]:
    """Which sites worked / failed / were skipped (not how many jobs they had)."""
    return {name: _source_state(st) for name, st in (record.get("sources") or {}).items()}


def _merge_sources(old: dict, new: dict) -> dict:
    """A site counts as read for the day if any run read it; then failed; then skipped."""
    rank = {"ok": 3, "error": 2, "skipped": 1, "none": 0}
    out = {}
    for name in {**old, **new}:
        a, b = old.get(name), new.get(name)
        if rank[_source_state(b)] >= rank[_source_state(a)]:
            out[name] = dict(b) if b else dict(a)
        else:
            out[name] = dict(a)
        if "scanned" in out[name]:  # keep the bigger count: a run can be cut short
            out[name]["scanned"] = max(x.get("scanned", 0) for x in (a, b) if x and "scanned" in x)
        if any(x and x.get("partial") for x in (a, b)) and "scanned" in out[name] and not (b and "scanned" in b and not b.get("partial")):
            out[name]["partial"] = (b or a).get("partial")
        elif "partial" in out[name] and b and "scanned" in b and not b.get("partial"):
            del out[name]["partial"]  # the latest run read all of it
    return out


def merge_runs(old: dict, new: dict) -> dict:
    """Fold another run of the same day into the day's record (the dashboard and the suggestions
    think in days): what was found adds up, "what is open right now" comes from the fuller run, and
    each site shows its best result of the day."""
    snapshot = new if new.get("scanned", 0) >= old.get("scanned", 0) else old
    out = dict(snapshot)
    out["date"] = new["date"]
    out["runs"] = int(old.get("runs", 1)) + 1
    for key in ("new", "sent"):
        out[key] = old.get(key, 0) + new.get(key, 0)
    for key in ("new_by_subfield", "new_by_level", "new_by_qualification", "new_by_site"):
        total = Counter(old.get(key) or {})
        total.update(new.get(key) or {})
        out[key] = dict(total)
    out["scanned"] = max(old.get("scanned", 0), new.get("scanned", 0))
    out["matched"] = max(old.get("matched", 0), new.get("matched", 0))
    out["sources"] = _merge_sources(old.get("sources") or {}, new.get("sources") or {})
    posts = [p for p in (old.get("postings"), new.get("postings")) if p]
    if posts:
        out["postings"] = {k: sum(p.get(k, 0) for p in posts) for k in posts[-1]}
        out["postings"]["left"] = posts[-1].get("left", 0)
    ais = [a for a in (old.get("ai"), new.get("ai")) if a]
    if ais:
        out["ai"] = {"checked": sum(a.get("checked", 0) for a in ais), "hidden": sum(a.get("hidden", 0) for a in ais),
                     "error": ais[-1].get("error")}
    return out


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
