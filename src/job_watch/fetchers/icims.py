"""iCIMS career portals (careers-{company}.icims.com).

iCIMS has no public JSON API, but its search page renders server-side when
requested with ``in_iframe=1``:

GET https://{host}/jobs/search?ss=1&in_iframe=1&pr={page}&searchKeyword=...

options:
  host:            e.g. careers-kimley-horn.icims.com
  search_keyword:  optional keyword (e.g. "Las Vegas") to cut down pages
  search_location: optional iCIMS location filter value, copied from the URL
                   after picking a location in the portal's search form
  render_js:       true to fall back to Playwright if the portal is JS-only
"""

from __future__ import annotations

import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from ..models import Posting
from . import browser
from .base import Fetcher, clean

JOB_HREF = re.compile(r"/jobs/(\d+)/[^/?#]*/job")
LOC_TEXT = re.compile(r"\b(?:US|USA|CA)-[A-Z]{2}-[A-Za-z .'\-]+")


class IcimsFetcher(Fetcher):
    type_name = "icims"
    required_options = ("host",)

    def page_url(self, page: int) -> str:
        params = {"ss": 1, "in_iframe": 1, "pr": page}
        if self.options.get("search_keyword"):
            params["searchKeyword"] = self.options["search_keyword"]
        if self.options.get("search_location"):
            params["searchLocation"] = self.options["search_location"]
        return f"https://{self.options['host']}/jobs/search?{urlencode(params)}"

    def fetch(self) -> list[Posting]:
        postings: list[Posting] = []
        seen: set[str] = set()
        for page in range(self.max_pages):
            url = self.page_url(page)
            if self.options.get("render_js"):
                html = browser.render(self.http, url, "a[href*='/jobs/']")
            else:
                html = self.http.get(url).text
            batch = [p for p in self.parse(html, url) if p.external_id not in seen]
            if not batch:
                break
            seen.update(p.external_id for p in batch)
            postings.extend(batch)
            total_pages = _total_pages(html)
            if total_pages is not None and page + 1 >= total_pages:
                break
        return postings

    def parse(self, html: str, base_url: str) -> list[Posting]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[Posting] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            m = JOB_HREF.search(a["href"])
            if not m or m.group(1) in seen:
                continue
            job_id = m.group(1)
            h = a.find(["h2", "h3", "h4"])
            title = clean(h.get_text(" ") if h else a.get_text(" "))
            if not title:
                title = clean(re.sub(r"^\d+\s*-\s*", "", a.get("title", "")))
            if not title:
                continue
            seen.add(job_id)
            url = urljoin(base_url, a["href"]).replace("?in_iframe=1", "").replace("&in_iframe=1", "")
            out.append(
                self.make_posting(
                    title=title,
                    location=_row_location(a),
                    url=url,
                    external_id=job_id,
                )
            )
        return out


def _row_location(anchor) -> str:
    """Find the location text in the job's row (layout varies by portal theme)."""
    row = anchor
    for _ in range(6):
        if row.parent is None:
            break
        row = row.parent
        classes = row.get("class") or []
        if "row" in classes or row.name in ("li", "tr"):
            break
    # Labelled field: <span>Job Locations</span><span>US-NV-Las Vegas</span>
    for label in row.find_all(string=re.compile(r"Location", re.IGNORECASE)):
        el = label.parent
        sib = el.find_next_sibling()
        if sib is not None:
            text = clean(sib.get_text(" "))
            if text:
                return text
    m = LOC_TEXT.search(row.get_text(" "))
    return clean(m.group(0)) if m else ""


def _total_pages(html: str) -> int | None:
    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", html, re.IGNORECASE)
    return int(m.group(1)) if m else None
