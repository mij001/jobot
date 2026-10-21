"""Try out candidate job sites from the machine jobot really runs on (GitHub Actions).

    python -m jobot --probe [candidates.txt]

For each URL in the file (one per line, `#` comments) it reports whether the site answers at all, whether the
page is a feed, how many vacancy-looking links the page holds and whether the site's robots.txt allows an
automated visit. Many sites treat cloud servers differently from home connections, so a site that works from
a laptop can still be unreachable from GitHub – this tells you before you add it to config.yaml.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import requests

from .http import Http
from .robots import RobotsCache
from .sources import company_pages
from .sources.rss import parse as parse_feed
from .swarm import parallel_map

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def read_candidates(path: str | Path) -> list[str]:
    urls = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and line.startswith(("http://", "https://")):
            urls.append(line)
    return list(dict.fromkeys(urls))


def probe_one(url: str) -> dict:
    http = Http(delay=0, timeout=(8, 20), retries=0)
    out: dict = {"url": url, "status": None, "kind": "", "title": "", "jobs": 0, "sample": [], "bytes": 0,
                 "robots": None, "seconds": 0.0, "error": ""}
    started = time.monotonic()
    try:
        resp = http.session.get(url, timeout=http.timeout, allow_redirects=True)
        out["status"], out["bytes"] = resp.status_code, len(resp.content)
        text = resp.text if resp.ok else ""
        if resp.ok:
            head = text[:600].lower()
            if "<rss" in head or "<feed" in head or "<?xml" in head and ("<item" in text[:3000] or "<entry" in text[:3000]):
                out["kind"] = "feed"
                try:
                    jobs = parse_feed(text, "probe")
                    out["jobs"], out["sample"] = len(jobs), [j.title for j in jobs[:3]]
                except Exception as exc:
                    out["error"] = f"feed not readable: {exc}"
            else:
                out["kind"] = "page"
                if m := _TITLE.search(text):
                    out["title"] = " ".join(m.group(1).split())[:70]
                jobs = company_pages.parse(text, {"url": resp.url, "name": "probe"})
                out["jobs"], out["sample"] = len(jobs), [j.title[:60] for j in jobs[:3]]
                if re.search(r"just a moment|attention required|enable javascript|captcha", text[:4000], re.I) and not jobs:
                    out["kind"] = "challenge"  # a bot check page, not the content
        out["robots"] = RobotsCache().allows(http, url) if resp.ok else None
    except requests.RequestException as exc:
        out["error"] = f"{type(exc).__name__}: {str(exc)[:90]}"
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


def run(path: str | Path, workers: int = 8) -> list[dict]:
    urls = read_candidates(path)
    print(f"Probing {len(urls)} addresses from this machine…\n")
    results = [r if e is None else {"url": u, "error": str(e), "status": None, "kind": "", "jobs": 0, "sample": [],
                                    "robots": None, "bytes": 0, "seconds": 0, "title": ""}
               for u, (r, e) in zip(urls, parallel_map(probe_one, urls, workers=workers), strict=True)]
    order = {"feed": 0, "page": 1, "challenge": 2, "": 3}
    for r in sorted(results, key=lambda r: (r["status"] != 200, order.get(r["kind"], 3), -r["jobs"], r["url"])):
        ok = r["status"] == 200 and r["kind"] in ("feed", "page")
        flag = "OK  " if ok and r["jobs"] else "page" if ok else "FAIL"
        robots = {True: "robots ok", False: "robots DISALLOW", None: "robots ?"}[r["robots"]]
        print(f"[{flag}] {r['status'] or '---'} {r['kind'] or '-':9} {r['jobs']:3} links  {r['bytes'] // 1024:5} KB  "
              f"{r['seconds']:4}s  {robots:15} {r['url']}")
        if r["title"]:
            print(f"         title: {r['title']}")
        if r["sample"]:
            print(f"         e.g.   {' | '.join(r['sample'])}")
        if r["error"]:
            print(f"         {r['error']}")
    good = [r for r in results if r["status"] == 200 and r["jobs"] and r["robots"] is not False]
    print(f"\n{len(good)} of {len(results)} gave vacancy links and allow automated visits.")
    return results
