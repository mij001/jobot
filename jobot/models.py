"""Core data types shared by scrapers, filters and notifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Job:
    source: str  # human-readable site name, e.g. "topjobs.lk"
    source_id: str  # id unique within that site
    title: str
    url: str
    company: str = ""
    location: str = ""
    description: str = ""  # short text / snippet, may be empty
    category: str = ""  # the site's own category label, if any
    posted: str = ""  # ISO date or free text ("2 days ago")
    closing: str = ""  # ISO date if known
    salary: str = ""
    level_hint: str | None = None  # experience level key suggested by the site itself

    # Filled in by the filter step.
    subfields: list[str] = field(default_factory=list)
    level: str | None = None
    also_on: list[tuple[str, str]] = field(default_factory=list)  # (source, url) duplicates
    ai_score: int | None = None  # 0-10 from the optional AI reviewer
    ai_reason: str = ""

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def fingerprint(self) -> str:
        """Site-independent key used to spot the same vacancy on several sites."""
        return f"{_norm(self.title)}|{_norm(self.company)}"


def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\(\s*\d+\s*\)", " ", text)  # "(2)" vacancy counts on topjobs
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(pvt|ltd|plc|private|limited|the|sri lanka|lk)\b", " ", text)
    return " ".join(text.split())
