"""The AI helpers: triage of unmatched jobs, remote-job vetting, alert e-mails of unknown layout, the daily budget."""

import imaplib
import json
from datetime import date
from email.message import EmailMessage

import pytest
import requests

from jobot import main as jobot_main
from jobot import postings, triage
from jobot.http import Http, SourceSkipped
from jobot.models import Job
from jobot.schedule import Schedule
from jobot.sources import jooble, mailbox

TODAY = date(2026, 10, 21)
ENV = {"AI_API_KEY": "k"}


class FakeResp:
    def __init__(self, content):
        self.status_code, self.headers, self.ok = 200, {}, True
        self._body = {"choices": [{"message": {"content": content}}]}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeAI:
    """Answers the three helper prompts; `rule(kind, item) -> dict` builds one answer row per item."""

    def __init__(self, triage_rule=None, vet_rule=None, alert_rule=None):
        self.rules = {"triage": triage_rule, "vet": vet_rule, "alert": alert_rule}
        self.calls: list[tuple[str, object]] = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        system, user = json["messages"][0]["content"], json["messages"][1]["content"]
        kind = "triage" if system.startswith("You screen") else "vet" if system.startswith("You check") else "alert"
        payload = __import__("json").loads(user)
        self.calls.append((kind, payload))
        rule = self.rules[kind]
        if rule is None:
            return FakeResp("not json at all")
        rows = [rule(item) for item in payload] if kind != "alert" else rule(payload)
        return FakeResp(__import__("json").dumps({"results": rows}))


def make_helpers(cfg, tmp_path, ai_post, env=ENV, enabled=True, budget=30):
    cfg.ai.enabled, cfg.ai.daily_budget = True, budget
    return triage.Helpers(cfg, dict(env), Schedule(tmp_path / "schedule.json"), tmp_path, TODAY, enabled=enabled,
                          post=ai_post, sleep=lambda s: None)


def job(title, **kw):
    kw.setdefault("source", "topjobs.lk")
    kw.setdefault("source_id", title)
    kw.setdefault("url", "https://x/" + title.replace(" ", "-"))
    kw.setdefault("company", "Acme")
    return Job(title=title, **kw)


# -- plain rules ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Technical Officer", True), ("Project Engineer", True), ("Assistant Engineer", True), ("Maintenance Supervisor", True),
    ("Sales Executive", False), ("Software Engineer", False), ("Accounts Executive", False), ("Driver", False),
    ("Embedded Software Engineer", True), ("Graphic Designer", False), ("Full Stack Developer", False),
])
def test_worth_asking_skips_the_obvious_no(title, expected):
    assert triage.worth_asking(job(title)) is expected


def test_decisions_roundtrip_prune_and_quiet_save(tmp_path):
    path = tmp_path / "d.json"
    d = triage.Decisions(path)
    d.put("a", True, "power", date(2026, 10, 1))
    d.put("b", False, "", date(2026, 7, 1))
    d.save()
    again = triage.Decisions(path)
    assert again.get("a") == (True, "power") and again.get("b") == (False, "") and again.get("zzz") is None
    again.prune(TODAY)  # "b" is older than KEEP_DAYS
    assert again.get("b") is None and again.get("a") is not None
    stamp = path.stat().st_mtime_ns
    triage.Decisions(path).save()  # nothing changed: nothing written
    assert path.stat().st_mtime_ns == stamp


def test_schedule_ai_budget_counts_per_day_and_persists(tmp_path):
    s = Schedule(tmp_path / "s.json")
    assert [s.spend_ai("2026-10-21", 2) for _ in range(3)] == [True, True, False]
    assert s.ai_spent("2026-10-21") == 2 and s.ai_spent("2026-10-22") == 0
    s.save()
    again = Schedule(tmp_path / "s.json")
    assert again.ai_spent("2026-10-21") == 2
    assert again.spend_ai("2026-10-22", 2) is True  # a new day starts afresh
    assert again.ai_spent("2026-10-22") == 1


# -- triage ------------------------------------------------------------------------------------------------------------

def test_triage_rescues_what_keywords_missed_and_remembers_answers(cfg, tmp_path):
    jobs = [job("Technical Officer", description="Maintenance of switchgear"), job("Project Engineer"),
            job("Sales Executive"), job("Electrical Engineer")]
    matched = [jobs[3]]
    fake = FakeAI(triage_rule=lambda it: {"id": it["id"], "relevant": it["title"] == "Technical Officer", "field": "power",
                                          "why": "switchgear work"})
    h = make_helpers(cfg, tmp_path, fake)
    out = h.triage(jobs, matched)
    asked = [i["title"] for _, items in fake.calls for i in items]
    assert sorted(asked) == ["Project Engineer", "Technical Officer"]  # not the matched job, not the obvious no
    assert jobs[0].preset == ["power"] and "keywords missed" in jobs[0].ai_note
    assert jobs[1].uid in out.rejected and not jobs[1].preset
    assert out.rescued == 1 and out.asked == 2
    assert any("AI triage" in n for n in out.notes)
    h.save()

    # the next run: same jobs, answers come from the cache, no request at all
    fake2 = FakeAI(triage_rule=lambda it: pytest.fail("asked again"))
    jobs2 = [job("Technical Officer", description="Maintenance of switchgear"), job("Project Engineer")]
    h2 = make_helpers(cfg, tmp_path, fake2)
    out2 = h2.triage(jobs2, [])
    assert not fake2.calls and out2.rescued == 1 and jobs2[0].preset == ["power"] and jobs2[1].uid in out2.rejected


def test_triage_unknown_field_falls_back_and_unanswered_jobs_are_retried(cfg, tmp_path):
    jobs = [job("Technical Officer"), job("Assistant Engineer")]

    def rule(it):
        return {"id": it["id"], "relevant": True, "field": "astrology"}

    h = make_helpers(cfg, tmp_path, FakeAI(triage_rule=rule))
    h.triage(jobs, [])
    assert jobs[0].preset == (["general"] if any(s.key == "general" for s in cfg.subfields) else [])

    # an answer that skips an id leaves it undecided
    only_first = FakeAI(triage_rule=lambda it: {"id": it["id"], "relevant": False} if it["title"] == "Technical Officer" else {"id": "other"})
    h2 = make_helpers(cfg, tmp_path / "x", only_first)
    (tmp_path / "x").mkdir()
    out = h2.triage([job("Technical Officer"), job("Assistant Engineer")], [])
    assert out.asked == 1 and h2.decisions.get(job("Assistant Engineer").uid) is None


def test_triage_stops_when_the_daily_budget_is_used_up(cfg, tmp_path):
    cfg.ai.triage_batch = 5
    jobs = [job(f"Technical Officer {i}") for i in range(12)]
    fake = FakeAI(triage_rule=lambda it: {"id": it["id"], "relevant": False})
    h = make_helpers(cfg, tmp_path, fake, budget=1)
    out = h.triage(jobs, [])
    assert len(fake.calls) == 1 and out.asked == 5
    assert any("budget is used up" in n for n in out.notes)


def test_no_key_or_switched_off_means_no_requests(cfg, tmp_path):
    jobs = [job("Technical Officer")]
    fake = FakeAI(triage_rule=lambda it: pytest.fail("must not ask"))
    for kwargs in ({"env": {}}, {"enabled": False}):
        h = make_helpers(cfg, tmp_path, fake, **kwargs)
        out = h.triage(jobs, [])
        assert not fake.calls and not out.rescued and not out.rejected and not jobs[0].preset
    cfg.ai.helpers = False
    assert not make_helpers(cfg, tmp_path, fake).on


def test_garbled_answer_changes_nothing(cfg, tmp_path):
    jobs = [job("Technical Officer")]
    h = make_helpers(cfg, tmp_path, FakeAI())  # replies with non-JSON text
    out = h.triage(jobs, [])
    assert not out.rescued and not out.rejected and h.decisions.get(jobs[0].uid) is None
    assert any("no answer" in n for n in out.notes)


# -- remote vetting ----------------------------------------------------------------------------------------------------

def remote(title, rule="unsure", **kw):
    j = job(title, source="Remote OK", remote=True, location="Remote – Worldwide", description="Join us. " * 20, **kw)
    j.remote_rule = rule
    return j


def test_vet_remote_drops_closed_and_not_fully_remote_and_notes_the_rest(cfg, tmp_path):
    jobs = [remote("Open one"), remote("Closed one"), remote("Hybrid one"), remote("Unclear one"), remote("Silent one")]
    verdicts = {
        "Open one": {"open": "open", "fully_remote": True, "why": "worldwide, contractors welcome"},
        "Closed one": {"open": "closed", "fully_remote": True, "why": "US work authorisation"},
        "Hybrid one": {"open": "open", "fully_remote": False, "why": "two office days"},
        "Unclear one": {"open": "unclear", "fully_remote": None, "why": "no location given"},
    }
    titles = {j.uid: j.title for j in jobs}

    def rule(it):
        row = verdicts.get(titles[it["id"]])
        return {"id": it["id"], **row} if row else {"id": "someone-else"}

    h = make_helpers(cfg, tmp_path, FakeAI(vet_rule=rule))
    out = h.vet_remote(jobs + [job("Not remote")])
    assert set(out.vetoed) == {jobs[1].uid, jobs[2].uid}
    assert "US work authorisation" in out.vetoed[jobs[1].uid] and "not fully remote" in out.vetoed[jobs[2].uid]
    assert "open to Sri Lanka" in jobs[0].ai_note and "worldwide" in jobs[0].ai_note
    assert jobs[3].ai_note.startswith("Remote – check eligibility")
    assert jobs[4].ai_note.startswith("Eligibility not checked")  # unanswered + unsure by the plain rules
    assert out.vetted == 4


def test_vet_remote_without_ai_keeps_plain_rule_results(cfg, tmp_path):
    sure, unsure = remote("Sure", rule="open"), remote("Unsure")
    h = make_helpers(cfg, tmp_path, FakeAI(vet_rule=lambda it: pytest.fail("must not ask")), env={})
    out = h.vet_remote([sure, unsure])
    assert not out.vetoed and not sure.ai_note and unsure.ai_note.startswith("Eligibility not checked")


def test_vet_remote_ignores_ids_it_was_not_asked_about(cfg, tmp_path):
    only = remote("Only one")
    h = make_helpers(cfg, tmp_path, FakeAI(vet_rule=lambda it: {"id": "forged", "open": "closed"}))
    out = h.vet_remote([only])
    assert not out.vetoed


# -- postings.pick -------------------------------------------------------------------------------------------------------

def test_pick_skips_jobs_the_ai_turned_down(cfg):
    a, b = job("Technical Officer"), job("Assistant Engineer")
    first = postings.pick([a, b], [], lambda j: True, cfg)
    assert {j.title for j in first} == {"Technical Officer", "Assistant Engineer"}
    assert [j.title for j in postings.pick([a, b], [], lambda j: True, cfg, skip={a.uid})] == ["Assistant Engineer"]


# -- alert e-mails ---------------------------------------------------------------------------------------------------

def alert_mail(sender="Jobs <jobs@weirdboard.lk>", subject="3 new jobs for you", message_id="<m1@x>"):
    msg = EmailMessage()
    msg["From"], msg["Subject"], msg["Message-ID"], msg["Date"] = sender, subject, message_id, "Tue, 20 Oct 2026 08:00:00 +0530"
    msg.set_content("plain")
    msg.add_alternative(
        '<html><body><p>Your alert</p>'
        '<table><tr><td><a href="https://weirdboard.lk/v/101?ref=a">Power Systems Engineer</a><br>Lanka Grid, Colombo</td></tr>'
        '<tr><td><a href="https://weirdboard.lk/v/102">Solar PV Designer</a><br>Sun Co</td></tr></table>'
        '<a href="https://weirdboard.lk/unsubscribe?u=1">Unsubscribe from alerts</a>'
        '<a href="https://weirdboard.lk/">Open the website</a></body></html>', subtype="html")
    return msg.as_bytes()


def test_unknown_layout_alert_is_read_by_the_ai_once(cfg, tmp_path):
    def rule(payload):
        links = {l["n"]: l["url"] for l in payload["links"]}
        assert not any("unsubscribe" in u for u in links.values())  # never offered
        by_url = {u: n for n, u in links.items()}
        return [{"link": by_url["https://weirdboard.lk/v/101?ref=a"], "title": "Power Systems Engineer", "company": "Lanka Grid", "location": "Colombo"},
                {"link": 99, "title": "Made-up link"},  # a link number it was never given
                {"link": by_url["https://weirdboard.lk/v/102"], "title": "Solar PV Designer", "company": "Sun Co"}]

    fake = FakeAI(alert_rule=rule)
    h = make_helpers(cfg, tmp_path, fake)
    jobs = mailbox.parse_message(alert_mail(), ["weirdboard.lk"], extract=h.extract_alert)
    assert [j.title for j in jobs] == ["Power Systems Engineer", "Solar PV Designer"]
    assert jobs[0].url == "https://weirdboard.lk/v/101?ref=a" and jobs[0].company == "Lanka Grid" and jobs[0].posted == "2026-10-20"
    assert jobs[0].source == "Email alert (weirdboard.lk)"
    assert [c[0] for c in fake.calls] == ["alert"]

    # the same message again (the next run reads the same three days of mail): remembered, no request
    h.save()
    h2 = make_helpers(cfg, tmp_path, FakeAI(alert_rule=lambda p: pytest.fail("asked again")))
    assert mailbox.parse_message(alert_mail(), ["weirdboard.lk"], extract=h2.extract_alert) == []


def test_known_layouts_never_reach_the_ai(cfg, tmp_path):
    msg = EmailMessage()
    msg["From"], msg["Subject"] = "LinkedIn <jobs-noreply@linkedin.com>", "Jobs for you"
    msg.set_content("x")
    msg.add_alternative('<a href="https://www.linkedin.com/comm/jobs/view/3912345678?trk=x">Electrical Engineer</a>', subtype="html")
    h = make_helpers(cfg, tmp_path, FakeAI(alert_rule=lambda p: pytest.fail("the plain parser handles LinkedIn")))
    jobs = mailbox.parse_message(msg.as_bytes(), ["linkedin.com"], extract=h.extract_alert)
    assert [j.title for j in jobs] == ["Electrical Engineer"]


def test_alert_without_ai_budget_or_key_is_left_for_later(cfg, tmp_path):
    h = make_helpers(cfg, tmp_path, FakeAI(), env={})
    assert mailbox.parse_message(alert_mail(), ["weirdboard.lk"], extract=h.extract_alert) == []
    assert h.decisions.get("mail:anything") is None and not h.decisions.entries  # not remembered: tried again later
    cfg.ai.alert_calls = 1
    h2 = make_helpers(cfg, tmp_path, FakeAI(alert_rule=lambda p: []))
    mailbox.parse_message(alert_mail(message_id="<a>"), ["weirdboard.lk"], extract=h2.extract_alert)
    mailbox.parse_message(alert_mail(message_id="<b>"), ["weirdboard.lk"], extract=h2.extract_alert)
    assert len(h2.decisions.entries) == 1  # at most `alert_calls` unknown e-mails per run


# -- channels that are on by default but not set up -----------------------------------------------------------------

def test_mailbox_login_refused_is_a_skip_not_a_failure(monkeypatch):
    class Box:
        def __init__(self, *a, **k):
            pass

        def login(self, user, password):
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

        def logout(self):
            pass

    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", Box)
    opts = {"senders": ["linkedin.com"], "_env": {"IMAP_USERNAME": "me@example.com", "IMAP_PASSWORD": "nope"}}
    with pytest.raises(SourceSkipped, match="refused the login"):
        mailbox.fetch(Http(delay=0), opts, None)


def test_scrape_shows_unconfigured_channels_as_skipped(cfg, monkeypatch):
    cfg.sources = {"email_alerts": {"senders": ["linkedin.com"]}, "jooble": {}}
    jobs, results = jobot_main.scrape(cfg, env={})
    assert jobs == [] and [bool(r.skipped) for r in results] == [True, True] and not any(r.error for r in results)
    assert "JOOBLE_API_KEY" in results[1].skipped


def test_a_rejected_login_or_key_found_while_reading_is_skipped_too(cfg, monkeypatch):
    class Refusing:
        NAME = "Refusing"

        @staticmethod
        def fetch(http, opts, cfg):
            raise SourceSkipped("the key was rejected")

    monkeypatch.setattr(jobot_main, "SOURCES", {"refusing": Refusing})
    cfg.sources = {"refusing": {}}
    jobs, results = jobot_main.scrape(cfg, env={})
    assert results[0].skipped == "the key was rejected" and results[0].error is None


def test_jooble_rejected_key_is_skipped(monkeypatch):
    class Conn(Http):
        def post(self, url, **kw):
            resp = requests.Response()
            resp.status_code = 403
            raise requests.HTTPError(response=resp)

    with pytest.raises(SourceSkipped, match="rejected the key"):
        jooble.fetch(Conn(delay=0), {"queries": ["electrical engineer"], "_env": {"JOOBLE_API_KEY": "bad"}}, None)


# -- the whole run -------------------------------------------------------------------------------------------------------

def test_run_end_to_end_with_helpers(tmp_path, monkeypatch, cfg):
    """A generic-titled job is rescued by the AI, a closed remote job is dropped, an open one is sent with its note."""
    import yaml
    from pathlib import Path

    class Board:
        NAME = "Board"

        @staticmethod
        def fetch(http, opts, cfg):
            return [
                Job(source="Board", source_id="1", title="Project Engineer", url="https://b/1", company="Lanka Power"),
                Job(source="Board", source_id="2", title="Receptionist", url="https://b/2"),
                Job(source="Board", source_id="3", title="Embedded Firmware Engineer", url="https://b/3", company="Acme", remote=True,
                    location="Remote – Worldwide", description="Build firmware. " * 20, remote_rule="unsure"),
                Job(source="Board", source_id="4", title="Hardware Engineer", url="https://b/4", company="USCo", remote=True,
                    location="Remote – Worldwide", description="Must be authorised to work in the US. " * 10, remote_rule="unsure"),
            ]

    sent = []

    class Channel:
        @staticmethod
        def send(report, env):
            sent.append(report)

    def rule_triage(it):
        return {"id": it["id"], "relevant": True, "field": "power", "why": "utility company"}

    def rule_vet(it):
        closed = "USCo" in it["company"]
        return {"id": it["id"], "open": "closed" if closed else "open", "fully_remote": True, "why": "US only" if closed else "worldwide"}

    fake = FakeAI(triage_rule=rule_triage, vet_rule=rule_vet)
    monkeypatch.setattr(jobot_main, "SOURCES", {"board": Board})
    monkeypatch.setattr(jobot_main.notifiers, "configured_channels", lambda env: {"fake": Channel})
    real = triage.Helpers
    monkeypatch.setattr(jobot_main.triage, "Helpers", lambda *a, **k: real(*a, post=fake, sleep=lambda s: None, **k))
    monkeypatch.setenv("AI_API_KEY", "k")
    monkeypatch.setattr(jobot_main.ai, "review", lambda jobs, *a, **k: jobot_main.ai.ReviewResult(model="m", scored=0, hidden=0))
    monkeypatch.setattr(jobot_main.postings, "read_posting", lambda *a, **k: (_ for _ in ()).throw(requests.HTTPError(response=type("R", (), {"status_code": 404})())))
    config = tmp_path / "config.yaml"
    raw = yaml.safe_load((Path(__file__).parent / "fixtures" / "default_config.yaml").read_text(encoding="utf-8"))
    raw["sources"] = {"board": {}}
    raw["ai"]["enabled"] = True
    config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    state = tmp_path / "seen.json"

    assert jobot_main.run(["--config", str(config), "--state", str(state)]) == 0
    titles = [j.title for j in sent[0].jobs]
    assert "Project Engineer" in titles and "Embedded Firmware Engineer" in titles
    assert "Receptionist" not in titles and "Hardware Engineer" not in titles
    by_title = {j.title: j for j in sent[0].jobs}
    assert "keywords missed" in by_title["Project Engineer"].ai_note
    assert "open to Sri Lanka" in by_title["Embedded Firmware Engineer"].ai_note
    assert (tmp_path / "ai_decisions.json").exists()
    assert json.loads((tmp_path / "schedule.json").read_text())["ai"]["calls"] == len(fake.calls)

    # the second run sends nothing new and asks the AI nothing more
    before = len(fake.calls)
    assert jobot_main.run(["--config", str(config), "--state", str(state)]) == 0
    assert len(fake.calls) == before and sent[1].jobs == []


def test_budget_zero_still_runs_with_plain_rules(tmp_path, cfg):
    h = make_helpers(cfg, tmp_path, FakeAI(triage_rule=lambda it: pytest.fail("no budget")), budget=0)
    out = h.triage([job("Technical Officer")], [])
    assert not out.rescued and any("budget is used up" in n for n in out.notes)
