"""Generic HTML scraper driven by CSS selectors in the config.

Two modes:

1. Selector mode — each job is an element matching `item_selector`:
     item_selector:     "li.job"
     title_selector:    "a"            (text; defaults to the item itself)
     link_selector:     "a"            (href; defaults to the first <a>)
     location_selector: ".location"    (optional)

2. Link mode — every <a> whose href matches `link_regex` is a job:
     link_regex: "/careers/[^/]+$"
   The location is read from the text around the link (its "row"): any
   "City, ST" / "City, State" found there. `default_location` is used if
   none is found.

Common options:
  url:              page to fetch
  extra_urls:       more pages with the same layout (e.g. one per job category)
  render_js:        true to render with Playwright first (optional dependency)
  wait_selector:    with render_js, wait for this selector before reading
  default_location: used when no location selector / no location text
  exclude_titles:   list of link texts to ignore (nav links like "Apply")

Paging (optional), for lists split across pages via a query parameter:
  page_param:  e.g. "jobOffset"
  page_step:   how much the parameter grows per page (e.g. 10)
  page_start:  first value (default 0)
  max_pages:   stop after this many pages (default 20); paging also stops
               when a page adds no new postings
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..filters import US_STATES
from ..models import Posting
from . import browser
from .base import ConfigError, Fetcher, clean


class HtmlFetcher(Fetcher):
    type_name = "html"
    required_options = ("url",)

    def __init__(self, employer, http):
        super().__init__(employer, http)
        if not (self.options.get("item_selector") or self.options.get("link_regex")):
            raise ConfigError(f"{employer.id}: html needs item_selector or link_regex")

    def fetch(self) -> list[Posting]:
        o = self.options
        postings: list[Posting] = []
        seen: set[str] = set()
        for base in [o["url"], *o.get("extra_urls", [])]:
            pages = int(o.get("max_pages", 20)) if o.get("page_param") else 1
            for i in range(pages):
                url = base
                if o.get("page_param"):
                    value = int(o.get("page_start", 0)) + i * int(o.get("page_step", 1))
                    url = _with_param(base, o["page_param"], value)
                if o.get("render_js"):
                    html = browser.render(self.http, url, o.get("wait_selector"))
                else:
                    html = self.http.get(url).text
                new = [p for p in self.parse(html, url) if p.url not in seen]
                if not new:
                    break
                for p in new:
                    seen.add(p.url)
                    postings.append(p)
        return postings

    def parse(self, html: str, base_url: str) -> list[Posting]:
        soup = BeautifulSoup(html, "html.parser")
        o = self.options
        default_loc = o.get("default_location", "")
        skip = {t.lower() for t in o.get("exclude_titles", [])}
        out: list[Posting] = []
        seen: set[str] = set()

        if o.get("item_selector"):
            for item in soup.select(o["item_selector"]):
                title_el = item.select_one(o["title_selector"]) if o.get("title_selector") else item
                link_el = (
                    item.select_one(o["link_selector"]) if o.get("link_selector") else None
                ) or (item if item.name == "a" else item.find("a"))
                loc_el = item.select_one(o["location_selector"]) if o.get("location_selector") else None
                title = clean(title_el.get_text(" ")) if title_el else ""
                href = link_el.get("href") if link_el else None
                url = urljoin(base_url, href) if href else base_url
                if not title or title.lower() in skip or (url, title) in seen:
                    continue
                seen.add((url, title))
                out.append(
                    self.make_posting(
                        title=title,
                        location=clean(loc_el.get_text(" ")) if loc_el else default_loc,
                        url=url,
                    )
                )
        else:
            rx = re.compile(o["link_regex"])
            for a in soup.find_all("a", href=True):
                url = urljoin(base_url, a["href"])
                title = clean(a.get_text(" "))
                if not rx.search(url) or not title or title.lower() in skip or url in seen:
                    continue
                seen.add(url)
                location = _row_location(a, rx, base_url) or default_loc
                out.append(self.make_posting(title=title, location=location, url=url))
        return out


def _with_param(url: str, name: str, value) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != name]
    query.append((name, str(value)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


_STATE_ALT = "|".join(
    [re.escape(n) for n in sorted(US_STATES.values(), key=len, reverse=True)] + list(US_STATES)
)
_CITY_STATE = re.compile(
    rf"\b((?:[A-Z][A-Za-z.'\-]+ ){{0,3}}[A-Z][A-Za-z.'\-]+),\s*({_STATE_ALT})(?![A-Za-z])"
)


def _row_location(anchor, job_rx: re.Pattern, base_url: str) -> str:
    """Location text in the element that holds this job link and no other job."""
    own = urljoin(base_url, anchor["href"])
    row = None
    node = anchor.parent
    while node is not None and node.name not in ("body", "html", "[document]"):
        others = {
            urljoin(base_url, x["href"])
            for x in node.find_all("a", href=True)
            if job_rx.search(urljoin(base_url, x["href"]))
        }
        if others - {own}:
            break
        row = node
        node = node.parent
    if row is None:
        return ""
    # Leave out the job title itself so "Highway Engineer Las Vegas, NV"
    # doesn't read as a city called "Highway Engineer Las Vegas".
    text = " | ".join(
        clean(t) for t in row.find_all(string=True) if anchor not in t.parents and clean(t)
    )
    found: list[str] = []
    for m in _CITY_STATE.finditer(text):
        loc = f"{m.group(1)}, {m.group(2)}"
        if loc not in found:
            found.append(loc)
    if re.search(r"(?<![A-Za-z])(remote|hybrid)(?![A-Za-z])", text, re.IGNORECASE):
        found.append("Remote/Hybrid")
    return " / ".join(found)
