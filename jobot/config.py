"""Loads config.yaml into typed objects and applies command-line overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass
class Subfield:
    key: str
    label: str
    keywords: list[str]
    enabled: bool = True


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
class Config:
    subfields: list[Subfield]
    levels: list[Level]
    exclude_title_keywords: list[str] = field(default_factory=list)
    match_description: bool = True
    min_description_hits: int = 2
    description_match_titles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    include_overseas: bool = True
    overseas_keywords: list[str] = field(default_factory=list)
    include_unknown_level: bool = True
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    send_when_empty: bool = True
    remember_days: int = 60

    @property
    def enabled_subfields(self) -> list[Subfield]:
        return [s for s in self.subfields if s.enabled]

    @property
    def enabled_levels(self) -> list[Level]:
        return [lv for lv in self.levels if lv.enabled]

    def level(self, key: str | None) -> Level | None:
        return next((lv for lv in self.levels if lv.key == key), None)

    def subfield(self, key: str) -> Subfield | None:
        return next((s for s in self.subfields if s.key == key), None)

    def enabled_sources(self) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self.sources.items() if v.get("enabled", True)}

    # -- command-line overrides -------------------------------------------

    def only_subfields(self, keys: list[str]) -> None:
        self._only(self.subfields, keys, "sub-field")

    def only_levels(self, keys: list[str]) -> None:
        self._only(self.levels, keys, "experience level")

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

    notify = raw.get("notify") or {}
    return Config(
        subfields=subfields,
        levels=levels,
        exclude_title_keywords=_str_list(raw.get("exclude_title_keywords"), "exclude_title_keywords"),
        match_description=bool(raw.get("match_description", True)),
        min_description_hits=int(raw.get("min_description_hits", 2)),
        description_match_titles=_str_list(raw.get("description_match_titles"), "description_match_titles"),
        locations=_str_list(raw.get("locations"), "locations"),
        include_overseas=bool(raw.get("include_overseas", True)),
        overseas_keywords=_str_list(raw.get("overseas_keywords"), "overseas_keywords"),
        include_unknown_level=bool(raw.get("include_unknown_level", True)),
        sources={str(k): dict(v or {}) for k, v in (raw.get("sources") or {}).items()},
        send_when_empty=bool(notify.get("send_when_empty", True)),
        remember_days=int(notify.get("remember_days", 60)),
    )


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as fh:
        return parse_config(yaml.safe_load(fh) or {})
