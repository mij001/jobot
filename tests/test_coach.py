"""The career coach: counted skill demand / gaps / resume match, plus the AI parts (faked)."""

import json
from datetime import date

import pytest

from jobot import coach, resume
from jobot.history import History

TODAY = date(2026, 10, 15)
RESUME = resume.Resume(name="cv.pdf", kind="file", updated="2026-10-14", text="""Nimal Perera
BSc in Electrical and Electronic Engineering
Skills: Python, MATLAB, PLC (Siemens TIA Portal), AutoCAD, KiCad
Project: LoRa soil moisture network on ESP32 with MQTT""")


def entry(i, skills, importance="good", day="2026-10-10", closing=None, ai_score=7, **kw):
    e = {"id": f"S:{i}", "date": day, "title": f"Engineer {i}", "company": f"Co {i}", "importance": importance,
         "skills": skills, "ai_score": ai_score, "requirements": "BSc in EEE", **kw}
    if closing:
        e["closing"] = closing
    return e


ENTRIES = [
    entry(1, ["PLC", "SCADA / HMI", "Siemens"]),
    entry(2, ["PLC", "SCADA / HMI", "ETAP"], day="2026-10-12"),
    entry(3, ["SCADA / HMI", "Python"], importance="top"),
    entry(4, ["ETAP", "Power systems analysis"], closing="2026-10-14"),   # closed
    entry(5, ["SCADA / HMI", "Siemens", "PLC"], importance="low"),       # held back by the AI: ignored
    entry(6, ["IoT"], day="2026-06-01"),                                  # too old for the window
    entry(7, ["MQTT-less"]),
    entry(8, ["PLC"], day="2026-10-13"),
]


def test_demand_and_gaps_count_relevant_recent_adverts(cfg):
    resume_skills = {"Python", "PLC", "AutoCAD"}
    recent = coach.relevant_entries(ENTRIES, date(2026, 10, 1))
    assert [e["id"] for e in recent] == ["S:1", "S:2", "S:3", "S:4", "S:7", "S:8"]
    market = coach.demand(recent, resume_skills)
    assert market["jobs"] == 6
    top = {r["skill"]: r for r in market["skills"]}
    assert (top["PLC"]["jobs"], top["PLC"]["have"], top["PLC"]["share"]) == (3, True, 0.5)
    assert (top["SCADA / HMI"]["jobs"], top["SCADA / HMI"]["have"]) == (3, False)
    assert market["skills"][0]["skill"] in ("PLC", "SCADA / HMI")
    assert [g["skill"] for g in coach.gaps(market["skills"])] == ["SCADA / HMI", "ETAP"]  # asked for ≥ 2 times, not shown


def test_match_jobs_ranks_open_jobs_by_resume_fit():
    marks = {"S:3": {"s": "dismissed"}, "S:8": {"s": "shortlist"}}
    rows = coach.match_jobs(ENTRIES, {"Python", "PLC", "AutoCAD"}, marks, TODAY)
    assert [r["id"] for r in rows] == ["S:1", "S:2", "S:7", "S:8"]  # closed, dismissed and held-back jobs are out
    one = rows[0]
    assert (one["match"], one["matched"], one["missing"]) == (33, ["PLC"], ["SCADA / HMI", "Siemens"])
    assert rows[2]["match"] is None  # fewer than 2 skills in the advert: no percentage


class FakeAI:
    """Answers the three prompts the coach sends."""

    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, url, json, headers, timeout):
        system, user = (m["content"] for m in json["messages"])
        kind = ("analysis" if "resume (name and contact" in system else "projects" if "portfolio projects" in system
                else "prepare" if "prepare to apply" in system else "tailor")
        self.calls.append((kind, user))
        if kind in self.fail:
            return Resp(503, "busy")
        body = {
            "analysis": {"summary": "Solid graduate profile.", "level": "entry", "strengths": ["Embedded project", "Python"],
                         "gaps": ["No SCADA exposure"], "improvements": [{"area": "Projects", "tip": "Add the LoRa project's results"}],
                         "headline": "EEE graduate – embedded & automation", "skills": ["LoRa", "MQTT"],
                         "digest": "Final-year EEE graduate; Python, MATLAB, PLC basics; LoRa/ESP32 project."},
            "projects": {"projects": [{"title": "Mini SCADA with OpenPLC", "goal": "Monitor a pump", "why": "SCADA asked in 3 adverts",
                                       "skills": ["SCADA / HMI", "PLC"], "steps": ["Install OpenPLC", "Build HMI"], "deliverables": ["GitHub repo"],
                                       "weeks": 3, "difficulty": "intermediate", "show_it": "README with screenshots"}] * 6},
            "prepare": {"letter": "Dear hiring team, ...\n\n[Your name]", "bullets": ["Built a PLC pump controller"],
                        "keywords": ["SCADA", "PLC"], "questions": [{"q": "Explain ladder logic", "tip": "Use the pump project"}] * 9,
                        "study": ["Revise ladder logic"], "gaps": ["No ETAP: try the free trial"]},
            "tailor": {"results": [{"id": "S:1", "verdict": "Strong PLC fit", "tips": ["Lead with PLC work", "Mention TIA Portal", "third"]}]},
        }[kind]
        return Resp(200, json_body={"choices": [{"message": {"content": "```json\n" + json_dumps(body) + "\n```"}}]})


def json_dumps(o):
    return json.dumps(o)


class Resp:
    def __init__(self, status, text="", json_body=None):
        self.status_code, self.text, self._json, self.headers = status, text, json_body, {}
        self.ok = status < 400

    def json(self):
        return self._json


def test_full_report_with_ai(cfg):
    cfg.coach.projects = 2
    fake = FakeAI()
    report = coach.build_report(cfg, {"AI_API_KEY": "k"}, ENTRIES, {}, RESUME, TODAY, post=fake, sleep=lambda s: None)
    assert [c[0] for c in fake.calls] == ["analysis", "projects", "tailor"]
    assert "Nimal" not in fake.calls[0][1] and "[name]" in fake.calls[0][1]  # redacted before it leaves
    assert "SCADA / HMI: 3 of 6 adverts" in fake.calls[0][1]
    assert "SCADA / HMI (Control & automation): 3 adverts" in fake.calls[1][1] and "Final-year EEE graduate" in fake.calls[1][1]
    assert report["ai"] and report["model"] == "gemini-pro-latest"
    assert report["analysis"]["level"] == "entry" and report["analysis"]["skills"] == ["LoRa", "MQTT"]
    assert report["digest"].startswith("Final-year EEE graduate")
    assert [p["title"] for p in report["projects"]] == ["Mini SCADA with OpenPLC"] * 2  # capped at coach.projects
    assert report["projects"][0]["difficulty"] == "intermediate" and report["projects"][0]["weeks"] == 3
    top = report["matches"][0]
    assert top["id"] == "S:1" and top["verdict"] == "Strong PLC fit" and top["tips"] == ["Lead with PLC work", "Mention TIA Portal"]
    assert report["resume_skills"] == ["Python", "MATLAB / Simulink", "AutoCAD", "KiCad", "PLC", "Siemens",
                                       "ARM / STM32 / ESP32", "IoT"]
    assert report["resume_extra_skills"] == ["LoRa", "MQTT"]
    assert report["resume"] == {"name": "cv.pdf", "kind": "file", "updated": "2026-10-14", "chars": RESUME.chars, "sent_to_ai": True}


def test_each_ai_failure_degrades_one_part_only(cfg):
    report = coach.build_report(cfg, {"AI_API_KEY": "k"}, ENTRIES, {}, RESUME, TODAY,
                                post=FakeAI(fail={"analysis", "projects"}), sleep=lambda s: None)
    assert report["analysis"] is None and report["projects"] == []
    assert any("Resume analysis unavailable" in n for n in report["notes"]) and any("Project ideas unavailable" in n for n in report["notes"])
    assert report["digest"].startswith("Skills shown on the resume:") and report["matches"][0]["tips"]  # tips still worked
    assert report["demand"]["jobs"] == 6


def test_without_a_key_only_the_counted_parts(cfg):
    fake = FakeAI()
    report = coach.build_report(cfg, {}, ENTRIES, {}, RESUME, TODAY, post=fake)
    assert fake.calls == [] and not report["ai"] and report["analysis"] is None and report["projects"] == []
    assert report["demand"]["skills"] and report["matches"] and "no AI key" in report["notes"][-1]


def test_send_resume_off_keeps_the_text_away_from_the_ai(cfg):
    cfg.coach.send_resume = False
    fake = FakeAI()
    report = coach.build_report(cfg, {"AI_API_KEY": "k"}, ENTRIES, {}, RESUME, TODAY, post=fake, sleep=lambda s: None)
    assert [c[0] for c in fake.calls] == ["projects", "tailor"]
    everything = " ".join(c[1] for c in fake.calls)
    assert "BSc in Electrical" not in everything and "LoRa soil moisture" not in everything  # no resume text
    assert "Skills shown on the resume:" in fake.calls[0][1]
    assert report["resume"]["sent_to_ai"] is False and report["analysis"] is None


def test_thin_data_is_called_out(cfg):
    report = coach.build_report(cfg, {}, ENTRIES[:2], {}, RESUME, TODAY)
    assert "Only 2 relevant adverts" in report["notes"][0]


def test_weekly_schedule(cfg):
    cfg.coach.weekly_report = "sunday"
    assert coach.weekly_due(cfg, date(2026, 10, 18)) and not coach.weekly_due(cfg, date(2026, 10, 15))
    cfg.coach.weekly_report = "daily"
    assert coach.weekly_due(cfg, TODAY)
    cfg.coach.weekly_report = "off"
    assert not coach.weekly_due(cfg, TODAY)
    cfg.coach.weekly_report, cfg.coach.enabled = "daily", False
    assert not coach.weekly_due(cfg, TODAY)


@pytest.fixture
def fast_vault(monkeypatch):
    from jobot import vault
    monkeypatch.setattr(vault, "ITERATIONS", 1000)


def test_run_reads_the_vault_and_saves_the_report(tmp_path, cfg, fast_vault):
    from jobot.models import Job
    env = {"DASHBOARD_PASSWORD": "pw"}
    h = History.open(tmp_path, env)
    assert coach.run(cfg, env, h, TODAY) is None  # no resume yet
    h.add_jobs(date(2026, 10, 10), [Job(source="t", source_id="1", title="Controls Engineer", url="https://t/1",
                                         description="PLC and SCADA, ETAP studies. BSc in EEE.", subfields=["general"], qualifications=["degree"])],
               set(), cfg)
    h.save()
    h.vault.write(resume.NAME, {"kind": "text", "name": "pasted text", "updated": "2026-10-14", "text": RESUME.text})
    h.vault.write("marks", {})
    report = coach.run(cfg, {**env}, History.open(tmp_path, env), TODAY)
    assert report["demand"]["jobs"] == 1 and {r["skill"] for r in report["demand"]["skills"]} >= {"PLC", "SCADA / HMI", "ETAP"}
    again = History.open(tmp_path, env)
    assert again.vault.read("career")["date"] == "2026-10-15" and "career" in again.vault.meta["shards"]
    assert coach.digest_for_review(again, cfg).startswith("Skills shown on the resume:")
    cfg.coach.enabled = False
    assert coach.digest_for_review(again, cfg) == ""
    assert coach.digest_for_review(History.open(tmp_path, {}), cfg) == ""


def _vault_with_jobs(tmp_path, cfg, env):
    from jobot.models import Job
    h = History.open(tmp_path, env)
    def add(i, title, closing, day=date(2026, 10, 10)):
        h.add_jobs(day, [Job(source="t", source_id=str(i), title=title, url=f"https://t/{i}", company=f"Co {i}",
                             description="PLC and SCADA. BSc in EEE.", closing=closing, subfields=["general"])], set(), cfg)
    add(1, "Closes in two days", "2026-10-17")
    add(2, "Closes in ten days", "2026-10-25")
    add(3, "Not shortlisted, closes tomorrow", "2026-10-16")
    add(4, "Closed yesterday", "2026-10-14")
    h.save()
    return h


def test_closing_soon_lists_shortlisted_jobs_only(tmp_path, cfg, fast_vault):
    env = {"DASHBOARD_PASSWORD": "pw"}
    h = _vault_with_jobs(tmp_path, cfg, env)
    assert coach.closing_soon(h, TODAY) == []  # nothing shortlisted yet
    h.vault.write("marks", {"t:1": {"s": "shortlist", "t": "x"}, "t:2": {"s": "shortlist", "t": "x"},
                            "t:4": {"s": "shortlist", "t": "x"}, "t:3": {"s": "dismissed", "t": "x"}})
    rows = coach.closing_soon(History.open(tmp_path, env), TODAY)
    assert [(r["title"], r["days"]) for r in rows] == [("Closes in two days", 2)]
    assert coach.closing_soon(History.open(tmp_path, env), TODAY, days=10)[1]["title"] == "Closes in ten days"
    assert coach.closing_soon(History.open(tmp_path, {}), TODAY) == []


def test_reminders_appear_in_every_message_format(cfg):
    from jobot.report import Report
    rows = [{"id": "t:1", "title": "Site Engineer", "company": "ZTE", "url": "https://t/1", "closing": "2026-10-17", "days": 2}]
    report = Report([], [], cfg, TODAY, reminders=rows)
    assert "== Closing soon – your shortlist ==" in report.email_text() and "closes 2026-10-17 (in 2 days)" in report.email_text()
    assert "Closing soon" in report.email_html() and 'href="https://t/1"' in report.email_html()
    assert "⏰" in "\n".join(report.telegram_messages())
    assert "Closing soon" not in Report([], [], cfg, TODAY).email_text()


def test_weekly_lines_name_the_skills_to_build(tmp_path, cfg, fast_vault):
    env = {"DASHBOARD_PASSWORD": "pw"}
    h = History.open(tmp_path, env)
    assert coach.weekly_lines(h, cfg) == []
    h.write_named("career", {"demand": {"skills": [
        {"skill": "SCADA / HMI", "jobs": 31, "have": False}, {"skill": "PLC", "jobs": 40, "have": True},
        {"skill": "ETAP", "jobs": 22, "have": False}]}, "projects": [{"title": "Mini SCADA with OpenPLC"}]})
    assert coach.weekly_lines(h, cfg) == ["🎯 Skills to build: SCADA / HMI (31 adverts), ETAP (22 adverts)", "🛠 Portfolio idea: Mini SCADA with OpenPLC"]
    cfg.coach.enabled = False
    assert coach.weekly_lines(h, cfg) == []


def test_prepare_for_a_job_saves_and_keeps_only_the_newest(tmp_path, cfg, fast_vault, monkeypatch):
    env = {"DASHBOARD_PASSWORD": "pw", "AI_API_KEY": "k"}
    h = _vault_with_jobs(tmp_path, cfg, env)
    h.vault.write(resume.NAME, {"kind": "text", "text": RESUME.text, "updated": "2026-10-14"})
    fake = FakeAI()
    got = coach.prepare(cfg, env, History.open(tmp_path, env), "t:1", TODAY, post=fake, sleep=lambda s: None)
    kind, prompt = fake.calls[0]
    assert kind == "prepare" and "Closes in two days" in prompt and "[name]" in prompt and "Nimal" not in prompt
    assert got["letter"].endswith("[Your name]") and got["bullets"] == ["Built a PLC pump controller"]
    assert len(got["questions"]) == 8 and got["gaps"] and got["model"] == "gemini-pro-latest"
    store = History.open(tmp_path, env).vault.read("prepare")
    assert list(store) == ["t:1"]

    monkeypatch.setattr(coach, "KEEP_PREPARED", 2)
    for jid, day in (("t:2", date(2026, 10, 16)), ("t:3", date(2026, 10, 17))):
        coach.prepare(cfg, env, History.open(tmp_path, env), jid, day, post=fake, sleep=lambda s: None)
    assert sorted(History.open(tmp_path, env).vault.read("prepare")) == ["t:2", "t:3"]  # the oldest fell away

    assert coach.prepare(cfg, env, History.open(tmp_path, env), "nope:1", TODAY, post=fake) is None
    assert coach.prepare(cfg, {"DASHBOARD_PASSWORD": "pw"}, History.open(tmp_path, env), "t:1", TODAY, post=fake) is None  # no key
    no_resume = coach.prepare(cfg, {**env, "DASHBOARD_PASSWORD": "pw"}, History.open(tmp_path, env), "t:4", TODAY, post=fake, save=False)
    assert no_resume is not None and History.open(tmp_path, env).vault.read("prepare").keys() == {"t:2", "t:3"}  # save=False writes nothing


def test_empty_demand_is_not_reported_as_a_complete_resume(cfg):
    from jobot import resume as resume_mod
    entries = [{"id": f"t:{i}", "date": TODAY.isoformat(), "title": "Engineer", "importance": "good"} for i in range(6)]
    rsm = resume_mod.Resume(name="pasted text", kind="text", updated="", text="Python, MATLAB")
    report = coach.build_report(cfg, {"AI_API_KEY": "k"}, entries, {}, rsm, TODAY, post=FakeAI(), sleep=lambda s: None)
    assert report["demand"]["skills"] == []
    assert not any("already shows every skill" in n for n in report["notes"])
    assert any("No recognisable skills" in n for n in report["notes"])
