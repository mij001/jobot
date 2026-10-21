"""Command-line entry point: scrape → filter → notify → remember."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import time

import requests

from . import ai, coach, notifiers, postings, stats, suggestions
from .history import History
from .config import GROUP_BY, ORDER_BY, Config, ConfigError, load_config
from .filters import select_jobs
from .http import Http, SourceTimeout
from .models import Job
from .report import Report, SourceResult
from .schedule import Schedule
from .sources import SOURCES
from .storage import SeenStore
from .swarm import parallel_map

ROOT = Path(__file__).resolve().parent.parent
SRI_LANKA_TZ = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger("jobot")


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobot", description="Sri Lankan EEE job hunter")
    p.add_argument("--config", default=str(ROOT / "config.yaml"), help="path to config.yaml")
    p.add_argument("--state", default=str(ROOT / "data" / "seen_jobs.json"),
                   help="where already-sent jobs are remembered (statistics go next to it)")
    p.add_argument("--subfields", help="only these sub-fields this run, e.g. power,electronics")
    p.add_argument("--levels", help="only these experience levels this run, e.g. internship,entry")
    p.add_argument("--sources", help="only these sites this run, e.g. topjobs,ikman")
    p.add_argument("--qualifications", help="only these qualifications this run, e.g. degree,diploma")
    unknown = p.add_mutually_exclusive_group()
    unknown.add_argument("--include-unknown-level", dest="include_unknown", action="store_true",
                         default=None, help="keep jobs whose level can't be determined")
    unknown.add_argument("--exclude-unknown-level", dest="include_unknown", action="store_false",
                         help="drop jobs whose level can't be determined")
    p.add_argument("--dry-run", action="store_true",
                   help="print the report instead of sending it; don't update the state file")
    p.add_argument("--all", action="store_true",
                   help="report every matching open job, not only ones not sent before")
    p.add_argument("--order-by", choices=list(ORDER_BY), help="how to sort jobs in the message")
    p.add_argument("--group-by", choices=list(GROUP_BY), help="how to group jobs in the message")
    p.add_argument("--no-ai", action="store_true", help="skip the AI review step this run")
    p.add_argument("--career", action="store_true",
                   help="only refresh the career report (resume analysis, skill gaps, portfolio ideas), then exit")
    p.add_argument("--prepare", metavar="JOB_ID",
                   help="cover letter, resume bullets, interview questions and a study plan for one job, then exit")
    p.add_argument("--probe", nargs="?", const=str(ROOT / "candidates.txt"), metavar="FILE",
                   help="try the addresses in FILE (default candidates.txt) from this machine and report which "
                        "sites answer and hold vacancy links, then exit")
    p.add_argument("--auto", action="store_true",
                   help="scheduled run: the first run after schedule.digest_hour of the day sends the daily summary, "
                        "the runs in between only message you when they find new jobs")
    p.add_argument("--no-read", action="store_true",
                   help="don't open the job adverts themselves (posters, PDFs) this run")
    p.add_argument("--list", action="store_true", help="show sub-fields, levels and sources, then exit")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def apply_overrides(cfg: Config, args: argparse.Namespace) -> None:
    if subfields := _csv(args.subfields):
        cfg.only_subfields(subfields)
    if levels := _csv(args.levels):
        cfg.only_levels(levels)
    if sources := _csv(args.sources):
        cfg.only_sources(sources)
    if qualifications := _csv(args.qualifications):
        cfg.only_qualifications(qualifications)
    if args.include_unknown is not None:
        cfg.include_unknown_level = args.include_unknown
    if args.order_by:
        cfg.order_by = args.order_by
    if args.group_by:
        cfg.group_by = args.group_by


def print_options(cfg: Config) -> None:
    def mark(on: bool) -> str:
        return "[x]" if on else "[ ]"
    print("Sub-fields (--subfields):")
    for s in cfg.subfields:
        print(f"  {mark(s.enabled)} {s.key:<18} {s.label}")
    print("Experience levels (--levels):")
    for lv in cfg.levels:
        print(f"  {mark(lv.enabled)} {lv.key:<18} {lv.label}")
    print(f"  {mark(cfg.include_unknown_level)} {'(unknown level)':<18} jobs that don't state a level")
    print("Qualifications (--qualifications):")
    for q in cfg.qualifications:
        print(f"  {mark(q.enabled)} {q.key:<18} {q.label}")
    print(f"  {mark(cfg.include_unknown_qualification)} {'(not stated)':<18} adverts that don't say")
    print("Sources (--sources):")
    for key, opts in cfg.sources.items():
        name = SOURCES[key].NAME if key in SOURCES else "(not supported)"
        print(f"  {mark(opts.get('enabled', True))} {key:<18} {name}")


def scrape(cfg: Config, env: dict[str, str] | None = None, schedule: Schedule | None = None,
           now: datetime | None = None, full: bool = True) -> tuple[list[Job], list[SourceResult]]:
    """Read every enabled site, all of them at the same time. A site that timed out or errored is asked
    once more at the end. Sites with `every_hours` are skipped on quick runs until they are due again."""
    env = dict(os.environ if env is None else env)
    blocked_here = env.get("GITHUB_ACTIONS") == "true" and not env.get("JOBOT_ALLOW_BLOCKED")
    now = now or datetime.now(SRI_LANKA_TZ)
    plan: list[tuple[str, dict, object, SourceResult]] = []
    results: list[SourceResult] = []
    for key, opts in cfg.enabled_sources().items():
        module = SOURCES.get(str(opts.get("type") or key))  # `type:` lets one site have several instances
        if module is None:
            log.warning("Unknown source %r in config – skipped", key)
            continue
        if not full and schedule is not None and opts.get("every_hours") and \
                not schedule.source_due(key, float(opts["every_hours"]), now):
            continue  # a slow or touchy site that was read recently
        result = SourceResult(name=str(opts.get("name") or module.NAME))
        results.append(result)
        if blocked_here and opts.get("skip_on_github_actions"):
            result.skipped = "it blocks GitHub's servers"
            log.info("%-14s skipped: it blocks GitHub's servers", result.name)
            continue
        if (needs := getattr(module, "missing", lambda _env: None)(env)):  # e.g. a secret that isn't set
            result.skipped = needs
            log.info("%-14s skipped: %s", result.name, needs)
            continue
        plan.append((key, opts, module, result))

    def work(item) -> tuple[list[Job], list[str]]:
        key, opts, module, result = item
        started = time.monotonic()
        http = Http(delay=float(opts.get("delay_seconds", 1.0)), deadline=started + cfg.schedule.site_seconds)
        found = module.fetch(http, {**opts, "_env": env}, cfg)
        log.info("%-14s %4d jobs scanned in %3.0fs%s", result.name, len(found), time.monotonic() - started,
                 f"  (partly failed: {'; '.join(http.warnings[:3])})" if http.warnings else "")
        return found, list(http.warnings)

    outcomes = parallel_map(work, plan, workers=cfg.schedule.workers)
    again = [i for i, (_, err) in enumerate(outcomes) if err is not None and cfg.schedule.retry_failed and _transient(err)]
    if again:
        log.info("Asking %d site(s) that failed once more: %s", len(again), ", ".join(plan[i][3].name for i in again))
        for i, outcome in zip(again, parallel_map(work, [plan[i] for i in again], workers=cfg.schedule.workers), strict=True):
            outcomes[i] = outcome

    jobs: list[Job] = []
    for (key, opts, _module, result), (done, err) in zip(plan, outcomes, strict=True):
        if err is not None:
            result.error = _short_error(err)
            log.warning("%-14s FAILED: %s", result.name, result.error)
            log.debug("details", exc_info=err)
            continue
        found, warnings = done
        result.fetched, result.warnings = len(found), warnings
        jobs.extend(found)
        if schedule is not None and opts.get("every_hours"):
            schedule.mark_source(key, now)
    return jobs, results


def _transient(exc: Exception) -> bool:
    """Worth asking again: a timeout, a dropped connection or a 5xx – not a refusal or a rate limit."""
    if isinstance(exc, SourceTimeout):
        return False  # it already used its time
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None):
        return resp.status_code >= 500
    return isinstance(exc, (requests.Timeout, requests.ConnectionError, TimeoutError))


def _short_error(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None):
        if resp.status_code in (429, 999):
            return f"HTTP {resp.status_code}, rate-limited"
        return f"HTTP {resp.status_code}"
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def dashboard_url(env: dict[str, str]) -> str | None:
    """The settings/history page on GitHub Pages, when running from GitHub."""
    owner, _, repo = env.get("GITHUB_REPOSITORY", "").partition("/")
    return f"https://{owner}.github.io/{repo}/" if owner and repo else None


def run_career(cfg: Config, args: argparse.Namespace) -> int:
    """`--career`: rebuild the career report from the saved resume and history; no scraping, no e-mail."""
    env = dict(os.environ)
    if args.no_ai:
        env.update(AI_API_KEY="", AI_BASE_URL="")
    today = datetime.now(SRI_LANKA_TZ).date()
    history = History.open(Path(args.state).parent, env)
    if not history.enabled:
        log.error("%s", history.note)
        return 1
    report = coach.run(cfg, env, history, today, save=not args.dry_run)
    if report is None:
        log.error("No resume saved yet – paste or upload one on the dashboard's Coach tab, then run this again.")
        return 1
    for note in report["notes"]:
        log.info("%s", note)
    return 0


def run_prepare(cfg: Config, args: argparse.Namespace) -> int:
    env = dict(os.environ)
    today = datetime.now(SRI_LANKA_TZ).date()
    history = History.open(Path(args.state).parent, env)
    result = coach.prepare(cfg, env, history, args.prepare.strip(), today, save=not args.dry_run)
    if result is not None and args.dry_run:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0 if result is not None else 1


def _redact(text: str, env: dict[str, str]) -> str:
    for key in ("TELEGRAM_BOT_TOKEN", "SMTP_PASSWORD", "AI_API_KEY", "DASHBOARD_PASSWORD", "IMAP_PASSWORD", "JOOBLE_API_KEY"):
        if env.get(key):
            text = text.replace(env[key], "***")
    return text


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        cfg = load_config(args.config)
        apply_overrides(cfg, args)
    except (ConfigError, OSError) as exc:
        log.error("Config problem: %s", exc)
        return 2

    if args.list:
        print_options(cfg)
        return 0
    if args.probe:
        from . import probe
        probe.run(args.probe)
        return 0
    if args.career:
        return run_career(cfg, args)
    if args.prepare:
        return run_prepare(cfg, args)

    log.info("Sub-fields: %s", ", ".join(s.key for s in cfg.enabled_subfields) or "(none)")
    log.info("Levels:     %s%s", ", ".join(lv.key for lv in cfg.enabled_levels) or "(none)",
             " + unknown" if cfg.include_unknown_level else "")
    if cfg.qualifications:
        log.info("Education:  %s%s", ", ".join(q.key for q in cfg.enabled_qualifications) or "(none)",
                 " + not stated" if cfg.include_unknown_qualification else "")

    env = dict(os.environ)
    now = datetime.now(SRI_LANKA_TZ)
    today = now.date()
    data_dir = Path(args.state).parent
    schedule = Schedule(data_dir / "schedule.json")
    # A scheduled run is either the day's first (the "digest": summary, reminders, "nothing new" notice) or a
    # quick check in between that only messages you when it finds something and skips slow sites.
    quick = args.auto and not schedule.digest_due(now, cfg.schedule.digest_hour)
    if args.auto:
        log.info("%s", "Quick check (the daily summary is sent by the first run after %02d:00)" % cfg.schedule.digest_hour
                 if quick else "Daily run")

    all_jobs, results = scrape(cfg, env, schedule, now, full=not quick)
    matched = select_jobs(all_jobs, cfg)
    store = SeenStore(args.state)

    # Open the adverts themselves (text, posters, PDFs), then filter again with what they say.
    read_stats = None
    if cfg.postings.enabled and not args.no_read:
        cache = postings.PostingCache(data_dir / "postings_cache.json")
        to_read = postings.pick(all_jobs, matched, (lambda j: True) if args.all else store.is_new, cfg)
        vision = None if args.no_ai else ai.poster_reader(cfg, env)
        read_stats = postings.enrich(to_read, cache, cfg, today, vision=vision)
        log.info("%s", read_stats.summary or "No new adverts to read")
        if not args.dry_run:
            cache.prune(today)
            cache.save()
        matched = select_jobs(all_jobs, cfg)

    new = matched if args.all else [j for j in matched if store.is_new(j)]
    log.info("%d jobs scanned, %d match your filters, %d new", len(all_jobs), len(matched), len(new))
    history = History.open(data_dir, env)  # encrypted with DASHBOARD_PASSWORD; empty without it
    history.import_legacy(data_dir, cfg)
    if history.note:
        log.info("%s", history.note)

    shown, ai_note, outcome = new, None, None
    if cfg.ai.enabled and not args.no_ai:
        if env.get("AI_API_KEY") or env.get("AI_BASE_URL"):
            outcome = ai.review(new, cfg, env, profile_extra=coach.digest_for_review(history, cfg))
            ai_note = outcome.summary
            shown = [j for j in new if not ai.is_hidden(j, cfg)]
            log.info("%s", ai_note)
        else:
            log.info("AI review is on but AI_API_KEY isn't set – skipping it")

    record = stats.run_record(today, results, all_jobs, matched, new, shown, cfg, outcome, read_stats)
    runs = history.merged_runs(record)
    tips = suggestions.generate(runs, cfg, today)
    weekly_day = not quick and cfg.weekly_summary in ("daily", today.strftime("%A").lower())
    reminders = [] if quick else coach.closing_soon(history, today)
    stats_line = f"{len(all_jobs)} jobs scanned · {len(matched)} open matches · {len(new)} new · {len(shown)} sent"
    report = Report(
        jobs=shown, sources=results, cfg=cfg, day=today, ai_note=ai_note, stats_line=stats_line,
        read_note=read_stats.summary if read_stats else None,
        history_note=history.note if weekly_day else None, dashboard_url=dashboard_url(env),
        weekly=(stats.week_summary(runs, cfg, today) + coach.weekly_lines(history, cfg)) if weekly_day else [],
        reminders=reminders, at=now.strftime("%H:%M") if quick else None,
        tips=[t["text"] for t in tips if t["kind"] != "insight"][:3] if weekly_day else [],
    )
    checked = [r for r in results if not r.skipped]
    all_sources_failed = bool(checked) and all(r.error for r in checked)

    if args.dry_run:
        print(report.email_text())
        return 1 if all_sources_failed else 0

    channels = notifiers.configured_channels(env)
    if not channels:
        print(report.email_text())
        log.warning("No notification channel configured (set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
                    "or SMTP_USERNAME/SMTP_PASSWORD/EMAIL_TO). Jobs were printed above and NOT "
                    "marked as sent.")
        return 1 if all_sources_failed else 0

    delivered = False
    if shown or (not quick and (cfg.send_when_empty or reminders)):
        for name, channel in channels.items():
            try:
                channel.send(report, env)
                delivered = True
                log.info("Sent via %s", name)
            except Exception as exc:
                log.error("Sending via %s failed: %s", name, _redact(str(exc), env))
    else:
        delivered = True

    if delivered:
        for job in new:
            store.add(job, today)
        store.prune(cfg.remember_days, today)
        store.save()
        if not quick:
            schedule.mark_digest(now)
        schedule.save()
        # Quiet quick runs change nothing, so they commit nothing: the history is only rewritten when there are
        # new jobs, or a site's status differs from what the day's record already says.
        previous = history.runs[-1] if history.runs and history.runs[-1].get("date") == record["date"] else None
        if not quick or new or previous is None or stats.status_signature(previous) != stats.status_signature(record):
            history.add_run(record)
            history.suggestions = tips
            history.add_jobs(today, new, {j.uid for j in new} - {j.uid for j in shown}, cfg)
            history.backfill_skills(cfg)
            history.save()
        if not quick and history.enabled and coach.weekly_due(cfg, today):  # never lets the coach break the daily run
            try:
                coach.run(cfg, {**env, **({"AI_API_KEY": "", "AI_BASE_URL": ""} if args.no_ai else {})}, history, today)
            except Exception as exc:
                log.warning("Career coach failed: %s", _redact(str(exc), env)[:200])

    if not delivered or all_sources_failed:
        return 1
    return 0


def main() -> None:
    sys.exit(run())
