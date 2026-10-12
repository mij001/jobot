"""Report formatting, the seen-jobs store and the end-to-end CLI run."""

import json
from datetime import date

import pytest

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
    config.write_text(
        (jobot_main.ROOT / "config.yaml").read_text(encoding="utf-8").split("\nsources:")[0]
        + "\nsources:\n  fake: {}\n  broken: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(jobot_main.notifiers, "configured_channels", lambda env: {"fake": FakeChannel})
    return config, tmp_path / "seen.json", sent


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
