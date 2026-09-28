"""SmartRecruiters public Posting API.

GET https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=0

options:
  company: identifier in jobs.smartrecruiters.com/{company}/..., e.g. AECOM2
  q:       optional keyword
  city:    optional, e.g. "Las Vegas"
  country: optional ISO code, e.g. "us"
"""

from __future__ import annotations

from ..models import Posting
from .base import Fetcher, clean


class SmartRecruitersFetcher(Fetcher):
    type_name = "smartrecruiters"
    required_options = ("company",)
    page_size = 100

    def fetch(self) -> list[Posting]:
        company = self.options["company"]
        url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
        postings: list[Posting] = []
        offset = 0
        for _ in range(self.max_pages):
            params = {"limit": self.page_size, "offset": offset}
            for k in ("q", "city", "country", "region"):
                if self.options.get(k):
                    params[k] = self.options[k]
            data = self.http.get_json(url, params=params)
            batch = self.parse(data)
            postings.extend(batch)
            offset += self.page_size
            if not batch or offset >= int(data.get("totalFound") or 0):
                break
        return postings

    def parse(self, data: dict) -> list[Posting]:
        company = self.options["company"]
        out = []
        for job in data.get("content", []) or []:
            loc = job.get("location") or {}
            location = clean(loc.get("fullLocation")) or ", ".join(
                x for x in (clean(loc.get("city")), clean(loc.get("region"))) if x
            )
            if loc.get("remote"):
                location = f"{location} (Remote)" if location else "Remote"
            elif loc.get("hybrid"):
                location = f"{location} (Hybrid)"
            job_id = str(job.get("id"))
            out.append(
                self.make_posting(
                    title=clean(job.get("name")),
                    location=location,
                    url=f"https://jobs.smartrecruiters.com/{company}/{job_id}",
                    external_id=job_id,
                    department=clean((job.get("department") or {}).get("label")),
                    posted_date=(job.get("releasedDate") or "")[:10] or None,
                )
            )
        return out
