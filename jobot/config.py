"""Loads config.yaml into typed objects and applies command-line overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


ORDER_BY = {
    "best_match": "Best match first (AI score, then newest)",
    "newest": "Newest first",
    "closing_soon": "Closing soonest first",
    "company": "Company A–Z",
    "title": "Job title A–Z",
}
WEEKLY = {d: d.title() for d in
          ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "daily", "off")}
GROUP_BY = {
    "level": "Experience level",
    "qualification": "Qualification (degree / diploma)",
    "subfield": "Sub-field",
    "site": "Job site",
    "none": "No grouping",
}


@dataclass
class Subfield:
    key: str
    label: str
    keywords: list[str]
    enabled: bool = True
    # When set, the ad must ALSO mention one of these somewhere (title,
    # description or category) – e.g. "Lecturer" only if it says "electrical".
    requires_any: list[str] = field(default_factory=list)


@dataclass
class Level:
    key: str
    label: str
    keywords: list[str]
    enabled: bool = True
    min_years: int | None = None
    max_years: int | None = None

    def covers_years(self, years: int) -> bool:
        if self.min_years is None:
            return False
        return self.min_years <= years and (self.max_years is None or years <= self.max_years)


@dataclass
class Qualification:
    key: str
    label: str
    keywords: list[str]
    enabled: bool = True
    # Used only when the advert itself names no qualification, e.g. a
    # "Technical Officer" poster that couldn't be read is almost always diploma level.
    title_hints: list[str] = field(default_factory=list)

    @property
    def short(self) -> str:
        """"Degree (BSc / BEng / NVQ 7)" -> "Degree"."""
        return self.label.split(" (")[0].strip() or self.key


@dataclass
class PostingsConfig:
    """Opening each job's own page to read the full advert (text, poster or PDF)."""
    enabled: bool = True
    max_per_run: int = 60  # pages opened per run; already-read adverts are cached
    workers: int = 3  # adverts read at the same time (each worker on its own connection)
    max_seconds: int = 240  # stop opening adverts after this long; the rest waits for the next run
    read_posters: bool = True  # OCR poster images (Tesseract)
    ai_vision: bool = True  # let the AI read posters OCR can't
    max_ai_reads: int = 5
    skip_titles: list[str] = field(default_factory=list)  # don't open these "maybe" ads


@dataclass
class ScheduleConfig:
    """How the frequent runs behave (how OFTEN they start is the cron line in .github/workflows/daily.yml)."""
    digest_hour: int = 8  # the first run after this hour (Sri Lanka time) sends the daily summary
    workers: int = 6  # job sites read at the same time
    site_seconds: int = 240  # a site that hasn't finished by then is given up on for this run
    run_seconds: int = 540  # the whole read of all sites (retries included) is cut off after this long
    retry_seconds: int = 90  # the second chance given to a failed site is this long at most
    retry_failed: bool = True  # ask a site that timed out or errored once more before giving up


@dataclass
class CoachConfig:
    """The career coach: resume analysis, skill gaps, portfolio projects, resume matching."""
    enabled: bool = True
    weekly_report: str = "sunday"  # weekday name, "daily" or "off": when the report is refreshed
    window_days: int = 90  # how far back the adverts used for skill demand go
    projects: int = 4  # portfolio project ideas per report
    extra_skills: list[str] = field(default_factory=list)  # more skills to look for in adverts
    send_resume: bool = True  # false: the resume text never goes to the AI (counts only)


@dataclass
class AIConfig:
    enabled: bool = False
    provider: str = "gemini"
    models: list[str] = field(default_factory=list)  # fast models: scoring the daily jobs
    smart_models: list[str] = field(default_factory=list)  # stronger models: career coach, harder tasks
    profile: str = ""
    min_score: int = 4
    batch_size: int = 20
    requests_per_minute: int = 8


@dataclass
class Config:
    subfields: list[Subfield]
    levels: list[Level]
    exclude_title_keywords: list[str] = field(default_factory=list)
    match_description: bool = True
    min_description_hits: int = 2
    description_match_titles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    watch_companies: list[str] = field(default_factory=list)  # employers you want to hear about first
    avoid_companies: list[str] = field(default_factory=list)  # employers you never want
    include_overseas: bool = True
    overseas_keywords: list[str] = field(default_factory=list)
    include_unknown_level: bool = True
    qualifications: list[Qualification] = field(default_factory=list)
    include_unknown_qualification: bool = True
    postings: PostingsConfig = field(default_factory=PostingsConfig)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    send_when_empty: bool = True
    remember_days: int = 60
    order_by: str = "best_match"
    group_by: str = "level"
    weekly_summary: str = "monday"  # weekday name, or "off"
    top_picks_score: int = 8  # AI score that makes a job a "top pick" (0 = off)
    dropped_list: int = 8  # weekly: list this many open jobs your own settings dropped, with the reason (0 = off)
    ai: AIConfig = field(default_factory=AIConfig)
    coach: CoachConfig = field(default_factory=CoachConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)

    @property
    def enabled_subfields(self) -> list[Subfield]:
        return [s for s in self.subfields if s.enabled]

    @property
    def enabled_levels(self) -> list[Level]:
        return [lv for lv in self.levels if lv.enabled]

    @property
    def enabled_qualifications(self) -> list[Qualification]:
        return [q for q in self.qualifications if q.enabled]

    def level(self, key: str | None) -> Level | None:
        return next((lv for lv in self.levels if lv.key == key), None)

    def qualification(self, key: str | None) -> Qualification | None:
        return next((q for q in self.qualifications if q.key == key), None)

    def qualification_label(self, keys: list[str]) -> str:
        """["degree", "diploma"] -> "Degree or Diploma"; three -> "Degree, Diploma or Vocational"."""
        names = [q.short for k in keys if (q := self.qualification(k))]
        return " or ".join(filter(None, [", ".join(names[:-1]), names[-1] if names else ""]))

    def subfield(self, key: str) -> Subfield | None:
        return next((s for s in self.subfields if s.key == key), None)

    def enabled_sources(self) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self.sources.items() if v.get("enabled", True)}

    # -- command-line overrides -------------------------------------------

    def only_subfields(self, keys: list[str]) -> None:
        self._only(self.subfields, keys, "sub-field")

    def only_levels(self, keys: list[str]) -> None:
        self._only(self.levels, keys, "experience level")

    def only_qualifications(self, keys: list[str]) -> None:
        self._only(self.qualifications, keys, "qualification")

    def only_sources(self, keys: list[str]) -> None:
        unknown = set(keys) - set(self.sources)
        if unknown:
            raise ConfigError(f"Unknown source(s): {', '.join(sorted(unknown))}. "
                              f"Available: {', '.join(self.sources)}")
        for k, v in self.sources.items():
            v["enabled"] = k in keys

    @staticmethod
    def _only(items: list, keys: list[str], what: str) -> None:
        known = {i.key for i in items}
        unknown = set(keys) - known
        if unknown:
            raise ConfigError(f"Unknown {what}(s): {', '.join(sorted(unknown))}. "
                              f"Available: {', '.join(i.key for i in items)}")
        for i in items:
            i.enabled = i.key in keys


def _str_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{where} must be a list")
    return [str(v).strip() for v in value if str(v).strip()]


def _opt_int(value: Any, where: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{where} must be a whole number") from None


def parse_config(raw: dict[str, Any]) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a YAML mapping")

    subfields = []
    for key, body in (raw.get("subfields") or {}).items():
        body = body or {}
        subfields.append(Subfield(
            key=str(key),
            label=str(body.get("label") or key),
            keywords=_str_list(body.get("keywords"), f"subfields.{key}.keywords"),
            enabled=bool(body.get("enabled", True)),
            requires_any=_str_list(body.get("requires_any"), f"subfields.{key}.requires_any"),
        ))
    if not subfields:
        raise ConfigError("config needs at least one entry under `subfields`")

    levels = []
    for key, body in (raw.get("experience_levels") or {}).items():
        body = body or {}
        levels.append(Level(
            key=str(key),
            label=str(body.get("label") or key),
            keywords=_str_list(body.get("keywords"), f"experience_levels.{key}.keywords"),
            enabled=bool(body.get("enabled", True)),
            min_years=_opt_int(body.get("min_years"), f"experience_levels.{key}.min_years"),
            max_years=_opt_int(body.get("max_years"), f"experience_levels.{key}.max_years"),
        ))

    qualifications = []
    for key, body in (raw.get("qualifications") or {}).items():
        body = body or {}
        qualifications.append(Qualification(
            key=str(key),
            label=str(body.get("label") or key),
            keywords=_str_list(body.get("keywords"), f"qualifications.{key}.keywords"),
            enabled=bool(body.get("enabled", True)),
            title_hints=_str_list(body.get("title_hints"), f"qualifications.{key}.title_hints"),
        ))

    notify = raw.get("notify") or {}
    return Config(
        subfields=subfields,
        levels=levels,
        exclude_title_keywords=_str_list(raw.get("exclude_title_keywords"), "exclude_title_keywords"),
        match_description=bool(raw.get("match_description", True)),
        min_description_hits=int(raw.get("min_description_hits", 2)),
        description_match_titles=_str_list(raw.get("description_match_titles"), "description_match_titles"),
        locations=_str_list(raw.get("locations"), "locations"),
        watch_companies=_str_list(raw.get("watch_companies"), "watch_companies"),
        avoid_companies=_str_list(raw.get("avoid_companies"), "avoid_companies"),
        include_overseas=bool(raw.get("include_overseas", True)),
        overseas_keywords=_str_list(raw.get("overseas_keywords"), "overseas_keywords"),
        include_unknown_level=bool(raw.get("include_unknown_level", True)),
        qualifications=qualifications,
        include_unknown_qualification=bool(raw.get("include_unknown_qualification", True)),
        postings=_parse_postings(raw.get("postings") or {}),
        sources={str(k): dict(v or {}) for k, v in (raw.get("sources") or {}).items()},
        send_when_empty=bool(notify.get("send_when_empty", True)),
        remember_days=int(notify.get("remember_days", 60)),
        order_by=_choice(notify.get("order_by", "best_match"), ORDER_BY, "notify.order_by"),
        group_by=_choice(notify.get("group_by", "level"), GROUP_BY, "notify.group_by"),
        weekly_summary=_choice(notify.get("weekly_summary", "monday"), WEEKLY, "notify.weekly_summary"),
        top_picks_score=int(notify.get("top_picks_score", 8) or 0),
        dropped_list=max(0, int(notify.get("dropped_list", 8) or 0)),
        ai=_parse_ai(raw.get("ai") or {}),
        coach=_parse_coach(raw.get("coach") or {}),
        schedule=_parse_schedule(raw.get("schedule") or {}),
    )


def _choice(value: Any, options: dict[str, str], where: str) -> str:
    value = str(value or "").strip().lower()
    if value not in options:
        raise ConfigError(f"{where} must be one of: {', '.join(options)}")
    return value


def _parse_postings(body: dict[str, Any]) -> PostingsConfig:
    if not isinstance(body, dict):
        raise ConfigError("postings must be a mapping")
    return PostingsConfig(
        enabled=bool(body.get("enabled", True)),
        max_per_run=_opt_int(body.get("max_per_run", 60), "postings.max_per_run") or 0,
        workers=min(8, max(1, _opt_int(body.get("workers", 3), "postings.workers") or 3)),
        max_seconds=min(900, max(20, _opt_int(body.get("max_seconds", 240), "postings.max_seconds") or 240)),
        read_posters=bool(body.get("read_posters", True)),
        ai_vision=bool(body.get("ai_vision", True)),
        max_ai_reads=_opt_int(body.get("max_ai_reads", 5), "postings.max_ai_reads") or 0,
        skip_titles=_str_list(body.get("skip_titles"), "postings.skip_titles"),
    )


def _parse_schedule(body: dict[str, Any]) -> ScheduleConfig:
    if not isinstance(body, dict):
        raise ConfigError("schedule must be a mapping")
    hour = _opt_int(body.get("digest_hour", 8), "schedule.digest_hour")
    return ScheduleConfig(
        digest_hour=8 if hour is None else min(23, max(0, hour)),
        workers=min(16, max(1, _opt_int(body.get("workers", 6), "schedule.workers") or 6)),
        site_seconds=min(1200, max(30, _opt_int(body.get("site_seconds", 240), "schedule.site_seconds") or 240)),
        run_seconds=min(1500, max(60, _opt_int(body.get("run_seconds", 540), "schedule.run_seconds") or 540)),
        retry_seconds=min(600, max(15, _opt_int(body.get("retry_seconds", 90), "schedule.retry_seconds") or 90)),
        retry_failed=bool(body.get("retry_failed", True)),
    )


def _parse_coach(body: dict[str, Any]) -> CoachConfig:
    if not isinstance(body, dict):
        raise ConfigError("coach must be a mapping")
    return CoachConfig(
        enabled=bool(body.get("enabled", True)),
        weekly_report=_choice(body.get("weekly_report", "sunday"), WEEKLY, "coach.weekly_report"),
        window_days=max(7, _opt_int(body.get("window_days", 90), "coach.window_days") or 90),
        projects=min(8, max(1, _opt_int(body.get("projects", 4), "coach.projects") or 4)),
        extra_skills=_str_list(body.get("extra_skills"), "coach.extra_skills"),
        send_resume=bool(body.get("send_resume", True)),
    )


def _parse_ai(body: dict[str, Any]) -> AIConfig:
    if not isinstance(body, dict):
        raise ConfigError("ai must be a mapping")
    return AIConfig(
        enabled=bool(body.get("enabled", False)),
        provider=str(body.get("provider") or "gemini").strip().lower(),
        models=_str_list(body.get("models"), "ai.models"),
        smart_models=_str_list(body.get("smart_models"), "ai.smart_models"),
        profile=str(body.get("profile") or ""),
        min_score=_opt_int(body.get("min_score", 4), "ai.min_score") or 0,
        batch_size=_opt_int(body.get("batch_size"), "ai.batch_size") or 20,
        requests_per_minute=_opt_int(body.get("requests_per_minute"), "ai.requests_per_minute") or 8,
    )


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as fh:
        return parse_config(yaml.safe_load(fh) or {})
