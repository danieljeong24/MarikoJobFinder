"""Workday: the JSON API behind *.myworkdayjobs.com career sites.

POST https://{host}/wday/cxs/{tenant}/{site}/jobs
body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "..."}

options:
  host:        e.g. hntb.wd5.myworkdayjobs.com
  tenant:      e.g. hntb
  site:        e.g. HNTB_Careers
  search_text: optional server-side keyword search (e.g. "Las Vegas")
  applied_facets: optional dict copied from the browser's request payload
"""

from __future__ import annotations

from ..models import Posting
from .base import Fetcher, clean


class WorkdayFetcher(Fetcher):
    type_name = "workday"
    required_options = ("host", "tenant", "site")
    page_size = 20  # Workday rejects limits above 20

    @property
    def api_url(self) -> str:
        o = self.options
        return f"https://{o['host']}/wday/cxs/{o['tenant']}/{o['site']}/jobs"

    def fetch(self) -> list[Posting]:
        postings: list[Posting] = []
        offset = 0
        total = None
        for _ in range(self.max_pages):
            body = {
                "appliedFacets": self.options.get("applied_facets", {}),
                "limit": self.page_size,
                "offset": offset,
                "searchText": self.options.get("search_text", ""),
            }
            data = self.http.post_json(
                self.api_url, json=body, headers={"Accept": "application/json"}
            )
            page = self.parse(data)
            postings.extend(page)
            # Workday only reports `total` on the first page.
            if total is None:
                total = int(data.get("total") or 0)
            offset += self.page_size
            if not page or offset >= total:
                break
        return postings

    def parse(self, data: dict) -> list[Posting]:
        o = self.options
        out = []
        for job in data.get("jobPostings", []) or []:
            path = job.get("externalPath") or ""
            bullets = job.get("bulletFields") or []
            out.append(
                self.make_posting(
                    title=clean(job.get("title")),
                    location=clean(job.get("locationsText")),
                    url=f"https://{o['host']}/{o['site']}{path}" if path else "",
                    external_id=clean(bullets[0]) if bullets else (path or None),
                    posted_date=clean(job.get("postedOn")) or None,
                )
            )
        return out
