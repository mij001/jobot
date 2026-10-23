"""Decides which jobs are EEE-relevant, tags sub-fields and experience level."""

from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache

from .config import Config
from .models import Job

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
}
_NUM = r"(\d{1,2}|" + "|".join(_WORD_NUMBERS) + r")"
# "3-5 years", "3 to 5 yrs", "5+ years", "minimum of five years", "2 years'"
_YEARS_RE = re.compile(
    _NUM + r"\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*" + _NUM + r"\s*\+?\s*)?(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_EXPERIENCE_RE = re.compile(r"\bexp(?:erience[sd]?|\.)?\b", re.IGNORECASE)

# "NVQ Level 05", "NVQ L5", "NVQ-5", "NVQ level IV", "NVQ 5/6", "NVQ level 5 or 6"
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7}
_NVQ_NUM = r"(?:0?[1-7]|vii|vi|v|iv|iii|ii|i)\b"
_NVQ_RE = re.compile(
    r"\bnvq\s*[-–:]?\s*(?:level|lvl|l)?\s*[-–:.]?\s*(" + _NVQ_NUM + r")"
    r"((?:\s*(?:/|,|&|or|and|-|–|to)\s*(?:level\s*)?" + _NVQ_NUM + r"(?!\s*\+?\s*(?:years?|yrs?)))*)",
    re.IGNORECASE,
)
# "degree" that isn't a qualification: "360 degree", "a high degree of", "40 degrees Celsius".
_NOT_A_DEGREE = re.compile(
    r"\b\d+\s*-?\s*degrees?\b|\bdegrees?\s+(?:of|celsius|fahrenheit|centigrade)\b",
    re.IGNORECASE,
)


# Places outside Sri Lanka. Job sites outside Sri Lanka (LinkedIn, its alert e-mails) list jobs the world over, and an
# alert's text reads "Amazon · Austin, TX 17 school alumni" with the place only inside it.
_US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK "
              "OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
_US_PLACE = re.compile(r"[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+)*,\s*(?:" + "|".join(_US_STATES) + r")\b(?!\w)")
_FOREIGN_PLACE = re.compile(
    r"\b(?:taiwan|taipei|hsinchu|zhubei|taichung|singapore|malaysia|kuala lumpur|penang|india|bengaluru|bangalore|hyderabad|"
    r"chennai|mumbai|pune|delhi|noida|gurgaon|gurugram|kolkata|china|shenzhen|shanghai|beijing|hong kong|japan|tokyo|"
    r"osaka|korea|seoul|thailand|bangkok|vietnam|philippines|manila|indonesia|jakarta|bangladesh|dhaka|pakistan|"
    r"karachi|lahore|nepal|maldives|australia|sydney|melbourne|brisbane|perth|new zealand|auckland|united states|"
    r"usa|u\.s\.a?\.?|canada|toronto|vancouver|montreal|united kingdom|england|scotland|london|manchester|"
    r"germany|berlin|munich|france|paris|netherlands|amsterdam|ireland|dublin|spain|italy|sweden|norway|denmark|"
    r"finland|poland|switzerland|zurich|israel|egypt|nigeria|kenya|south africa|dubai|abu dhabi|sharjah|"
    r"uae|united arab emirates|qatar|doha|kuwait|saudi arabia|riyadh|jeddah|oman|muscat|bahrain|"
    r"san jose|san francisco|seattle|boston|new york|chicago|dallas|houston|los angeles|san diego|silicon valley|"
    r"austin|atlanta|phoenix|denver|portland|raleigh|santa clara|sunnyvale|mountain view|palo alto|cupertino|fremont|"
    r"milpitas|irvine|boulder|minneapolis|detroit|pittsburgh|philadelphia|washington dc|"
    r"portugal|lisbon|porto|czech|prague|romania|bucharest|hungary|budapest|austria|vienna|belgium|brussels|greece|athens|"
    r"turkey|istanbul|russia|moscow|ukraine|kyiv|brazil|argentina|mexico|chile|colombia|peru|ghana|morocco|tunisia|"
    r"ethiopia|uganda|tanzania|jordan|lebanon|iraq|iran|cyprus|malta|luxembourg|estonia|latvia|lithuania|cambodia|"
    r"myanmar|mongolia|kazakhstan|uzbekistan|brunei|europe|emea|apac|latam|north america)\b",
    re.IGNORECASE)
_SRI_LANKA = re.compile(r"\bsri lanka\b|\bcolombo\b|\b(?:western|central|southern|northern|eastern|uva|sabaragamuwa|"
                        r"north western|north central) province\b", re.IGNORECASE)


def foreign_place(text: str) -> str | None:
    """The place outside Sri Lanka that `text` names ("Austin, TX", "Hsinchu", "Singapore"), or None. A text that also
    names Sri Lanka is left alone."""
    if not text or _SRI_LANKA.search(text):
        return None
    m = _US_PLACE.search(text) or _FOREIGN_PLACE.search(text)
    return m.group(0).strip() if m else None


@lru_cache(maxsize=4096)
def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive pattern; a trailing * matches any word ending."""
    kw = keyword.strip()
    wildcard = kw.endswith("*")
    kw = kw.rstrip("*").strip()
    parts = [re.escape(p) for p in kw.split()]
    body = r"\s+".join(parts)
    if wildcard:
        body += r"[\w-]*"
    # Custom boundaries so keywords like "E&E" or "B.Sc." work too.
    return re.compile(r"(?<![\w])" + body + r"(?![\w])", re.IGNORECASE)


def matches(keyword: str, text: str) -> bool:
    return bool(text) and keyword_pattern(keyword).search(text) is not None


def matching_keywords(keywords: list[str], text: str) -> list[str]:
    return [k for k in keywords if matches(k, text)]


def distinct_hits(keywords: list[str], text: str) -> set[str]:
    """Keywords (lower-cased) found in text, not counting a match that is only part
    of a longer keyword's match – "Electrical Engineering" is one hit, not
    "electrical" + "electrical engineer*"."""
    if not text:
        return set()
    spans: dict[str, list[tuple[int, int]]] = {}
    for k in keywords:
        found = [m.span() for m in keyword_pattern(k).finditer(text)]
        if found:
            spans[k.lower()] = found
    longer = [s for found in spans.values() for s in found]

    def inside(span: tuple[int, int]) -> bool:
        return any(a <= span[0] and span[1] <= b and b - a > span[1] - span[0] for a, b in longer)

    return {k for k, found in spans.items() if any(not inside(s) for s in found)}


def match_subfields(job: Job, cfg: Config) -> list[str]:
    """Return keys of the enabled sub-fields this job belongs to."""
    everything = f"{job.title}\n{job.description}\n{job.category}"
    usable = [sf for sf in cfg.enabled_subfields
              if not sf.requires_any or matching_keywords(sf.requires_any, everything)]
    title_hits: list[str] = []
    for sf in usable:
        if matching_keywords(sf.keywords, job.title):
            title_hits.append(sf.key)
    if title_hits or not cfg.match_description:
        return title_hits
    if cfg.description_match_titles and not matching_keywords(cfg.description_match_titles, job.title):
        return []

    # Weaker evidence: description + the site's category label. The category
    # counts as a single hit however many keywords it contains, so a job is
    # never accepted on "Electronics / Electrical" alone.
    found = distinct_hits(list({k for sf in usable for k in sf.keywords}), job.description)
    desc_hits: set[str] = set()
    category_hit = False
    per_subfield: dict[str, int] = {}
    for sf in usable:
        d = {k.lower() for k in sf.keywords} & found
        c = bool(matching_keywords(sf.keywords, job.category))
        desc_hits |= d
        category_hit |= c
        if d or c:
            per_subfield[sf.key] = len(d) + int(c)
    if len(desc_hits) + int(category_hit) < max(1, cfg.min_description_hits):
        return []
    return sorted(per_subfield, key=lambda k: -per_subfield[k])


def years_required(text: str) -> int | None:
    """Smallest 'N years' figure mentioned near the word 'experience'."""
    if not text:
        return None
    found: list[int] = []
    for m in _YEARS_RE.finditer(text):
        window = text[max(0, m.start() - 80): m.end() + 80]
        if not _EXPERIENCE_RE.search(window):
            continue
        first = m.group(1).lower()
        n = _WORD_NUMBERS.get(first) if not first.isdigit() else int(first)
        if n is not None and n <= 30:
            found.append(n)
    return min(found) if found else None


def classify_level(job: Job, cfg: Config) -> str | None:
    # a) Title keywords. Levels are ordered junior -> senior; the most senior
    #    match wins ("Trainee Engineer" -> entry, "Senior Manager" -> management).
    title_levels = [lv.key for lv in cfg.levels if matching_keywords(lv.keywords, job.title)]
    if title_levels:
        return title_levels[-1]

    # b) "N years of experience" in title / description.
    years = job.min_years if job.min_years is not None else years_required(f"{job.title}\n{job.description}")
    if years is not None:
        for lv in cfg.levels:
            if lv.covers_years(years):
                return lv.key

    # c) Whatever the job site says.
    if job.level_hint and cfg.level(job.level_hint):
        return job.level_hint
    return None


def _nvq_level(token: str) -> int:
    token = token.lower().lstrip("0")
    return int(token) if token.isdigit() else _ROMAN[token]


def _expand_nvq(m: re.Match) -> str:
    first = _nvq_level(m.group(1))
    rest = [_nvq_level(t) for t in re.findall(_NVQ_NUM, m.group(2) or "", re.IGNORECASE)]
    levels = [first, *rest]
    if len(rest) == 1 and re.search(r"-|–|to", m.group(2)):  # "NVQ 3 - 5" is a range
        levels = list(range(min(levels), max(levels) + 1))
    return " " + " ".join(f"nvq level {n}" for n in levels) + " "


def qualification_text(text: str) -> str:
    """Normalise NVQ levels and drop non-qualification uses of "degree"."""
    return _NVQ_RE.sub(_expand_nvq, _NOT_A_DEGREE.sub(" ", text))


def qualifications_with_source(job: Job, cfg: Config) -> tuple[list[str], bool]:
    """(qualification levels, guessed). The levels are what the advert accepts, e.g. ["degree", "diploma"] for
    "BSc or HND in Electrical Engineering"; empty when the advert doesn't say. `guessed` is True when the advert says
    nothing and the levels only come from the job title ("Technical Officer" -> diploma)."""
    if not cfg.qualifications:
        return [], False
    text = qualification_text(f"{job.title}\n{job.description}")
    found = [q.key for q in cfg.qualifications if matching_keywords(q.keywords, text)]
    if found:
        return found, False
    guess = [q for q in cfg.qualifications if matching_keywords(q.title_hints, job.title)][:1]
    if not guess:
        return [], False
    return [guess[0].key], not guess[0].guess_filters  # a trade title ("Electrician") counts as asking for that level


def classify_qualifications(job: Job, cfg: Config) -> list[str]:
    return qualifications_with_source(job, cfg)[0]


def qualification_allowed(keys: list[str], cfg: Config, guessed: bool = False) -> bool:
    """A job passes if it accepts at least one qualification you've ticked. A level that is only a guess from the
    job title counts as "not stated": a title alone must not hide a job (LinkedIn cards carry nothing else)."""
    if not cfg.qualifications:
        return True
    if not keys or guessed:
        return cfg.include_unknown_qualification
    return any((q := cfg.qualification(k)) is not None and q.enabled for k in keys)


def is_excluded(job: Job, cfg: Config) -> bool:
    if matching_keywords(cfg.exclude_title_keywords, job.title):
        return True
    if cfg.avoid_companies and matching_keywords(cfg.avoid_companies, job.company):
        return True
    if job.remote:  # open to Sri Lanka by construction: neither the overseas nor the place filter applies
        return False
    if not cfg.include_overseas:
        where = f"{job.title}\n{job.location}"  # (an alert e-mail puts "Employer · Austin, TX" in the title)
        if matching_keywords(cfg.overseas_keywords, where) or foreign_place(where):
            return True
    if cfg.locations and job.location:
        loc = job.location.lower()
        if not any(want.lower() in loc for want in cfg.locations):
            return True
    return False


def level_allowed(level: str | None, cfg: Config) -> bool:
    if level is None:
        return cfg.include_unknown_level
    lv = cfg.level(level)
    return bool(lv and lv.enabled)


def explain(job: Job, cfg: Config) -> list[str]:
    """Walk one job through the same checks as `select_jobs` and say what each decided – for `--explain`, when a posting
    you saw on a site never reached you. The last line is the verdict."""
    out: list[str] = []
    if matching_keywords(cfg.exclude_title_keywords, job.title):
        return [f"DROPPED: the title has an excluded word ({', '.join(matching_keywords(cfg.exclude_title_keywords, job.title))})"]
    if is_excluded(job, cfg):
        where = foreign_place(f"{job.title}\n{job.location}")
        return [f"DROPPED: the job is outside Sri Lanka ({where})" if where and not cfg.include_overseas else
                "DROPPED: employer on your avoid list, or the place/overseas filter"]
    preset = [k for k in (job.preset or job.subfields) if (sf := cfg.subfield(k)) and sf.enabled]
    subs = preset + [k for k in match_subfields(job, cfg) if k not in preset]
    everything = replace(cfg, subfields=[replace(s, enabled=True) for s in cfg.subfields])
    off = [k for k in match_subfields(job, everything) if k not in subs]
    if not subs:
        out.append("sub-field: none of the keywords for your enabled sub-fields is in the title"
                   + (f" (it would match {', '.join(off)}, which is switched off)" if off else ""))
        from . import triage
        if triage.worth_asking(job):
            out.append("  -> the AI triage may still pick it (it looks like engineering work)"
                       + ("; as an associate / graduate engineer role it is kept even without the AI"
                          if triage.entry_level_engineer(job) else ""))
            return out + ["NOT MATCHED by keywords (see above)"]
        return out + ["DROPPED: no sub-field, and the title doesn't look like engineering work"]
    out.append(f"sub-field: {', '.join(subs)}")
    level = classify_level(replace(job, subfields=subs), cfg)
    out.append(f"level: {level or 'not stated'}" + ("" if level_allowed(level, cfg) else "  -> switched off"))
    if not level_allowed(level, cfg):
        return out + ["DROPPED: that experience level is switched off"]
    quals, guessed = qualifications_with_source(job, cfg)
    out.append(f"qualification: {', '.join(quals) or 'not stated'}" + (" (only guessed from the title)" if guessed else ""))
    if not qualification_allowed(quals, cfg, guessed):
        return out + ["DROPPED: the advert asks for a qualification you switched off"]
    from . import requirements  # imported here: requirements itself builds on this module
    verdict, why = requirements.assess(replace(job, subfields=subs), cfg)
    out.append(f"requirements (plain rules): {verdict} - {why}")
    if verdict == "no":
        return out + ["HELD BACK: it fails your requirements (the AI also reads the full posting before anything is sent)"]
    return out + ["KEPT" + (" (the AI reads the full posting next)" if verdict != "match" else "")]


def select_jobs(jobs: list[Job], cfg: Config) -> list[Job]:
    """Tag and filter jobs, merging duplicates posted on several sites.

    Safe to call again after the posting reader has added the full advert text."""
    selected: list[Job] = []
    by_fp: dict[str, Job] = {}
    seen_uids: set[str] = set()
    for job in jobs:
        if job.uid in seen_uids:
            continue
        seen_uids.add(job.uid)
        if job.preset is None:  # sub-fields a source tagged itself (e.g. a company page set to "power")
            job.preset = list(job.subfields)
        job.also_on = []
        if is_excluded(job, cfg):
            continue
        job.watched = bool(cfg.watch_companies and matching_keywords(cfg.watch_companies, job.company))
        preset = [k for k in job.preset if (sf := cfg.subfield(k)) and sf.enabled]
        job.subfields = preset + [k for k in match_subfields(job, cfg) if k not in preset]
        if not job.subfields:
            continue
        job.min_years = years_required(f"{job.title}\n{job.description}")
        job.level = classify_level(job, cfg)
        if not level_allowed(job.level, cfg):
            continue
        job.qualifications, job.qual_guess = qualifications_with_source(job, cfg)
        if not qualification_allowed(job.qualifications, cfg, job.qual_guess):
            continue
        first = by_fp.get(job.fingerprint)
        if first is not None:
            if first.source.startswith("Email alert") and not job.source.startswith("Email alert"):
                # the same vacancy read from an alert e-mail first: the site's own listing has the cleaner title and company
                job.also_on = [*first.also_on, (first.source, first.url)]
                selected[selected.index(first)] = by_fp[job.fingerprint] = job
            elif job.source != first.source and all(s != job.source for s, _ in first.also_on):
                first.also_on.append((job.source, job.url))
            continue
        by_fp[job.fingerprint] = job
        selected.append(job)
    return selected
