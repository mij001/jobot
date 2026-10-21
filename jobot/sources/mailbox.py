"""Job-alert e-mails sent to you by job sites (XpressJobs, LinkedIn, Rooster, Jobsnet, Indeed …).

Some sites refuse visits from cloud servers but happily e-mail you new jobs when you subscribe to an alert.
This reads those e-mails from your own mailbox over IMAP – read-only, only messages from the senders you list,
nothing is marked read, moved or deleted – and turns the vacancy links in them into jobs.

On by default, but it is simply skipped (it says so in the report) until it can log in: it needs IMAP_USERNAME /
IMAP_PASSWORD secrets, or reuses SMTP_USERNAME / SMTP_PASSWORD (a Gmail app password works for both). Subscribe
to the alerts yourself on each site, pointed at that mailbox, then list the sender domains in `senders`.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import re
from datetime import date, timedelta
from email import policy
from html import unescape
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup

from ..config import Config
from ..http import Http, SourceSkipped
from ..models import Job

NAME = "Email alerts"
log = logging.getLogger(__name__)

MAX_BYTES = 2_000_000
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# What a vacancy link looks like on each site; anything else falls back to the generic words.
_JOB_PATH = {
    "linkedin.com": re.compile(r"/jobs/view/|/comm/jobs/view/"),
    "xpress.jobs": re.compile(r"/job[s]?/"),
    "rooster.jobs": re.compile(r"/jobs?/"),
    "indeed.com": re.compile(r"/viewjob|/rc/clk|/pagead/|/job/"),
    "jobsnet.lk": re.compile(r"/job"),
    "topjobs.lk": re.compile(r"JobAdvertismentServlet|/vacancy"),
}
_GENERIC = re.compile(r"job|vacanc|career|position|opening|apply", re.I)
_NOISE = re.compile(
    r"^(view( all)?( more)?( jobs?)?|see( all| more)?( jobs?)?|apply( now)?|unsubscribe|manage|settings|"
    r"preferences|update|edit|learn more|help|privacy|terms|home|login|log in|sign in|click here|open|"
    r"more|read more|search|jobs?)$", re.I)


# "Your application was viewed" / "Applied on Oct 20" mails are about jobs you already applied for, not new ones.
_APPLIED_LINK = re.compile(r"application_viewed|job_application|applied_job|application_status|application_sent", re.I)
_APPLIED_TEXT = re.compile(r"\bapplied on\b|\byou applied\b|application (?:was )?(?:viewed|sent|submitted|status)|\byour application\b", re.I)


def missing(env: dict[str, str]) -> str | None:
    if not (env.get("IMAP_USERNAME") or env.get("SMTP_USERNAME")) or not (env.get("IMAP_PASSWORD") or env.get("SMTP_PASSWORD")):
        return "needs IMAP_USERNAME and IMAP_PASSWORD (or the SMTP_ ones) secrets"
    return None


def _imap_date(day: date) -> str:
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def _real_url(href: str) -> str:
    """Some alert mails wrap the vacancy address in a tracking link (…?url=https%3A%2F%2F…): unwrap it."""
    parts = urlsplit(href)
    for key in ("url", "u", "redirect", "target", "link"):
        for value in parse_qs(parts.query).get(key, []):
            if value.startswith(("http://", "https://")):
                return unquote(value)
    return href


def _domain(host: str) -> str:
    bits = host.lower().split(".")
    return ".".join(bits[-2:]) if len(bits) >= 2 else host.lower()


def parse_message(raw: bytes, sender_domains: list[str], extract=None) -> list[Job]:
    """The vacancies in one alert e-mail. `extract` (the AI, see triage.Helpers.extract_alert) is only asked when the
    layout is one the plain rules find nothing in."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    sender = msg.get("From", "").lower()
    domain = next((d for d in sender_domains if d.lower() in sender), "")
    if not domain:
        return []
    body = msg.get_body(preferencelist=("html",))
    if body is None:
        return []
    html = body.get_content()
    soup = BeautifulSoup(html, "html.parser")
    day = ""
    try:
        day = email.utils.parsedate_to_datetime(msg.get("Date")).date().isoformat()
    except (TypeError, ValueError):
        pass
    label = f"Email alert ({_domain(domain) if '.' in domain else domain})"
    pattern = next((p for d, p in _JOB_PATH.items() if d in domain.lower()), _GENERIC)
    jobs, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = _real_url(unescape(a["href"]).strip())
        if not href.startswith(("http://", "https://")):
            continue
        text = " ".join(a.get_text(" ", strip=True).split())
        if not (6 <= len(text) <= 140) or _NOISE.match(text):
            continue
        if not (pattern.search(href) or pattern.search(unquote(a["href"]))):
            continue
        key = re.sub(r"[?#].*$", "", href) if "linkedin" in href else href
        job_id = (re.search(r"/jobs/view/(?:[\w-]*-)?(\d{6,})", href) or re.search(r"(\d{6,})", href))
        ident = job_id.group(1) if job_id and "linkedin" in href else hashlib.sha1(key.encode()).hexdigest()[:16]
        if ident in seen:
            continue
        seen.add(ident)
        # a card usually reads "Title / Company · Location": take what follows the link as company and place
        around = " ".join((a.find_parent(["td", "div", "li"]) or a).get_text(" ", strip=True).split())
        if _APPLIED_LINK.search(href) or _APPLIED_TEXT.search(around[:300]):
            continue  # a job you already applied for
        extra = around.replace(text, "", 1).strip(" -–·|,")[:100]
        jobs.append(Job(source=label, source_id=ident, title=text, url=href, company=extra, posted=day))
    if not jobs and extract is not None:
        jobs = _ask_ai(extract, msg, soup, label, day)
    return jobs


def _ask_ai(extract, msg, soup: BeautifulSoup, label: str, day: str) -> list[Job]:
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = _real_url(unescape(a["href"]).strip())
        text = " ".join(a.get_text(" ", strip=True).split())
        if href.startswith(("http://", "https://")) and href not in seen and 6 <= len(text) <= 140 \
                and not _NOISE.match(text) and not re.search(r"unsubscribe|optout|opt-out|preferences", href, re.I):
            seen.add(href)
            links.append((text, href))
    stamp = f"{msg.get('Message-ID') or ''}|{msg.get('Date') or ''}|{msg.get('Subject') or ''}|{msg.get('From') or ''}"
    found = extract(hashlib.sha1(stamp.encode("utf-8", "replace")).hexdigest()[:16], str(msg.get("From") or ""),
                    str(msg.get("Subject") or ""), soup.get_text(" ", strip=True), links)
    return [Job(source=label, source_id=hashlib.sha1(row["url"].encode()).hexdigest()[:16], title=row["title"], url=row["url"],
                company=row.get("company", ""), location=row.get("location", ""), posted=day) for row in found or []]


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    env = opts.get("_env") or {}
    if problem := missing(env):
        raise RuntimeError(problem)
    user = env.get("IMAP_USERNAME") or env["SMTP_USERNAME"]
    password = env.get("IMAP_PASSWORD") or env["SMTP_PASSWORD"]
    senders = [str(s) for s in opts.get("senders") or []]
    if not senders:
        raise RuntimeError("list the sender domains of your job alerts under sources.email_alerts.senders")
    since = _imap_date(date.today() - timedelta(days=int(opts.get("days", 3))))
    limit = int(opts.get("max_messages", 60))
    box = imaplib.IMAP4_SSL(opts.get("host") or "imap.gmail.com", int(opts.get("port", 993)), timeout=30)
    jobs: dict[str, Job] = {}
    try:
        try:
            box.login(user, password)
        except imaplib.IMAP4.error as exc:  # wrong or missing app password, IMAP not switched on: a set-up issue
            raise SourceSkipped("the mailbox refused the login (Gmail needs an app password and IMAP switched on)") from exc
        box.select(opts.get("folder") or "INBOX", readonly=True)  # read-only: nothing is marked as read
        ids: list[bytes] = []
        for sender in senders:
            status, data = box.search(None, "SINCE", since, "FROM", f'"{sender}"')
            if status == "OK" and data and data[0]:
                ids.extend(data[0].split())
        for msg_id in sorted(set(ids), key=int, reverse=True)[:limit]:
            status, data = box.fetch(msg_id, "(BODY.PEEK[])")
            if status != "OK" or not data or not isinstance(data[0], tuple) or len(data[0][1]) > MAX_BYTES:
                continue
            for job in parse_message(data[0][1], senders, opts.get("_extract")):
                jobs.setdefault(job.uid, job)
    finally:
        try:
            box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    log.info("Email alerts: %d vacancy link(s) in %d message(s)", len(jobs), len(set(ids)))
    return list(jobs.values())
