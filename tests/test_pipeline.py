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

    def fake_review(jobs, cfg, env):
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


def test_run_logs_statistics(fake_env):
    config, state, sent = fake_env
    args = ["--config", str(config), "--state", str(state)]
    jobot_main.run(["--dry-run", *args])
    assert not (state.parent / "stats.json").exists()  # dry runs log nothing
    jobot_main.run(args)
    jobot_main.run(args)
    data = json.loads((state.parent / "stats.json").read_text())
    assert [r["new"] for r in data["runs"]] == [1, 0]
    assert data["runs"][0]["sources"]["BrokenSite"]["error"].startswith("RuntimeError")
    assert isinstance(data["suggestions"], list)
    log = (state.parent / "jobs_log.csv").read_text().splitlines()
    assert log[0].startswith("date,status,site,title") and "Embedded Engineer" in log[1] and len(log) == 2
    assert "jobs scanned" in sent[0].email_text()


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
    stats = json.loads((state.parent / "stats.json").read_text())["runs"][-1]
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
