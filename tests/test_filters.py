import json
from pathlib import Path

import pytest

from job_watch.config import EmployerFilterOverrides
from job_watch.filters import evaluate, find_keywords
from job_watch.models import Posting

CASES = json.loads((Path(__file__).parent / "fixtures" / "filter_cases.json").read_text())


def posting(title, location="Las Vegas, NV", department=""):
    return Posting(
        employer_id="x", firm="X", title=title, location=location, url="https://x/1",
        source="test", department=department,
    )


@pytest.mark.parametrize("case", CASES, ids=[f"{c['title']} @ {c['location']!r}" for c in CASES])
def test_filter_cases(config, case):
    result = evaluate(posting(case["title"], case["location"]), config.filters)
    assert result.matched is case["expect"], f"{case.get('why', '')}: {result.summary}"
    if "unverified" in case:
        assert result.location_unverified is case["unverified"]


def test_whole_word_roman_numerals():
    assert find_keywords("Engineer II", ["engineer I"]) == []
    assert find_keywords("Engineer I", ["engineer I"]) == ["engineer I"]
    assert find_keywords("Engineer I/II", ["engineer I"]) == ["engineer I"]
    assert find_keywords("Engineer III", ["II"]) == []


def test_multiword_keyword_matches_hyphen_and_space():
    assert find_keywords("Engineer-in-Training", ["engineer in training"])
    assert find_keywords("Entry Level Engineer", ["entry-level"])


def test_department_can_satisfy_discipline(config):
    # "Engineer I" alone passes via the generic term; an analyst needs the
    # department to say it's transportation.
    p = posting("Analyst I", department="Transportation Planning")
    assert evaluate(p, config.filters).matched
    assert not evaluate(posting("Analyst I", department="Finance"), config.filters).matched


def test_civil_department_needs_professional_title(config):
    # Seen live at Clark County: a Public Works trades job with "I/II" in it.
    worker = posting("MAINTENANCE WORKER I/II - CDL (ROAD DIVISION)",
                     "Clark County - Las Vegas", department="Public Works")
    assert not evaluate(worker, config.filters).matched
    clerk = posting("Office Specialist II", department="Public Works")
    assert not evaluate(clerk, config.filters).matched
    engineer = posting("Assistant/Associate Engineer", department="Public Works")
    assert evaluate(engineer, config.filters).matched


def test_overrides_skip_checks(config):
    p = posting("Civil Engineer (GS-7/9)", location="Nellis AFB, Nevada")
    assert not evaluate(p, config.filters).matched
    overrides = EmployerFilterOverrides(skip_level=True, skip_discipline=True, skip_location=True)
    assert evaluate(p, config.filters, overrides).matched


def test_extra_level_include(config):
    p = posting("Staff Engineer - Transportation")
    assert not evaluate(p, config.filters).matched
    assert evaluate(p, config.filters, EmployerFilterOverrides(extra_level_include=["staff"])).matched


def test_remote_can_be_disabled(config):
    filters = config.filters.model_copy(deep=True)
    filters.location.remote_ok = False
    assert not evaluate(posting("Transportation Engineer I", "Remote"), filters).matched


def test_reasons_explain_rejection(config):
    r = evaluate(posting("Senior Traffic Engineer"), config.filters)
    assert not r.matched
    assert "excluded" in r.summary and "senior" in r.summary.lower()
