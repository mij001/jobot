from datetime import date

import pytest

from jobot.config import ConfigError, parse_config
from jobot.models import Job
from jobot.ordering import group_jobs, sort_jobs, to_date
from jobot.report import Report, SourceResult

TODAY = date(2026, 10, 13)


def job(title, **kw):
    kw.setdefault("subfields", ["general"])
    return Job(source=kw.pop("source", "topjobs.lk"), source_id=title, title=title, url="https://x/" + title, **kw)


@pytest.mark.parametrize("text,expected", [
    ("2026-10-08", date(2026, 10, 8)),
    ("2026-10-08T10:00:00Z", date(2026, 10, 8)),
    ("13 hours", TODAY),
    ("2 days", date(2026, 10, 11)),
    ("1 week ago", date(2026, 10, 6)),
    ("bump_up", TODAY),
    ("", None),
    ("soon", None),
])
def test_to_date(text, expected):
    assert to_date(text, TODAY) == expected


def test_sort_orders():
    a = job("Alpha", company="Zeta", posted="2026-10-01", closing="2026-10-20", ai_score=5)
    b = job("Bravo", company="Acme", posted="2 days", closing="2026-10-15", ai_score=9)
    c = job("Charlie", company="", posted="", closing="2026-10-01")  # closed already, no score
    titles = lambda js: [j.title for j in js]  # noqa: E731
    assert titles(sort_jobs([a, b, c], "newest", TODAY)) == ["Bravo", "Alpha", "Charlie"]
    assert titles(sort_jobs([a, b, c], "closing_soon", TODAY)) == ["Bravo", "Alpha", "Charlie"]
    assert titles(sort_jobs([a, b, c], "company", TODAY)) == ["Bravo", "Alpha", "Charlie"]
    assert titles(sort_jobs([c, b, a], "title", TODAY)) == ["Alpha", "Bravo", "Charlie"]
    assert titles(sort_jobs([a, c, b], "best_match", TODAY)) == ["Bravo", "Alpha", "Charlie"]


def test_group_by_options(cfg):
    jobs = [job("A", level="entry", subfields=["power"]), job("B", source="Rooster", subfields=["telecom"]),
            job("C", level="internship", subfields=["power", "general"])]
    cfg.group_by = "level"
    assert [g for g, _ in group_jobs(jobs, cfg, TODAY)] == [
        "Internship / Trainee", "Entry level / Fresh graduate", "Level not stated"]
    cfg.group_by = "subfield"
    assert [(g, [j.title for j in js]) for g, js in group_jobs(jobs, cfg, TODAY)] == [
        ("Power & Energy", ["A", "C"]), ("Telecommunication", ["B"])]
    cfg.group_by = "site"
    assert [g for g, _ in group_jobs(jobs, cfg, TODAY)] == ["topjobs.lk", "Rooster"]
    cfg.group_by = "none"
    [(label, items)] = group_jobs(jobs, cfg, TODAY)
    assert label is None and len(items) == 3


def test_ungrouped_report_has_no_headings(cfg):
    cfg.group_by = "none"
    report = Report([job("Embedded Engineer", level="entry")], [SourceResult("x", 1)], cfg, TODAY)
    assert "📂" not in report.telegram_messages()[0]
    assert "==" not in report.email_text()


def test_bad_option_is_rejected():
    with pytest.raises(ConfigError, match="order_by"):
        parse_config({"subfields": {"x": {"keywords": ["a"]}}, "notify": {"order_by": "random"}})
