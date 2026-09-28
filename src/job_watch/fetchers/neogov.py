"""NEOGOV / GovernmentJobs.com agency job boards.

Every agency on governmentjobs.com/careers/{agency} publishes an RSS feed:

GET https://www.governmentjobs.com/SearchEngine/JobsFeed?agency={agency}

Items carry NEOGOV-specific tags (<joblisting:location>, <joblisting:department>,
...) which feedparser flattens to `joblisting_location` etc.

options:
  agency: the slug in governmentjobs.com/careers/{agency}
  host:   optional, defaults to www.governmentjobs.com
          (school districts use www.schooljobs.com)
  default_location: used when an item has no location tag
"""

from __future__ import annotations

from urllib.parse import quote

from .base import clean
from .rss import RssFetcher


class NeogovFetcher(RssFetcher):
    type_name = "neogov"
    required_options = ("agency",)

    def feed_url(self) -> str:
        host = self.options.get("host", "www.governmentjobs.com")
        return f"https://{host}/SearchEngine/JobsFeed?agency={quote(self.options['agency'])}"

    def entry_location(self, e) -> str:
        for key in ("joblisting_location", "location"):
            if e.get(key):
                return clean(e.get(key))
        # Some feeds only carry city/state separately.
        city, state = clean(e.get("joblisting_city")), clean(e.get("joblisting_state"))
        if city or state:
            return ", ".join(filter(None, [city, state]))
        return self.options.get("default_location", "")

    def entry_department(self, e) -> str:
        parts = [clean(e.get(k)) for k in ("joblisting_department", "joblisting_categories")]
        return " | ".join(p for p in parts if p)

    def entry_to_posting(self, e):
        p = super().entry_to_posting(e)
        job_id = clean(e.get("joblisting_jobid") or e.get("joblisting_id"))
        if job_id:
            p.external_id = job_id
        return p
