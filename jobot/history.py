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

from .config import Config
from .filters import matching_keywords
from .models import Job
from .vault import Vault, WrongPassword

log = logging.getLogger(__name__)

STATS = "stats"
MAX_RUNS = 200
MAX_MONTHS = 24
TIERS = ("top", "good", "maybe", "low")  # shown as Top picks / Good fits / Worth a look / Low priority


def tier(score: int | None, hidden: bool, title: str, subfields: list[str], level: str | None,
         qualifications: list[str], cfg: Config) -> str:
    """How much a job deserves your attention: top | good | maybe | low."""
    if hidden:
        return "low"
    if score is not None:
        top = cfg.top_picks_score or 8
        return "top" if score >= top else "good" if score >= 6 else "maybe"
    # No AI review: judge by how clearly the advert fits what you asked for.
    points = 0
    if any(matching_keywords(sf.keywords, title) for k in subfields if (sf := cfg.subfield(k))):
        points += 1  # the title itself says EEE
    points += bool(qualifications)  # the advert states a qualification you accept
    points += bool(level)  # and a level you accept
    return "good" if points >= 2 else "maybe"


def importance(job: Job, cfg: Config, hidden: bool = False) -> str:
    return tier(job.ai_score, hidden, job.title, job.subfields, job.level, job.qualifications, cfg)


def job_entry(job: Job, day: date, hidden: bool, cfg: Config) -> dict:
    entry: dict[str, Any] = {
        "id": job.uid, "date": day.isoformat(), "status": "hidden" if hidden else "sent",
        "source": job.source, "title": job.title, "company": job.company, "location": job.location,
        "url": job.url, "also_on": [list(p) for p in job.also_on], "subfields": list(job.subfields),
        "level": job.level, "qualifications": list(job.qualifications), "min_years": job.min_years,
        "ai_score": job.ai_score, "ai_reason": job.ai_reason, "importance": importance(job, cfg, hidden),
        "posted": job.posted, "closing": job.closing, "requirements": job.requirements,
        "contact": job.contact, "salary": job.salary, "read_via": job.read_via,
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
        self._names: set[str] = set(vault.meta.get("shards", [])) if vault else set()
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

    def add_run(self, record: dict) -> None:
        self.runs = (self.runs + [record])[-MAX_RUNS:]

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

    # -- saving ---------------------------------------------------------------

    def save(self) -> None:
        if not self.enabled:
            return
        newest = sorted(self._names)[-MAX_MONTHS:]
        for name in sorted(self._names - set(newest)):  # very old months fall away
            self.vault.path(name).unlink(missing_ok=True)
            self._shards.pop(name, None)
        self._names = set(newest)
        for name, entries in self._shards.items():
            if name in self._names:
                self.vault.write(name, sorted(entries.values(), key=lambda e: (e["date"], e["id"])))
        self.vault.write(STATS, {"runs": self.runs, "suggestions": self.suggestions})
        self.vault.save_meta([STATS, *self._names])
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
