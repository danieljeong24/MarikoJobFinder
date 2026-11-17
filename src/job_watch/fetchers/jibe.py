"""iCIMS Jibe career sites (e.g. careers.kimley-horn.com).

GET https://{host}/api/jobs?location=...&limit=100&page=1

options:
  host:     e.g. careers.kimley-horn.com
  location: optional server-side location search (e.g. "Las Vegas")
  keywords: optional keyword search
"""

from __future__ import annotations

from ..models import Posting
from .base import Fetcher, clean


class JibeFetcher(Fetcher):
    type_name = "jibe"
    required_options = ("host",)
    page_size = 100

    def fetch(self) -> list[Posting]:
        url = f"https://{self.options['host']}/api/jobs"
        postings: list[Posting] = []
        for page in range(1, self.max_pages + 1):
            params = {"limit": self.page_size, "page": page}
            for opt, param in (("location", "location"), ("keywords", "keywords")):
                if self.options.get(opt):
                    params[param] = self.options[opt]
            data = self.http.get_json(url, params=params, headers={"Accept": "application/json"})
            batch = self.parse(data)
            postings.extend(batch)
            if not batch or len(postings) >= int(data.get("totalCount") or 0):
                break
        return postings

    def parse(self, data: dict) -> list[Posting]:
        host = self.options["host"]
        out = []
        for item in data.get("jobs", []) or []:
            job = item.get("data") or item
            slug = str(job.get("slug") or job.get("req_id"))
            out.append(
                self.make_posting(
                    title=clean(job.get("title")),
                    location=clean(job.get("full_location") or job.get("location_name")),
                    url=f"https://{host}/jobs/{slug}?lang=en-us",
                    external_id=clean(job.get("req_id")) or slug,
                    department=clean(" / ".join(
                        c for c in (job.get("category") or []) if isinstance(c, str))),
                    posted_date=(job.get("posted_date") or "")[:10] or None,
                )
            )
        return out
