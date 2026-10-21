"""Parallel fetching, quick vs daily runs, the day's merged statistics and the extra job channels."""

import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
import requests

from jobot import main as jobot_main
from jobot import stats
from jobot.http import Http, SourceTimeout
from jobot.models import Job
from jobot.report import Report, SourceResult
from jobot.schedule import Schedule
from jobot.sources import jooble, mailbox
from jobot.swarm import gather, parallel_map

from test_pipeline import FakeSource, fake_env  # noqa: F401  (fixture)

SL = timezone(timedelta(hours=5, minutes=30))


def job(i, **kw):
    return Job(source="S", source_id=str(i), title=f"Engineer {i}", url=f"https://s/{i}", **kw)


# -- the swarm ------------------------------------------------------------------------------------------------

def test_parallel_map_runs_side_by_side_keeps_order_and_isolates_errors():
    started = time.monotonic()

    def slow(i):
        time.sleep(0.3)
        if i == 2:
            raise ValueError("bad item")
        return i * 10

    out = parallel_map(slow, [1, 2, 3, 4], workers=4)
    assert time.monotonic() - started < 0.9  # four 0.3 s items in about 0.3 s, not 1.2 s
    assert [v for v, _ in out] == [10, None, 30, 40] and isinstance(out[1][1], ValueError)


class FakeHttp:
    def __init__(self):
        self.warnings = []
        self.clones = 0

    def clone(self):
        self.clones += 1
        return self

    def note(self, message):
        self.warnings.append(message)


def test_gather_keeps_what_worked_and_notes_what_did_not():
    http = FakeHttp()

    def fn(conn, item):
        if item == "b":
            raise requests.ConnectionError("timed out")
        return [job(item)]

    jobs = gather(http, ["a", "b", "c"], fn, workers=3, label=lambda i: f"area {i}")
    assert [j.source_id for j in jobs] == ["a", "c"]
    assert http.warnings == ["area b: ConnectionError: timed out"]
    with pytest.raises(requests.ConnectionError):  # every part failed: the site failed
        gather(http, ["x"], lambda c, i: (_ for _ in ()).throw(requests.ConnectionError("down")))


def test_gather_works_with_a_plain_connection():
    class Plain:  # a test double without clone/note
        pass
    assert [j.source_id for j in gather(Plain(), [1, 2], lambda c, i: [job(i)])] == ["1", "2"]


def test_http_gives_up_after_its_deadline():
    http = Http(delay=0, deadline=time.monotonic() - 1)
    with pytest.raises(SourceTimeout):
        http.get("https://example.invalid/")
    clone = Http(delay=0, deadline=time.monotonic() + 100).clone()
    assert clone.deadline is not None and clone.warnings == [] and clone.timeout == Http().timeout


# -- the schedule --------------------------------------------------------------------------------------------------

def test_schedule_digest_and_slow_site_timetable(tmp_path):
    path = tmp_path / "schedule.json"
    s = Schedule(path)
    morning, noon = datetime(2026, 10, 21, 6, 13, tzinfo=SL), datetime(2026, 10, 21, 12, 43, tzinfo=SL)
    assert not s.digest_due(morning, 8) and s.digest_due(noon, 8)  # not before digest_hour
    s.save()
    assert not path.exists()  # nothing changed: nothing written
    s.mark_digest(noon)
    s.mark_source("linkedin", noon)
    s.save()
    again = Schedule(path)
    assert not again.digest_due(noon + timedelta(hours=3), 8) and again.digest_due(noon + timedelta(days=1), 8)
    assert not again.source_due("linkedin", 3, noon + timedelta(hours=2))
    assert again.source_due("linkedin", 3, noon + timedelta(hours=2, minutes=45))  # a run that starts a bit early still counts
    assert again.source_due("other", 3, noon)
    before = path.read_text()
    again.save()
    assert path.read_text() == before


# -- scrape ----------------------------------------------------------------------------------------------------------

class Slow:
    NAME = "Slow"

    @staticmethod
    def fetch(http, opts, cfg):
        time.sleep(0.3)
        return [job(opts.get("id", 1))]


def test_scrape_reads_sites_at_once_names_instances_and_honours_cadence(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(jobot_main, "SOURCES", {"slow": Slow})
    cfg.sources = {"a": {"type": "slow", "name": "Site A", "id": 1}, "b": {"type": "slow", "name": "Site B", "id": 2},
                   "c": {"type": "slow", "name": "Site C", "id": 3, "every_hours": 3}}
    schedule = Schedule(tmp_path / "s.json")
    now = datetime(2026, 10, 21, 12, 13, tzinfo=SL)
    started = time.monotonic()
    jobs, results = jobot_main.scrape(cfg, {}, schedule, now, full=True)
    assert time.monotonic() - started < 0.8  # three sites in about the time of one
    assert [r.name for r in results] == ["Site A", "Site B", "Site C"] and len(jobs) == 3
    assert "c" in schedule.sources  # the slow site's timetable starts

    jobs, results = jobot_main.scrape(cfg, {}, schedule, now + timedelta(minutes=30), full=False)
    assert [r.name for r in results] == ["Site A", "Site B"]  # Site C isn't due again for 3 hours
    jobs, results = jobot_main.scrape(cfg, {}, schedule, now + timedelta(hours=3), full=False)
    assert [r.name for r in results] == ["Site A", "Site B", "Site C"]


def test_scrape_asks_a_timed_out_site_once_more_but_not_a_refusal(cfg, monkeypatch):
    calls = {"flaky": 0, "refused": 0}

    class Flaky:
        NAME = "Flaky"

        @staticmethod
        def fetch(http, opts, cfg):
            calls["flaky"] += 1
            if calls["flaky"] == 1:
                raise requests.ReadTimeout("slow")
            return [job(1)]

    class Refused:
        NAME = "Refused"

        @staticmethod
        def fetch(http, opts, cfg):
            calls["refused"] += 1
            resp = requests.Response()
            resp.status_code = 403
            raise requests.HTTPError("no", response=resp)

    monkeypatch.setattr(jobot_main, "SOURCES", {"flaky": Flaky, "refused": Refused})
    cfg.sources = {"flaky": {}, "refused": {}}
    jobs, results = jobot_main.scrape(cfg, {})
    assert calls == {"flaky": 2, "refused": 1} and len(jobs) == 1
    assert results[0].error is None and results[1].error == "HTTP 403"
    cfg.schedule.retry_failed = False
    calls["flaky"] = 0
    assert jobot_main.scrape(cfg, {})[1][0].error is not None and calls["flaky"] == 1


def test_scrape_skips_sites_that_need_a_secret_that_is_missing(cfg, monkeypatch):
    monkeypatch.setattr(jobot_main, "SOURCES", {"jooble": jooble})
    cfg.sources = {"jooble": {}}
    jobs, [result] = jobot_main.scrape(cfg, {})
    assert jobs == [] and "JOOBLE_API_KEY" in result.skipped and not result.error


# -- quick runs vs the daily digest ------------------------------------------------------------------------------------

def freeze(monkeypatch, when):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return when.astimezone(tz) if tz else when
    monkeypatch.setattr(jobot_main, "datetime", Frozen)


def test_quick_runs_only_message_for_new_jobs_and_the_first_run_after_the_digest_hour_sends_the_summary(fake_env, monkeypatch):
    config, state, sent = fake_env
    args = ["--config", str(config), "--state", str(state), "--auto"]
    freeze(monkeypatch, datetime(2026, 10, 21, 6, 13, tzinfo=SL))
    assert jobot_main.run(args) == 0  # 06:13: before 08:00, so a quick check
    assert [j.title for j in sent[0].jobs] == ["Embedded Engineer"] and sent[0].at == "06:13"
    assert "06:13" in sent[0].title

    freeze(monkeypatch, datetime(2026, 10, 21, 6, 43, tzinfo=SL))
    jobot_main.run(args)
    assert len(sent) == 1  # nothing new: no "no new jobs" message from a quick run

    freeze(monkeypatch, datetime(2026, 10, 21, 8, 13, tzinfo=SL))
    jobot_main.run(args)
    assert len(sent) == 2 and sent[1].jobs == [] and sent[1].at is None  # the daily run says so
    assert json.loads((state.parent / "schedule.json").read_text())["digest"] == "2026-10-21"

    freeze(monkeypatch, datetime(2026, 10, 21, 8, 43, tzinfo=SL))
    jobot_main.run(args)
    assert len(sent) == 2  # only one digest a day
    freeze(monkeypatch, datetime(2026, 10, 22, 9, 13, tzinfo=SL))
    jobot_main.run(args)
    assert len(sent) == 3  # and the next day's first run is a digest again


def test_a_run_without_auto_is_always_a_full_run(fake_env, monkeypatch):
    config, state, sent = fake_env
    freeze(monkeypatch, datetime(2026, 10, 21, 3, 0, tzinfo=SL))
    jobot_main.run(["--config", str(config), "--state", str(state)])
    jobot_main.run(["--config", str(config), "--state", str(state)])
    assert len(sent) == 2 and sent[1].jobs == []  # manual runs keep the old behaviour


def test_quiet_quick_runs_change_no_files(fake_env, monkeypatch):
    config, state, sent = fake_env
    args = ["--config", str(config), "--state", str(state), "--auto"]
    freeze(monkeypatch, datetime(2026, 10, 21, 6, 13, tzinfo=SL))
    jobot_main.run(args)
    snapshot = {p.name: p.read_text() for p in state.parent.iterdir() if p.is_file()}
    freeze(monkeypatch, datetime(2026, 10, 21, 6, 43, tzinfo=SL))
    jobot_main.run(args)
    assert {p.name: p.read_text() for p in state.parent.iterdir() if p.is_file()} == snapshot  # nothing to commit


# -- the day's statistics ------------------------------------------------------------------------------------------------

def record(**kw):
    base = {"date": "2026-10-21", "sources": {"A": {"scanned": 100}, "B": {"error": "HTTP 500"}, "C": {"skipped": "x"}},
            "scanned": 100, "matched": 10, "new": 2, "sent": 1, "new_by_subfield": {"general": 2}, "new_by_level": {"entry": 2},
            "new_by_qualification": {}, "new_by_site": {"A": 2}, "open_by_subfield": {"general": 10}, "ai": {"checked": 2, "hidden": 1, "error": None},
            "postings": {"opened": 3, "cached": 1, "posters": 1, "pdfs": 0, "ai": 0, "failed": 0, "left": 5}}
    return {**base, **kw}


def test_runs_of_one_day_merge_into_one_record():
    first = record()
    second = record(sources={"A": {"error": "timeout"}, "B": {"scanned": 40}, "C": {"skipped": "x"}}, scanned=60, matched=6,
                    new=1, sent=1, new_by_subfield={"telecom": 1}, new_by_site={"B": 1}, open_by_subfield={"telecom": 4},
                    ai={"checked": 1, "hidden": 0, "error": None}, postings={"opened": 1, "cached": 0, "posters": 0, "pdfs": 1, "ai": 0, "failed": 0, "left": 2})
    merged = stats.merge_runs(first, second)
    assert merged["runs"] == 2 and merged["new"] == 3 and merged["sent"] == 2
    assert merged["new_by_subfield"] == {"general": 2, "telecom": 1} and merged["new_by_site"] == {"A": 2, "B": 1}
    assert merged["scanned"] == 100 and merged["open_by_subfield"] == {"general": 10}  # the fuller run's snapshot
    assert merged["sources"]["A"] == {"scanned": 100}  # read once that day: counts as read
    assert merged["sources"]["B"] == {"scanned": 40}   # failed first, worked later
    assert merged["sources"]["C"] == {"skipped": "x"}
    assert merged["ai"] == {"checked": 3, "hidden": 1, "error": None}
    assert merged["postings"]["opened"] == 4 and merged["postings"]["left"] == 2
    assert stats.status_signature(merged) == {"A": "ok", "B": "ok", "C": "skipped"}


# -- the extra channels --------------------------------------------------------------------------------------------------

def alert_mail(sender, html):
    msg = EmailMessage()
    msg["From"], msg["Subject"], msg["Date"] = sender, "New jobs for you", "Tue, 20 Oct 2026 07:00:00 +0530"
    msg.set_content("plain version")
    msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


def test_alert_emails_become_jobs():
    html = """<html><body>
      <table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4477000001/?trackingId=abc&amp;refId=x">Electrical Engineer</a><br>Acme Power · Colombo</td></tr>
      <tr><td><a href="https://www.linkedin.com/comm/jobs/view/4477000001/?trackingId=other">Electrical Engineer</a></td></tr>
      <tr><td><a href="https://www.linkedin.com/comm/jobs/view/4477000002/">Automation Engineer - Trainee</a></td></tr>
      <tr><td><a href="https://www.linkedin.com/comm/jobs/search/?x=1">See all jobs</a></td></tr>
      <tr><td><a href="https://www.linkedin.com/e/v2?unsubscribe=1">Unsubscribe</a></td></tr></table></body></html>"""
    jobs = mailbox.parse_message(alert_mail("LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", html), ["linkedin.com", "xpress.jobs"])
    assert [j.title for j in jobs] == ["Electrical Engineer", "Automation Engineer - Trainee"]  # one per vacancy, links like "See all jobs" skipped
    assert jobs[0].source_id == "4477000001" and "Acme Power" in jobs[0].company and jobs[0].posted == "2026-10-20"
    assert jobs[0].source == "Email alert (linkedin.com)"
    assert mailbox.parse_message(alert_mail("Someone <x@evil.example>", html), ["linkedin.com"]) == []  # only the senders you list


def test_alert_emails_unwrap_tracking_links():
    html = '<a href="https://click.example.com/r?url=https%3A%2F%2Fxpress.jobs%2Fjob%2Felectrical-engineer-123&amp;s=1">Electrical Engineer – Colombo</a>'
    [j] = mailbox.parse_message(alert_mail("XpressJobs <alerts@xpress.jobs>", html), ["xpress.jobs"])
    assert j.url == "https://xpress.jobs/job/electrical-engineer-123"


def test_mailbox_needs_credentials_and_senders():
    assert "IMAP_USERNAME" in mailbox.missing({})
    assert mailbox.missing({"SMTP_USERNAME": "me@x", "SMTP_PASSWORD": "pw"}) is None
    with pytest.raises(RuntimeError, match="senders"):
        mailbox.fetch(None, {"_env": {"IMAP_USERNAME": "a", "IMAP_PASSWORD": "b"}}, None)


class FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_jooble_maps_results_and_pages():
    pages = {"1": [{"id": 5, "title": "<b>Electrical</b> Engineer", "link": "https://jooble.org/desc/5", "company": "Acme", "location": "Colombo",
                    "snippet": "Design &nbsp;<b>power</b> systems", "updated": "2026-10-20T00:00:00.0000000", "salary": ""}] + [
                {"id": 100 + i, "title": f"T{i}", "link": f"https://jooble.org/desc/{100 + i}"} for i in range(9)],
             "2": []}

    class FakeJoobleHttp(FakeHttp):
        def post(self, url, json):
            assert url.endswith("/KEY") and json["location"] == "Sri Lanka"
            return FakeResp({"jobs": pages[json["page"]]})

    jobs = jooble.fetch(FakeJoobleHttp(), {"_env": {"JOOBLE_API_KEY": "KEY"}, "queries": ["electrical engineer"]}, None)
    assert len(jobs) == 10 and jobs[0].title == "Electrical Engineer" and jobs[0].description == "Design power systems"
    assert jobs[0].posted == "2026-10-20" and jobs[0].company == "Acme"
    assert jooble.missing({}) and jooble.missing({"JOOBLE_API_KEY": "k"}) is None


def test_quick_report_title_has_the_time(cfg):
    r = Report([job(1)], [SourceResult("S", 1)], cfg, date(2026, 10, 21), at="14:43")
    assert r.title == "1 new EEE job in Sri Lanka – 21 Oct 2026, 14:43"
    r.sources = [SourceResult("S", 5, warnings=["area CCE: ReadTimeout"])]
    assert "S: 5 scanned (partly failed: area CCE: ReadTimeout)" in r.source_summary()


# -- sites that block GitHub, pages, near misses ---------------------------------------------------------------------

def test_blocked_sites_run_when_jobot_runs_on_your_own_runner(cfg, monkeypatch):
    monkeypatch.setattr(jobot_main, "SOURCES", {"slow": Slow})
    cfg.sources = {"x": {"type": "slow", "name": "Blocked", "skip_on_github_actions": True}}
    jobs, [result] = jobot_main.scrape(cfg, {"GITHUB_ACTIONS": "true"})
    assert jobs == [] and "blocks GitHub" in result.skipped
    jobs, [result] = jobot_main.scrape(cfg, {"GITHUB_ACTIONS": "true", "JOBOT_ALLOW_BLOCKED": "1"})
    assert len(jobs) == 1 and result.skipped is None


class PageHttp(FakeHttp):
    """A site with a robots.txt, a paged listing and a feed."""

    def __init__(self, pages, robots=""):
        super().__init__()
        self.pages, self.robots, self.requested = pages, robots, []

    def get(self, url, params=None, timeout=None):
        self.requested.append((url, (params or {}).get("page")))
        text = self.robots if url.endswith("/robots.txt") else self.pages[(url, (params or {}).get("page"))]

        class R:
            pass
        r = R()
        r.text = text
        return r


def test_pages_source_follows_robots_pages_and_feeds():
    from jobot.sources import company_pages
    listing = '<a href="/v/1">Lecturer in Electrical Engineering</a><a href="/v/2">Technical Officer (Electronics)</a>'
    feed = '<?xml version="1.0"?><rss version="2.0"><channel><item><title>Electrical Engineer – Acme</title><link>https://acme.lk/j/9</link></item></channel></rss>'
    pages = {("https://uni.lk/vacancies", None): listing, ("https://uni.lk/vacancies", 2): "<p>nothing more</p>",
             ("https://acme.lk/feed", None): feed}
    http = PageHttp(pages, robots="User-agent: *\nDisallow: /private/")
    opts = {"pages": [{"url": "https://uni.lk/vacancies", "name": "University", "pages": 3}, {"url": "https://acme.lk/feed", "name": "Acme"}]}
    jobs = company_pages.fetch(http, opts, None)
    assert sorted(j.title for j in jobs) == ["Electrical Engineer – Acme", "Lecturer in Electrical Engineering", "Technical Officer (Electronics)"]
    assert ("https://uni.lk/vacancies", 2) in http.requested and ("https://uni.lk/vacancies", 3) not in http.requested  # stops at an empty page

    blocked = PageHttp({}, robots="User-agent: *\nDisallow: /vacancies")
    with pytest.raises(RuntimeError, match="robots.txt"):
        company_pages.fetch(blocked, {"pages": [{"url": "https://uni.lk/vacancies", "name": "University"}]}, None)
    assert not [r for r in blocked.requested if not r[0].endswith("robots.txt")]  # never visited the page itself


def test_near_misses_say_what_your_settings_dropped(cfg):
    cfg.only_subfields(["general"])  # power & the rest off
    cfg.only_levels(["entry", "internship"])
    jobs = [
        Job(source="S", source_id="1", title="Power Systems Engineer", url="https://s/1", company="Grid Co", posted="2026-10-20"),
        Job(source="S", source_id="2", title="Senior Electrical Engineer", url="https://s/2", company="Big Co", posted="2026-10-19",
            description="10 years of experience"),
        Job(source="S", source_id="3", title="Electrical Engineer", url="https://s/3", company="Fits Co", posted="2026-10-21"),  # fine: sent normally
        Job(source="S", source_id="4", title="Chef", url="https://s/4"),
        Job(source="S", source_id="5", title="Power Systems Engineer", url="https://s/5", company="Grid Co"),  # same vacancy elsewhere
    ]
    missed = stats.near_misses(jobs, cfg)
    assert [(j.source_id, why) for j, why in missed] == [
        ("1", "Power & Energy is switched off"), ("2", "Senior level is switched off")] or \
        [(j.source_id) for j, _ in missed] == ["1", "2"]
    assert all(j.title != "Chef" and j.source_id != "3" for j, _ in missed) and len(missed) == 2
    assert stats.near_misses(jobs, cfg, limit=1)[0][0].source_id == "1"  # newest first


def test_quick_runs_ask_for_fewer_pages(cfg, monkeypatch):
    seen = []

    class Pages:
        NAME = "Pages"

        @staticmethod
        def fetch(http, opts, cfg):
            seen.append((opts.get("max_pages"), opts.get("query_pages")))
            return []

    monkeypatch.setattr(jobot_main, "SOURCES", {"p": Pages})
    cfg.sources = {"p": {"max_pages": 4, "quick_pages": 1, "query_pages": 2, "quick_query_pages": 1}, "q": {"type": "p", "max_pages": 3}}
    jobot_main.scrape(cfg, {}, full=True)
    jobot_main.scrape(cfg, {}, full=False)
    assert seen == [(4, 2), (3, None), (1, 1), (3, None)]  # a site without quick_pages keeps its setting


def test_a_slow_site_cannot_run_past_the_whole_run_budget(cfg, monkeypatch):
    class Hangs:
        NAME = "Hangs"

        @staticmethod
        def fetch(http, opts, cfg):
            while True:  # a site that keeps asking for more pages
                http._wait()

    monkeypatch.setattr(jobot_main, "SOURCES", {"hangs": Hangs})
    cfg.sources = {"hangs": {"delay_seconds": 0.05}}
    cfg.schedule.run_seconds, cfg.schedule.site_seconds = 60, 1  # the site's own budget is the shorter one here
    started = time.monotonic()
    jobs, [result] = jobot_main.scrape(cfg, {})
    assert time.monotonic() - started < 5 and jobs == [] and "took too long" in result.error
    cfg.schedule.run_seconds, cfg.schedule.site_seconds = 1, 60  # and the run's budget caps a generous site budget
    started = time.monotonic()
    jobot_main.scrape(cfg, {})
    assert time.monotonic() - started < 5
