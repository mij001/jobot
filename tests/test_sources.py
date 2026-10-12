import json

from jobot.sources import ikman, linkedin, rooster, topjobs, xpressjobs


def test_topjobs_parse(fixture_text):
    jobs = topjobs.parse(fixture_text("topjobs.html"), category="topjobs:MAE")
    assert len(jobs) == 3
    first = jobs[0]
    assert first.title == "Assistant Engineer"  # "(1)" vacancy count stripped
    assert first.company == "Jobfactory"
    assert first.posted == "2026-10-12" and first.closing == "2026-10-19"
    assert first.location == "Moragahahena"
    assert "jc=0001558876" in first.url and first.source_id == "1558876"
    # Some ads use letter codes for the agency/employer.
    assert "ac=DEFZZZ" in jobs[1].url


def test_xpressjobs_to_job(fixture_text):
    items = json.loads(fixture_text("xpressjobs.json"))
    job = xpressjobs.to_job(items[0], category="Electronics / Electrical", level_hint="mid")
    assert job.title == "Design and Planning Engineer – Electrical"
    assert job.company == "Hayleys Fentons Limited"
    assert job.url == "https://xpress.jobs/jobs/view/340332"
    assert job.closing == "2026-10-26"
    assert "five years" in job.description
    assert job.level_hint == "mid"


def test_xpressjobs_fetch_tags_career_levels(cfg, fixture_text):
    items = json.loads(fixture_text("xpressjobs.json"))

    class FakeHttp:
        def get(self, url, params=None):
            class R:
                @staticmethod
                def json():
                    if url == xpressjobs.FILTERS_API:
                        return {"sectors": [{"sectorId": 24, "sectorName": "Electronics / Electrical"}]}
                    if params["page"] > 1:
                        return []
                    if params.get("careerLevels") == 3:
                        return [items[0]]
                    if params.get("careerLevels"):
                        return []
                    return items
            return R()

    opts = {"sectors": [24], "career_levels": {1: "entry", 3: "mid"}}
    jobs = xpressjobs.fetch(FakeHttp(), opts, cfg)
    assert [(j.source_id, j.level_hint, j.category) for j in jobs] == [
        ("340332", "mid", "Electronics / Electrical"),
        ("338459", None, "Electronics / Electrical"),
    ]


def test_ikman_parse(fixture_text):
    jobs, pages = ikman.parse(fixture_text("ikman.html"), "engineer-jobs")
    assert pages == 2
    assert [j.title for j in jobs] == ["Maintenance Officer - Ahangama", "Electrical Engineer"]
    assert jobs[0].url == "https://ikman.lk/en/ad/maintenance-officer-ahangama-galle-1"
    assert jobs[0].salary == "Rs 120,000 - 170,000"
    assert jobs[0].closing == "2026-10-31"
    assert jobs[0].category == "Engineering"
    assert ikman.parse(fixture_text("ikman.html"), "internships-and-trainees-jobs")[0][0].level_hint == "internship"


def test_rooster_to_job(fixture_text):
    items = json.loads(fixture_text("rooster.json"))["body"]["data"]
    sales, eng = (rooster.to_job(i) for i in items)
    assert sales.salary == "180,000 - 200,000 LKR month"
    assert eng.url == "https://rooster.jobs/jobs/515801"
    assert "**" not in eng.description
    assert eng.category == "Engineering / Electrical Engineering / Engineering"
    assert eng.level_hint == "internship"
    assert eng.posted == "2026-10-05"


def test_linkedin_parse_both_card_layouts(fixture_text):
    jobs = linkedin.parse(fixture_text("linkedin.html"))
    assert [(j.source_id, j.title, j.company) for j in jobs] == [
        ("4012345678", "Electrical Engineer", "Example Power (Pvt) Ltd"),
        ("4087654321", "Embedded Engineering Intern", "ChipWorks"),
    ]
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/4012345678/"
    assert jobs[0].location == "Colombo, Western Province, Sri Lanka"
    assert jobs[1].posted == "2026-10-08"


def test_linkedin_experience_filter(cfg):
    opts = {"experience_codes": {"internship": [1], "entry": [2, 3], "mid": [3, 4],
                                 "senior": [4], "management": [5, 6]}}
    assert linkedin.experience_filter(opts, cfg) == "1,2,3,4"
    cfg.only_levels(["internship"])
    assert linkedin.experience_filter(opts, cfg) == "1"
    cfg.only_levels([lv.key for lv in cfg.levels])
    assert linkedin.experience_filter(opts, cfg) == ""


def test_linkedin_waits_and_retries_once_when_rate_limited(cfg, fixture_text, monkeypatch):
    import requests

    waits = []
    monkeypatch.setattr(linkedin.time, "sleep", waits.append)
    calls = {"n": 0}

    class Resp:
        def __init__(self, status, text=""):
            self.status_code, self.text = status, text

    class FakeHttp:
        def get(self, url, params=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.HTTPError(response=Resp(429))
            return Resp(200, fixture_text("linkedin.html"))

    jobs = linkedin.fetch(FakeHttp(), {"keywords": ["electrical engineer"], "retry_wait_seconds": 30}, cfg)
    assert waits == [30] and len(jobs) == 2
