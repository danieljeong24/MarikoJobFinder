"""Lever postings API.

GET https://api.lever.co/v0/postings/{company}?mode=json

options:
  company: the slug in jobs.lever.co/{company}
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import Posting
from .base import Fetcher, clean


class LeverFetcher(Fetcher):
    type_name = "lever"
    required_options = ("company",)

    def fetch(self) -> list[Posting]:
        url = f"https://api.lever.co/v0/postings/{self.options['company']}"
        return self.parse(self.http.get_json(url, params={"mode": "json"}))

    def parse(self, data: list) -> list[Posting]:
        out = []
        for job in data or []:
            cats = job.get("categories") or {}
            locs = cats.get("allLocations") or [cats.get("location")]
            created = job.get("createdAt")
            posted = (
                datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat()
                if isinstance(created, (int, float))
                else None
            )
            workplace = job.get("workplaceType") or ""
            location = " / ".join(clean(x) for x in locs if x)
            if workplace in ("remote", "hybrid"):
                location = f"{location} ({workplace})" if location else workplace
            out.append(
                self.make_posting(
                    title=clean(job.get("text")),
                    location=location,
                    url=job.get("hostedUrl") or "",
                    external_id=job.get("id"),
                    department=clean(" ".join(filter(None, [cats.get("department"), cats.get("team")]))),
                    posted_date=posted,
                )
            )
        return out
