"""Decide whether a posting is an entry-level civil/transportation role in the LV metro.

All keyword matching is case-insensitive and whole-word, so "Engineer I"
does not match "Engineer II" and "lead" does not match "leadership".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .config import EmployerFilterOverrides, Filters
from .models import Posting

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming", "DC": "District of Columbia",
}


@dataclass
class FilterResult:
    matched: bool
    reasons: list[str] = field(default_factory=list)
    location_unverified: bool = False
    remote: bool = False

    @property
    def summary(self) -> str:
        return "; ".join(self.reasons)


@lru_cache(maxsize=4096)
def _pattern(keyword: str) -> re.Pattern[str]:
    # Whole-word match. \b doesn't work next to punctuation like "Sr." so use
    # explicit alphanumeric lookarounds. Internal spaces match any whitespace
    # or hyphen ("entry level" == "entry-level").
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", keyword.strip()) if p]
    body = r"[\s\-]+".join(parts)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    if not text:
        return []
    return [k for k in keywords if _pattern(k).search(text)]


def _state_tokens(text: str) -> set[str]:
    """US states mentioned in a location string, as 2-letter codes."""
    found: set[str] = set()
    for code, name in US_STATES.items():
        if re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", text) or re.search(
            rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text, re.IGNORECASE
        ):
            found.add(code)
    return found


def check_level(title: str, filters: Filters, overrides: EmployerFilterOverrides) -> tuple[bool, str]:
    excluded = find_keywords(title, filters.level.exclude)
    if excluded:
        return False, f"level: excluded by {excluded}"
    included = find_keywords(title, filters.level.include + overrides.extra_level_include)
    if included:
        return True, f"level: matched {included}"
    return False, "level: no entry-level keyword in title"


def check_discipline(posting: Posting, filters: Filters) -> tuple[bool, str]:
    d = filters.discipline
    # A civil/transportation term in the title wins over an exclusion ("Civil
    # Engineer - Data Center" is still civil); exclusions only veto the
    # generic fallback.
    included = find_keywords(posting.title, d.include)
    if included:
        return True, f"discipline: matched {included}"
    # A civil department ("Public Works") only counts when the title is a
    # professional role, so "Maintenance Worker I/II" in Public Works fails.
    if "department" in d.match_fields and posting.department:
        dept = find_keywords(posting.department, d.include)
        role = find_keywords(posting.title, d.role_words)
        if dept and role:
            return True, f"discipline: department {dept} + role {role}"
    excluded = find_keywords(posting.title, d.exclude)
    if excluded:
        return False, f"discipline: excluded by {excluded}"
    generic = find_keywords(posting.title, d.generic)
    if generic:
        return True, f"discipline: generic {generic}"
    return False, "discipline: not civil/transportation"


def check_location(location: str, filters: Filters) -> tuple[bool, str, bool, bool]:
    """Returns (ok, reason, location_unverified, remote)."""
    loc = filters.location
    text = location or ""

    cities = find_keywords(text, loc.include)
    if cities:
        states = _state_tokens(text)
        wanted = {s.upper() if len(s) == 2 else _code_for(s) for s in loc.require_state}
        if not loc.require_state or not states or states & wanted:
            return True, f"location: matched {cities}", False, False
        return False, f"location: {cities} but state is {sorted(states)}", False, False

    if loc.remote_ok:
        remote = find_keywords(text, loc.remote_keywords)
        if remote:
            return True, f"location: remote/hybrid {remote}", False, True

    if loc.keep_unknown and any(re.search(p, text, re.IGNORECASE) for p in loc.unknown_patterns):
        return True, f"location: unverified ({text!r})", True, False

    return False, f"location: {text!r} not in Las Vegas metro", False, False


def _code_for(name: str) -> str:
    for code, full in US_STATES.items():
        if full.lower() == name.lower():
            return code
    return name.upper()


def evaluate(
    posting: Posting,
    filters: Filters,
    overrides: EmployerFilterOverrides | None = None,
) -> FilterResult:
    overrides = overrides or EmployerFilterOverrides()
    result = FilterResult(matched=True)

    checks: list[tuple[bool, str]] = []
    if not overrides.skip_level:
        checks.append(check_level(posting.title, filters, overrides))
    if not overrides.skip_discipline:
        checks.append(check_discipline(posting, filters))
    if not overrides.skip_location:
        ok, reason, unverified, remote = check_location(posting.location, filters)
        checks.append((ok, reason))
        result.location_unverified = unverified
        result.remote = remote

    for ok, reason in checks:
        result.reasons.append(reason)
        if not ok:
            result.matched = False
    return result
