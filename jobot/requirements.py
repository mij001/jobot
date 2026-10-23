"""What you are looking for, written out in plain words, and a plain-rule check of a job against it.

The same requirements are given to the AI, which reads each posting against them (ai.py), and to `assess`, a
rule-based judge that needs no AI. `assess` runs first to turn away the obvious misses cheaply, and decides on its own
when the AI is unavailable. Both answer "match" (meets them as far as can be seen), "maybe" (nothing fails, but the
posting doesn't settle it) or "no" (a requirement clearly fails).

Edit `ai.requirements` in config.yaml to change them; left blank they are worded from your settings (enabled
sub-fields, experience levels, qualifications, `include_overseas`).
"""

from __future__ import annotations

import re

from .config import Config
from .filters import distinct_hits, matching_keywords
from .models import Job

# Title words that mean the work is not engineering, or is software / IT-desk work rather than EEE work.
NOT_TECH = re.compile(r"\b(?:sales|marketing|account\w*|finance|financial|hr|human resources?|driver|cook|chef|waiter|nurse|"
                      r"cashier|clerk|receptionist|secretary|audit\w*|legal|teacher|pre[\s-]?school|beautician|tailor|"
                      r"security guard|cleaner|helper|packing|merchandiser|customer service|telesales|data entry|"
                      r"content writer|graphic|designer? \(graphic|hotel|hospitality|insurance|banking|recruit\w*|admin\w*|"
                      r"inventory|supply chain|procurement|purchas\w*|logistics|warehouse|store ?keeper|compliance|governance|"
                      r"brand|social media|tutor|teaching)\b", re.I)
# The words that make a title "electrical / electronic / telecom" for sure (HARDWAREISH also has "hardware", "control" …).
STRICT_EEE = re.compile(r"\b(?:electr\w*|telecom\w*|embedded|firmware|pcb|fpga|plc|scada|instrument\w*|substation\w*|solar|rf|vlsi|"
                        r"asic|switchgear|mechatronic\w*|automation|elv|cctv|biomedical)\b", re.I)
# IT-office work, from the title alone: not electrical or electronic however it is worded.
IT_OFFICE = re.compile(r"\b(?:(?:it|ict|information technology|information security|cyber ?security|digital|data|web|server|"
                       r"system|systems) (?:executive|officer|assistant|specialist|administrator|manager|analyst)|"
                       r"(?:executive|officer|assistant|specialist|manager|analyst)\s*[-–:(/|]*\s*(?:it|ict|information technology)|"
                       r"(?:it|ict) (?:support|services?|and|&)|information (?:technology|security)|cyber ?security|"
                       r"server support|help ?desk|service ?desk|desktop support|customer support|technical writer|"
                       r"digital services|ai transformation|artificial intelligence|machine learning|"
                       r"(?:lecturer|tutor|instructor|trainer|teacher|programme coordinator)\b[^|]*\b(?:it|ict|information technology|"
                       r"software|cyber|computing|computer science|programming|networking|network technology)|"
                       r"(?:it|ict|software|cyber ?security|computing)\b[^|]*\b(?:lecturer|tutor|instructor|trainer))\b", re.I)
# Clearly software, from the title alone.
SOFTWARE = re.compile(r"\b(?:software|developer|programmer|front[\s-]?end|back[\s-]?end|full[\s-]?stack|web|ui|ux|qa|"
                      r"data (?:scientist|analyst|engineer)|machine learning|java|python|php|\.net|react|mobile app|"
                      r"android|ios|sap|erp|crm|seo|database|dba|business analyst|scrum|product owner)\b", re.I)
# IT operations / support titles: they can be real network or hardware work, so the posting text decides, not the title.
IT_DESK = re.compile(r"\b(?:(?:it|desktop|help ?desk|service ?desk|technical|application|user|l[123]|level\s*[123]|tier\s*[123]) support|"
                     r"system(?:s)? (?:administrator|admin)|microsoft 365|office 365|m365|sharepoint|solutions? engineer|"
                     r"forward deployed|infrastructure|operations engineer|devops|cloud|sre|site reliability|techops|platform)\b", re.I)
HARDWAREISH = re.compile(r"\b(?:electr\w*|embedded|firmware|hardware|pcb|fpga|power|telecom\w*|network\w*|instrument\w*|"
                         r"automation|control\w*|plc|scada|solar|substation|mechatronic\w*|robot\w*|rf|signal|"
                         r"maintenance|commissioning|technical officer|technician)\b", re.I)

# Words in a posting's text that show electrical / electronic / telecom / control work.
EVIDENCE = re.compile(r"\b(?:electrical|electronics?|embedded|firmware|pcb|fpga|vlsi|asic|microcontroller\w*|circuit\w*|"
                      r"switchgear|substation\w*|transformer\w*|scada|plc|automation|instrumentation|telecom\w*|"
                      r"radio|antenna\w*|fib(?:er|re)|cabling|inverter\w*|solar|battery|batteries|semiconductor\w*|"
                      r"sensor\w*|iot|cctv|elv|low[\s-]current|commissioning|power (?:system|electronics|plant|supply|"
                      r"distribution|quality)|network (?:hardware|equipment|devices?|infrastructure)|routers?|switches|"
                      r"ccna|ccnp|hvac|mep|generator\w*|ups|motor drives?|wiring|earthing|protection relay\w*)\b", re.I)

# Selling is not engineering, whatever the product ("Sales Engineer - Industrial Automation"), unless you switched
# the technical-sales sub-field on.
SALES = re.compile(r"\b(?:sales|pre-?sales|marketing|business development|account (?:manager|executive))\b", re.I)

_MIN_TEXT = 400  # a posting shorter than this says too little to be held against a job


def lines(cfg: Config) -> list[str]:
    """The requirements, one per line. `ai.requirements` if set; otherwise worded from the settings."""
    if cfg.ai.requirements:
        return list(cfg.ai.requirements)
    out = []
    wanted = [q.short for q in cfg.enabled_qualifications] or ["any"]
    unwanted = [q.short for q in cfg.qualifications if not q.enabled]
    out.append(f"Qualification: the job must accept someone with a {' or '.join(wanted).lower()}-level qualification in "
               "Electrical & Electronic Engineering (EEE)"
               + (f"; a job that asks only for {' / '.join(unwanted).lower()} level qualifications, or for a degree in an unrelated "
                  "field, doesn't match" if unwanted else "") + ".")
    fields = "; ".join(s.label for s in cfg.enabled_subfields)
    out.append("Work: engineering work in these fields - " + fields + ". Pure software development, IT help-desk, user or "
               "application support, cloud / Microsoft 365 administration, sales, finance, admin, HR, supply chain, civil- or "
               "mechanical-only work and other non-EEE jobs don't match. A generic title (\"Associate Engineer\", \"Technical "
               "Officer\") matches only when the posting shows electrical, electronic, telecom, network-hardware or control work.")
    levels = [lv for lv in cfg.enabled_levels]
    if levels:
        capped = [lv.max_years for lv in levels if lv.max_years is not None]
        reach = f" (up to about {max(capped)} years of experience asked)" if len(capped) == len(levels) and capped else ""
        out.append("Level: " + ", ".join(lv.label for lv in levels) + reach + ". Jobs above that level don't match.")
    out.append("Place: located in Sri Lanka, or fully remote and open to someone living in Sri Lanka."
               + (" Jobs abroad are acceptable too." if cfg.include_overseas else " A job that needs relocating abroad doesn't match."))
    return out


def title_says_eee(job: Job, cfg: Config) -> bool:
    """The title names an electrical / electronic / telecom field (a bare "Lecturer" or "Sales Engineer" does not)."""
    return any(matching_keywords(sf.keywords, job.title) for sf in cfg.enabled_subfields if sf.key not in _ROLE_FIELDS)


_ROLE_FIELDS = {"teaching", "technical_sales"}  # their keywords ("lecturer", "sales engineer") are roles, not electrical work


def evidence_terms(job: Job, cfg: Config) -> set[str]:
    """Electrical / electronic / telecom words in the posting text (and your technical sub-fields' own keywords)."""
    text = f"{job.description}\n{job.category}"
    found = {m.group(0).lower() for m in EVIDENCE.finditer(text)}
    words = sorted({k for sf in cfg.enabled_subfields if sf.key not in _ROLE_FIELDS for k in sf.keywords})
    return found | distinct_hits(words, text)


def assess(job: Job, cfg: Config) -> tuple[str, str]:
    """(verdict, reason) from plain rules: "no" when the job clearly isn't EEE work, "match" when its own title names an
    EEE field, "maybe" when nothing fails but the posting doesn't settle it."""
    title = job.title
    says = title_says_eee(job, cfg)
    sales_wanted = any(sf.key == "technical_sales" for sf in cfg.enabled_subfields)
    if SALES.search(title) and not sales_wanted:
        return "no", "a sales role"
    strict = bool(STRICT_EEE.search(title))
    not_tech = {m.group(0).lower() for m in NOT_TECH.finditer(title)}
    if not_tech and not strict and not (all(w.startswith("admin") for w in not_tech) and HARDWAREISH.search(title)):
        return "no", "not engineering work"  # ("Network Administrator" is fine; "Graphic Designer | IT Hardware" is not)
    if SOFTWARE.search(title) and not strict and not (HARDWAREISH.search(title) and says):
        return "no", "software / IT work, not electrical or electronic"
    evidence = evidence_terms(job, cfg)
    if IT_OFFICE.search(title) and not strict and len(evidence) < 2:
        return "no", "IT office or support work, nothing electrical or electronic in it"
    if says and not job.rescued:
        return "match", "the title names an EEE field"
    has_text = len(job.description) >= 200
    if has_text and not evidence and not says:
        return "no", "the posting doesn't mention electrical, electronic or telecom work"
    if IT_DESK.search(title) and len(evidence) < 2 and not says:
        return "no" if len(job.description) >= _MIN_TEXT else "maybe", "IT support / systems work unless the posting says otherwise"
    if len(evidence) >= 2 or (says and evidence):
        return "maybe", "the posting mentions " + ", ".join(sorted(evidence)[:3])
    return "maybe", "the title and posting don't say what the work is"
