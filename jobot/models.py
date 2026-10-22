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

    # Filled in by the posting reader (jobot.postings) from the advert itself.
    read_via: str = ""  # how the advert was read: "page", "poster", "pdf", "ai", joined by "+"
    contact: str = ""  # e-mail address to apply to
    requirements: str = ""  # one-line summary of what the advert asks for

    # Filled in by the filter step.
    subfields: list[str] = field(default_factory=list)
    level: str | None = None
    qualifications: list[str] = field(default_factory=list)  # e.g. ["degree", "diploma"]
    qual_guess: bool = False  # `qualifications` is only a guess from the job title (the advert doesn't say)
    min_years: int | None = None  # "N years experience" found in the advert
    also_on: list[tuple[str, str]] = field(default_factory=list)  # (source, url) duplicates
    ai_score: int | None = None  # 0-10 from the optional AI reviewer
    ai_reason: str = ""
    watched: bool = False  # the employer is on your watch list
    remote: bool = False  # a fully remote job that is open to people in Sri Lanka
    remote_rule: str = ""  # what the plain-text check said about it: "open" or "unsure" (the AI settles those)
    ai_note: str = ""  # why the AI let this job through / what to check ("Open to Sri Lanka: no US hours needed")
    preset: list[str] | None = field(default=None, repr=False)  # sub-fields set by the source

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def fingerprint(self) -> str:
        """Site-independent key used to spot the same vacancy on several sites."""
        if m := _LINKEDIN_ID.search(self.url):  # the search and an alert e-mail word the same LinkedIn job differently
            return f"linkedin|{m.group(1)}"
        return f"{_norm(self.title)}|{_norm(self.company)}"


_LINKEDIN_ID = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[\w-]*-)?(\d{6,})")


def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\(\s*\d+\s*\)", " ", text)  # "(2)" vacancy counts on topjobs
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(pvt|ltd|plc|private|limited|the|sri lanka|lk)\b", " ", text)
    return " ".join(text.split())
