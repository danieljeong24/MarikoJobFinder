"""Runner and HTTP client behavior, with no real network."""

from datetime import date

import httpx
import pytest

from job_watch import runner
from job_watch.config import Config, Employer, Settings
from job_watch.digest import render_json, render_text
from job_watch.http import PoliteClient, RobotsDisallowed
from job_watch.models import Posting
from job_watch.store import Store


def _cfg(config):
    return Config(
        settings=config.settings,
        filters=config.filters,
        employers=[
            Employer(id="good", name="Good Firm", category="local", type="rss", options={"url": "x"}),
            Employer(id="bad", name="Bad Firm", category="national", type="rss", options={"url": "x"}),
        ],
    )


def test_one_site_failing_does_not_kill_run(config, monkeypatch):
    def fake_fetch(employer, http):
        if employer.id == "bad":
            raise httpx.ConnectError("boom")
        return [Posting("good", "Good Firm", "Civil Engineer I", "Las Vegas, NV",
                        "https://good/1", "rss", external_id="1")]

    monkeypatch.setattr(runner, "fetch_one", fake_fetch)
    store = Store(":memory:")
    report = runner.run(_cfg(config), store, http=None, today=date(2026, 9, 28))

    assert [p.title for p in report.new] == ["Civil Engineer I"]
    assert [e.employer_id for e in report.errors] == ["bad"]
    text = render_text(report)
    assert "SITES THAT FAILED (1)" in text and "Bad Firm" in text and "ConnectError" in text
    assert '"failed_sites"' in render_json(report)


def test_failed_site_keeps_its_postings_open(config, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(employer, http):
        calls["n"] += 1
        if calls["n"] > 2:  # second run: everything fails
            raise httpx.ReadTimeout("slow")
        return [Posting(employer.id, employer.name, "Civil Engineer I", "Las Vegas, NV",
                        f"https://{employer.id}/1", "rss", external_id="1")]

    monkeypatch.setattr(runner, "fetch_one", fake_fetch)
    store = Store(":memory:")
    runner.run(_cfg(config), store, None, today=date(2026, 9, 21))
    runner.run(_cfg(config), store, None, today=date(2026, 9, 28))
    assert all(p.closed_date is None for p in store.list_postings(status="all"))


def _client(handler, **settings):
    s = Settings(request_delay_seconds=0, backoff_base_seconds=0, **settings)
    c = PoliteClient(s, transport=httpx.MockTransport(handler))
    c._sleep = lambda _: None
    return c


def test_retries_on_429_then_succeeds():
    hits = {"n": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        hits["n"] += 1
        if hits["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as c:
        assert c.get_json("https://ex.com/api") == {"ok": True}
    assert hits["n"] == 3


def test_gives_up_after_max_retries():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(503)

    with _client(handler, max_retries=2) as c, pytest.raises(httpx.HTTPStatusError):
        c.get("https://ex.com/api")


def test_respects_robots_txt():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="ok")

    with _client(handler) as c:
        assert c.get("https://ex.com/public").text == "ok"
        with pytest.raises(RobotsDisallowed):
            c.get("https://ex.com/private/jobs")


def test_sends_configured_user_agent():
    seen = {}

    def handler(request):
        seen[request.url.path] = request.headers["User-Agent"]
        return httpx.Response(200, text="")

    with _client(handler, user_agent="job-watch-test/1.0") as c:
        c.get("https://ex.com/x")
    assert seen["/x"] == "job-watch-test/1.0"


def test_vague_locations_are_resolved(config, monkeypatch):
    """'3 Locations' postings get their real locations looked up, then re-filtered."""
    from job_watch.fetchers.workday import WorkdayFetcher

    emp = Employer(id="wd", name="WD", category="national", type="workday",
                   options={"host": "h", "tenant": "t", "site": "s"})
    lv = Posting("wd", "WD", "Civil Engineer I", "3 Locations", "u1", "workday", extra={"path": "/a"})
    elsewhere = Posting("wd", "WD", "Civil Engineer I", "2 Locations", "u2", "workday", extra={"path": "/b"})
    lookups = {"/a": "Denver, CO / Las Vegas, NV", "/b": "Denver, CO / Austin, TX"}
    monkeypatch.setattr(WorkdayFetcher, "resolve_location",
                        lambda self, p: lookups[p.extra["path"]])
    runner.resolve_unverified(emp, _client(lambda r: httpx.Response(404)), [lv, elsewhere], config)
    assert lv.location == "Denver, CO / Las Vegas, NV"
    assert elsewhere.location == "Denver, CO / Austin, TX"
    from job_watch.filters import evaluate
    assert evaluate(lv, config.filters).matched
    assert not evaluate(elsewhere, config.filters).matched


def test_same_posting_on_two_sites_shown_once(config, monkeypatch):
    def fake_fetch(employer, http):
        return [Posting(employer.id, "HNTB", "New Grad Civil Engineer I", "Las Vegas, NV",
                        f"https://{employer.id}/1", "workday", external_id="R-1")]

    monkeypatch.setattr(runner, "fetch_one", fake_fetch)
    cfg = _cfg(config)
    store = Store(":memory:")
    report = runner.run(cfg, store, None, today=date(2026, 9, 28))
    assert len(report.new) == 1 and len(report.duplicate_keys) == 1
    runner.mark_delivered(store, report)
    assert store.new_matches() == []  # the hidden duplicate was marked too


def test_per_employer_robots_override():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /feed\n")
        return httpx.Response(200, text="ok")

    with _client(handler) as c:
        with pytest.raises(RobotsDisallowed):
            c.get("https://ex.com/feed")
        with c.robots_policy(False):
            assert c.get("https://ex.com/feed").text == "ok"
        with pytest.raises(RobotsDisallowed):
            c.get("https://ex.com/feed")
