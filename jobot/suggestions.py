"""Turns the statistics history into practical suggestions.

Each suggestion is a dict: {"id", "kind": "tip" | "warning" | "insight",
"text", "action"} – `action` (or None) is something the settings page can
apply with one tap, e.g. {"type": "enable_subfield", "key": "lifts"}.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from .config import Config

BUSY = 5            # open jobs that make a switched-off sub-field / level worth a look
MAX_PER_RULE = 3


def _recent(runs: list[dict], today: date, days: int) -> list[dict]:
    return [r for r in runs if (today - date.fromisoformat(r["date"])).days < days]


def generate(runs: list[dict], cfg: Config, today: date) -> list[dict]:
    if not runs:
        return []
    out: list[dict] = []
    latest = runs[-1]
    open_by = Counter(latest.get("open_by_subfield", {}))

    # 1. Switched-off sub-fields that have plenty of open jobs.
    off = [(k, n) for k, n in open_by.most_common() if (sf := cfg.subfield(k)) and not sf.enabled and n >= BUSY]
    for k, n in off[:MAX_PER_RULE]:
        out.append({"id": f"enable_subfield:{k}", "kind": "tip",
                    "text": f"{cfg.subfield(k).label} has {n} open jobs right now, but it's switched off.",
                    "action": {"type": "enable_subfield", "key": k, "label": f"Switch on {cfg.subfield(k).label}"}})

    # 2. Experience levels that are hiding many jobs in your fields.
    for lv_key, n in Counter(latest.get("open_level_filtered", {})).most_common():
        lv = cfg.level(lv_key)
        if lv and not lv.enabled and n >= BUSY:
            out.append({"id": f"enable_level:{lv_key}", "kind": "tip",
                        "text": f"{n} {lv.label} jobs match your sub-fields, but that level is switched off.",
                        "action": {"type": "enable_level", "key": lv_key, "label": f"Show {lv.label} jobs"}})

    # 2b. Qualification levels hiding many jobs in your fields (only ever an
    #     offer: a degree holder may not want diploma-level jobs at all).
    for q_key, n in Counter(latest.get("open_qualification_filtered", {})).most_common():
        q = cfg.qualification(q_key)
        if q and not q.enabled and n >= BUSY:
            out.append({"id": f"enable_qualification:{q_key}", "kind": "tip",
                        "text": f"{n} open jobs in your sub-fields ask for {q.short.lower()} level "
                                "qualifications, which you've switched off.",
                        "action": {"type": "enable_qualification", "key": q_key, "label": f"Show {q.short} jobs"}})

    # 3. Sub-fields that never match anything (needs a month of history).
    month = _recent(runs, today, 30)
    if len(month) >= 14:
        seen = Counter()
        for r in month:
            seen.update({k: 1 for k, n in r.get("open_by_subfield", {}).items() if n})
        dead = [sf for sf in cfg.enabled_subfields if not seen[sf.key]]
        for sf in dead[:MAX_PER_RULE]:
            out.append({"id": f"disable_subfield:{sf.key}", "kind": "tip",
                        "text": f"{sf.label} hasn't matched a single job in 30 days.",
                        "action": {"type": "disable_subfield", "key": sf.key, "label": f"Switch off {sf.label}"}})

    # 4. Sites that keep failing.
    last5 = runs[-5:]
    if len(last5) >= 3:
        fails: Counter = Counter()
        last_error: dict[str, str] = {}
        for r in last5:
            for name, st in r.get("sources", {}).items():
                if "error" in st:
                    fails[name] += 1
                    last_error[name] = st["error"]
        for name, n in fails.most_common():
            if n >= 3:
                out.append({"id": f"failing:{name}", "kind": "warning",
                            "text": f"{name} failed in {n} of the last {len(last5)} runs ({last_error[name]}).",
                            "action": None})

    # 5. The AI reviewer.
    week = _recent(runs, today, 7)
    ai_runs = [r["ai"] for r in week if r.get("ai")]
    checked = sum(a.get("checked", 0) for a in ai_runs)
    hidden = sum(a.get("hidden", 0) for a in ai_runs)
    if cfg.ai.enabled and checked >= 10 and hidden / checked >= 0.75 and cfg.ai.min_score > 1:
        out.append({"id": "ai_threshold", "kind": "tip",
                    "text": f"The AI hid {hidden} of {checked} new jobs this week ({hidden * 100 // checked}%). "
                            f"Lowering the cut-off from {cfg.ai.min_score} would show more.",
                    "action": {"type": "set_ai_min_score", "value": cfg.ai.min_score - 1,
                               "label": f"Hide below {cfg.ai.min_score - 1} instead"}})
    if cfg.ai.enabled and len(week) >= 3 and not ai_runs:
        out.append({"id": "ai_key", "kind": "tip",
                    "text": "The AI reviewer is on but hasn't run – add a free Gemini key as the AI_API_KEY secret "
                            "to get a fit score and reason for every job.",
                    "action": None})

    # 6. Nothing new for a while.
    last = runs[-5:]
    if len(last) == 5 and not any(r.get("new") for r in last):
        out.append({"id": "drought", "kind": "tip",
                    "text": "No new matching jobs in the last 5 runs. Switch on more sub-fields or levels, "
                            "or 'Also match keywords in descriptions'.",
                    "action": None})

    # 7. What the market looks like right now.
    busiest = [(k, n) for k, n in open_by.most_common() if cfg.subfield(k)][:3]
    if busiest:
        out.append({"id": "busiest", "kind": "insight",
                    "text": "Most open EEE jobs right now: "
                            + ", ".join(f"{cfg.subfield(k).label} ({n})" for k, n in busiest) + ".",
                    "action": None})
    if latest.get("top_companies"):
        out.append({"id": "hiring", "kind": "insight",
                    "text": "Hiring the most: "
                            + ", ".join(f"{c} ({n})" for c, n in latest["top_companies"][:3]) + ".",
                    "action": None})
    return out
