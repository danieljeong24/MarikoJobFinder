from datetime import date

import pytest

from job_watch.filters import evaluate
from job_watch.models import Posting
from job_watch.runner import RunReport, mark_delivered
from job_watch.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _postings(run, employer_id="examplefirm"):
    return [
        Posting(employer_id=employer_id, firm="Example Firm", title=p["title"],
                location=p["location"], url=f"https://example.com/jobs/{p['id']}",
                source="test", external_id=p["id"])
        for p in run["postings"]
    ]


def _sync(store, config, run, employer_id="examplefirm"):
    rows = []
    for p in _postings(run, employer_id):
        r = evaluate(p, config.filters)
        rows.append((p, r.matched, r.summary, r.location_unverified))
    return store.sync_employer(employer_id, rows, date.fromisoformat(run["date"]))


def _deliver(store, run_date):
    report = RunReport(run_date=run_date, new=store.new_matches(), closed=store.newly_closed_matches())
    mark_delivered(store, report)
    return report


def test_three_run_lifecycle(store, config, load_fixture):
    runs = load_fixture("diff_runs.json")["runs"]

    # Run 1: A and B are new matches; C (senior) is stored but not reported.
    res = _sync(store, config, runs[0])
    assert res.inserted == 3 and not res.closed
    r1 = _deliver(store, runs[0]["date"])
    assert sorted(p.title for p in r1.new) == ["Civil EIT", "Transportation Engineer I"]
    assert r1.closed == []

    # Run 2: B disappears -> closed; D appears -> new; A is not repeated.
    res = _sync(store, config, runs[1])
    assert len(res.closed) == 1
    r2 = _deliver(store, runs[1]["date"])
    assert [p.title for p in r2.new] == ["Junior Traffic Engineer"]
    assert [p.title for p in r2.closed] == ["Civil EIT"]
    assert r2.closed[0].closed_date == "2026-09-14"

    # Run 3: B comes back (reopened, not re-announced); C (unmatched) closes silently.
    res = _sync(store, config, runs[2])
    assert len(res.reopened) == 1
    r3 = _deliver(store, runs[2]["date"])
    assert r3.new == [] and r3.closed == []

    all_rows = {p.title: p for p in store.list_postings(status="all", matched_only=False)}
    assert len(all_rows) == 4, "rows are never deleted"
    assert all_rows["Civil EIT"].closed_date is None
    assert all_rows["Civil EIT"].first_seen == "2026-09-07"
    assert all_rows["Senior Bridge Engineer"].closed_date == "2026-09-21"
    assert all_rows["Transportation Engineer I"].last_seen == "2026-09-21"


def test_undelivered_postings_show_again(store, config, load_fixture):
    run = load_fixture("diff_runs.json")["runs"][0]
    _sync(store, config, run)
    assert len(store.new_matches()) == 2
    # No mark_delivered (e.g. --dry-run or email failure): still new next time.
    _sync(store, config, run)
    assert len(store.new_matches()) == 2


def test_failed_employer_does_not_touch_others(store, config, load_fixture):
    run = load_fixture("diff_runs.json")["runs"][0]
    _sync(store, config, run, employer_id="firm-a")
    _sync(store, config, run, employer_id="firm-b")
    _deliver(store, run["date"])
    # firm-b returns nothing now; firm-a is not affected.
    store.sync_employer("firm-b", [], date(2026, 9, 14))
    open_rows = store.list_postings(status="open", matched_only=False)
    assert {p.employer_id for p in open_rows} == {"firm-a"}


def test_loosening_filters_surfaces_old_posting_once(store, config, load_fixture):
    run = load_fixture("diff_runs.json")["runs"][0]
    _sync(store, config, run)
    _deliver(store, run["date"])

    looser = config.filters.model_copy(deep=True)
    looser.level.exclude = [k for k in looser.level.exclude if k.lower() != "senior"]
    looser.level.include.append("senior")
    rows = []
    for p in _postings(run):
        r = evaluate(p, looser)
        rows.append((p, r.matched, r.summary, r.location_unverified))
    store.sync_employer("examplefirm", rows, date(2026, 9, 14))
    assert [p.title for p in store.new_matches()] == ["Senior Bridge Engineer"]


def test_duplicate_postings_in_one_fetch_are_collapsed(store, config, load_fixture):
    run = load_fixture("diff_runs.json")["runs"][0]
    run = dict(run, postings=run["postings"] + run["postings"][:1])
    res = _sync(store, config, run)
    assert res.inserted == 3


def test_posting_key_ignores_tracking_params():
    a = Posting("e", "F", "T", "L", "https://x.com/job/1?utm_source=li", "s")
    b = Posting("e", "F", "T", "L", "https://x.com/job/1/", "s")
    c = Posting("e", "F", "T", "L", "https://x.com/job?id=2", "s")
    d = Posting("e", "F", "T", "L", "https://x.com/job?id=3", "s")
    assert a.key == b.key
    assert c.key != d.key
