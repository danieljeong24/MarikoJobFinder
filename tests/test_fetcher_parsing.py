"""Each fetcher's parser against a recorded-shape fixture. No network."""

from job_watch.fetchers.greenhouse import GreenhouseFetcher
from job_watch.fetchers.icims import IcimsFetcher
from job_watch.fetchers.lever import LeverFetcher
from job_watch.fetchers.neogov import NeogovFetcher
from job_watch.fetchers.oracle_hcm import OracleHcmFetcher
from job_watch.fetchers.smartrecruiters import SmartRecruitersFetcher
from job_watch.fetchers.taleo import TaleoFetcher
from job_watch.fetchers.ultipro import UltiproFetcher
from job_watch.fetchers.usajobs import UsajobsFetcher
from job_watch.fetchers.workday import WorkdayFetcher
from job_watch.fetchers.html import HtmlFetcher
from job_watch.filters import evaluate

from .conftest import make_employer


def matched_titles(postings, config, employer=None):
    overrides = employer.filters if employer else None
    return [p.title for p in postings if evaluate(p, config.filters, overrides).matched]


def test_workday(load_fixture, config):
    f = WorkdayFetcher(make_employer("workday", host="x.wd5.myworkdayjobs.com", tenant="x", site="Careers"), None)
    ps = f.parse(load_fixture("workday.json"))
    assert len(ps) == 3
    assert ps[0].url == "https://x.wd5.myworkdayjobs.com/Careers/job/Las-Vegas-NV/Transportation-Engineer-I_R-30101"
    assert ps[0].external_id == "R-30101"
    assert matched_titles(ps, config) == ["Transportation Engineer I", "Roadway Design EIT"]


def test_greenhouse(load_fixture, config):
    f = GreenhouseFetcher(make_employer("greenhouse", board_token="examplefirm"), None)
    ps = f.parse(load_fixture("greenhouse.json"))
    assert ps[0].department == "Transportation"
    assert matched_titles(ps, config) == ["Junior Traffic Engineer"]


def test_lever(load_fixture, config):
    f = LeverFetcher(make_employer("lever", company="examplefirm"), None)
    ps = f.parse(load_fixture("lever.json"))
    assert ps[0].location == "North Las Vegas, NV (hybrid)"
    assert ps[0].posted_date == "2025-09-26"
    assert matched_titles(ps, config) == ["Civil Engineer - Entry Level"]


def test_usajobs_grade_cap(load_fixture, config):
    emp = make_employer("usajobs", max_low_grade=9)
    emp.filters.skip_level = emp.filters.skip_discipline = emp.filters.skip_location = True
    ps = UsajobsFetcher(emp, None).parse(load_fixture("usajobs.json"))
    assert [p.title for p in ps] == ["Civil Engineer (GS-7/9)", "Civil Engineer (GS-9/11)"]
    assert ps[0].url == "https://www.usajobs.gov:443/job/845000101"
    assert len(matched_titles(ps, config, emp)) == 2


def test_smartrecruiters(load_fixture, config):
    f = SmartRecruitersFetcher(make_employer("smartrecruiters", company="AECOM2"), None)
    ps = f.parse(load_fixture("smartrecruiters.json"))
    assert ps[0].url == "https://jobs.smartrecruiters.com/AECOM2/744000150000001"
    assert ps[1].location.endswith("(Remote)")
    assert matched_titles(ps, config) == [
        "Entry-Level Civil Engineer - Transportation", "Traffic Engineer II",
    ]


def test_oracle_hcm(load_fixture, config):
    f = OracleHcmFetcher(make_employer("oracle_hcm", host="h.oraclecloud.com", site="CX_1"), None)
    ps = f.parse(load_fixture("oracle_hcm.json"))
    assert ps[0].url == "https://h.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/88001"
    assert "Henderson" in ps[1].location and "(Hybrid)" in ps[1].location
    assert matched_titles(ps, config) == ["Transportation Engineer in Training", "Graduate Civil Engineer"]


def test_taleo(load_fixture, config):
    f = TaleoFetcher(make_employer("taleo", host="hdr.taleo.net", section="ex", portal="1"), None)
    ps = f.parse(load_fixture("taleo.json"))
    assert ps[0].location == "Las Vegas-Nevada-United States"
    assert ps[0].url == "https://hdr.taleo.net/careersection/ex/jobdetail.ftl?job=192315&lang=en"
    assert ps[1].location.count("/") == 1
    assert matched_titles(ps, config) == ["Transportation Engineer I"]


def test_ultipro(load_fixture, config):
    f = UltiproFetcher(make_employer("ultipro", host="recruiting2.ultipro.com", tenant="T", board_id="B"), None)
    ps = f.parse(load_fixture("ultipro.json"))
    assert ps[0].location == "Henderson, NV"
    assert ps[0].url.endswith("/T/JobBoard/B/OpportunityDetail?opportunityId=f2c53c84-bd66-45f6-99d6-40d6684ab9a3")
    assert matched_titles(ps, config) == ["Transportation EIT"]


def test_neogov(load_fixture, config):
    f = NeogovFetcher(make_employer("neogov", agency="clarkcounty"), None)
    assert f.feed_url() == "https://www.governmentjobs.com/SearchEngine/JobsFeed?agency=clarkcounty"
    ps = f.parse(load_fixture("neogov.xml"))
    assert [p.external_id for p in ps] == ["4004033", "5131829"]
    assert ps[0].location == "Las Vegas, NV"
    assert "Public Works" in ps[0].department
    assert ps[0].posted_date == "2026-09-21"
    assert matched_titles(ps, config) == ["Assistant/Associate Engineer"]


def test_icims(load_fixture, config):
    f = IcimsFetcher(make_employer("icims", host="careers-kimley-horn.icims.com"), None)
    html = load_fixture("icims.html")
    ps = f.parse(html, "https://careers-kimley-horn.icims.com/jobs/search")
    assert [p.external_id for p in ps] == ["18290", "23448"]
    assert ps[0].location == "US-NV-Las Vegas"
    assert "in_iframe" not in ps[0].url
    assert matched_titles(ps, config) == ["Experienced Civil EIT - Land Development"]


def test_html_link_mode(config):
    html = """
      <a href="/careers">Careers</a>
      <a href="/careers/civil-designer---land-development">Civil Designer - Land Development</a>
      <a href="/careers/assistant-project-manager">Assistant Project Manager</a>
    """
    emp = make_employer("html", url="https://www.lochsa.com/careers",
                        link_regex=r"lochsa\.com/careers/[^/?#]+$")
    ps = HtmlFetcher(emp, None).parse(html, "https://www.lochsa.com/careers")
    assert [p.title for p in ps] == ["Civil Designer - Land Development", "Assistant Project Manager"]
    assert ps[0].location == ""  # -> flagged unverified by the filter
    r = evaluate(ps[0], config.filters)
    assert r.matched and r.location_unverified


def test_html_selector_mode():
    html = """<ul>
      <li class="job"><a href="/j/1">Traffic Engineer I</a><span class="loc">Henderson, NV</span></li>
      <li class="job"><a href="/j/2">Accountant</a><span class="loc">Las Vegas, NV</span></li>
    </ul>"""
    emp = make_employer("html", url="https://ex.com/careers", item_selector="li.job",
                        title_selector="a", location_selector=".loc")
    ps = HtmlFetcher(emp, None).parse(html, "https://ex.com/careers")
    assert [(p.title, p.location, p.url) for p in ps] == [
        ("Traffic Engineer I", "Henderson, NV", "https://ex.com/j/1"),
        ("Accountant", "Las Vegas, NV", "https://ex.com/j/2"),
    ]


def test_workday_detail_location(load_fixture):
    loc = WorkdayFetcher.parse_detail_location(load_fixture("workday_detail.json"))
    assert loc == "Kansas City, MO / Las Vegas, NV / Denver, CO"


def test_html_link_mode_reads_location_from_row(config):
    # Shape of careers.jacobs.com (Avature) after rendering.
    html = """
    <article><h3><a href="/en_US/careers/JobDetail/Highway-Engineer/46004">Highway Engineer</a></h3>
      <span>Las Vegas, Nevada, United States</span> <a href="/en_US/careers/ApplicationMethods?jobId=46004">Apply</a></article>
    <article><h3><a href="/en_US/careers/JobDetail/Civil-Engineer-I/46010">Civil Engineer I</a></h3>
      <span>Denver, CO</span><span>Remote</span></article>
    <article><h3><a href="/en_US/careers/JobDetail/Junior-Civil-Engineer/46011">Junior Civil Engineer</a></h3></article>
    """
    emp = make_employer("html", url="https://careers.jacobs.com/en_US/careers/SearchJobs",
                        link_regex="/careers/JobDetail/")
    ps = HtmlFetcher(emp, None).parse(html, "https://careers.jacobs.com/en_US/careers/SearchJobs")
    assert [(p.title, p.location) for p in ps] == [
        ("Highway Engineer", "Las Vegas, Nevada"),
        ("Civil Engineer I", "Denver, CO / Remote/Hybrid"),
        ("Junior Civil Engineer", ""),
    ]


def test_html_detail_location_lookup():
    class FakeHttp:
        def get(self, url, **kw):
            class R:
                text = "<p>This position is located in the Las Vegas office only.</p>"
            return R()

    emp = make_employer("html", url="https://www.lochsa.com/career-category/civil",
                        link_regex="/careers/", detail_location_keywords=["Las Vegas", "Boise"])
    f = HtmlFetcher(emp, FakeHttp())
    p = f.make_posting(title="Civil Designer", location="", url="https://www.lochsa.com/careers/x")
    assert f.resolve_location(p) == "Las Vegas"


def test_html_paging(monkeypatch):
    pages = {
        "0": '<a href="/j/1">Civil Engineer I</a><a href="/j/2">Traffic EIT</a>',
        "2": '<a href="/j/3">Junior Civil Engineer</a>',
        "4": '<a href="/j/3">Junior Civil Engineer</a>',  # repeat -> stop
    }
    requested = []

    class FakeHttp:
        def get(self, url, **kw):
            requested.append(url)
            offset = url.split("jobOffset=")[1]

            class R:
                text = pages.get(offset, "")
            return R()

    emp = make_employer("html", url="https://ex.com/SearchJobs?jobRecordsPerPage=2",
                        link_regex="/j/\\d+", page_param="jobOffset", page_step=2)
    ps = HtmlFetcher(emp, FakeHttp()).fetch()
    assert [p.title for p in ps] == ["Civil Engineer I", "Traffic EIT", "Junior Civil Engineer"]
    assert len(requested) == 3
    assert "jobRecordsPerPage=2" in requested[0]


def test_workday_myworkdaysite_job_urls(load_fixture):
    f = WorkdayFetcher(make_employer(
        "workday", host="wd1.myworkdaysite.com", tenant="imeg", site="Imeg_Careers",
        job_url_base="https://wd1.myworkdaysite.com/recruiting/imeg/Imeg_Careers"), None)
    ps = f.parse(load_fixture("workday.json"))
    assert ps[0].url == ("https://wd1.myworkdaysite.com/recruiting/imeg/Imeg_Careers"
                         "/job/Las-Vegas-NV/Transportation-Engineer-I_R-30101")


# The next three fixtures are trimmed real responses recorded on 2026-11-11.

def test_adp(load_fixture):
    from job_watch.fetchers.adp import AdpFetcher

    f = AdpFetcher(make_employer("adp", cid="5388ae22-6327-499a-a62d-abed736e9939"), None)
    ps = f.parse(load_fixture("adp.json"))
    assert ps[0].title == "Project Manager- Water Resources"
    assert ps[0].location == "San Diego, CA"
    assert ps[0].external_id == "9201865511120_1"
    assert "jobId=9201865511120_1" in ps[0].url and "cid=5388ae22" in ps[0].url
    assert ps[0].posted_date and ps[0].posted_date.startswith("2026-")


def test_pinpoint(load_fixture, config):
    from job_watch.fetchers.pinpoint import PinpointFetcher

    f = PinpointFetcher(make_employer("pinpoint", company="woodrodgers"), None)
    ps = f.parse(load_fixture("pinpoint.json"))
    assert [(p.title, p.location) for p in ps][:2] == [
        ("Assistant Engineer", "Denver, CO"), ("Engineer", "Denver, CO")]
    assert ps[0].url.startswith("https://woodrodgers.pinpointhq.com/en/postings/")
    assert matched_titles(ps, config) == []  # right roles, wrong city


def test_sitemap(load_fixture, config):
    from job_watch.fetchers.sitemap import SitemapFetcher

    emp = make_employer("sitemap", url="https://careers.terracon.com/sitemap.xml",
                        link_regex="/job/(?P<city>las-vegas|henderson)/(?P<title>[^/]+)/",
                        state="NV")
    emp.filters.extra_level_include = ["staff engineer"]
    ps = SitemapFetcher(emp, None).parse(load_fixture("sitemap.xml"))
    assert [(p.title, p.location) for p in ps] == [
        ("Project Manager", "Las Vegas, NV"), ("Staff Engineer", "Las Vegas, NV")]
    assert matched_titles(ps, config, emp) == ["Staff Engineer"]


def test_sitemap_title_keeps_roman_numerals():
    from job_watch.fetchers.sitemap import _words

    assert _words("engineering-technician-ii") == "Engineering Technician II"
