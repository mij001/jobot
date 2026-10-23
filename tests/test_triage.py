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


def test_jobs_you_already_applied_for_are_not_new_vacancies():
    msg = EmailMessage()
    msg["From"], msg["Subject"] = "LinkedIn <jobs-noreply@linkedin.com>", "Your application was viewed"
    msg.set_content("x")
    msg.add_alternative(
        '<table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4480404741?trk=eml-email_jobs_job_application_viewed_01-applied_jobs-0">'
        'Electrical Engineering Intern</a><br>BPPL Holdings PLC Applied on Oct 20</td></tr></table>'
        '<table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4479965615?trk=eml-email_job_alert_digest_01">Electrical Engineer</a>'
        '<br>Samsung C&amp;T</td></tr></table>', subtype="html")
    jobs = mailbox.parse_message(msg.as_bytes(), ["linkedin.com"])
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


# -- the LinkedIn posts that were missed ---------------------------------------------------------------------------------

LINKEDIN_MISSES = [("Associate Engineer - TechOps", "CodeGen International", "Colombo (On-site)"),
                   ("Associate Engineer – Platform SRE", "LSEG", "Colombo (Hybrid)"),
                   ("Technical Officer telecom projects", "Luminex PLC", "Jaffna District (On-site)")]


def linkedin_posts():
    return [Job(source="LinkedIn", source_id=str(i), title=t, url=f"https://www.linkedin.com/jobs/view/{i}/", company=c, location=l)
            for i, (t, c, l) in enumerate(LINKEDIN_MISSES, 1)]


def test_a_matched_job_is_not_hidden_by_a_guess_from_its_title(cfg):
    """"Technical Officer telecom projects" matched telecom, but "technical officer" made it a diploma job (switched off)."""
    from jobot.filters import select_jobs
    tech = linkedin_posts()[2]
    assert select_jobs([tech], cfg) == [tech]
    assert tech.subfields == ["telecom"] and tech.qualifications == ["diploma"] and tech.qual_guess

    # ... but when the advert itself asks for a diploma, the filter still applies
    strict = Job(source="topjobs.lk", source_id="9", title="Technical Officer - Telecom", url="https://t/9",
                 description="Applicants must hold an HND in Telecommunication Engineering")
    assert select_jobs([strict], cfg) == [] and not strict.qual_guess


def test_a_title_guess_counts_when_unstated_qualifications_are_not_wanted(cfg):
    from jobot.filters import select_jobs
    cfg.include_unknown_qualification = False
    assert select_jobs([linkedin_posts()[2]], cfg) == []


def test_ai_does_not_hide_a_job_for_a_guessed_qualification(cfg):
    from jobot import ai
    j = job("Technical Officer telecom projects")
    j.ai_score, j.level, j.qualifications, j.qual_guess = 7, "entry", ["diploma"], True
    assert not ai.is_hidden(j, cfg)
    j.qual_guess = False
    assert ai.is_hidden(j, cfg)  # the advert really asks for a diploma


def test_entry_level_engineer_titles_are_kept_even_when_the_ai_cannot_answer(cfg, tmp_path):
    posts = linkedin_posts()[:2] + [job("Associate Software Engineer"), job("Senior Associate Engineer Civil"), job("Sales Executive")]
    for env in ({}, ENV):  # no key at all / a key but a garbled answer
        h = make_helpers(cfg, tmp_path / ("a" if env else "b"), FakeAI(), env=env)
        (tmp_path / ("a" if env else "b")).mkdir(exist_ok=True)
        out = h.triage(posts, [])
        assert out.rescued >= 2 and posts[0].preset == ["general"] and posts[1].preset == ["general"]
        assert "check it suits EEE" in posts[0].ai_note
        assert not posts[2].preset and not posts[4].preset  # software development / sales: not guessed
        assert h.decisions.get(posts[0].uid) is None  # not remembered: the AI still gets to decide later


def test_an_ai_no_beats_the_entry_level_fallback(cfg, tmp_path):
    post = linkedin_posts()[1]
    h = make_helpers(cfg, tmp_path, FakeAI(triage_rule=lambda it: {"id": it["id"], "relevant": False}))
    out = h.triage([post], [])
    assert post.uid in out.rejected and not post.preset and not out.unchecked


def test_generic_engineer_jobs_are_asked_before_the_long_tail(cfg, tmp_path):
    """A long queue of technician / officer titles must not starve "Associate Engineer"."""
    cfg.ai.triage_batch, cfg.ai.triage_calls = 5, 1
    noise = [job(f"Maintenance Technician {i}", source="topjobs.lk") for i in range(30)] + \
            [job(f"Executive Officer {i}", source="topjobs.lk") for i in range(30)]
    posts = linkedin_posts()[:2]
    fake = FakeAI(triage_rule=lambda it: {"id": it["id"], "relevant": True, "field": "networking", "why": "ok"})
    h = make_helpers(cfg, tmp_path, fake)
    h.triage(noise + posts, [])
    asked = [i["title"] for _, items in fake.calls for i in items]
    assert len(asked) == 5 and {p.title for p in posts} <= set(asked)
    assert posts[0].preset == ["networking"] and "Picked by the AI" in posts[0].ai_note


def test_triage_priority_order():
    ranked = sorted([job("Executive Officer"), job("Maintenance Technician"), job("Project Engineer"),
                     job("Associate Engineer - TechOps"), job("Embedded Associate Engineer")], key=triage.priority)
    assert [j.title for j in ranked[:2]] == ["Embedded Associate Engineer", "Associate Engineer - TechOps"]
    assert ranked[-1].title == "Executive Officer"


def test_a_no_from_the_stricter_prompt_is_doubted_only_for_entry_level_engineer_roles(cfg, tmp_path):
    entry, other = linkedin_posts()[0], job("Technical Officer Maintenance")
    path = tmp_path / "ai_decisions.json"
    path.write_text(f'{{\n"{entry.uid}": "n:20261001",\n"{other.uid}": "n:20261001",\n"topjobs.lk:2": "y:power:20261001",\n"mail:abc": "n:20261001"\n}}\n',
                    encoding="utf-8")  # no "_version": written by the first prompt
    d = triage.Decisions(path)
    assert d.old_prompt and d.doubtful(entry.uid) and d.doubtful(other.uid) and not d.doubtful("mail:abc") and not d.doubtful("topjobs.lk:2")
    d.save()  # rewritten even though nothing was added, now with the version
    assert '"_version": "2"' in path.read_text(encoding="utf-8")
    assert not triage.Decisions(path).old_prompt

    # asked again (and kept without the AI): only the entry-level engineer role; the other old "no" stands
    h = make_helpers(cfg, tmp_path, FakeAI(), env={})
    h.decisions = triage.Decisions(tmp_path / "old.json")
    (tmp_path / "old.json").write_text(path.read_text(encoding="utf-8").replace('"_version": "2"', '"_version": "1"'), encoding="utf-8")
    h.decisions = triage.Decisions(tmp_path / "old.json")
    out = h.triage([entry, other], [])
    assert entry.preset == ["general"] and out.unchecked == 1 and other.uid in out.rejected and not other.preset


def test_a_busy_ai_cannot_stall_the_run(cfg, tmp_path):
    """Two requests in a row without an answer: the helpers stop asking for the rest of the run."""
    cfg.ai.triage_batch, cfg.ai.triage_calls = 5, 4
    jobs = [job(f"Maintenance Engineer {i}") for i in range(40)]
    fake = FakeAI()  # answers with nonsense every time
    h = make_helpers(cfg, tmp_path, fake)
    out = h.triage(jobs, [])
    assert any("isn't answering" in n for n in out.notes)
    assert h.schedule.ai_spent(TODAY.isoformat()) == 2  # two requests (each tried on every model); the rest cost nothing


def test_waiting_for_the_ai_has_a_time_limit(cfg, tmp_path, monkeypatch):
    cfg.ai.triage_batch, cfg.ai.helper_seconds = 5, 10
    import types
    clock = iter(range(0, 1000, 8))  # every request "takes" 8 s
    monkeypatch.setattr(triage, "time", types.SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    fake = FakeAI(triage_rule=lambda it: {"id": it["id"], "relevant": False})
    h = make_helpers(cfg, tmp_path, fake)
    out = h.triage([job(f"Maintenance Engineer {i}") for i in range(40)], [])
    assert h.schedule.ai_spent(TODAY.isoformat()) == 2 and any("ai.helper_seconds" in n for n in out.notes)


def test_linkedin_reads_generic_titles_deeper(cfg):
    from jobot.sources import linkedin

    class Http_:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None, **kw):
            self.calls.append((params["keywords"], params["start"]))

            class R:
                text = "".join(f'<div class="base-card" data-entity-urn="urn:li:jobPosting:{params["start"] + i}{len(self.calls)}">'
                               f'<a class="base-card__full-link" href="https://x/y"></a><h3 class="base-search-card__title">T{i}</h3></div>'
                               for i in range(10))
            R.self = self
            return R()

    http = Http_()
    linkedin.fetch(http, {"keywords": ["electrical engineer"], "broad_keywords": ["associate engineer"], "broad_pages": 2,
                          "max_pages": 1, "location": "Sri Lanka"}, cfg)
    assert http.calls == [("electrical engineer", 0), ("associate engineer", 0), ("associate engineer", 10)]


def test_run_sends_the_three_missed_linkedin_posts_without_any_ai_key(tmp_path, monkeypatch):
    """Regression for the posts the bot did not find: no keyword names a field, and no AI is available at all."""
    from pathlib import Path

    import yaml

    class LinkedIn:
        NAME = "LinkedIn"

        @staticmethod
        def fetch(http, opts, cfg):
            return linkedin_posts() + [Job(source="LinkedIn", source_id="99", title="Marketing Executive", url="https://l/99", company="X")]

    sent = []

    class Channel:
        @staticmethod
        def send(report, env):
            sent.append(report)

    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.setattr(jobot_main, "SOURCES", {"linkedin": LinkedIn})
    monkeypatch.setattr(jobot_main.notifiers, "configured_channels", lambda env: {"fake": Channel})
    config = tmp_path / "config.yaml"
    raw = yaml.safe_load((Path(__file__).parent / "fixtures" / "default_config.yaml").read_text(encoding="utf-8"))
    raw["sources"] = {"linkedin": {}}
    config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")

    assert jobot_main.run(["--config", str(config), "--state", str(tmp_path / "seen.json"), "--no-read"]) == 0
    by = {j.title: j for j in sent[0].jobs}
    assert set(by) == {t for t, _, _ in LINKEDIN_MISSES}
    assert by["Technical Officer telecom projects"].qual_guess and "guessed from the title" in sent[0].email_text()
    assert "check it suits EEE" in by["Associate Engineer - TechOps"].ai_note


def test_explain_says_where_a_job_is_lost(cfg):
    from jobot import filters
    kept = filters.explain(linkedin_posts()[2], cfg)
    assert kept[-1] == "KEPT" and any("only guessed from the title" in l for l in kept)
    assert filters.explain(linkedin_posts()[0], cfg)[-1].startswith("NOT MATCHED")
    assert filters.explain(job("Marketing Executive"), cfg)[-1].startswith("DROPPED")
    hnd = Job(source="x", source_id="1", title="Technical Officer - Telecom", url="u", description="HND only")
    assert filters.explain(hnd, cfg)[-1].startswith("DROPPED: the advert asks for a qualification")
    senior = job("Senior Telecom Engineer 10 years experience")
    assert "level" in " ".join(filters.explain(senior, cfg))


def test_explain_command_prints_the_verdict(capsys):
    assert jobot_main.run(["--explain", "Technical Officer telecom projects | Luminex PLC | Jaffna"]) == 0
    out = capsys.readouterr().out
    assert "Luminex PLC" in out and "KEPT" in out


@pytest.mark.parametrize("title,expected", [
    ("Associate Engineer - TechOps", True), ("Associate Engineer – Platform SRE", True), ("Graduate Trainee Engineer", True),
    ("Junior Engineer", True), ("Engineering Intern", True), ("Trainee Engineer - Telecom", True),
    ("Assistant Engineer - Civil", False), ("Assistant Engineer (Mechanical)", False), ("Trainee Engineer - Quantity Surveying", False),
    ("Junior Engineer Structural", False), ("Trainee Engineer (Production)", False), ("Marketing Executive", False),
])
def test_entry_level_engineer_fallback_leaves_other_branches_to_the_ai(title, expected):
    assert triage.entry_level_engineer(job(title)) is expected


def test_helpers_stop_when_the_run_is_nearly_out_of_time(cfg, tmp_path):
    import time
    fake = FakeAI(triage_rule=lambda it: pytest.fail("must not ask"))
    h = make_helpers(cfg, tmp_path, fake)
    h.stop_at = time.monotonic() - 1
    out = h.triage([job("Maintenance Engineer"), linkedin_posts()[0]], [])
    assert not fake.calls and any("running out of time" in n for n in out.notes)
    assert out.unchecked == 1  # the entry-level engineer role is still kept


def test_run_total_budget_is_validated(cfg):
    from jobot.config import load_config
    assert load_config(jobot_main.ROOT / "config.yaml").schedule.total_seconds == 900


def test_the_same_linkedin_job_from_the_search_and_an_alert_email_is_sent_once(cfg):
    from jobot.filters import select_jobs
    mail = Job(source="Email alert (linkedin.com)", source_id="x", title="Associate Engineer - TechOps CodeGen International · Colombo (On-site) 1 company alum",
               url="https://www.linkedin.com/comm/jobs/view/4482078513/?trackingId=abc&trk=eml-x", description="associate engineer techops engineer")
    card = Job(source="LinkedIn", source_id="4482078513", title="Associate Engineer - TechOps", url="https://www.linkedin.com/jobs/view/4482078513/",
               company="CodeGen International")
    for j in (mail, card):
        j.preset = ["networking"]
    assert mail.fingerprint == card.fingerprint
    (kept,) = select_jobs([mail, card], cfg)
    assert kept is card and kept.also_on == [("Email alert (linkedin.com)", mail.url)]  # the clean listing wins, the e-mail is a link
