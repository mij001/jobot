"""Report formatting, the seen-jobs store and the end-to-end CLI run."""

import json
from datetime import date
from pathlib import Path

import pytest
import requests
import yaml

from jobot import main as jobot_main
from jobot.config import ConfigError
from jobot.models import Job
from jobot.report import TELEGRAM_LIMIT, Report, SourceResult
from jobot.storage import SeenStore


def make_job(i, **kw):
    defaults = dict(source="topjobs.lk", source_id=str(i), title=f"Electrical Engineer {i}",
                    url=f"https://example.lk/{i}", company=f"Company {i}", subfields=["general"])
    defaults.update(kw)
    return Job(**defaults)


def test_telegram_messages_split_and_escape(cfg):
    jobs = [make_job(i, title=f"Electrical <Engineer> & Co #{i}", level="entry") for i in range(80)]
    report = Report(jobs, [SourceResult("topjobs.lk", 300)], cfg, date(2026, 10, 12))
    messages = report.telegram_messages()
    assert len(messages) > 1
    assert all(len(m) <= TELEGRAM_LIMIT for m in messages)
    joined = "\n".join(messages)
    assert "&lt;Engineer&gt; &amp; Co" in joined
    assert joined.count("https://example.lk/") == 80
    assert "80 new EEE jobs" in messages[0]


def test_empty_report_mentions_failed_sources(cfg):
    report = Report([], [SourceResult("LinkedIn", error="HTTP 429, rate-limited")], cfg, date(2026, 10, 12))
    assert report.title.startswith("No new EEE jobs")
    assert "LinkedIn: failed (HTTP 429, rate-limited)" in report.email_text()


def test_seen_store_roundtrip_and_prune(tmp_path):
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    a, b = make_job(1), make_job(2)
    store.add(a, date(2026, 1, 1))
    store.add(b, date(2026, 10, 1))
    store.prune(60, date(2026, 10, 12))
    store.save()

    again = SeenStore(path)
    assert again.is_new(a) and not again.is_new(b)
    # Same vacancy on another site is not new either.
    assert not again.is_new(make_job(99, source="XpressJobs", title=b.title, company=b.company))


def test_overrides_reject_unknown_keys(cfg):
    with pytest.raises(ConfigError, match="Unknown sub-field"):
        cfg.only_subfields(["quantum"])
    with pytest.raises(ConfigError, match="Unknown experience level"):
        cfg.only_levels(["guru"])


class FakeSource:
    NAME = "FakeSite"

    @staticmethod
    def fetch(http, opts, cfg):
        return [
            Job(source="FakeSite", source_id="1", title="Embedded Engineer", url="https://f/1"),
            Job(source="FakeSite", source_id="2", title="Chef", url="https://f/2"),
        ]


class BrokenSource:
    NAME = "BrokenSite"

    @staticmethod
    def fetch(http, opts, cfg):
        raise RuntimeError("layout changed")


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    sent = []

    class FakeChannel:
        @staticmethod
        def send(report, env):
            sent.append(report)

    monkeypatch.setattr(jobot_main, "SOURCES", {"fake": FakeSource, "broken": BrokenSource})
    config = tmp_path / "config.yaml"
    raw = yaml.safe_load((Path(__file__).parent / "fixtures" / "default_config.yaml").read_text(encoding="utf-8"))
    raw["sources"] = {"fake": {}, "broken": {}}
    del raw["ai"], raw["notify"]  # defaults: no AI, plain messages
    config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(jobot_main.notifiers, "configured_channels", lambda env: {"fake": FakeChannel})
    monkeypatch.setattr(jobot_main.postings, "read_posting", fake_read_posting)
    ADVERTS.clear()
    return config, tmp_path / "seen.json", sent


ADVERTS: dict[str, str] = {}  # url -> advert text "read" from the posting
OPENED: list[str] = []


def fake_read_posting(http, url, read_posters=True, vision=None):
    OPENED.append(url)
    if url not in ADVERTS:
        raise requests.HTTPError(response=type("R", (), {"status_code": 404})())
    return jobot_main.postings.Posting(text=ADVERTS[url], via=["poster"])


def test_run_sends_new_jobs_once(fake_env):
    config, state, sent = fake_env
    args = ["--config", str(config), "--state", str(state)]

    assert jobot_main.run(args) == 0
    assert [j.title for j in sent[0].jobs] == ["Embedded Engineer"]
    assert any(s.error for s in sent[0].sources)  # broken site reported, not fatal
    assert "FakeSite:1" in json.loads(state.read_text())["ids"]

    assert jobot_main.run(args) == 0
    assert sent[1].jobs == []  # already sent yesterday


def test_dry_run_does_not_touch_state(fake_env, capsys):
    config, state, sent = fake_env
    assert jobot_main.run(["--config", str(config), "--state", str(state), "--dry-run"]) == 0
    assert "Embedded Engineer" in capsys.readouterr().out
    assert not state.exists() and not sent


def test_cli_level_override(fake_env):
    config, state, sent = fake_env
    jobot_main.run(["--config", str(config), "--state", str(state),
                    "--levels", "senior", "--exclude-unknown-level"])
    assert sent[0].jobs == []


def test_source_skipped_on_github_actions(cfg, monkeypatch):
    monkeypatch.setattr(jobot_main, "SOURCES", {"fake": FakeSource, "broken": BrokenSource})
    cfg.sources = {"fake": {}, "broken": {"skip_on_github_actions": True}}
    jobs, results = jobot_main.scrape(cfg, env={"GITHUB_ACTIONS": "true"})
    assert [j.source_id for j in jobs] == ["1", "2"]
    assert results[1].skipped and not results[1].error
    # Off GitHub, the source runs normally (and here fails).
    _, results = jobot_main.scrape(cfg, env={})
    assert results[1].error and not results[1].skipped


def test_ai_hidden_jobs_are_not_sent_but_remembered(fake_env, monkeypatch):
    config, state, sent = fake_env
    config.write_text(config.read_text(encoding="utf-8") + "\nai:\n  enabled: true\n  min_score: 5\n",
                      encoding="utf-8")
    monkeypatch.setenv("AI_API_KEY", "k")

    def fake_review(jobs, cfg, env, **kw):
        for j in jobs:
            j.ai_score, j.ai_reason = 2, "not a fit"
        return jobot_main.ai.ReviewResult(model="m", scored=len(jobs), hidden=len(jobs))

    monkeypatch.setattr(jobot_main.ai, "review", fake_review)
    assert jobot_main.run(["--config", str(config), "--state", str(state)]) == 0
    assert sent[0].jobs == []
    assert "1 hidden as poor fits" in sent[0].email_text()
    assert "FakeSite:1" in json.loads(state.read_text())["ids"]


def test_live_config_is_valid():
    """Whatever you saved in config.yaml (by hand or on the settings page) must load."""
    from jobot.config import load_config
    from jobot.sources import SOURCES
    cfg = load_config(jobot_main.ROOT / "config.yaml")
    assert set(cfg.sources) <= set(SOURCES)
    assert cfg.enabled_subfields and cfg.enabled_sources()


PASSWORD = "correct horse battery staple"


def open_history(state):
    from jobot.vault import Vault
    return Vault(state.parent / "history", PASSWORD)


def test_run_keeps_encrypted_history(fake_env, monkeypatch):
    config, state, sent = fake_env
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    args = ["--config", str(config), "--state", str(state)]
    jobot_main.run(["--dry-run", *args])
    assert not (state.parent / "history").exists()  # dry runs keep nothing
    jobot_main.run(args)
    jobot_main.run(args)

    folder = state.parent / "history"
    assert not (state.parent / "stats.json").exists() and not (state.parent / "jobs_log.csv").exists()
    assert "Embedded Engineer" not in "".join(p.read_text() for p in folder.iterdir())  # nothing readable
    vault = open_history(state)
    stats = vault.read("stats")
    assert [r["new"] for r in stats["runs"]] == [1, 0]
    assert stats["runs"][0]["sources"]["BrokenSite"]["error"].startswith("RuntimeError")
    assert isinstance(stats["suggestions"], list)
    [shard] = [n for n in vault.meta["shards"] if n.startswith("jobs-")]
    [entry] = vault.read(shard)
    assert entry["title"] == "Embedded Engineer" and entry["status"] == "sent" and entry["importance"] in ("good", "maybe")
    assert "jobs scanned" in sent[0].email_text()


def test_no_password_means_no_history(fake_env, monkeypatch):
    config, state, sent = fake_env
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    assert jobot_main.run(["--config", str(config), "--state", str(state)]) == 0
    assert not (state.parent / "history").exists() and not (state.parent / "stats.json").exists()
    assert "FakeSite:1" in json.loads(state.read_text())["ids"]  # the bot's own memory still works
    assert "History isn't being saved" in Report(**{**sent[0].__dict__, "history_note": jobot_main.History.open(
        state.parent, {}).note}).email_text()


def test_wrong_password_never_overwrites_history(fake_env, monkeypatch):
    config, state, sent = fake_env
    args = ["--config", str(config), "--state", str(state)]
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    jobot_main.run(args)
    before = {p.name: p.read_text() for p in (state.parent / "history").iterdir()}
    monkeypatch.setenv("DASHBOARD_PASSWORD", "something else")
    assert jobot_main.run(args) == 0  # the daily message still goes out
    assert {p.name: p.read_text() for p in (state.parent / "history").iterdir()} == before


def test_old_plaintext_stats_move_into_the_vault(fake_env, monkeypatch):
    config, state, sent = fake_env
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    (state.parent).mkdir(exist_ok=True)
    (state.parent / "stats.json").write_text(json.dumps(
        {"runs": [{"date": "2026-10-01", "new": 4, "sent": 4}], "suggestions": [{"id": "x"}]}))
    (state.parent / "jobs_log.csv").write_text(
        "date,status,site,title,company,location,subfields,level,ai_score,ai_reason,closing,url\n"
        "2026-10-01,sent,topjobs.lk,Power Engineer,Acme,Colombo,Power & Energy,Mid level,8,great,2026-10-20,https://t/1\n"
        "2026-09-30,hidden by AI,ikman.lk,Sales Engineer,Beta,,,not stated,2,no,,https://t/2\n")
    jobot_main.run(["--config", str(config), "--state", str(state)])
    assert not (state.parent / "stats.json").exists() and not (state.parent / "jobs_log.csv").exists()
    vault = open_history(state)
    assert [r["date"] for r in vault.read("stats")["runs"]] == ["2026-10-01", jobot_main.datetime.now(
        jobot_main.SRI_LANKA_TZ).date().isoformat()]
    [power] = vault.read("jobs-2026-10")[:1]
    assert (power["title"], power["importance"], power["level"]) == ("Power Engineer", "top", "mid")
    assert vault.read("jobs-2026-09")[0]["importance"] == "low"


class PosterSource:
    NAME = "PosterSite"

    @staticmethod
    def fetch(http, opts, cfg):
        return [  # list pages that only give a title – the advert is a poster
            Job(source="PosterSite", source_id="1", title="Project Engineer", url="https://p/1"),
            Job(source="PosterSite", source_id="2", title="Electrical Engineer", url="https://p/2"),
            Job(source="PosterSite", source_id="3", title="Civil Engineer", url="https://p/3"),
        ]


def test_run_reads_adverts_and_filters_by_qualification(fake_env, monkeypatch):
    config, state, sent = fake_env
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    monkeypatch.setattr(jobot_main, "SOURCES", {"fake": PosterSource})
    config.write_text(config.read_text(encoding="utf-8").replace("broken: {}", ""), encoding="utf-8")
    ADVERTS.update({
        "https://p/1": "Project Engineer\nBSc in Electrical Engineering\nPLC, SCADA and switchgear\n"
                       "Minimum 2 years experience\nE-mail CV to jobs@acme.lk",
        "https://p/2": "Electrical Engineer\nNDT / HND in Electrical Engineering",
    })
    OPENED.clear()
    args = ["--config", str(config), "--state", str(state)]
    assert jobot_main.run(args) == 0
    # Civil Engineer isn't opened at all; the diploma-only advert is dropped for a degree holder.
    assert OPENED == ["https://p/2", "https://p/1"]
    [job] = sent[0].jobs
    assert job.title == "Project Engineer" and job.qualifications == ["degree"] and job.min_years == 2
    assert job.contact == "jobs@acme.lk"
    text = sent[0].email_text()
    assert "Needs: Degree · 2+ yrs experience · read from poster" in text
    assert "Adverts read: 2 opened (2 posters via OCR)" in text
    cache = json.loads((state.parent / "postings_cache.json").read_text())
    assert set(cache) == {"PosterSite:1", "PosterSite:2"}
    stats = open_history(state).read("stats")["runs"][-1]
    assert stats["postings"]["opened"] == 2 and stats["new_by_qualification"] == {"degree": 1}

    # Next day: adverts come from the cache; the diploma job is still filtered, not re-sent.
    OPENED.clear()
    assert jobot_main.run(args) == 0
    assert OPENED == [] and sent[1].jobs == []

    # Tick "Diploma" and the HND job shows up (it was never marked as sent).
    assert jobot_main.run([*args, "--qualifications", "degree,diploma"]) == 0
    assert [j.title for j in sent[2].jobs] == ["Electrical Engineer"] and OPENED == []


def test_no_read_flag_skips_postings(fake_env):
    config, state, sent = fake_env
    OPENED.clear()
    jobot_main.run(["--config", str(config), "--state", str(state), "--no-read"])
    assert OPENED == [] and not (state.parent / "postings_cache.json").exists()


def test_dashboard_link_in_messages(cfg):
    from jobot.main import dashboard_url
    assert dashboard_url({"GITHUB_REPOSITORY": "mij001/jobot"}) == "https://mij001.github.io/jobot/"
    assert dashboard_url({}) is None
    report = Report([make_job(1)], [], cfg, date(2026, 10, 12), dashboard_url="https://mij001.github.io/jobot/")
    assert "https://mij001.github.io/jobot/" in report.email_text()
    assert 'href="https://mij001.github.io/jobot/"' in report.email_html()
    assert 'href="https://mij001.github.io/jobot/"' in "\n".join(report.telegram_messages())
    assert "github.io" not in Report([make_job(1)], [], cfg, date(2026, 10, 12)).email_text()


def _set_config(config, **sections):
    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    for key, values in sections.items():
        raw.setdefault(key, {}).update(values)
    config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _save_resume(state, text="BSc in EEE. Skills: Python, PLC, AutoCAD"):
    from jobot.vault import Vault
    folder = state.parent / "history"
    vault = Vault(folder, PASSWORD)
    vault.write("resume", {"kind": "text", "name": "pasted text", "updated": "2026-10-14", "text": text})
    vault.save_meta(["resume"])


def test_career_flag_builds_the_report_without_fetching_jobs(fake_env, monkeypatch):
    config, state, sent = fake_env
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    args = ["--config", str(config), "--state", str(state), "--career"]
    assert jobot_main.run(args) == 1  # no resume yet: says so
    _save_resume(state)
    assert jobot_main.run([*args, "--dry-run"]) == 0 and "career" not in open_history(state).meta.get("shards", [])
    assert jobot_main.run(args) == 0
    report = open_history(state).read("career")
    assert report["resume_skills"] == ["Python", "AutoCAD", "PLC"] and not report["ai"] and sent == []  # nothing was sent
    monkeypatch.delenv("DASHBOARD_PASSWORD")
    assert jobot_main.run(args) == 1  # needs the password


def test_daily_run_refreshes_the_career_report_and_uses_its_digest(fake_env, monkeypatch):
    config, state, sent = fake_env
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    _set_config(config, coach={"weekly_report": "daily"}, ai={"enabled": True, "min_score": 1})
    monkeypatch.setenv("AI_API_KEY", "k")
    _save_resume(state)
    seen = []

    def fake_review(jobs, cfg, env, **kw):
        seen.append(kw.get("profile_extra", ""))
        for j in jobs:
            j.ai_score, j.ai_reason = 8, "fits"
        return jobot_main.ai.ReviewResult(model="m", scored=len(jobs), hidden=0)

    monkeypatch.setattr(jobot_main.ai, "review", fake_review)
    monkeypatch.setattr(jobot_main.coach.ai, "ask_json", lambda *a, **k: (None, None, "offline"))
    args = ["--config", str(config), "--state", str(state)]
    jobot_main.run(args)
    assert seen == [""]  # no report existed yet when the first review ran
    report = open_history(state).read("career")
    assert report["digest"].startswith("Skills shown on the resume: Python") and any("unavailable" in n for n in report["notes"])
    state_file = json.loads(state.read_text())
    state_file["ids"].clear(); state_file["fingerprints"].clear()
    state.write_text(json.dumps(state_file))  # make the job "new" again
    jobot_main.run(args)
    assert seen[1].startswith("Skills shown on the resume: Python")  # the next day's review sees the digest

    # --no-ai keeps the coach from calling the AI too
    calls = []
    monkeypatch.setattr(jobot_main.coach.ai, "ask_json", lambda *a, **k: calls.append(1) or (None, None, "x"))
    jobot_main.run([*args, "--no-ai"])
    assert calls == []


def test_shortlist_reminders_go_out_even_when_nothing_is_new(fake_env, monkeypatch):
    from datetime import timedelta
    config, state, sent = fake_env
    monkeypatch.setenv("DASHBOARD_PASSWORD", PASSWORD)
    args = ["--config", str(config), "--state", str(state)]
    jobot_main.run(args)  # first day: logs "Embedded Engineer" in the history
    today = jobot_main.datetime.now(jobot_main.SRI_LANKA_TZ).date()
    vault = open_history(state)
    shard = next(n for n in vault.meta["shards"] if n.startswith("jobs-"))
    rows = vault.read(shard)
    rows[0]["closing"] = (today + timedelta(days=2)).isoformat()
    vault.write(shard, rows)
    vault.write("marks", {rows[0]["id"]: {"s": "shortlist", "t": "x"}})
    _set_config(config, notify={"send_when_empty": False})
    jobot_main.run(args)  # nothing new, send_when_empty is off – but a shortlisted job closes soon
    assert len(sent) == 2 and sent[1].jobs == []
    [reminder] = sent[1].reminders
    assert reminder["title"] == "Embedded Engineer" and reminder["days"] == 2
    assert "Closing soon" in sent[1].email_text()
