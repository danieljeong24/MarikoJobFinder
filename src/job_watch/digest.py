"""Render a RunReport as terminal text or JSON."""

from __future__ import annotations

import json

from .runner import RunReport
from .store import StoredPosting

CATEGORY_ORDER = [
    ("public", "Public agencies"),
    ("local", "Local firms"),
    ("national", "National firms"),
    ("federal", "Federal (USAJOBS)"),
]


def _line(p: StoredPosting) -> list[str]:
    flag = "  [location unverified]" if p.location_unverified else ""
    lines = [f"  • {p.title}", f"      {p.firm} — {p.location or 'location n/a'}{flag}"]
    if p.url:
        lines.append(f"      {p.url}")
    return lines


def render_text(report: RunReport) -> str:
    out: list[str] = []
    bar = "=" * 72
    out.append(bar)
    out.append(f"job-watch digest — {report.run_date}")
    out.append(bar)

    if report.new:
        out.append(f"\nNEW POSTINGS ({len(report.new)})")
        for cat, label in CATEGORY_ORDER + [(None, "Other")]:
            group = [
                p for p in report.new
                if report.categories.get(p.employer_id) == cat
                or (cat is None and report.categories.get(p.employer_id)
                    not in {c for c, _ in CATEGORY_ORDER})
            ]
            if not group:
                continue
            out.append(f"\n{label}")
            out.append("-" * len(label))
            for p in group:
                out.extend(_line(p))
    else:
        out.append("\nNo new matching postings since the last run.")

    if report.closed:
        out.append(f"\nCLOSED SINCE LAST RUN ({len(report.closed)})")
        for p in report.closed:
            out.append(f"  • {p.title} — {p.firm} (closed {p.closed_date})")

    if report.stats:
        checked = sum(s.fetched for s in report.stats)
        out.append(f"\nChecked {len(report.stats)} site(s), {checked} posting(s) total.")

    if report.errors:
        out.append(f"\nSITES THAT FAILED ({len(report.errors)})")
        for e in report.errors:
            out.append(f"  ✗ {e.name} [{e.employer_id}]: {e.error}")

    out.append("")
    return "\n".join(out)


def render_json(report: RunReport) -> str:
    return json.dumps(report.to_dict(), indent=2)
