"""Reading each posting against the requirements: place, plain rules, the AI verdict, waiting for the posting."""

import json
from datetime import date

import pytest
import requests

from jobot import ai, filters, judge, postings, requirements
from jobot.models import Job
from jobot.schedule import Schedule

TODAY = date(2026, 10, 23)


@pytest.fixture(autouse=True)
def _your_settings(cfg):
    """The settings config.yaml ships with: jobs abroad off, technical sales off."""
    cfg.include_overseas = False
    for sf in cfg.subfields:
        if sf.key == "technical_sales":
            sf.enabled = False


def job(title, **kw):
    kw.setdefault("source", "LinkedIn")
    kw.setdefault("source_id", title)
    kw.setdefault("url", "https://www.linkedin.com/jobs/view/" + str(abs(hash(title)) % 10**9 + 10**8) + "/")
    return Job(title=title, **kw)


LONG_IT = ("The role will support, maintain and automate Microsoft Windows server and platform infrastructure across our "
           "environments. You will monitor services, patch servers, manage Active Directory and cloud subscriptions, write "
           "PowerShell scripts and take part in an on-call rota for incidents. " * 3)
LONG_EEE = ("You will commission low-voltage switchgear and PLC control panels, test protection relays and prepare earthing "
            "and cabling drawings for substations. A BSc in electrical engineering is required. " * 3)


# -- place ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "ASIC Engineer, Project Leo Amazon · Austin, TX 17 school alumni",
    "FPGA Engineer, Hardware & Electronics HARMAN International · Richardson, TX (Hybrid) 2 company alumni",
    "FPGA Design Engineer University of Southern California · Arlington, VA 5 company alumni",
    "Neural Processing Unit Design Engineer MediaTek · Hsinchu 98 company alumni",
    "Mask Techno Engineer STMicroelectronics · Singapore, Singapore",
    "Telephony Engineer Optomi · United States (Remote) $85-$90 / hour",
])
def test_jobs_abroad_are_filtered(cfg, text):
    cfg.include_overseas = False
    j = job(text, source="Email alert (linkedin.com)")
    j.preset = ["electronics"]
    assert filters.is_excluded(j, cfg) and filters.select_jobs([j], cfg) == []


@pytest.mark.parametrize("text", [
    "Electrical Engineer Samsung C&T · Colombo District (Hybrid)",
    "FPGA Engineer Zone24x7 · Colombo, Western Province, Sri Lanka",
    "Engineer I NPI GPV · Kochchikade, Western Province, Sri Lanka 11 school alumni",
    "Telecom Engineer · Jaffna",
])
def test_jobs_in_sri_lanka_are_not_mistaken_for_foreign_ones(cfg, text):
    cfg.include_overseas = False
    assert not filters.is_excluded(job(text), cfg)


def test_jobs_abroad_come_back_when_you_ask_for_them(cfg):
    cfg.include_overseas = True
    assert not filters.is_excluded(job("FPGA Engineer Acme · Austin, TX"), cfg)


def test_a_vetted_remote_job_is_never_called_foreign(cfg):
    cfg.include_overseas = False
    j = job("Firmware Engineer", location="Remote – Worldwide", remote=True)
    assert not filters.is_excluded(j, cfg)


# -- the plain rules ------------------------------------------------------------------------------------------------------

def test_sales_engineer_is_a_no_even_for_automation(cfg):
    assert requirements.assess(job("Sales Engineer – Industrial Automation & Projects"), cfg) == ("no", "a sales role")


def test_rules_verdicts(cfg):
    assert requirements.assess(job("Electrical Engineer"), cfg)[0] == "match"
    assert requirements.assess(job("Marketing Executive"), cfg)[0] == "no"
    assert requirements.assess(job("Executive - Inventory Planning and Governance"), cfg)[0] == "no"
    assert requirements.assess(job("Senior Software Engineer"), cfg)[0] == "no"
    assert requirements.assess(job("Embedded Software Engineer"), cfg)[0] == "match"
    # a title that names no field is decided by the posting
    assert requirements.assess(job("Associate Engineer"), cfg)[0] == "maybe"
    assert requirements.assess(job("Associate Engineer", description=LONG_EEE), cfg)[0] == "maybe"
    assert requirements.assess(job("Associate Engineer", description="Our team is hiring. " * 40), cfg)[0] == "no"


def test_it_operations_titles_are_decided_by_the_posting_not_the_title(cfg):
    assert requirements.assess(job("Associate Engineer – Platform SRE"), cfg)[0] == "maybe"  # nothing read yet
    assert requirements.assess(job("Associate Engineer – Platform SRE", description=LONG_IT), cfg)[0] == "no"
    assert requirements.assess(job("Associate Engineer - TechOps", description=LONG_EEE), cfg)[0] == "maybe"
    assert requirements.assess(job("Network Support Engineer", description="Install and test routers, switches and fibre links. " * 12), cfg)[0] == "maybe"


def test_the_requirements_are_worded_from_the_settings_unless_you_write_them(cfg):
    text = "\n".join(requirements.lines(cfg))
    assert "degree" in text and "Sri Lanka" in text and "abroad doesn't match" in text and "Telecommunication" in text
    cfg.ai.requirements = ["Only power-sector jobs."]
    assert requirements.lines(cfg) == ["Only power-sector jobs."]


# -- qualification guesses ---------------------------------------------------------------------------------------------------

def test_trade_titles_still_count_as_the_level_they_name(cfg):
    for q in cfg.qualifications:
        q.guess_filters = q.key == "vocational"  # what config.yaml sets
    tech = job("Electronic Technicians - Kandy", source="topjobs.lk")
    tech.preset = ["electronics"]
    assert filters.select_jobs([tech], cfg) == []
    officer = job("Technical Officer telecom projects")
    assert filters.select_jobs([officer], cfg) == [officer] and officer.qual_guess


# -- the AI's reading ---------------------------------------------------------------------------------------------------------

def test_the_prompt_carries_the_requirements_and_the_posting_text(cfg):
    cfg.ai.enabled = True
    seen = {}

    def post(url, json, headers, timeout):
        seen["system"], seen["user"] = json["messages"][0]["content"], json["messages"][1]["content"]
        rows = [{"id": j["id"], "verdict": "no", "failed": ["work"], "score": 8, "reason": "Windows servers"} for j in
                __import__("json").loads(seen["user"].split("Job adverts:\n")[1])]
        return type("R", (), {"status_code": 200, "ok": True, "text": "", "headers": {},
                              "json": lambda self: {"choices": [{"message": {"content": __import__("json").dumps({"results": rows})}}]}})()

    j = job("Associate Engineer – Platform SRE", description=LONG_IT, company="LSEG", location="Colombo")
    result = ai.review([j], cfg, {"AI_API_KEY": "k"}, post=post, sleep=lambda s: None)
    assert "Place: located in Sri Lanka" in seen["system"] and "REQUIREMENTS" in seen["system"]
    assert "Windows server" in seen["user"] and '"text_is_short": false' in seen["user"]
    assert j.ai_verdict == "no" and j.ai_score == 4  # a "no" can't keep a high score
    assert ai.is_hidden(j, cfg) and result.held == [j]


def test_a_job_the_ai_could_not_judge_is_reported_as_unreviewed(cfg):
    cfg.ai.enabled = True
    j = job("Associate Engineer")
    result = ai.review([j], cfg, {"AI_API_KEY": "k"}, post=lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")),
                       sleep=lambda s: None)
    assert result.unreviewed == [j] and not ai.is_hidden(j, cfg)


# -- the judge ------------------------------------------------------------------------------------------------------------------

class FakeReview:
    def __init__(self, verdicts=None, fail=False):
        self.verdicts, self.fail, self.asked = verdicts or {}, fail, []

    def __call__(self, jobs, cfg, env, profile_extra=""):
        self.asked.extend(j.title for j in jobs)
        result = ai.ReviewResult(scored=0)
        for j in jobs:
            if self.fail:
                result.unreviewed.append(j)
                continue
            j.ai_verdict = self.verdicts.get(j.title, "match")
            j.ai_score = {"no": 3, "maybe": 5, "match": 8}[j.ai_verdict]
            j.ai_reason = "reason for " + j.title
            result.scored += 1
        result.held = [j for j in jobs if ai.is_hidden(j, cfg)]
        return result


def run_judge(cfg, tmp_path, jobs, review, env=None, **kw):
    cfg.ai.enabled = True
    return judge.judge(jobs, cfg, {"AI_API_KEY": "k"} if env is None else env, Schedule(tmp_path / "s.json"), review=review, **kw)


def test_rule_misses_never_reach_the_ai_and_ai_misses_are_held_back(cfg, tmp_path):
    jobs = [job("Electrical Engineer"), job("Sales Engineer – Industrial Automation"), job("Associate Engineer", description=LONG_EEE),
            job("Associate Engineer – Platform SRE", description=LONG_IT)]
    review = FakeReview({"Associate Engineer – Platform SRE": "no"})
    out = run_judge(cfg, tmp_path, jobs, review)
    assert "Sales Engineer – Industrial Automation" not in review.asked  # turned away by the rules
    assert [j.title for j in out.shown] == ["Electrical Engineer", "Associate Engineer"]
    assert {j.title for j in out.held} == {"Sales Engineer – Industrial Automation", "Associate Engineer – Platform SRE"}
    assert out.waiting == []
    assert judge.held_note(out.held).startswith("Held back (not matching your requirements), closest first:")


def test_an_unread_posting_waits_instead_of_being_judged_on_its_title(cfg, tmp_path):
    jobs = [job("Associate Engineer"), job("Electrical Engineer")]
    jobs[0].unread = True
    review = FakeReview()
    out = run_judge(cfg, tmp_path, jobs, review)
    assert [j.title for j in out.waiting] == ["Associate Engineer"] and [j.title for j in out.shown] == ["Electrical Engineer"]
    assert review.asked == ["Electrical Engineer"]  # no AI request wasted on a title alone
    assert any("waiting" in n for n in out.notes)


def test_a_waiting_job_is_judged_on_what_exists_after_enough_tries(cfg, tmp_path):
    schedule = Schedule(tmp_path / "s.json")
    cfg.ai.defer_runs = 3
    j = job("Associate Engineer")
    j.unread = True
    for _ in range(3):
        schedule.put_off(j.uid, TODAY.isoformat())
    out = judge.judge([j], cfg, {}, schedule, review=FakeReview())
    assert out.waiting == [] and out.shown == []  # still nothing shows electrical work: not sent
    assert out.held == [j] and "nothing in the title or posting" in j.ai_reason
    keyword = job("Telecom Engineer")
    keyword.unread = True
    for _ in range(3):
        schedule.put_off(keyword.uid, TODAY.isoformat())
    assert judge.judge([keyword], cfg, {}, schedule, review=FakeReview()).shown == [keyword]  # a title naming a field is enough


def test_when_the_ai_cannot_answer_uncertain_jobs_wait_and_clear_ones_go(cfg, tmp_path):
    clear, vague = job("Electrical Engineer"), job("Associate Engineer")
    out = run_judge(cfg, tmp_path, [clear, vague], FakeReview(fail=True))
    assert out.shown == [clear] and out.waiting == [vague]  # a title that names an EEE field needs no AI
    assert any("AI couldn't be asked" in n for n in out.notes)


def test_without_an_ai_key_the_plain_rules_decide_and_nothing_waits(cfg, tmp_path):
    jobs = [job("Associate Engineer", description="Test and commission PLC control panels and switchgear. " * 6),
            job("Associate Engineer", source_id="x2"), job("Marketing Executive"), job("Electrical Engineer")]
    out = run_judge(cfg, tmp_path, jobs, FakeReview(), env={})
    assert [j.title for j in out.shown] == ["Associate Engineer", "Electrical Engineer"] and out.shown[0].description
    assert sorted(j.title for j in out.held) == ["Associate Engineer", "Marketing Executive"]  # the one with no text shows nothing
    assert out.waiting == []


def test_out_of_time_skips_the_ai_and_waits(cfg, tmp_path):
    review = FakeReview()
    out = run_judge(cfg, tmp_path, [job("Associate Engineer")], review, time_left=30)
    assert not review.asked and out.waiting and "out of time" in out.ai_note


def test_resend_all_never_waits(cfg, tmp_path):
    j = job("Associate Engineer")
    j.unread = True
    out = run_judge(cfg, tmp_path, [j], FakeReview(), wait=False)
    assert out.waiting == [] and out.shown == [j]


# -- waiting is remembered ---------------------------------------------------------------------------------------------------------

def test_put_offs_are_saved_counted_and_forgotten(tmp_path):
    s = Schedule(tmp_path / "s.json")
    assert s.put_off("a", "2026-10-23") == 1 and s.put_off("a", "2026-10-23") == 2 and s.put_off("b", "2026-10-19") == 1
    s.save()
    again = Schedule(tmp_path / "s.json")
    assert again.put_offs("a") == 2
    again.forget_old_put_offs("2026-10-23")  # "b" is older than three days
    assert again.put_offs("b") == 0 and again.put_offs("a") == 2
    again.settle("a")
    assert again.put_offs("a") == 0


# -- reading the postings -------------------------------------------------------------------------------------------------------------

class Cache:
    def __init__(self):
        self.entries = {}

    def get(self, uid):
        return self.entries.get(uid)

    def put(self, uid, posting, today):
        self.entries[uid] = {"text": posting.text, "via": "", "email": "", "closing": ""}
        return self.entries[uid]

    def touch(self, uid, today):
        pass


def test_enrich_marks_unread_postings_and_caps_linkedin(cfg, monkeypatch):
    cfg.postings.linkedin_max, cfg.postings.workers = 2, 1
    monkeypatch.setattr(postings, "read_posting", lambda http, url, *a, **k: postings.Posting(text="BSc in electrical engineering " * 30, via=["page"]))
    jobs = [job(f"Engineer {i}", url=f"https://www.linkedin.com/jobs/view/{1000000 + i}/") for i in range(4)]
    jobs.append(job("Other", source="topjobs.lk", url="https://www.topjobs.lk/x"))
    cache = Cache()
    stats = postings.enrich(jobs, cache, cfg, TODAY, http=type("H", (), {"clone": lambda self: self})())
    assert [j.unread for j in jobs] == [False, False, True, True, False]  # LinkedIn: two per run, the rest next time
    assert stats.left == 2 and stats.opened == 3


def test_a_page_that_is_gone_is_not_waited_for(cfg, monkeypatch):
    import requests
    cfg.postings.workers = 1

    def gone(http, url, *a, **k):
        raise requests.HTTPError(response=type("R", (), {"status_code": 404})())

    monkeypatch.setattr(postings, "read_posting", gone)
    j = job("Gone", source="topjobs.lk", url="https://www.topjobs.lk/gone")
    postings.enrich([j], Cache(), cfg, TODAY, http=type("H", (), {"clone": lambda self: self})())
    assert j.unread is False


# -- the whole run ------------------------------------------------------------------------------------------------------------------------

def test_run_holds_back_misses_and_defers_the_unreadable(tmp_path, monkeypatch, cfg):
    from pathlib import Path

    import yaml

    from jobot import main as jobot_main

    class Site:
        NAME = "Site"

        @staticmethod
        def fetch(http, opts, cfg):
            return [
                Job(source="Site", source_id="1", title="Electrical Engineer", url="https://s/1", company="Lanka Power", location="Colombo"),
                Job(source="Site", source_id="2", title="FPGA Engineer Acme · Austin, TX", url="https://s/2"),
                Job(source="Site", source_id="3", title="Sales Engineer – Industrial Automation", url="https://s/3"),
                Job(source="Site", source_id="4", title="Power Engineer", url="https://s/4", company="CEB", location="Kandy"),
            ]

    sent = []

    class Channel:
        @staticmethod
        def send(report, env):
            sent.append(report)

    def unreadable(http, url, *a, **k):
        import requests
        raise requests.HTTPError(response=type("R", (), {"status_code": 429})())

    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setattr(jobot_main, "SOURCES", {"site": Site})
    monkeypatch.setattr(jobot_main.notifiers, "configured_channels", lambda env: {"fake": Channel})
    monkeypatch.setattr(jobot_main.postings, "read_posting", unreadable)
    config = tmp_path / "config.yaml"
    raw = yaml.safe_load((Path(__file__).parent / "fixtures" / "default_config.yaml").read_text(encoding="utf-8"))
    raw["sources"] = {"site": {}}
    raw["include_overseas"] = False
    raw["subfields"]["technical_sales"]["enabled"] = False
    config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    state = tmp_path / "seen.json"
    args = ["--config", str(config), "--state", str(state)]

    assert jobot_main.run(args) == 0
    assert sent[0].jobs == []  # both clear matches wait: their postings could not be opened (HTTP 429)
    assert "waiting" in sent[0].email_text()
    seen = json.loads(state.read_text()) if state.exists() else {"ids": {}}
    assert "Site:1" not in seen["ids"] and "Site:3" in seen["ids"] and "Site:2" not in json.dumps(seen)
    schedule = json.loads((tmp_path / "schedule.json").read_text())
    assert set(schedule["deferred"]) == {"Site:1", "Site:4"}

    # the posting opens on the next run: both go out, and the waiting list is cleared
    monkeypatch.setattr(jobot_main.postings, "read_posting",
                        lambda http, url, *a, **k: jobot_main.postings.Posting(text="Commissioning of electrical switchgear, BSc in electrical engineering. " * 8, via=["page"]))
    assert jobot_main.run(args) == 0
    assert sorted(j.title for j in sent[1].jobs) == ["Electrical Engineer", "Power Engineer"]
    assert "deferred" not in json.loads((tmp_path / "schedule.json").read_text())


def test_a_rescued_job_with_no_electrical_evidence_is_not_let_in_on_a_maybe(cfg, tmp_path):
    piling = job("Trainee Engineers", description="Trainee engineers needed for our shoring and piling projects.", company="Rohana Shoring & Piling")
    piling.rescued = "rule"
    real = job("Associate Engineer", description="Install and test low-voltage switchgear and PLC panels. " * 4)
    real.rescued = "ai"
    out = run_judge(cfg, tmp_path, [piling, real], FakeReview({"Trainee Engineers": "maybe", "Associate Engineer": "maybe"}))
    assert [j.title for j in out.shown] == ["Associate Engineer"] and out.held == [piling]
    assert "doesn't show electrical" in piling.ai_reason


@pytest.mark.parametrize("text", ["FPGA Engineer GMV · Lisbon, Lisbon, Portugal · Email alert (linkedin.com)", "RF Engineer · Europe", "Hardware Engineer · Atlanta"])
def test_more_places_abroad(cfg, text):
    assert filters.foreign_place(text)


@pytest.mark.parametrize("title", [
    "IT Executive - Chilaw", "IT Assistant / IT Executive", "Executive - IT", "IT Support Specialist (Hard Ware)",
    "Executive - Information Technology", "IT and Digital Services Officer", "AI Transformation Officer",
    "Information Security Engineer", "Server Support Engineer", "Customer Support Engineer",
    "Education & Enablement Specialist (Technical Writer)", "Graphic Designer | IT Hardware & Social Media Administrator",
    "Executive - Purchase", "Assistant Lecturer - IT ( Badulla Branch)", "Lecturer - IT ( Galle Branch)",
    "Visiting Lecturers - IT | Networking | Software Engineering | Cyber Security", "IoT Data Engineer",
])
def test_it_office_and_other_non_eee_titles_are_turned_away_by_the_rules(cfg, title):
    assert requirements.assess(job(title, source="topjobs.lk"), cfg)[0] == "no"


@pytest.mark.parametrize("title", [
    "Electrical Engineer", "Network Engineer", "ELV Engineer", "Embedded Engineer", "Lecturer - Electrical Engineering",
    "Project Engineer - BMS | ELV", "UPS Engineer", "Core Network Engineer", "Maintenance Engineer", "Electronics Engineer (m/f/d)",
    "Solar Electrical Engineer (O&M)", "Network Administrator",
])
def test_real_eee_titles_pass_the_rules(cfg, title):
    assert requirements.assess(job(title, source="topjobs.lk"), cfg)[0] in ("match", "maybe")


def test_an_it_title_with_real_electrical_content_in_the_posting_is_not_turned_away(cfg):
    j = job("IT Support Engineer", description="Install, test and repair routers, switches, UPS units and structured cabling on site. " * 4)
    assert requirements.assess(j, cfg)[0] == "maybe"


def test_a_bare_lecturer_post_needs_electrical_content_in_the_posting(cfg, tmp_path):
    bare = job("POST OF LECTURER (ON CONTRACT)", source="gazette.lk")
    eee = job("POST OF LECTURER (ON CONTRACT)", source="gazette.lk", source_id="2",
              description="Department of Electrical and Electronic Engineering seeks a lecturer in power systems and electronics. " * 3)
    assert requirements.assess(bare, cfg)[0] == "maybe" and requirements.assess(eee, cfg)[0] == "maybe"
    out = run_judge(cfg, tmp_path, [bare, eee], FakeReview(), env={})
    assert out.shown == [eee] and out.held == [bare]


def test_the_level_requirement_states_the_years_from_your_settings(cfg):
    text = " ".join(requirements.lines(cfg))
    assert "Mid level (2-4 years of experience)" in text and "more than 4 years" in text
    assert "Network engineering and network administration" in text


def test_linkedin_alert_links_are_cleaned_and_can_be_read(cfg):
    from email.message import EmailMessage

    from jobot.sources import mailbox

    msg = EmailMessage()
    msg["From"], msg["Subject"] = "LinkedIn <jobs-noreply@linkedin.com>", "Jobs for you"
    msg.set_content("x")
    msg.add_alternative('<a href="https://www.linkedin.com/comm/jobs/view/4480962453/?trackingId=abc%3D%3D&amp;trk=eml-x">'
                        'Engineer I NPI</a><a href="https://www.linkedin.com/comm/jobs/view/4471983716?trk=y">Jobs similar to FPGA Engineer</a>',
                        subtype="html")
    (j,) = mailbox.parse_message(msg.as_bytes(), ["linkedin.com"])
    assert j.url == "https://www.linkedin.com/jobs/view/4480962453/" and j.title == "Engineer I NPI"
    assert postings.page_url("https://www.linkedin.com/comm/jobs/view/4480962453?trk=x").endswith("/jobPosting/4480962453")
