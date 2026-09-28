"""Oracle Recruiting Cloud / Fusion HCM candidate-experience sites.

Career sites at https://{host}/hcmUI/CandidateExperience/en/sites/{site} are a
JS app; the job list comes from a public (no login) REST resource:

GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
    ?onlyData=true&expand=requisitionList.secondaryLocations
    &finder=findReqs;siteNumber={site},limit=25,offset=0,keyword=...

options:
  host:     e.g. emit.fa.ca3.oraclecloud.com
  site:     site number, e.g. CX_2001
  keyword:  optional
  location: optional free-text location (e.g. "Las Vegas, NV, United States")
  radius:   optional, miles; used with location
"""

from __future__ import annotations

from urllib.parse import quote

from ..models import Posting
from .base import Fetcher, clean


class OracleHcmFetcher(Fetcher):
    type_name = "oracle_hcm"
    required_options = ("host", "site")
    page_size = 25

    def _finder(self, offset: int) -> str:
        o = self.options
        parts = [f"siteNumber={o['site']}", f"limit={self.page_size}", f"offset={offset}",
                 "sortBy=POSTING_DATES_DESC"]
        if o.get("keyword"):
            parts.append(f'keyword="{o["keyword"]}"')
        if o.get("location"):
            parts.append(f'location="{o["location"]}"')
            if o.get("radius"):
                parts.append(f"radius={int(o['radius'])}")
                parts.append("radiusUnit=MI")
        return "findReqs;" + ",".join(parts)

    def fetch(self) -> list[Posting]:
        o = self.options
        url = f"https://{o['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        postings: list[Posting] = []
        offset = 0
        for _ in range(self.max_pages):
            # Oracle expects the finder's ; , = unencoded, so build the query by hand.
            finder = quote(self._finder(offset), safe=";,=")
            full = (f"{url}?onlyData=true&expand=requisitionList.secondaryLocations"
                    f"&finder={finder}")
            data = self.http.get_json(full, headers={"Accept": "application/json"})
            batch = self.parse(data)
            postings.extend(batch)
            items = data.get("items") or [{}]
            total = int(items[0].get("TotalJobsCount") or 0)
            offset += self.page_size
            if not batch or offset >= total:
                break
        return postings

    def parse(self, data: dict) -> list[Posting]:
        o = self.options
        out = []
        for item in data.get("items", []) or []:
            for req in item.get("requisitionList", []) or []:
                locs = [clean(req.get("PrimaryLocation"))]
                locs += [clean(s.get("Name")) for s in req.get("secondaryLocations", []) or []]
                workplace = clean(req.get("WorkplaceType"))
                location = " / ".join(x for x in locs if x)
                if workplace and workplace.lower() not in ("on-site", "onsite"):
                    location = f"{location} ({workplace})"
                job_id = str(req.get("Id"))
                out.append(
                    self.make_posting(
                        title=clean(req.get("Title")),
                        location=location,
                        url=f"https://{o['host']}/hcmUI/CandidateExperience/en/sites/{o['site']}/job/{job_id}",
                        external_id=job_id,
                        department=clean(req.get("JobFamily") or req.get("Organization")),
                        posted_date=clean(req.get("PostedDate")) or None,
                    )
                )
        return out
