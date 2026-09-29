"""job-watch command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .config import Config, load_config
from .digest import render_json, render_text
from .emailer import EmailConfigError, send_digest
from .fetchers import REGISTRY, get_fetcher, needs_browser
from .fetchers.base import ConfigError
from .fetchers.browser import playwright_available
from .filters import evaluate
from .http import PoliteClient
from .runner import fetch_one, mark_delivered, resolve_unverified, run, select_employers
from .store import Store


def _default_config() -> str:
    return os.environ.get("JOB_WATCH_CONFIG", "config.yaml")


def _load(args) -> Config:
    path = Path(args.config)
    if not path.exists():
        sys.exit(f"config not found: {path} (pass --config or set JOB_WATCH_CONFIG)")
    load_dotenv(path.resolve().parent / ".env")
    load_dotenv()  # also ./.env
    cfg = load_config(path)
    if getattr(args, "db", None):
        cfg.settings.db_path = args.db
    if getattr(args, "delay", None) is not None:
        cfg.settings.request_delay_seconds = args.delay
    return cfg


def cmd_run(args) -> int:
    cfg = _load(args)
    store = Store(cfg.settings.db_file)
    with PoliteClient(cfg.settings) as http:
        report = run(cfg, store, http, only=args.only)

    text = render_text(report)
    print(render_json(report) if args.json else text)

    if args.email:
        subject = f"job-watch: {len(report.new)} new posting(s) — {report.run_date}"
        if report.errors:
            subject += f" ({len(report.errors)} site(s) failed)"
        if report.new or report.closed or report.errors or args.email_always:
            try:
                send_digest(subject, text)
                print("Emailed digest.", file=sys.stderr)
            except (EmailConfigError, OSError) as exc:
                print(f"Email failed: {exc}", file=sys.stderr)
                print("Postings were NOT marked as reported; they'll appear again next run.",
                      file=sys.stderr)
                store.close()
                return 2

    if not args.dry_run:
        mark_delivered(store, report)
    store.close()
    return 1 if args.fail_on_error and report.errors else 0


def cmd_check_config(args) -> int:
    cfg = _load(args)
    ok = True
    have_pw = playwright_available()
    print(f"{len(cfg.employers)} employers; types available: {', '.join(sorted(REGISTRY))}")
    print(f"Playwright installed: {'yes' if have_pw else 'no'}\n")
    for e in cfg.employers:
        status = "enabled " if e.enabled else "disabled"
        note = ""
        try:
            get_fetcher(e, http=None)  # type: ignore[arg-type]
        except ConfigError as exc:
            ok = False
            note = f"  !! {exc}"
        if needs_browser(e):
            note += "  (needs Playwright)" + ("" if have_pw else " - NOT INSTALLED")
        print(f"  [{status}] {e.id:<24} {e.type:<16} {e.category:<9}{note}")
    if any(e.type == "usajobs" and e.enabled for e in cfg.employers):
        if not (os.environ.get("USAJOBS_API_KEY") and os.environ.get("USAJOBS_EMAIL")):
            print("\n  !! USAJOBS_API_KEY / USAJOBS_EMAIL not set; the usajobs entry will fail")
    return 0 if ok else 1


def cmd_probe(args) -> int:
    """Fetch employers without touching the database and explain the filter decisions."""
    cfg = _load(args)
    employers = select_employers(cfg, args.ids or None) if args.ids or args.all else []
    if not employers:
        sys.exit("give one or more employer ids, or --all")
    rc = 0
    with PoliteClient(cfg.settings) as http:
        for e in employers:
            print(f"\n=== {e.name} [{e.id}] ({e.type}) ===")
            try:
                postings = fetch_one(e, http)
                resolve_unverified(e, http, postings, cfg)
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                rc = 1
                continue
            matched = 0
            for p in postings:
                r = evaluate(p, cfg.filters, e.filters)
                matched += r.matched
                if r.matched or args.verbose:
                    mark = "+" if r.matched else "-"
                    print(f"  {mark} {p.title} | {p.location}")
                    if args.verbose:
                        print(f"      {r.summary}")
                        print(f"      {p.url}")
            print(f"  -> {len(postings)} fetched, {matched} matched")
    return rc


def cmd_links(args) -> int:
    """Print every link on a page, to help write link_regex / selectors."""
    from urllib.parse import urljoin

    from bs4 import BeautifulSoup

    from .fetchers import browser

    cfg = _load(args)
    with PoliteClient(cfg.settings) as http:
        if args.render_js:
            html = browser.render(http, args.url)
        else:
            html = http.get(args.url).text
    soup = BeautifulSoup(html, "html.parser")
    links = soup.find_all("a", href=True)
    for a in links:
        text = " ".join(a.get_text(" ").split())[:70]
        print(f"{text:<70}  {urljoin(args.url, a['href'])}")
    print(f"\n{len(links)} link(s); page is {len(html)} characters")
    if not links:
        print("No links: the page probably builds its content with JavaScript. "
              "Try again with --render-js (needs Playwright).")
    return 0


def cmd_list(args) -> int:
    cfg = _load(args)
    store = Store(cfg.settings.db_file)
    rows = store.list_postings(status=args.status, matched_only=not args.everything)
    if args.email:
        from datetime import date

        from .runner import RunReport

        report = RunReport(run_date=date.today().isoformat(), new=rows,
                           categories={e.id: e.category for e in cfg.employers})
        heading = {"open": "ALL OPEN POSTINGS", "closed": "CLOSED POSTINGS"}.get(args.status, "ALL POSTINGS")
        text = render_text(report, heading=heading)
        print(text)
        try:
            send_digest(f"job-watch: {len(rows)} open posting(s) - {report.run_date}", text)
            print("Emailed.", file=sys.stderr)
        except (EmailConfigError, OSError) as exc:
            print(f"Email failed: {exc}", file=sys.stderr)
            store.close()
            return 2
    elif args.json:
        print(json.dumps([r.to_dict() for r in rows], indent=2))
    else:
        for r in rows:
            closed = f"  closed {r.closed_date}" if r.closed_date else ""
            print(f"{r.first_seen}  {r.firm:<22.22} {r.title}  [{r.location}]{closed}")
            print(f"            {r.url}")
        print(f"\n{len(rows)} posting(s)")
    store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="job-watch", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose-log", action="store_true", help="log each request")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--config", default=_default_config(), help="path to config.yaml")
        sp.add_argument("--db", help="override settings.db_path")

    r = sub.add_parser("run", help="fetch all sites and print what's new")
    common(r)
    r.add_argument("--json", action="store_true", help="print the digest as JSON")
    r.add_argument("--email", action="store_true", help="email the digest (SMTP env vars)")
    r.add_argument("--email-always", action="store_true",
                   help="with --email, send even when nothing changed")
    r.add_argument("--only", nargs="+", metavar="ID", help="only these employer ids")
    r.add_argument("--dry-run", action="store_true",
                   help="don't mark postings as reported (they'll show again next run)")
    r.add_argument("--delay", type=float, help="override request_delay_seconds")
    r.add_argument("--fail-on-error", action="store_true",
                   help="exit 1 if any site failed (default: exit 0)")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("check-config", help="validate config.yaml")
    common(c)
    c.set_defaults(func=cmd_check_config)

    pr = sub.add_parser("probe", help="fetch employers and show filter decisions (no DB writes)")
    common(pr)
    pr.add_argument("ids", nargs="*", help="employer ids")
    pr.add_argument("--all", action="store_true", help="probe every enabled employer")
    pr.add_argument("--verbose", action="store_true", help="show non-matching postings and reasons")
    pr.add_argument("--delay", type=float, help="override request_delay_seconds")
    pr.set_defaults(func=cmd_probe)

    lk = sub.add_parser("links", help="print every link on a page (for writing html configs)")
    common(lk)
    lk.add_argument("url")
    lk.add_argument("--render-js", action="store_true", help="render with Playwright first")
    lk.set_defaults(func=cmd_links)

    ls = sub.add_parser("list", help="list postings stored in the database")
    common(ls)
    ls.add_argument("--status", choices=["open", "closed", "all"], default="open")
    ls.add_argument("--everything", action="store_true", help="include non-matching postings")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--email", action="store_true",
                    help="email the list (e.g. to send the full current list once)")
    ls.set_defaults(func=cmd_list)
    return p


def main(argv: list[str] | None = None) -> int:
    # Windows pipes/redirects default to a legacy code page that can't encode
    # the digest's bullets and check marks; force UTF-8 everywhere.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose_log else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
