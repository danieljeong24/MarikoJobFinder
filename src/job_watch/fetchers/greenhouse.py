"""Greenhouse job board API.

GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs

options:
  board_token: the slug in job-boards.greenhouse.io/{board_token}
"""

from __future__ import annotations

from ..models import Posting
from .base import Fetcher, clean


class GreenhouseFetcher(Fetcher):
    type_name = "greenhouse"
    required_options = ("board_token",)

    def fetch(self) -> list[Posting]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.options['board_token']}/jobs"
        return self.parse(self.http.get_json(url))

    def parse(self, data: dict) -> list[Posting]:
        out = []
        for job in data.get("jobs", []) or []:
            depts = ", ".join(clean(d.get("name")) for d in job.get("departments", []) or [])
            out.append(
                self.make_posting(
                    title=clean(job.get("title")),
                    location=clean((job.get("location") or {}).get("name")),
                    url=job.get("absolute_url") or "",
                    external_id=str(job["id"]) if job.get("id") is not None else None,
                    department=depts,
                    posted_date=(job.get("updated_at") or "")[:10] or None,
                )
            )
        return out
