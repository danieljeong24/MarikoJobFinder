"""Jobs listed in a site's sitemap.xml.

For career sites whose search pages are off-limits (robots.txt) but whose
sitemap lists every job URL with the city and title in the path, e.g.
https://careers.terracon.com/job/las-vegas/staff-engineer/37184/102589795280

options:
  url:         the sitemap URL
  link_regex:  only <loc> URLs matching this are jobs. Use named groups
               (?P<city>...) and (?P<title>...) to pull the location and
               title out of the URL; slugs are turned back into words.
  state:       optional, appended to the city (e.g. "NV")
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from ..models import Posting
from .base import Fetcher, clean

LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")


class SitemapFetcher(Fetcher):
    type_name = "sitemap"
    required_options = ("url", "link_regex")

    def fetch(self) -> list[Posting]:
        return self.parse(self.http.get(self.options["url"]).text)

    def parse(self, xml: str) -> list[Posting]:
        rx = re.compile(self.options["link_regex"])
        state = self.options.get("state", "")
        out: list[Posting] = []
        seen: set[str] = set()
        for url in LOC.findall(xml):
            m = rx.search(url)
            if not m or url in seen:
                continue
            seen.add(url)
            groups = m.groupdict()
            title = _words(groups.get("title") or url.rstrip("/").rsplit("/", 1)[-1])
            city = _words(groups.get("city") or "")
            location = ", ".join(x for x in (city, state) if x)
            out.append(self.make_posting(title=title, location=location, url=url))
        return out


_ROMAN = re.compile(r"^(?:i|ii|iii|iv|v|vi)$", re.IGNORECASE)


def _words(slug: str) -> str:
    words = clean(unquote(slug).replace("-", " ").replace("_", " ")).split()
    return " ".join(w.upper() if _ROMAN.match(w) else w.capitalize() for w in words)
