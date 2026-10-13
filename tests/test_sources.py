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


def test_observerjobs_parse(fixture_text):
    from jobot.sources import observerjobs
    jobs, last_page = observerjobs.parse(fixture_text("observerjobs.html"))
    assert last_page == 4
    first = jobs[0]
    assert "Engineer ( Electrical )" in first.title
    assert first.company == "National Water Supply And Drainage Board"
    assert (first.posted, first.closing) == ("2026-10-12", "2026-10-30")
    assert first.url.startswith("https://www.observerjobs.lk/vacancy/536/")
    assert "Engineering (Mech/Civil/Elect/Auto)" in first.category


def test_lankajobs_parse(fixture_text):
    from jobot.sources import lankajobs
    jobs, last_page = lankajobs.parse(fixture_text("lankajobs.html"))
    assert last_page == 4
    job = jobs[1]
    assert (job.title, job.company) == ("Engineer (Transmission)", "Independent Television Network Ltd")
    assert (job.posted, job.closing) == ("2026-10-08", "2026-10-14")  # site uses month/day/year
    assert job.url == "https://lankajobs.lk/Jobs/engineer-transmission-independent-television-network-ltd-sri-lanka"


def test_rss_parse_rss_and_atom(fixture_text):
    from jobot.sources import rss
    jobs = rss.parse(fixture_text("gazette_feed.xml"), "Gazette.lk")
    assert jobs[0].source == "Gazette.lk"
    assert jobs[0].title.startswith("Resident Engineer – Rubber Research Institute")
    assert jobs[0].posted == "2026-10-12"
    assert "Engineer Job Vacancies" in jobs[0].category
    assert "&#8211;" not in jobs[0].description
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>tag:x,1</id>
      <title>Electrical Engineer – Example PLC</title><link href="https://example.lk/jobs/1"/>
      <published>2026-10-11T08:00:00Z</published><summary>&lt;p&gt;PLC and SCADA&lt;/p&gt;</summary></entry></feed>"""
    [job] = rss.parse(atom, "Example")
    assert (job.title, job.url, job.posted, job.description) == (
        "Electrical Engineer – Example PLC", "https://example.lk/jobs/1", "2026-10-11", "PLC and SCADA")


def test_company_pages_parse(fixture_text):
    from jobot.sources import company_pages
    page = {"name": "SLT-Mobitel", "url": "https://careers.slt.lk/", "subfield": "telecom"}
    jobs = company_pages.parse(fixture_text("slt_careers.html"), page)
    assert [j.title for j in jobs] == ["TECHNICIAN (OCT 2026)", "Notice – Electrical Engineer (Grade III)"]
    assert jobs[0].url.startswith("https://careers.slt.lk/Application/InitApply")
    assert jobs[0].subfields == ["telecom"] and jobs[0].company == "SLT-Mobitel"


def test_company_page_subfield_survives_filtering(cfg, fixture_text):
    from jobot.filters import select_jobs
    from jobot.sources import company_pages
    page = {"name": "SLT-Mobitel", "url": "https://careers.slt.lk/", "subfield": "telecom"}
    picked = select_jobs(company_pages.parse(fixture_text("slt_careers.html"), page), cfg)
    assert picked[0].title == "TECHNICIAN (OCT 2026)" and picked[0].subfields == ["telecom"]
    cfg.only_subfields(["power"])  # telecom switched off -> plain technician link no longer matches
    picked = select_jobs(company_pages.parse(fixture_text("slt_careers.html"), page), cfg)
    assert [j.title for j in picked] == []
