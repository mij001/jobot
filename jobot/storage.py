"""Remembers which vacancies were already sent, in a small JSON file."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .models import Job


class SeenStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.ids: dict[str, str] = {}
        self.fingerprints: dict[str, str] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            self.ids = dict(data.get("ids", {}))
            self.fingerprints = dict(data.get("fingerprints", {}))

    @property
    def is_empty(self) -> bool:
        return not self.ids

    def is_new(self, job: Job) -> bool:
        return job.uid not in self.ids and job.fingerprint not in self.fingerprints

    def add(self, job: Job, today: date | None = None) -> None:
        stamp = (today or date.today()).isoformat()
        self.ids[job.uid] = stamp
        self.fingerprints[job.fingerprint] = stamp

    def prune(self, keep_days: int, today: date | None = None) -> None:
        cutoff = ((today or date.today()) - timedelta(days=keep_days)).isoformat()
        self.ids = {k: v for k, v in self.ids.items() if v >= cutoff}
        self.fingerprints = {k: v for k, v in self.fingerprints.items() if v >= cutoff}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "ids": dict(sorted(self.ids.items())),
            "fingerprints": dict(sorted(self.fingerprints.items())),
        }
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
