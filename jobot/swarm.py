"""Doing many requests at once, without hammering any one site.

Different sites are fetched at the same time (see main.scrape); inside one site
a few workers, each with its own connection and the site's usual delay between
requests, share the list of categories / searches / pages to read. One failed
item is noted as a warning and the rest still count – only when *every* item
failed does the site count as failed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(fn: Callable[[T], R], items: Iterable[T], workers: int = 3) -> list[tuple[R | None, Exception | None]]:
    """fn(item) for every item, `workers` at a time; (result, error) pairs in the order of `items`."""
    items = list(items)

    def call(item: T) -> tuple[R | None, Exception | None]:
        try:
            return fn(item), None
        except Exception as exc:  # reported per item; one bad item must not hide the rest
            return None, exc

    if workers <= 1 or len(items) <= 1:
        return [call(i) for i in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(call, items))


def gather(http: Any, items: Iterable[T], fn: Callable[[Any, T], list], workers: int = 3,
           label: Callable[[T], str] = str) -> list:
    """Run fn(connection, item) -> list of jobs for every item (a few at a time, each worker on its own
    connection) and join the lists. Failed items are noted on `http`; raises the first error if none worked."""
    items = list(items)
    clone = getattr(http, "clone", None)
    outcomes = parallel_map(lambda item: fn(clone() if clone else http, item), items, workers if clone else 1)
    jobs: list = []
    errors: list[tuple[T, Exception]] = []
    for item, (found, error) in zip(items, outcomes, strict=True):
        if error is not None:
            errors.append((item, error))
            if note := getattr(http, "note", None):
                note(f"{label(item)}: {_short(error)}")
        else:
            jobs.extend(found or [])
    if errors and len(errors) == len(items):
        raise errors[0][1]
    return jobs


def _short(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None):
        return f"HTTP {resp.status_code}"
    return f"{type(exc).__name__}: {str(exc)[:80]}"
