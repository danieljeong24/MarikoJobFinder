"""Pinpoint (pinpointhq.com) job boards.

GET https://{company}.pinpointhq.com/postings.json

options:
  company: the subdomain in {company}.pinpointhq.com
"""

from __future__ import annotations

from ..models import Posting
from .base import Fetcher, clean


class PinpointFetcher(Fetcher):
    type_name = "pinpoint"
    required_options = ("company",)

    def fetch(self) -> list[Posting]:
        url = f"https://{self.options['company']}.pinpointhq.com/postings.json"
        return self.parse(self.http.get_json(url, headers={"Accept": "application/json"}))

    def parse(self, data: dict) -> list[Posting]:
        out = []
        for job in data.get("data", []) or []:
            loc = job.get("location") or {}
            location = clean(loc.get("name") if isinstance(loc, dict) else loc)
            workplace = clean(job.get("workplace_type"))
            if workplace in ("remote", "hybrid"):
                location = f"{location} ({workplace})" if location else workplace
            dept = (job.get("job") or {}).get("department") or {}
            out.append(
                self.make_posting(
                    title=clean(job.get("title")),
                    location=location,
                    url=job.get("url") or "",
                    external_id=str(job.get("id")),
                    department=clean(dept.get("name") if isinstance(dept, dict) else dept),
                )
            )
        return out
