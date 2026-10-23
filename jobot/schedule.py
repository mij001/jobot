"""When things last happened, so frequent runs know what to do (data/schedule.json).

* the day's *digest* – the first run after `schedule.digest_hour` sends the daily
  summary (weekly summary, closing reminders, "nothing new" notice); runs in between
  only message you when they find something;
* slow or touchy sites (`every_hours:` in their settings, e.g. LinkedIn) are only
  asked again once that long has passed.

The file is only rewritten when it changes, so quiet runs commit nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

GRACE = timedelta(minutes=20)  # a run that starts a little early still counts as "due"


class Schedule:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.digest_day = ""
        self.sources: dict[str, str] = {}
        self.deferred: dict[str, list] = {}  # job uid -> [times put off, last day]: waiting for its posting / the AI
        self.ai_day = ""  # the AI helpers (triage, remote vetting …) share a small daily request budget
        self.ai_calls = 0
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            except ValueError:
                data = {}
            self.digest_day = str(data.get("digest") or "")
            self.sources = {str(k): str(v) for k, v in (data.get("sources") or {}).items()}
            self.deferred = {str(k): [int(v[0]), str(v[1])] for k, v in (data.get("deferred") or {}).items()
                             if isinstance(v, list) and len(v) == 2}
            ai = data.get("ai") or {}
            self.ai_day, self.ai_calls = str(ai.get("day") or ""), int(ai.get("calls") or 0)
        self._saved = self._data()

    def _data(self) -> dict:
        data: dict = {"digest": self.digest_day, "sources": dict(sorted(self.sources.items()))}
        if self.ai_calls:
            data["ai"] = {"day": self.ai_day, "calls": self.ai_calls}
        if self.deferred:
            data["deferred"] = dict(sorted(self.deferred.items()))
        return data

    # -- the daily digest -------------------------------------------------------

    def digest_due(self, now: datetime, hour: int) -> bool:
        return self.digest_day != now.date().isoformat() and now.hour >= hour

    def mark_digest(self, now: datetime) -> None:
        self.digest_day = now.date().isoformat()

    # -- slow sites ---------------------------------------------------------------

    def source_due(self, key: str, every_hours: float, now: datetime) -> bool:
        last = self.sources.get(key)
        if not last:
            return True
        try:
            return now - datetime.fromisoformat(last) >= timedelta(hours=every_hours) - GRACE
        except ValueError:
            return True

    def mark_source(self, key: str, now: datetime) -> None:
        self.sources[key] = now.replace(second=0, microsecond=0).isoformat()

    # -- the AI helpers' daily budget ------------------------------------------------------------

    def ai_spent(self, today: str) -> int:
        return self.ai_calls if self.ai_day == today else 0

    def spend_ai(self, today: str, limit: int) -> bool:
        """Count one AI request against today's budget; False (and nothing counted) when it is used up."""
        if self.ai_spent(today) >= limit:
            return False
        if self.ai_day != today:
            self.ai_day, self.ai_calls = today, 0
        self.ai_calls += 1
        return True

    # -- jobs put off until they can be judged ------------------------------------------------------

    def put_offs(self, uid: str) -> int:
        return self.deferred.get(uid, [0, ""])[0]

    def put_off(self, uid: str, today: str) -> int:
        n = self.put_offs(uid) + 1
        self.deferred[uid] = [n, today]
        return n

    def settle(self, uid: str) -> None:
        self.deferred.pop(uid, None)

    def forget_old_put_offs(self, today: str, days: int = 3) -> None:
        cutoff = (datetime.fromisoformat(today) - timedelta(days=days)).date().isoformat()
        self.deferred = {k: v for k, v in self.deferred.items() if v[1] >= cutoff}

    # -- saving -------------------------------------------------------------------

    def save(self) -> None:
        data = self._data()
        if data == self._saved:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        self._saved = data
