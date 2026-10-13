import csv
from datetime import date, timedelta

from jobot import stats, suggestions
from jobot.models import Job
from jobot.report import Report, SourceResult

TODAY = date(2026, 10, 13)


def job(title, sid=None, **kw):
    return Job(source=kw.pop("source", "topjobs.lk"), source_id=sid or title, title=title,
               url="https://x/" + title, **kw)


def test_open_jobs_count_switched_off_subfields(cfg):
    cfg.only_subfields(["electronics"])  # MEP & lifts switched off
    jobs = [job("MEP Engineer"), job("Lift Technician"), job("Senior Embedded Engineer"),
            job("Embedded Engineer"), job("Accountant")]
    by_sub, level_filtered = stats.open_jobs_by_subfield(jobs, cfg)
    assert by_sub["building_services"] == 1 and by_sub["lifts"] == 1 and by_sub["electronics"] == 2
    assert dict(level_filtered) == {"senior": 1}  # matches an ON sub-field but senior is off


def test_run_record_and_store(tmp_path, cfg):
    new = [job("Embedded Engineer", subfields=["electronics"], level="entry", company="ChipCo")]
    sources = [SourceResult("topjobs.lk", 10), SourceResult("LinkedIn", error="HTTP 429"),
               SourceResult("XpressJobs", skipped="blocks GitHub")]
    record = stats.run_record(TODAY, sources, new, new, new, [], cfg)
    assert record["sources"] == {"topjobs.lk": {"scanned": 10}, "LinkedIn": {"error": "HTTP 429"},
                                 "XpressJobs": {"skipped": "blocks GitHub"}}
    assert record["new_by_subfield"] == {"electronics": 1} and record["sent"] == 0
    assert record["top_companies"] == [("ChipCo", 1)]
    store = stats.StatsStore(tmp_path / "stats.json")
    store.add(record); store.suggestions = [{"id": "x"}]; store.save()
    again = stats.StatsStore(tmp_path / "stats.json")
    assert again.runs[0]["date"] == "2026-10-13" and again.suggestions == [{"id": "x"}]


def test_jobs_log_appends_and_marks_hidden(tmp_path, cfg):
    a = job("Embedded Engineer", subfields=["electronics"], level="entry", ai_score=9, ai_reason="fits")
    b = job("Sales Engineer", subfields=["technical_sales"], ai_score=2)
    path = tmp_path / "jobs_log.csv"
    stats.append_jobs_log(path, TODAY, [a, b], {b.uid}, cfg)
    stats.append_jobs_log(path, TODAY, [job("Network Engineer", subfields=["networking"])], set(), cfg)
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    assert [(r["title"], r["status"]) for r in rows] == [
        ("Embedded Engineer", "sent"), ("Sales Engineer", "hidden by AI"), ("Network Engineer", "sent")]
    assert rows[0]["subfields"] == "Electronics / Embedded / Hardware"
    assert rows[0]["level"] == "Entry level / Fresh graduate" and rows[0]["ai_score"] == "9"


def run(day_offset=0, **kw):
    base = {"date": (TODAY - timedelta(days=day_offset)).isoformat(), "sources": {}, "new": 1, "sent": 1,
            "open_by_subfield": {}, "open_level_filtered": {}, "top_companies": [], "ai": None}
    base.update(kw)
    return base


def test_suggestions(cfg):
    cfg.only_subfields(["electronics", "general"])
    runs = [run(4 - i, sources={"LinkedIn": {"error": "HTTP 429"}}) for i in range(4)]
    runs.append(run(0, open_by_subfield={"building_services": 12, "electronics": 3, "general": 9},
                    open_level_filtered={"senior": 7}, top_companies=[["CEB", 4]],
                    sources={"LinkedIn": {"error": "HTTP 429"}}))
    tips = {t["id"]: t for t in suggestions.generate(runs, cfg, TODAY)}
    assert tips["enable_subfield:building_services"]["action"] == {
        "type": "enable_subfield", "key": "building_services", "label": "Switch on Building Services / MEP (Electrical)"}
    assert "12 open jobs" in tips["enable_subfield:building_services"]["text"]
    assert tips["enable_level:senior"]["action"]["key"] == "senior"
    assert tips["failing:LinkedIn"]["kind"] == "warning"
    assert "General Electrical / Electronic (9)" in tips["busiest"]["text"]
    assert "CEB (4)" in tips["hiring"]["text"]
    assert "drought" not in tips


def test_ai_and_drought_suggestions(cfg):
    cfg.ai.enabled, cfg.ai.min_score = True, 5
    runs = [run(i, new=0, ai={"checked": 10, "hidden": 9, "error": None}) for i in range(5)][::-1]
    tips = {t["id"]: t for t in suggestions.generate(runs, cfg, TODAY)}
    assert tips["ai_threshold"]["action"] == {"type": "set_ai_min_score", "value": 4, "label": "Hide below 4 instead"}
    assert "drought" in tips


def test_report_top_picks_weekly_and_tips(cfg):
    jobs = [job("Embedded Engineer", subfields=["electronics"], level="entry", ai_score=9, company="ChipCo"),
            job("Network Engineer", subfields=["networking"], ai_score=6)]
    weekly = stats.week_summary([run(1, new=3, sent=2, new_by_subfield={"electronics": 3},
                                     new_by_site={"ITPro.lk": 3})], cfg, TODAY)
    report = Report(jobs, [SourceResult("topjobs.lk", 5)], cfg, TODAY, stats_line="5 jobs scanned · 2 new",
                    weekly=weekly, tips=["Switch on Lifts & Escalators"])
    tg = "\n".join(report.telegram_messages())
    assert "Top picks for you" in tg and "Embedded Engineer</a> – ChipCo (9/10)" in tg
    assert "Network Engineer</a>" not in tg.split("Top picks for you")[1].split("📂")[0]
    assert "Your week" in tg and "3 new matching jobs in the last 7 days" in tg
    assert "Most new jobs: Electronics / Embedded / Hardware (3)" in tg
    assert "💡" in tg and "5 jobs scanned · 2 new" in tg
    assert "Top picks for you" in report.email_html() and "Suggestions" in report.email_text()
