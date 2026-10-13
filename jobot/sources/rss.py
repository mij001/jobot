"""Any RSS/Atom feed of job adverts (default: Gazette.lk government vacancies).

Add more feeds in config.yaml under sources.rss.feeds – each needs a name
and a url. WordPress sites usually have one at <site>/feed.
"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..config import Config
from ..http import Http
from ..models import Job

NAME = "RSS feeds"
_TAGS = re.compile(r"<[^>]+>")
_ATOM = "{http://www.w3.org/2005/Atom}"


def _plain(text: str | None) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", text or "")).split())


def _date(text: str | None) -> str:
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        return text[:10]


def parse(xml: str, site: str) -> list[Job]:
    root = ET.fromstring(xml)
    jobs = []
    items = root.iter("item") if root.tag == "rss" or root.find("channel") is not None else root.iter(_ATOM + "entry")
    for it in items:
        if it.tag == "item":
            title, link = it.findtext("title"), it.findtext("link")
            desc = it.findtext("description")
            posted = _date(it.findtext("pubDate"))
            cats = [c.text or "" for c in it.findall("category")]
            guid = it.findtext("guid") or link
        else:  # Atom
            title = it.findtext(_ATOM + "title")
            link_el = it.find(_ATOM + "link")
            link = link_el.get("href") if link_el is not None else ""
            desc = it.findtext(_ATOM + "summary") or it.findtext(_ATOM + "content")
            posted = (it.findtext(_ATOM + "published") or it.findtext(_ATOM + "updated") or "")[:10]
            cats = [c.get("term", "") for c in it.findall(_ATOM + "category")]
            guid = it.findtext(_ATOM + "id") or link
        if not title or not link:
            continue
        jobs.append(Job(
            source=site,
            source_id=hashlib.sha1((guid or link).encode()).hexdigest()[:16],
            title=" ".join(title.split()),
            url=link.strip(),
            description=_plain(desc)[:600],
            category=" / ".join(c for c in cats if c),
            posted=posted,
        ))
    return jobs


def fetch(http: Http, opts: dict, cfg: Config) -> list[Job]:
    jobs: list[Job] = []
    errors = []
    for feed in opts.get("feeds") or []:
        name, url = feed.get("name") or "RSS", feed.get("url")
        if not url:
            continue
        for page in range(1, int(feed.get("pages", 1)) + 1):
            try:
                text = http.get(url, params={"paged": page} if page > 1 else None).text
                jobs.extend(parse(text, name))
            except Exception as exc:  # keep the other feeds going
                errors.append(f"{name}: {exc}")
                break
    if errors and not jobs:
        raise RuntimeError("; ".join(errors))
    return jobs
