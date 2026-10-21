"""Everything the dashboard shows, kept encrypted in data/history/ (see vault.py):

* every job that was sent (or held back by the AI), with its importance tier,
  one file per month so a daily run only rewrites the current month;
* one statistics record per run, plus the current suggestions.

Without a DASHBOARD_PASSWORD nothing is kept (the repository is public).
Your own marks (shortlisted / applied / dismissed) are added from the settings
page in the same folder (marks.enc.json) – the bot never touches that file.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from . import stats
from .config import Config
from .filters import matching_keywords
from .models import Job
from .skills import extract_skills
from .vault import Vault, WrongPassword

log = logging.getLogger(__name__)

STATS = "stats"
MAX_RUNS = 200
MAX_MONTHS = 24
TIERS = ("top", "good", "maybe", "low")  # shown as Top picks / Good fits / Worth a look / Low priority


_UP = {"maybe": "good", "good": "top"}


def tier(score: int | None, hidden: bool, title: str, subfields: list[str], level: str | None,
         qualifications: list[str], cfg: Config, watched: bool = False) -> str:
    """How much a job deserves your attention: top | good | maybe | low.
    A job from a watched employer moves up one tier (unless the AI held it back)."""
    if hidden:
        return "low"
    if score is not None:
        top = cfg.top_picks_score or 8
        found = "top" if score >= top else "good" if score >= 6 else "maybe"
    else:
        # No AI review: judge by how clearly the advert fits what you asked for.
        points = 0
        if any(matching_keywords(sf.keywords, title) for k in subfields if (sf := cfg.subfield(k))):
            points += 1  # the title itself says EEE
        points += bool(qualifications)  # the advert states a qualification you accept
        points += bool(level)  # and a level you accept
        found = "good" if points >= 2 else "maybe"
    return _UP.get(found, found) if watched else found


def importance(job: Job, cfg: Config, hidden: bool = False) -> str:
    return tier(job.ai_score, hidden, job.title, job.subfields, job.level, job.qualifications, cfg, job.watched)


def job_entry(job: Job, day: date, hidden: bool, cfg: Config) -> dict:
    entry: dict[str, Any] = {
        "id": job.uid, "date": day.isoformat(), "status": "hidden" if hidden else "sent",
        "source": job.source, "title": job.title, "company": job.company, "location": job.location,
        "url": job.url, "also_on": [list(p) for p in job.also_on], "subfields": list(job.subfields),
        "level": job.level, "qualifications": list(job.qualifications), "min_years": job.min_years,
        "ai_score": job.ai_score, "ai_reason": job.ai_reason, "importance": importance(job, cfg, hidden),
        "posted": job.posted, "closing": job.closing, "requirements": job.requirements,
        "contact": job.contact, "salary": job.salary, "read_via": job.read_via, "watched": job.watched or None,
        # the skills / tools / certificates the advert mentions (drives the dashboard's skill demand)
        "skills": extract_skills(f"{job.title}\n{job.description}", cfg.coach.extra_skills),
    }
    return {k: v for k, v in entry.items() if v not in ("", None, [])}


def _month(day: str) -> str:
    return f"jobs-{day[:7]}"


class History:
    def __init__(self, vault: Vault | None = None, note: str = ""):
        self.vault = vault
        self.note = note  # why nothing is being kept, if so
        self.runs: list[dict] = []
        self.suggestions: list[dict] = []
        self.has_stats = False
        self._shards: dict[str, dict[str, dict]] = {}  # loaded / changed this run
        self._dirty: set[str] = set()  # shards changed since they were last written
        self._names: set[str] = set(vault.meta.get("shards", [])) - {STATS} if vault else set()
        self._legacy: list[Path] = []

    @property
    def enabled(self) -> bool:
        return self.vault is not None

    @classmethod
    def open(cls, data_dir: str | Path, env: dict[str, str]) -> History:
        password = env.get("DASHBOARD_PASSWORD", "")
        if not password:
            note = ("History isn't being saved – add a DASHBOARD_PASSWORD secret to keep a "
                    "password-protected history of every job (see the README)")
            return cls(None, note)
        try:
            vault = Vault(Path(data_dir) / "history", password)
            history = cls(vault)
            stats = vault.read(STATS)
        except WrongPassword:
            return cls(None, "History not saved – DASHBOARD_PASSWORD doesn't match the password data/history "
                             "was encrypted with (delete that folder to start a new history)")
        if stats is not None:
            history.has_stats = True
            history.runs = list(stats.get("runs", []))
            history.suggestions = list(stats.get("suggestions", []))
        return history

    # -- adding ---------------------------------------------------------------

    def merged_runs(self, record: dict) -> list[dict]:
        """The run list as it will be once `record` is added: one record per day, so a day with
        many runs counts as one day (see stats.merge_runs)."""
        if self.runs and self.runs[-1].get("date") == record.get("date"):
            return [*self.runs[:-1], stats.merge_runs(self.runs[-1], record)]
        return (self.runs + [record])[-MAX_RUNS:]

    def add_run(self, record: dict) -> None:
        self.runs = self.merged_runs(record)

    def add_jobs(self, day: date, jobs: list[Job], hidden_uids: set[str], cfg: Config) -> None:
        if not self.enabled:
            return
        for job in jobs:
            self._add_entry(job_entry(job, day, job.uid in hidden_uids, cfg))

    def _add_entry(self, entry: dict) -> None:
        name = _month(entry["date"])
        if name not in self._shards:
            self._shards[name] = {e["id"]: e for e in (self.vault.read(name) or [])}
        self._shards[name][entry["id"]] = entry
        self._names.add(name)
        self._dirty.add(name)

    def import_legacy(self, data_dir: str | Path, cfg: Config) -> None:
        """Pick up the old plain-text stats.json / jobs_log.csv (once); they are
        deleted when the encrypted copy has been written."""
        if not self.enabled or self.has_stats:
            return
        data_dir = Path(data_dir)
        old_stats, old_log = data_dir / "stats.json", data_dir / "jobs_log.csv"
        if old_stats.exists():
            data = json.loads(old_stats.read_text(encoding="utf-8") or "{}")
            self.runs = list(data.get("runs", []))[-MAX_RUNS:]
            self.suggestions = list(data.get("suggestions", []))
            self._legacy.append(old_stats)
        if old_log.exists():
            with open(old_log, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    self._add_entry(_legacy_entry(row, cfg))
            self._legacy.append(old_log)
        if self._legacy:
            log.info("Moving %d earlier run(s) and the jobs log into the encrypted history", len(self.runs))

    # -- reading back -----------------------------------------------------------

    def entries(self, since: date) -> list[dict]:
        """Every logged job first seen on or after `since` (oldest month first)."""
        if not self.enabled:
            return []
        first = _month(since.isoformat())
        out: list[dict] = []
        for name in sorted(n for n in self._names if n.startswith("jobs-") and n >= first):
            rows = list(self._shards[name].values()) if name in self._shards else (self.vault.read(name) or [])
            out.extend(e for e in rows if e.get("date", "") >= since.isoformat())
        return out

    def backfill_skills(self, cfg: Config) -> int:
        """Jobs logged before skills were recorded get theirs from the text kept with them
        (title, what the advert asks for, the AI's reason). Only shards that change are rewritten."""
        if not self.enabled:
            return 0
        changed = 0
        for name in sorted(n for n in self._names if n.startswith("jobs-")):
            rows = self._shards.get(name)
            if rows is None:
                rows = {e["id"]: e for e in (self.vault.read(name) or [])}
            n = 0
            for entry in rows.values():
                if "skills" in entry:
                    continue
                text = " ".join(str(entry.get(k) or "") for k in ("title", "requirements", "ai_reason"))
                if found := extract_skills(text, cfg.coach.extra_skills):
                    entry["skills"] = found
                    n += 1
            if n:
                self._shards[name] = rows
                self._dirty.add(name)
                changed += n
        if changed:
            log.info("Skills added to %d earlier job(s) in the history", changed)
        return changed

    def write_named(self, name: str, obj: Any) -> None:
        """Save another encrypted file next to the history (e.g. the career report)."""
        if not self.enabled:
            return
        self.vault.write(name, obj)
        self._names.add(name)
        self.vault.save_meta(sorted({STATS, *self._names}))

    # -- saving ---------------------------------------------------------------

    def flush_jobs(self) -> None:
        """Write the job shards that changed (and the shard list), nothing else."""
        if not self.enabled:
            return
        for name in sorted(self._dirty & self._names):
            entries = self._shards[name]
            self.vault.write(name, sorted(entries.values(), key=lambda e: (e["date"], e["id"])))
        self._dirty.clear()
        self.vault.save_meta(sorted({STATS, *self._names}))

    def save(self) -> None:
        if not self.enabled:
            return
        newest = sorted(n for n in self._names if n.startswith("jobs-"))[-MAX_MONTHS:]
        for name in sorted(n for n in self._names if n.startswith("jobs-") and n not in newest):  # very old months fall away
            self.vault.path(name).unlink(missing_ok=True)
            self._shards.pop(name, None)
        self._names = {n for n in self._names if not n.startswith("jobs-")} | set(newest)
        self.flush_jobs()
        self.vault.write(STATS, {"runs": self.runs, "suggestions": self.suggestions})
        self.vault.save_meta(sorted({STATS, *self._names}))
        for path in self._legacy:  # the encrypted copy exists now
            path.unlink(missing_ok=True)
        self._legacy = []
        self.has_stats = True


def _legacy_entry(row: dict, cfg: Config) -> dict:
    """A row of the old jobs_log.csv -> a history entry."""
    labels = {sf.label: sf.key for sf in cfg.subfields}
    levels = {lv.label: lv.key for lv in cfg.levels}
    subfields = [labels[s.strip()] for s in (row.get("subfields") or "").split(";") if s.strip() in labels]
    level = levels.get(row.get("level") or "")
    try:
        score: int | None = int(row["ai_score"])
    except (KeyError, TypeError, ValueError):
        score = None
    hidden = (row.get("status") or "").startswith("hidden")
    url = row.get("url") or ""
    key = hashlib.sha1(f"{url}|{row.get('title')}|{row.get('company')}".encode()).hexdigest()[:12]
    entry = {
        "id": f"{row.get('site') or 'old'}:{key}", "date": row.get("date") or "2000-01-01",
        "status": "hidden" if hidden else "sent", "source": row.get("site") or "", "title": row.get("title") or "",
        "company": row.get("company") or "", "location": row.get("location") or "", "url": url,
        "subfields": subfields, "level": level, "ai_score": score, "ai_reason": row.get("ai_reason") or "",
        "closing": row.get("closing") or "",
        "importance": tier(score, hidden, row.get("title") or "", subfields, level, [], cfg),
    }
    return {k: v for k, v in entry.items() if v not in ("", None, [])}
