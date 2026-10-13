"""The posting reader (jobot.postings) and the degree / diploma filter."""

from datetime import date

import pytest
import requests

from jobot import postings
from jobot.filters import classify_qualifications, qualification_allowed, select_jobs
from jobot.models import Job

TODAY = date(2026, 10, 13)


def job(title, description="", sid=None, **kw):
    return Job(source=kw.pop("source", "topjobs.lk"), source_id=sid or title, title=title,
               url=kw.pop("url", "https://www.topjobs.lk/x/" + title.replace(" ", "-")),
               description=description, **kw)


@pytest.fixture
def page(fixture_text):
    return lambda name: fixture_text(f"postings/{name}")


# -- site readers --------------------------------------------------------------

def test_topjobs_reader_finds_poster(page):
    url = "https://www.topjobs.lk/employer/JobAdvertismentServlet?ac=DEFZZZ&jc=0001556801&ec=DEFZZZ"
    text, images, pdfs = postings.reader_for(url)(page("topjobs_ad.html"), url)
    assert text == "" and pdfs == []
    # Only the advert poster, not the site's own banner outside #remark.
    assert images == ["https://www.topjobs.lk/logo/DEFZZZ/8483c1022.png"]


def test_ikman_reader_uses_description_and_details(page):
    text, images, _ = postings.read_ikman(page("ikman_ad.html"), "https://ikman.lk/en/ad/hvac-engineer-colombo-1")
    text = postings.normalise(text)
    assert "Bachelor’s degree in Mechanical Engineering" in text  # 𝐁𝐨𝐥𝐝 letters made plain
    assert "Required education: Degree" in text
    assert images[0].endswith("/1200/1200/fitted.jpg")
    assert postings.find_email(text) == "careers@softlogic.lk"


def test_gazette_reader_prefers_english_pdf(page):
    text, images, pdfs = postings.read_gazette(page("gazette_post.html"), "https://www.gazette.lk/2026/10/x.html")
    assert pdfs[0].endswith("Resident-Engineer-RRISL-E.pdf")
    assert not any(p.endswith("-S.pdf") for p in pdfs)
    assert images == []  # the title banner isn't the advert
    assert "Closing Date: 2026-10-30" in text


def test_other_readers(page):
    text, images, _ = postings.read_lankajobs(page("lankajobs_job.html"), "https://lankajobs.lk/Jobs/x")
    assert "Engineer (Transmission)" in text and images[0].endswith("179143688808-en.jpg")
    text, images, _ = postings.read_techjobs(page("techjobs_job.html"), "https://techjobs.lk/vacancy?vacancy_id=1")
    assert images == ["https://techjobs.lk/./assets/images/job_posters/24-04-2020-015.jpg"]
    text, _, _ = postings.read_itpro(page("itpro_job.html"), "https://itpro.lk/job/15081/x")
    assert "PCB design" in text and "Login" not in text


def test_linkedin_link_is_rewritten_to_public_posting():
    assert postings.page_url("https://www.linkedin.com/jobs/view/4012345678/") == \
        "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4012345678"
    assert postings.page_url("https://ikman.lk/en/ad/x") == "https://ikman.lk/en/ad/x"


# -- extracting details ------------------------------------------------------------

def test_dates_emails_and_noise():
    assert postings.parse_date("30.10.2026") == "2026-10-30"
    assert postings.parse_date("2026/10/30") == "2026-10-30"
    assert postings.parse_date("30th October 2026") == "2026-10-30"
    assert postings.parse_date("Oct 30, 2026") == "2026-10-30"
    assert postings.find_closing("Applications should reach us on or before 25th October 2026.") == "2026-10-25"
    assert postings.find_closing("Closing date : 21/10/2026") == "2026-10-21"
    assert postings.find_email("Send CV to hr@acme.lk or visit topjobs (help@topjobs.lk)") == "hr@acme.lk"
    assert postings.find_email("logo@2x.png") == ""
    assert postings.normalise("𝐁𝐒𝐜 in​ EEE\n~ |\n\n  NVQ   5") == "BSc in EEE\nNVQ 5"
    assert not postings.useful("ACME\nLOGO")


def test_requirement_summary(cfg):
    one_line = "We are hiring. " * 12 + "Applicants must have a BSc in Electrical Engineering and 2 years of experience " * 3
    snippet = postings.requirement_summary(one_line, cfg)
    assert snippet.startswith("Applicants must have a BSc") and snippet.endswith("…") and len(snippet) <= 142
    text = ("We are a leading company.\n• BSc in Electrical Engineering or equivalent\n"
            "• Minimum 2 years experience in power systems\n• Valid driving licence\n• Passed G.C.E. A/L")
    assert postings.requirement_summary(text, cfg) == (
        "BSc in Electrical Engineering or equivalent · Minimum 2 years experience in power systems")


# -- degree vs diploma ------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("BSc Engineering degree in Electrical", ["degree"]),
    ("B.Sc. (Eng) or HND / NDT in Electrical Engineering", ["degree", "diploma"]),
    ("NVQ Level 05 or 06 in Electrical", ["diploma"]),
    ("NVQ L4 in electrical wiring, passed O/L", ["vocational", "school"]),
    ("NVQ level 7 in Electronics", ["degree"]),
    ("360 degree feedback, temperatures up to 40 degrees Celsius", []),
    ("Required education: Diploma", ["diploma"]),
    ("Undergraduates following an Electrical Engineering degree", ["degree"]),
])
def test_classify_qualifications(cfg, text, expected):
    assert classify_qualifications(job("Engineer", text), cfg) == expected


def test_title_hints_only_when_advert_is_silent(cfg):
    assert classify_qualifications(job("Technical Officer (Electrical)"), cfg) == ["diploma"]
    assert classify_qualifications(job("Technical Officer (Electrical)", "BSc or NDT"), cfg) == ["degree", "diploma"]
    assert classify_qualifications(job("Electrical Engineer"), cfg) == []


def test_degree_holder_sees_degree_and_either_or_jobs(cfg):
    assert [q.key for q in cfg.enabled_qualifications] == ["degree"]  # the default
    jobs = [job("Electrical Engineer", "BSc in Electrical Engineering"),
            job("Electronics Engineer", "Degree or HND in Electronics"),
            job("Junior Electrical Engineer", "NDT / HND in Electrical Engineering"),
            job("Embedded Engineer")]  # doesn't say
    assert [j.title for j in select_jobs(jobs, cfg)] == ["Electrical Engineer", "Electronics Engineer", "Embedded Engineer"]
    assert jobs[1].qualifications == ["degree", "diploma"]
    cfg.include_unknown_qualification = False
    assert [j.title for j in select_jobs(jobs, cfg)] == ["Electrical Engineer", "Electronics Engineer"]
    cfg.only_qualifications(["diploma"])
    assert [j.title for j in select_jobs(jobs, cfg)] == ["Electronics Engineer", "Junior Electrical Engineer"]


def test_no_qualifications_configured_means_no_filter(cfg):
    cfg.qualifications = []
    assert qualification_allowed([], cfg) and qualification_allowed(["anything"], cfg)


# -- which jobs get opened -------------------------------------------------------------

def test_pick_matched_first_then_maybes(cfg):
    matched_job = job("Electrical Engineer")
    thin = job("Project Engineer", sid="thin")  # title alone isn't EEE: open the advert
    civil = job("Civil Engineer", sid="civil")  # other field: skip
    chef = job("Chef", sid="chef")  # not technical at all
    rich = job("Site Engineer", "x" * 400, sid="rich")  # already has a full description
    senior = job("Senior Project Engineer", sid="senior")  # senior level is off
    old = job("Maintenance Engineer", sid="old")
    all_jobs = [thin, civil, chef, rich, senior, old, matched_job]
    picked = postings.pick(all_jobs, [matched_job], lambda j: j is not old, cfg)
    assert [j.source_id for j in picked] == ["Electrical Engineer", "thin"]


# -- reading postings (network faked) ---------------------------------------------------

class FakeResponse:
    def __init__(self, url, body=b"", ctype="text/html", status=200):
        self.url, self.content, self.status_code = url, body, status
        self.headers = {"Content-Type": ctype}
        self.text = body.decode("utf-8", "replace")


class FakeHttp:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **kw):
        self.calls.append(url)
        resp = self.pages.get(url)
        if resp is None or resp.status_code >= 400:
            raise requests.HTTPError(response=resp or FakeResponse(url, status=404))
        return resp


POSTER_TEXT = """WE ARE HIRING
Electrical Engineer
Qualifications
BSc in Electrical Engineering
Minimum 2 years experience with PLC and SCADA systems
Send your CV to careers@acme.lk
Closing date 30.10.2026
Acme Engineering Private Limited, Colombo"""


def test_read_posting_ocrs_posters(page, monkeypatch):
    url = "https://www.topjobs.lk/employer/JobAdvertismentServlet?jc=1"
    poster = "https://www.topjobs.lk/logo/DEFZZZ/8483c1022.png"
    http = FakeHttp({url: FakeResponse(url, page("topjobs_ad.html").encode()),
                     poster: FakeResponse(poster, b"PNG", "image/png")})
    monkeypatch.setattr(postings.ocr, "image_text", lambda data: POSTER_TEXT if data == b"PNG" else "")
    got = postings.read_posting(http, url)
    assert got.via == ["poster"] and "BSc in Electrical Engineering" in got.text


def test_ai_reads_posters_ocr_cannot(page, monkeypatch):
    url = "https://www.topjobs.lk/employer/JobAdvertismentServlet?jc=2"
    poster = "https://www.topjobs.lk/logo/DEFZZZ/8483c1022.png"
    http = FakeHttp({url: FakeResponse(url, page("topjobs_ad.html").encode()),
                     poster: FakeResponse(poster, b"PNG", "image/png")})
    monkeypatch.setattr(postings.ocr, "image_text", lambda data: "LOGO")
    seen = []
    got = postings.read_posting(http, url, vision=lambda data, mime: seen.append(mime) or POSTER_TEXT)
    assert got.via == ["ai"] and seen == ["image/png"] and "SCADA" in got.text


def test_enrich_caches_and_applies(cfg, tmp_path, monkeypatch):
    a = job("Project Engineer", sid="a", url="https://acme.lk/jobs/a")
    b = job("Site Engineer", sid="b", url="https://slow.lk/jobs/b")
    c = job("Plant Engineer", sid="c", url="https://slow.lk/jobs/c")
    html = f"<html><body><article><p>{POSTER_TEXT.replace(chr(10), '<br>')}</p></article></body></html>".encode()
    http = FakeHttp({"https://acme.lk/jobs/a": FakeResponse("https://acme.lk/jobs/a", html),
                     "https://slow.lk/jobs/b": FakeResponse("https://slow.lk/jobs/b", status=429)})
    cache = postings.PostingCache(tmp_path / "postings_cache.json")
    stats = postings.enrich([a, b, c], cache, cfg, TODAY, http=http)
    # b was rate-limited, so c (same site) waits for the next run.
    assert (stats.opened, stats.failed, stats.left) == (1, 1, 1)
    assert http.calls == ["https://acme.lk/jobs/a", "https://slow.lk/jobs/b"]
    assert a.read_via == "page" and a.contact == "careers@acme.lk" and a.closing == "2026-10-30"
    assert a.requirements == "BSc in Electrical Engineering · Minimum 2 years experience with PLC and SCADA systems"
    assert select_jobs([a], cfg) == [a] and a.qualifications == ["degree"] and a.min_years == 2
    cache.save()

    # Next run: read from the cache, nothing fetched.
    again = job("Project Engineer", sid="a", url="https://acme.lk/jobs/a")
    http2 = FakeHttp({})
    stats = postings.enrich([again], postings.PostingCache(tmp_path / "postings_cache.json"), cfg, TODAY, http=http2)
    assert stats.cached == 1 and http2.calls == [] and "SCADA" in again.description

    cache.prune(date(2026, 10, 20))
    assert cache.entries == {}


@pytest.mark.skipif(not postings.ocr.available(), reason="Tesseract not installed")
def test_tesseract_reads_text_image(tmp_path):
    import shutil
    import subprocess
    if shutil.which("pdftoppm") is None:
        pytest.skip("poppler not installed")
    # Make a real image of text without extra Python packages: text -> PDF -> PNG.
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(_tiny_pdf("Electrical Engineer BSc required"))
    subprocess.run(["pdftoppm", "-r", "150", "-png", "-singlefile", str(pdf), str(tmp_path / "a")], check=True)
    text = postings.ocr.image_text((tmp_path / "a.png").read_bytes())
    assert "Electrical Engineer" in text
    assert "BSc required" in postings.ocr.pdf_text(pdf.read_bytes())


def _tiny_pdf(line: str) -> bytes:
    stream = f"BT /F1 24 Tf 40 100 Td ({line}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 200] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out
