"""Generic HTML scraper driven by CSS selectors in the config.

Two modes:

1. Selector mode — each job is an element matching `item_selector`:
     item_selector:     "li.job"
     title_selector:    "a"            (text; defaults to the item itself)
     link_selector:     "a"            (href; defaults to the first <a>)
     location_selector: ".location"    (optional)

2. Link mode — every <a> whose href matches `link_regex` is a job:
     link_regex: "/careers/[^/]+$"

Common options:
  url:              page to fetch
  render_js:        true to render with Playwright first (optional dependency)
  wait_selector:    with render_js, wait for this selector before reading
  default_location: used when no location selector / no location text
  exclude_titles:   list of link texts to ignore (nav links like "Apply")
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

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
        url = self.options["url"]
        if self.options.get("render_js"):
            html = browser.render(self.http, url, self.options.get("wait_selector"))
        else:
            html = self.http.get(url).text
        return self.parse(html, url)

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
                out.append(self.make_posting(title=title, location=default_loc, url=url))
        return out
