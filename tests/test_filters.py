import pytest

from jobot.filters import (
    classify_level,
    match_subfields,
    matches,
    select_jobs,
    years_required,
)
from jobot.models import Job


def job(title, description="", category="", source="topjobs.lk", sid=None, **kw):
    return Job(source=source, source_id=sid or title, title=title, url="https://x/" + title,
               description=description, category=category, **kw)


@pytest.mark.parametrize("keyword,text,expected", [
    ("plc", "PLC Programmer", True),
    ("plc", "replica parts", False),
    ("intern", "Electrical Intern", True),
    ("intern", "Internal Auditor", False),
    ("electric*", "Electricity Board", True),
    ("electrical engineer*", "Electrical Engineering Graduate", True),
    ("E&E", "Graduate in E&E", True),
    ("power system*", "Power  Systems Engineer", True),
    ("senior*", "Site Engineers – Seniors", True),
])
def test_keyword_matching(keyword, text, expected):
    assert matches(keyword, text) is expected


def test_title_match_tags_subfields(cfg):
    j = job("Electrical & Instrumentation Engineer")
    assert set(match_subfields(j, cfg)) >= {"automation", "general"}


def test_description_needs_technical_title_and_two_keywords(cfg):
    # Non-technical title: never matched on description alone.
    assert match_subfields(job("Sales Executive", "electrical, solar, PLC programming"), cfg) == []
    # Technical title but only one keyword in the description.
    assert match_subfields(job("Assistant Engineer", "Diploma in electrical required"), cfg) == []
    # Technical title and two different keywords.
    assert match_subfields(job("Assistant Engineer", "Knowledge of switchgear and SCADA"), cfg)


def test_category_counts_once(cfg):
    sector = "Electronics / Electrical"
    assert match_subfields(job("Technician", "", category=sector), cfg) == []
    assert match_subfields(job("Technician", "Electrical wiring", category=sector), cfg)


def test_plc_company_suffix_is_not_automation(cfg):
    j = job("Tea Factory Officer", "Kahawatte Plantations PLC is seeking an officer")
    assert match_subfields(j, cfg) == []


def test_disabled_subfield_is_ignored(cfg):
    cfg.only_subfields(["telecom"])
    assert match_subfields(job("Solar PV Engineer"), cfg) == []
    assert match_subfields(job("RF Engineer - 5G"), cfg) == ["telecom"]


@pytest.mark.parametrize("text,years", [
    ("Minimum 3 years of experience", 3),
    ("3-5 years experience in power systems", 3),
    ("A minimum of five years' relevant experience", 5),
    ("5+ yrs exp.", 5),
    ("Company with 25 years of history", None),
    ("Fresh graduates or 1 – 2 years of experience", 1),
])
def test_years_required(text, years):
    assert years_required(text) == years


@pytest.mark.parametrize("title,description,hint,level", [
    ("Electrical Engineering Intern", "", None, "internship"),
    ("Trainee Engineer - Electrical", "", None, "entry"),
    ("Associate Embedded Engineer", "", None, "entry"),
    ("Senior Electrical Engineer", "", None, "senior"),
    ("Senior Manager - Electrical", "", None, "management"),
    ("Electrical Engineer", "Minimum 3 years of experience", None, "mid"),
    ("Electrical Engineer", "At least 6 years experience", None, "senior"),
    ("Electrical Engineer", "", "entry", "entry"),
    ("Electrical Engineer", "", None, None),
])
def test_classify_level(cfg, title, description, hint, level):
    assert classify_level(job(title, description, level_hint=hint), cfg) == level


def test_select_filters_levels_and_merges_duplicates(cfg):
    jobs = [
        job("Electrical Engineer", company="ABC (Pvt) Ltd", sid="1"),
        job("Electrical Engineer", company="ABC Pvt Ltd", source="XpressJobs", sid="9"),
        job("Senior Electrical Engineer", company="ABC", sid="2"),  # senior disabled by default
        job("Accountant - Electrical Company", sid="3"),  # excluded title
        job("HR Executive", sid="4"),
    ]
    picked = select_jobs(jobs, cfg)
    assert [j.title for j in picked] == ["Electrical Engineer"]
    assert picked[0].also_on == [("XpressJobs", "https://x/Electrical Engineer")]


def test_unknown_level_toggle(cfg):
    cfg.include_unknown_level = False
    assert select_jobs([job("Electrical Engineer")], cfg) == []


def test_overseas_toggle(cfg):
    j = job("Electrical Technicians (Kuwait)")
    assert select_jobs([j], cfg)
    cfg.include_overseas = False
    assert select_jobs([job("Electrical Technicians (Kuwait)")], cfg) == []
    assert select_jobs([job("Electrical Technician", location="Colombo")], cfg)


def test_location_filter(cfg):
    cfg.locations = ["Colombo"]
    jobs = [job("Electrical Engineer", location="Kandy", sid="a"),
            job("Electronic Engineer", location="Colombo 03", sid="b")]
    assert [j.title for j in select_jobs(jobs, cfg)] == ["Electronic Engineer"]
