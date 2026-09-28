"""Run every enabled employer, isolating failures per site."""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime

from .config import Config, Employer
from .fetchers import Fetcher, get_fetcher
from .filters import evaluate
from .http import PoliteClient
from .models import Posting
from .store import StoredPosting, Store

log = logging.getLogger(__name__)


@dataclass
class SiteError:
    employer_id: str
    name: str
    error: str


@dataclass
class SiteStat:
    employer_id: str
    name: str
    category: str
    fetched: int
    matched: int


@dataclass
class RunReport:
    run_date: str
    new: list[StoredPosting] = field(default_factory=list)
    closed: list[StoredPosting] = field(default_factory=list)
    errors: list[SiteError] = field(default_factory=list)
    stats: list[SiteStat] = field(default_factory=list)
    categories: dict[str, str] = field(default_factory=dict)  # employer_id -> category
    duplicate_keys: list[str] = field(default_factory=list)  # hidden repeats, still marked reported

    def to_dict(self) -> dict:
        return {
            "run_date": self.run_date,
            "new": [dict(p.to_dict(), category=self.categories.get(p.employer_id)) for p in self.new],
            "closed": [dict(p.to_dict(), category=self.categories.get(p.employer_id)) for p in self.closed],
            "failed_sites": [e.__dict__ for e in self.errors],
            "sites": [s.__dict__ for s in self.stats],
        }


def select_employers(config: Config, only: list[str] | None) -> list[Employer]:
    if only:
        known = {e.id for e in config.employers}
        unknown = [i for i in only if i not in known]
        if unknown:
            raise SystemExit(f"unknown employer id(s): {', '.join(unknown)}")
        return [e for e in config.employers if e.id in only]
    return [e for e in config.employers if e.enabled]


def fetch_one(employer: Employer, http: PoliteClient) -> list[Posting]:
    with http.robots_policy(employer.respect_robots_txt):
        return get_fetcher(employer, http).fetch()


def resolve_unverified(
    employer: Employer, http: PoliteClient, postings: list[Posting], config: Config
) -> None:
    """For matching postings with a vague location ("3 Locations"), ask the
    fetcher for the real one. Failures leave the posting as-is (flagged)."""
    if http is None:
        return
    fetcher = get_fetcher(employer, http)
    if type(fetcher).resolve_location is Fetcher.resolve_location:
        return  # this fetcher can't look locations up
    limit = int(employer.options.get("max_location_lookups", 60))
    with http.robots_policy(employer.respect_robots_txt):
        _resolve(fetcher, employer, postings, config, limit)


def _resolve(fetcher, employer, postings, config, limit) -> None:
    for p in postings:
        if limit <= 0:
            break
        r = evaluate(p, config.filters, employer.filters)
        if not (r.matched and r.location_unverified):
            continue
        limit -= 1
        try:
            loc = fetcher.resolve_location(p)
        except Exception as exc:
            log.info("location lookup failed for %s: %s", p.url, exc)
            continue
        if loc:
            p.location = loc


def run(
    config: Config,
    store: Store,
    http: PoliteClient,
    only: list[str] | None = None,
    today: date | None = None,
) -> RunReport:
    """Fetch, filter and diff. Call ``mark_delivered`` once the digest is out."""
    today = today or date.today()
    report = RunReport(run_date=today.isoformat())
    report.categories = {e.id: e.category for e in config.employers}
    run_id = store.start_run(datetime.now().isoformat(timespec="seconds"), today.isoformat())

    for employer in select_employers(config, only):
        log.info("fetching %s (%s)", employer.name, employer.type)
        try:
            postings = fetch_one(employer, http)
            resolve_unverified(employer, http, postings, config)
        except Exception as exc:  # one site must never kill the run
            msg = f"{type(exc).__name__}: {exc}"
            log.debug("%s failed:\n%s", employer.id, traceback.format_exc())
            report.errors.append(SiteError(employer.id, employer.name, msg))
            store.record_employer(run_id, employer.id, "error", 0, 0, msg)
            continue

        rows = []
        matched = 0
        for p in postings:
            r = evaluate(p, config.filters, employer.filters)
            matched += r.matched
            rows.append((p, r.matched, r.summary, r.location_unverified))
        try:
            store.sync_employer(employer.id, rows, today)
        except Exception as exc:
            msg = f"store error: {type(exc).__name__}: {exc}"
            report.errors.append(SiteError(employer.id, employer.name, msg))
            store.record_employer(run_id, employer.id, "error", len(postings), matched, msg)
            continue
        store.record_employer(run_id, employer.id, "ok", len(postings), matched, None)
        report.stats.append(SiteStat(employer.id, employer.name, employer.category, len(postings), matched))

    report.new, report.duplicate_keys = _dedupe(store.new_matches())
    report.closed = store.newly_closed_matches()
    store.finish_run(
        run_id,
        datetime.now().isoformat(timespec="seconds"),
        {"new": len(report.new), "closed": len(report.closed), "errors": len(report.errors)},
    )
    return report


def _dedupe(postings: list[StoredPosting]) -> tuple[list[StoredPosting], list[str]]:
    """Same firm + title + location listed on two career sites -> show once."""
    seen: set[tuple[str, str, str]] = set()
    keep, dupes = [], []
    for p in postings:
        k = (p.firm.lower(), p.title.lower(), p.location.lower())
        if k in seen:
            dupes.append(p.posting_key)
        else:
            seen.add(k)
            keep.append(p)
    return keep, dupes


def mark_delivered(store: Store, report: RunReport) -> None:
    """Record that these postings were shown, so the next run won't repeat them."""
    store.mark_reported(
        [p.posting_key for p in report.new] + report.duplicate_keys,
        [p.posting_key for p in report.closed],
        date.fromisoformat(report.run_date),
    )
