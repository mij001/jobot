"""Decides which jobs are EEE-relevant, tags sub-fields and experience level."""

from __future__ import annotations

import re
from functools import lru_cache

from .config import Config
from .models import Job

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
}
_NUM = r"(\d{1,2}|" + "|".join(_WORD_NUMBERS) + r")"
# "3-5 years", "3 to 5 yrs", "5+ years", "minimum of five years", "2 years'"
_YEARS_RE = re.compile(
    _NUM + r"\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*" + _NUM + r"\s*\+?\s*)?(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_EXPERIENCE_RE = re.compile(r"\bexp(?:erience[sd]?|\.)?\b", re.IGNORECASE)


@lru_cache(maxsize=4096)
def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive pattern; a trailing * matches any word ending."""
    kw = keyword.strip()
    wildcard = kw.endswith("*")
    kw = kw.rstrip("*").strip()
    parts = [re.escape(p) for p in kw.split()]
    body = r"\s+".join(parts)
    if wildcard:
        body += r"[\w-]*"
    # Custom boundaries so keywords like "E&E" or "B.Sc." work too.
    return re.compile(r"(?<![\w])" + body + r"(?![\w])", re.IGNORECASE)


def matches(keyword: str, text: str) -> bool:
    return bool(text) and keyword_pattern(keyword).search(text) is not None


def matching_keywords(keywords: list[str], text: str) -> list[str]:
    return [k for k in keywords if matches(k, text)]


def match_subfields(job: Job, cfg: Config) -> list[str]:
    """Return keys of the enabled sub-fields this job belongs to."""
    everything = f"{job.title}\n{job.description}\n{job.category}"
    usable = [sf for sf in cfg.enabled_subfields
              if not sf.requires_any or matching_keywords(sf.requires_any, everything)]
    title_hits: list[str] = []
    for sf in usable:
        if matching_keywords(sf.keywords, job.title):
            title_hits.append(sf.key)
    if title_hits or not cfg.match_description:
        return title_hits
    if cfg.description_match_titles and not matching_keywords(cfg.description_match_titles, job.title):
        return []

    # Weaker evidence: description + the site's category label. The category
    # counts as a single hit however many keywords it contains, so a job is
    # never accepted on "Electronics / Electrical" alone.
    desc_hits: set[str] = set()
    category_hit = False
    per_subfield: dict[str, int] = {}
    for sf in usable:
        d = {k.lower() for k in matching_keywords(sf.keywords, job.description)}
        c = bool(matching_keywords(sf.keywords, job.category))
        desc_hits |= d
        category_hit |= c
        if d or c:
            per_subfield[sf.key] = len(d) + int(c)
    if len(desc_hits) + int(category_hit) < max(1, cfg.min_description_hits):
        return []
    return sorted(per_subfield, key=lambda k: -per_subfield[k])


def years_required(text: str) -> int | None:
    """Smallest 'N years' figure mentioned near the word 'experience'."""
    if not text:
        return None
    found: list[int] = []
    for m in _YEARS_RE.finditer(text):
        window = text[max(0, m.start() - 80): m.end() + 80]
        if not _EXPERIENCE_RE.search(window):
            continue
        first = m.group(1).lower()
        n = _WORD_NUMBERS.get(first) if not first.isdigit() else int(first)
        if n is not None and n <= 30:
            found.append(n)
    return min(found) if found else None


def classify_level(job: Job, cfg: Config) -> str | None:
    # a) Title keywords. Levels are ordered junior -> senior; the most senior
    #    match wins ("Trainee Engineer" -> entry, "Senior Manager" -> management).
    title_levels = [lv.key for lv in cfg.levels if matching_keywords(lv.keywords, job.title)]
    if title_levels:
        return title_levels[-1]

    # b) "N years of experience" in title / description.
    years = years_required(f"{job.title}\n{job.description}")
    if years is not None:
        for lv in cfg.levels:
            if lv.covers_years(years):
                return lv.key

    # c) Whatever the job site says.
    if job.level_hint and cfg.level(job.level_hint):
        return job.level_hint
    return None


def is_excluded(job: Job, cfg: Config) -> bool:
    if matching_keywords(cfg.exclude_title_keywords, job.title):
        return True
    if not cfg.include_overseas and matching_keywords(cfg.overseas_keywords, f"{job.title}\n{job.location}"):
        return True
    if cfg.locations and job.location:
        loc = job.location.lower()
        if not any(want.lower() in loc for want in cfg.locations):
            return True
    return False


def level_allowed(level: str | None, cfg: Config) -> bool:
    if level is None:
        return cfg.include_unknown_level
    lv = cfg.level(level)
    return bool(lv and lv.enabled)


def select_jobs(jobs: list[Job], cfg: Config) -> list[Job]:
    """Tag and filter jobs, merging duplicates posted on several sites."""
    selected: list[Job] = []
    by_fp: dict[str, Job] = {}
    seen_uids: set[str] = set()
    for job in jobs:
        if job.uid in seen_uids:
            continue
        seen_uids.add(job.uid)
        if is_excluded(job, cfg):
            continue
        # A source may pre-tag a job (e.g. a company page set to "power").
        preset = [k for k in job.subfields if (sf := cfg.subfield(k)) and sf.enabled]
        job.subfields = preset + [k for k in match_subfields(job, cfg) if k not in preset]
        if not job.subfields:
            continue
        job.level = classify_level(job, cfg)
        if not level_allowed(job.level, cfg):
            continue
        first = by_fp.get(job.fingerprint)
        if first is not None:
            if job.source != first.source and all(s != job.source for s, _ in first.also_on):
                first.also_on.append((job.source, job.url))
            continue
        by_fp[job.fingerprint] = job
        selected.append(job)
    return selected
