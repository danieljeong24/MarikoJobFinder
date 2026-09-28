"""Generic RSS/Atom feed fetcher.

options:
  url:            the feed URL
  location_field: optional feed entry key holding the location
                  (feedparser flattens namespaced tags, e.g. <job:location> -> job_location)
  location_regex: optional regex with one group, applied to the entry summary,
                  when the location only appears in the description text
  default_location: used when nothing else yields a location
"""

from __future__ import annotations

import re

import feedparser

from ..models import Posting
from .base import Fetcher, FetcherError, clean


class RssFetcher(Fetcher):
    type_name = "rss"
    required_options = ("url",)

    def feed_url(self) -> str:
        return self.options["url"]

    def fetch(self) -> list[Posting]:
        resp = self.http.get(self.feed_url())
        return self.parse(resp.content)

    def parse(self, content: bytes | str) -> list[Posting]:
        feed = feedparser.parse(content)
        if feed.bozo and not feed.entries:
            raise FetcherError(f"could not parse feed: {feed.bozo_exception}")
        return [self.entry_to_posting(e) for e in feed.entries]

    def entry_to_posting(self, e) -> Posting:
        return self.make_posting(
            title=clean(e.get("title")),
            location=self.entry_location(e),
            url=e.get("link") or "",
            external_id=clean(e.get("id") or e.get("guid")) or None,
            department=self.entry_department(e),
            posted_date=_date(e),
        )

    def entry_location(self, e) -> str:
        field = self.options.get("location_field")
        if field and e.get(field):
            return clean(e.get(field))
        rx = self.options.get("location_regex")
        if rx:
            m = re.search(rx, clean(e.get("summary")), re.IGNORECASE)
            if m:
                return clean(m.group(1))
        return self.options.get("default_location", "")

    def entry_department(self, e) -> str:
        field = self.options.get("department_field")
        return clean(e.get(field)) if field else ""


def _date(e) -> str | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    if t:
        return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
    return None
