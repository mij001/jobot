"""The last gate before a job is sent: is it really what you asked for?

Every new job is read against your requirements (requirements.py) in up to three ways:

1. **plain rules** on the title and the posting text – always, free, instant; they turn away the obvious misses
   (sales, software / IT-desk work, nothing electrical in a long posting) before any AI is asked;
2. **the AI**, which reads the posting text against the same requirements and answers match / maybe / no;
3. **waiting** – a job whose posting couldn't be opened yet, or that the AI couldn't be asked about (quota, outage), is
   not sent half-checked: it is put off and judged on a later run (up to `ai.defer_runs` times; then the rules decide).

A job the AI or the rules call "no" is held back: not sent, but listed in the log, named in the message footer and kept
on the dashboard, so nothing disappears without a trace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import ai, requirements
from .config import Config
from .models import Job
from .schedule import Schedule

log = logging.getLogger(__name__)

NEEDS_TIME = 240  # seconds the AI review needs at the least; with less left it is skipped


@dataclass
class Judged:
    shown: list[Job] = field(default_factory=list)
    held: list[Job] = field(default_factory=list)  # judged "no": not sent
    waiting: list[Job] = field(default_factory=list)  # put off to a later run
    outcome: ai.ReviewResult | None = None
    ai_note: str | None = None
    notes: list[str] = field(default_factory=list)


def judge(kept: list[Job], cfg: Config, env: dict[str, str], schedule: Schedule, *, use_ai: bool = True,
          time_left: float = 1e9, profile_extra: str = "", review=None, wait: bool = True) -> Judged:
    out = Judged()
    for job in kept:
        job.rule_verdict, why = requirements.assess(job, cfg)
        if job.rule_verdict == "no" and not job.ai_reason:
            job.ai_reason = why

    def can_wait(job: Job) -> bool:
        return wait and schedule.put_offs(job.uid) < cfg.ai.defer_runs

    # A posting that couldn't be opened yet is read again next run rather than judged on a title alone.
    waiting = [j for j in kept if j.rule_verdict != "no" and j.unread and can_wait(j)]
    waiting_uids = {j.uid for j in waiting}
    candidates = [j for j in kept if j.rule_verdict != "no" and j.uid not in waiting_uids]

    has_key = bool(env.get("AI_API_KEY") or env.get("AI_BASE_URL"))
    ai_wanted = cfg.ai.enabled and use_ai
    unreviewed: list[Job] = []
    if ai_wanted and has_key and candidates and time_left < NEEDS_TIME:
        out.ai_note = "AI review skipped: the run was out of time"
        unreviewed = candidates
    elif ai_wanted and has_key and candidates:
        out.outcome = (review or ai.review)(candidates, cfg, env, profile_extra=profile_extra)
        out.ai_note = out.outcome.summary
        unreviewed = out.outcome.unreviewed
    elif ai_wanted and not has_key:
        log.info("AI review is on but AI_API_KEY isn't set – the plain rules decide")
    # The AI was meant to judge these but couldn't: wait for it, unless the title itself already names an EEE field.
    for job in unreviewed:
        if job.rule_verdict != "match" and can_wait(job) and job.uid not in waiting_uids:
            waiting.append(job)
            waiting_uids.add(job.uid)

    # A job the keywords never placed (picked by the AI triage or kept as a generic "Associate Engineer") has to show
    # electrical / electronic / telecom work in its posting; "maybe, the text is too short" is not enough for it.
    for job in kept:
        if job.rescued and job.ai_verdict == "maybe" and not requirements.evidence_terms(job, cfg):
            job.ai_verdict, job.ai_score = "no", min(job.ai_score if job.ai_score is not None else 4, 4)
            job.ai_reason = "the posting doesn't show electrical, electronic or telecom work"

    out.waiting = waiting
    judged = [j for j in kept if j.uid not in waiting_uids]
    out.held = sorted((j for j in judged if ai.is_hidden(j, cfg)), key=lambda j: -(j.ai_score or 0))
    out.shown = [j for j in judged if not ai.is_hidden(j, cfg)]
    if out.held:
        log.info("Held back %d job(s) that don't meet your requirements:", len(out.held))
        for j in out.held[:100]:
            log.info("  held back (%s): %s · %s – %s", f"{j.ai_score}/10" if j.ai_score is not None else "rules", j.title,
                     j.company or j.source, j.ai_reason)
    if waiting:
        why = "the posting couldn't be opened yet" if any(j.unread for j in waiting) else ""
        unreviewed_uids = {j.uid for j in unreviewed}
        if any(j.uid in unreviewed_uids for j in waiting):
            why = (why + " / " if why else "") + "the AI couldn't be asked"
        log.info("%d job(s) wait for a later run (%s)", len(waiting), why)
        out.notes.append(f"{len(waiting)} job(s) waiting to be judged on a later run ({why})")
    return out


def held_note(held: list[Job], show: int = 4) -> str:
    """"Held back, closest first: …" – so a job that was turned away is never invisible."""
    def one(j: Job) -> str:
        why = (j.ai_reason or "").rstrip(".")
        return f"{j.title} · {j.company or j.source}" + (f" ({why[:48]})" if why else "")

    names = "; ".join(one(j) for j in held[:show])
    return f"Held back (not matching your requirements), closest first: {names}" + \
        (f" … (+{len(held) - show} more on the dashboard)" if len(held) > show else "")
