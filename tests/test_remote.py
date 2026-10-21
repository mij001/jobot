"""Fully remote jobs: who may apply, the providers' formats, and the filters."""

import pytest

from jobot import history
from jobot.filters import select_jobs
from jobot.models import Job
from jobot.sources import linkedin, remote

OPEN = ["Worldwide", "Anywhere in the World", "Global", "APAC", "Asia", "South Asia", "Sri Lanka", "Anywhere", "Asia-Pacific",
        "Europe, LATAM, APAC, the U.S., Canada", "Worldwide excluding USA", "Remote – Asia (any time zone)"]
CLOSED = ["Anywhere in India", "USA, Canada, USA timezones", "Time zone: CET (+/- 3 hours)", "Southeast Asia", "East Asia",
          "Worldwide (must overlap US hours)", "North America", "Philippines", "Remote - India", "LATAM", "United States",
          "Worldwide, EST time zone", "Europe", "Germany", "Japan - Remote"]


@pytest.mark.parametrize("where", OPEN)
def test_open_to_sri_lanka(where):
    assert remote.open_to_sri_lanka(where)


@pytest.mark.parametrize("where", CLOSED)
def test_not_open_to_sri_lanka(where):
    assert not remote.open_to_sri_lanka(where)


def test_no_restriction_text_depends_on_the_board():
    assert not remote.open_to_sri_lanka("") and remote.open_to_sri_lanka("", empty_ok=True)


CLASSIC = ["remotive", "remoteok", "weworkremotely", "jobicy", "himalayas", "workingnomads"]


class FakeResp:
    def __init__(self, body=None, text=""):
        self._body, self.text = body, text

    def json(self):
        return self._body


class FakeBoards:
    """Answers each board's address with a small sample in that board's own format."""

    def __init__(self):
        self.warnings, self.requested = [], []

    def clone(self):
        return self

    def note(self, message):
        self.warnings.append(message)

    def get(self, url, params=None, **kw):
        self.requested.append((url, dict(params or {})))
        if "remotive" in url:
            return FakeResp({"jobs": [
                {"id": 1, "title": "Embedded Firmware Engineer", "url": "https://remotive.com/remote-jobs/1", "company_name": "Acme",
                 "candidate_required_location": "Worldwide", "publication_date": "2026-10-17T16:04:29", "salary": "$40k",
                 "category": "Engineering", "description": "<p>C and <b>RTOS</b></p>"},
                {"id": 2, "title": "Hardware Engineer", "url": "https://remotive.com/remote-jobs/2", "company_name": "Beta",
                 "candidate_required_location": "USA, Canada, USA timezones", "publication_date": "2026-10-17T16:04:29"}]})
        if "remoteok" in url:
            return FakeResp([{"legal": "link back"},
                             {"id": "9", "position": "Electronics Engineer", "company": "Gamma", "url": "https://remoteok.com/9", "location": "",
                              "date": "2026-10-20T08:00:05+00:00", "tags": ["hardware"], "salary_min": "40000", "salary_max": "60000"},
                             {"id": "10", "position": "Analog Designer", "company": "Delta", "url": "https://remoteok.com/10", "location": "United States"}])
        if "weworkremotely" in url:
            return FakeResp(text="""<?xml version="1.0"?><rss version="2.0"><channel>
              <item><title>Epsilon: Network Engineer</title><region>Anywhere in the World</region><category>DevOps</category>
              <pubDate>Tue, 20 Oct 2026 10:00:00 +0000</pubDate><link>https://weworkremotely.com/jobs/1</link><guid>https://weworkremotely.com/jobs/1</guid>
              <description>&lt;p&gt;Run the &lt;b&gt;network&lt;/b&gt;&lt;/p&gt;</description></item>
              <item><title>Zeta: Sales Lead</title><region>North America</region><link>https://weworkremotely.com/jobs/2</link></item></channel></rss>""")
        if "jobicy" in url:
            return FakeResp({"jobs": [
                {"id": 5, "jobTitle": "PCB Layout Engineer", "url": "https://jobicy.com/jobs/5", "companyName": "Eta", "jobGeo": "Anywhere",
                 "jobIndustry": ["Engineering"], "jobExcerpt": "Layout", "pubDate": "2026-10-21T04:41:14+00:00", "salaryMin": "50000",
                 "salaryMax": "70000", "salaryCurrency": "USD", "salaryPeriod": "yearly"},
                {"id": 6, "jobTitle": "Applied AI Engineer", "url": "https://jobicy.com/jobs/6", "companyName": "Theta", "jobGeo": "USA"}]})
        if "himalayas" in url:
            return FakeResp({"jobs": [
                {"title": "FPGA Engineer", "applicationLink": "https://himalayas.app/jobs/1", "guid": "g1", "companyName": "Iota",
                 "locationRestrictions": [], "timezoneRestrictions": [-11, 0, 5.5, 8], "pubDate": 1792578733, "excerpt": "RTL"},
                {"title": "Embedded Developer", "applicationLink": "https://himalayas.app/jobs/2", "guid": "g2", "companyName": "Kappa",
                 "locationRestrictions": ["United States"], "timezoneRestrictions": [-8, -5]},
                {"title": "Firmware Engineer", "applicationLink": "https://himalayas.app/jobs/3", "guid": "g3", "companyName": "Lambda",
                 "locationRestrictions": [], "timezoneRestrictions": [-8, -7, -6, -5]},  # open to anyone but asks for US time zones
                {"title": "Hardware Engineer", "applicationLink": "https://himalayas.app/jobs/4", "guid": "g4", "companyName": "Mu",
                 "locationRestrictions": "['Worldwide']", "timezoneRestrictions": "[0, 5, 6]"}]})
        if "workingnomads" in url:
            return FakeResp([{"url": "https://www.workingnomads.com/job/go/1/", "title": "Test Engineer", "company_name": "Nu", "location": "Global",
                              "category_name": "Engineering", "pub_date": "2026-10-20T13:39:57-04:00"},
                             {"url": "https://www.workingnomads.com/job/go/2/", "title": "Support", "company_name": "Xi", "location": "Time zone: CET (+/- 3 hours)"}])
        raise AssertionError(url)


def test_every_board_is_read_and_only_jobs_open_to_sri_lanka_stay(cfg):
    http = FakeBoards()
    jobs = remote.fetch(http, {"workers": 1, "queries": ["embedded"], "jobicy_tags": ["pcb"], "remoteok_tags": [],
                               "providers": CLASSIC}, cfg)
    titles = sorted(j.title for j in jobs)
    assert titles == ["Electronics Engineer", "Embedded Firmware Engineer", "FPGA Engineer", "Hardware Engineer", "Network Engineer",
                      "PCB Layout Engineer", "Test Engineer"]
    assert all(j.remote and j.location.startswith("Remote –") for j in jobs) and not http.warnings
    by = {j.title: j for j in jobs}
    assert by["Embedded Firmware Engineer"].source == "Remotive" and by["Embedded Firmware Engineer"].description == "C and RTOS"
    assert by["Embedded Firmware Engineer"].posted == "2026-10-17" and by["Embedded Firmware Engineer"].location == "Remote – open worldwide"
    assert by["Electronics Engineer"].salary == "40,000 - 60,000 USD a year" and by["Electronics Engineer"].location == "Remote – open worldwide"
    assert by["Network Engineer"].company == "Epsilon" and by["Network Engineer"].location == "Remote – Anywhere in the World"
    assert by["PCB Layout Engineer"].salary.startswith("50,000 - 70,000 USD") and by["PCB Layout Engineer"].category == "Engineering"
    assert by["FPGA Engineer"].posted == "2026-10-21"
    assert by["Hardware Engineer"].url == "https://himalayas.app/jobs/4"  # the one with a worldwide list (as text) and a usable zone list
    assert {"search": "embedded"} in [p for u, p in http.requested if "remotive" in u]  # and the engineering category call too


def test_a_board_that_fails_is_a_warning_not_a_lost_source(cfg):
    class Flaky(FakeBoards):
        def get(self, url, params=None, **kw):
            if "himalayas" in url:
                raise RuntimeError("boom")
            return super().get(url, params, **kw)

    http = Flaky()
    jobs = remote.fetch(http, {"workers": 1, "queries": ["embedded"], "jobicy_tags": ["pcb"], "remoteok_tags": [], "providers": CLASSIC}, cfg)
    assert jobs and http.warnings == ["himalayas: RuntimeError: boom"]


def test_the_same_remote_job_on_two_boards_is_one_job(cfg):
    class Dup(FakeBoards):
        def get(self, url, params=None, **kw):
            if "remoteok" in url:
                return FakeResp([{"legal": ""}, {"id": "1", "position": "Network Engineer", "company": "Epsilon", "url": "https://remoteok.com/1", "location": ""}])
            return super().get(url, params, **kw)

    jobs = remote.fetch(Dup(), {"workers": 1, "providers": ["remoteok", "weworkremotely"]}, cfg)
    assert [j.title for j in jobs] == ["Network Engineer"]


def test_remote_jobs_skip_the_place_filters_but_not_the_field_filters(cfg):
    cfg.include_overseas, cfg.locations = False, ["Colombo"]
    hw = Job(source="Remote OK", source_id="1", title="Hardware Engineer", url="https://r/1", company="Acme", location="Remote – open worldwide", remote=True)
    chef = Job(source="Remote OK", source_id="2", title="Chef", url="https://r/2", location="Remote – open worldwide", remote=True)
    local = Job(source="topjobs.lk", source_id="3", title="Hardware Engineer", url="https://r/3", location="Kandy")
    assert [j.title for j in select_jobs([hw, chef, local], cfg)] == ["Hardware Engineer"]  # the Kandy job is out, the remote one is in
    assert select_jobs([hw], cfg)[0].remote


def test_history_marks_remote_jobs(cfg):
    from datetime import date
    job = Job(source="Remote OK", source_id="1", title="Hardware Engineer", url="https://r/1", remote=True)
    assert history.job_entry(job, date(2026, 10, 21), False, cfg)["remote"] is True
    assert "remote" not in history.job_entry(Job(source="S", source_id="2", title="Engineer", url="https://s/2"), date(2026, 10, 21), False, cfg)


def test_linkedin_remote_mode_asks_for_remote_and_keeps_only_places_open_to_sri_lanka():
    cards = """<li><div class="base-card" data-entity-urn="urn:li:jobPosting:1111111"><a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/embedded-engineer-1111111">x</a>
      <h3 class="base-search-card__title">Embedded Engineer</h3><h4 class="base-search-card__subtitle">Acme</h4><span class="job-search-card__location">Sri Lanka</span></div></li>
      <li><div class="base-card" data-entity-urn="urn:li:jobPosting:2222222"><a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/qa-2222222">x</a>
      <h3 class="base-search-card__title">QA Engineer</h3><h4 class="base-search-card__subtitle">Beta</h4><span class="job-search-card__location">United States</span></div></li>"""

    class FakeLinkedIn:
        def __init__(self):
            self.params = []

        def get(self, url, params=None):
            self.params.append(params)

            class R:
                text = cards
            return R()

    http = FakeLinkedIn()
    jobs = linkedin.fetch(http, {"remote": True, "keywords": ["embedded engineer"], "location": "Sri Lanka"}, __import__("jobot.config", fromlist=["x"]).load_config(
        __import__("pathlib").Path(__file__).parent / "fixtures" / "default_config.yaml"))
    assert http.params[0]["f_WT"] == "2"
    assert [(j.title, j.remote, j.location) for j in jobs] == [("Embedded Engineer", True, "Remote – Sri Lanka")]


# -- more boards -----------------------------------------------------------------------------------------------------------

def test_eligibility_has_a_third_answer_for_places_that_are_not_named():
    assert remote.eligibility("Remote") == "unsure" and remote.eligibility("") == "unsure"
    assert remote.eligibility("", empty="open") == "open"
    assert remote.eligibility("Remote - US") == "closed" and remote.eligibility("Remote – Toronto") == "closed"
    assert remote.eligibility("Worldwide") == "open" and remote.eligibility("REMOTE (Global)") == "open"
    assert remote.eligibility("Flexible / multiple locations") == "unsure"


class MoreBoards(FakeBoards):
    def get(self, url, params=None, **kw):
        self.requested.append((url, dict(params or {})))
        if "jobspresso" in url:
            return FakeResp(text="""<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
              <item><title>Firmware Engineer</title><link>https://jobspresso.co/job/1/</link><dc:creator><![CDATA[Acme<br>⚲&nbsp;Worldwide]]></dc:creator>
              <pubDate>Wed, 21 Oct 2026 09:00:37 +0000</pubDate><description><![CDATA[Write C for sensors]]></description></item>
              <item><title>Support Lead</title><link>https://jobspresso.co/job/2/</link><dc:creator><![CDATA[Beta<br>⚲&nbsp;United States]]></dc:creator></item>
              <item><title>Hardware Tester</title><link>https://jobspresso.co/job/3/</link><dc:creator><![CDATA[Gamma<br>⚲ Remote]]></dc:creator></item></channel></rss>""")
        if "nodesk" in url:
            return FakeResp(text="""<?xml version="1.0"?><rss version="2.0"><channel><item><title>Embedded Engineer at Delta</title>
              <link>https://nodesk.co/remote-jobs/delta-embedded/</link><description>Build firmware</description></item></channel></rss>""")
        if "hnrss" in url:
            return FakeResp(text="""<?xml version="1.0"?><rss version="2.0"><channel>
              <item><title><![CDATA[New comment by a in "Ask HN: Who is hiring?"]]></title><link>https://news.ycombinator.com/item?id=1</link>
              <pubDate>Mon, 20 Oct 2026 10:00:00 +0000</pubDate>
              <description><![CDATA[ <p>Epsilon | Senior Firmware Engineer | REMOTE (Global) | Full-time<p>We make sensors. Apply at epsilon.example]]></description></item>
              <item><title><![CDATA[New comment by b in "Ask HN"]]></title><link>https://news.ycombinator.com/item?id=2</link>
              <description><![CDATA[ <p>Zeta | Backend Engineer | Helsinki | ONSITE | Full-time<p>No remote here]]></description></item>
              <item><title><![CDATA[New comment by c in "Ask HN"]]></title><link>https://news.ycombinator.com/item?id=3</link>
              <description><![CDATA[ <p>Eta | Embedded Developer | REMOTE (US only, US time zones) | Full-time<p>Americans only]]></description></item>
              <item><title><![CDATA[New comment by d in "Ask HN"]]></title><link>https://news.ycombinator.com/item?id=4</link>
              <description><![CDATA[ <p>Just a question about remote work, no pipes here<p>x]]></description></item></channel></rss>""")
        if "greenhouse" in url:
            return FakeResp({"jobs": [{"id": 1, "title": "Test Engineer", "absolute_url": "https://gh.example/1", "location": {"name": "Remote - Anywhere"}},
                                      {"id": 2, "title": "Sales", "absolute_url": "https://gh.example/2", "location": {"name": "Remote - US"}},
                                      {"id": 3, "title": "Onsite", "absolute_url": "https://gh.example/3", "location": {"name": "Berlin"}}]})
        if "lever" in url:
            return FakeResp([{"id": "l1", "text": "Power Electronics Engineer", "hostedUrl": "https://lever.example/1", "workplaceType": "remote",
                              "categories": {"location": "Remote"}, "createdAt": 1792014273795, "descriptionPlain": "Design converters"},
                             {"id": "l2", "text": "Onsite", "hostedUrl": "https://lever.example/2", "workplaceType": "onsite", "categories": {"location": "Austin"}}])
        if "ashbyhq" in url:
            return FakeResp({"jobs": [{"id": "a1", "title": "PCB Engineer", "jobUrl": "https://ashby.example/1", "location": "Remote - Worldwide",
                                       "isRemote": True, "workplaceType": "Remote", "descriptionPlain": "Lay out boards", "publishedAt": "2026-10-01T00:00:00+00:00"},
                                      {"id": "a2", "title": "Hybrid", "jobUrl": "https://ashby.example/2", "location": "SF", "isRemote": True, "workplaceType": "Hybrid"}]})
        if "remoteok" in url and (params or {}).get("tag") == "hardware":
            return FakeResp([{"legal": ""}, {"id": "t1", "position": "Analog Designer", "company": "Theta", "url": "https://remoteok.com/t1", "location": ""}])
        return super().get(url, params, **kw)


def test_the_new_boards_are_read_and_unsure_jobs_are_kept_for_the_ai(cfg):
    http = MoreBoards()
    jobs = remote.fetch(http, {"workers": 1, "providers": ["jobspresso", "nodesk", "hn_hiring", "boards", "remoteok"], "remoteok_tags": ["hardware"],
                               "boards": [{"ats": "greenhouse", "slug": "g", "name": "GreenCo"}, {"ats": "lever", "slug": "l", "name": "LeverCo"},
                                          {"ats": "ashby", "slug": "a", "name": "AshbyCo"}, {"ats": "icims", "slug": "x", "name": "Nope"}]}, cfg)
    by = {j.title: j for j in jobs}
    assert sorted(by) == ["Analog Designer", "Electronics Engineer", "Embedded Engineer", "Firmware Engineer", "Hardware Tester", "PCB Engineer",
                          "Power Electronics Engineer", "Senior Firmware Engineer", "Test Engineer"]  # ("Electronics Engineer": Remote OK's front page)
    assert (by["Firmware Engineer"].remote_rule, by["Firmware Engineer"].location, by["Firmware Engineer"].company) == ("open", "Remote – open worldwide", "Acme")
    assert by["Hardware Tester"].remote_rule == "unsure" and by["Hardware Tester"].location == "Remote – Remote"  # names no place: for the AI
    assert by["Embedded Engineer"].remote_rule == "unsure" and by["Embedded Engineer"].company == "Delta" and by["Embedded Engineer"].location == "Remote – place not stated"
    assert by["Senior Firmware Engineer"].company == "Epsilon" and by["Senior Firmware Engineer"].remote_rule == "open" and by["Senior Firmware Engineer"].posted == "2026-10-20"
    assert by["Test Engineer"].remote_rule == "open" and by["Test Engineer"].source == "GreenCo"
    assert by["Power Electronics Engineer"].remote_rule == "unsure" and by["Power Electronics Engineer"].description == "Design converters"
    assert by["PCB Engineer"].source == "AshbyCo" and by["PCB Engineer"].remote_rule == "open"
    assert by["Analog Designer"].remote_rule == "open"  # Remote OK: an empty place means no restriction
    assert http.warnings == ["Nope: unknown job board type 'icims'"]
    assert ("https://remoteok.com/api", {"tag": "hardware"}) in http.requested


def test_nodesk_feed_with_html_entities_still_parses(cfg):
    class Feed(FakeBoards):
        def get(self, url, params=None, **kw):
            return FakeResp(text="""<?xml version="1.0"?><rss version="2.0"><channel><item><title>PCB Designer at Iota</title>
              <link>https://nodesk.co/remote-jobs/iota/</link><description>Boards that don&rsquo;t fail&nbsp;ever &amp; more</description></item></channel></rss>""")

    (job,) = remote.nodesk(Feed(), {})
    assert job.title == "PCB Designer" and job.company == "Iota" and "don\u2019t fail" in job.description and "& more" in job.description


def test_hn_hiring_prefers_the_algolia_api(cfg):
    class Algolia(FakeBoards):
        def get(self, url, params=None, **kw):
            self.requested.append((url, dict(params or {})))
            if "hnrss" in url:
                raise AssertionError("the fallback must not be needed")
            if "story,author_whoishiring" in (params or {}).get("tags", ""):
                return FakeResp({"hits": [{"objectID": "9", "title": "Ask HN: Who wants to be hired? (October 2026)"},
                                          {"objectID": "7", "title": "Ask HN: Who is hiring? (October 2026)"}]})
            return FakeResp({"hits": [
                {"objectID": "71", "parent_id": 7, "created_at": "2026-10-14T10:00:00Z",
                 "comment_text": "Epsilon | Firmware Engineer | REMOTE (Global) | Full-time<p>We make sensors"},
                {"objectID": "72", "parent_id": 71, "created_at": "2026-10-14T11:00:00Z",
                 "comment_text": "Reply | not an advert | REMOTE"},
                {"objectID": "73", "parent_id": 7, "created_at": "2026-10-14T12:00:00Z", "comment_text": "A question about remote work"}]})

    http = Algolia()
    (job,) = remote.hn_hiring(http, {})
    assert (job.title, job.company, job.posted, job.url) == ("Firmware Engineer", "Epsilon", "2026-10-14", "https://news.ycombinator.com/item?id=71")
    assert any(p.get("tags") == "comment,story_7" for _, p in http.requested)  # the "hired?" thread was not used
