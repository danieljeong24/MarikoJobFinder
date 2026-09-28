"""UKG Pro (UltiPro) Recruiting job boards.

Board URL: https://{host}/{tenant}/JobBoard/{board_id}
JSON:      POST https://{host}/{tenant}/JobBoard/{board_id}/JobBoardView/LoadSearchResults

options:
  host:     e.g. recruiting2.ultipro.com
  tenant:   e.g. HOR1015HOCK
  board_id: the GUID after /JobBoard/
  query:    optional keyword
"""

from __future__ import annotations

from ..models import Posting
from .base import Fetcher, clean


class UltiproFetcher(Fetcher):
    type_name = "ultipro"
    required_options = ("host", "tenant", "board_id")
    page_size = 50

    @property
    def board_url(self) -> str:
        o = self.options
        return f"https://{o['host']}/{o['tenant']}/JobBoard/{o['board_id']}"

    def fetch(self) -> list[Posting]:
        url = f"{self.board_url}/JobBoardView/LoadSearchResults"
        headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
        postings: list[Posting] = []
        skip = 0
        for _ in range(self.max_pages):
            body = {
                "opportunitySearch": {
                    "Top": self.page_size,
                    "Skip": skip,
                    "QueryString": self.options.get("query", ""),
                    "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate",
                                 "Ascending": False}],
                    "Filters": [],
                },
                "matchCriteria": {"PreferredJobs": [], "Educations": [],
                                  "LicenseAndCertifications": [], "Skills": [],
                                  "hasNoLicenses": False, "SkippedSkills": []},
            }
            data = self.http.post_json(url, json=body, headers=headers)
            batch = self.parse(data)
            postings.extend(batch)
            skip += self.page_size
            if not batch or skip >= int(data.get("totalCount") or 0):
                break
        return postings

    def parse(self, data: dict) -> list[Posting]:
        out = []
        for opp in data.get("opportunities", []) or []:
            locs = []
            for loc in opp.get("Locations", []) or []:
                addr = loc.get("Address") or {}
                city = clean(addr.get("City"))
                state = clean((addr.get("State") or {}).get("Code"))
                text = ", ".join(x for x in (city, state) if x) or clean(loc.get("LocalizedDescription"))
                if text:
                    locs.append(text)
            location = " / ".join(locs)
            if opp.get("IsRemote") or opp.get("RemoteType"):
                location = f"{location} (Remote)" if location else "Remote"
            opp_id = str(opp.get("Id"))
            out.append(
                self.make_posting(
                    title=clean(opp.get("Title")),
                    location=location,
                    url=f"{self.board_url}/OpportunityDetail?opportunityId={opp_id}",
                    external_id=opp_id,
                    department=clean(opp.get("JobCategoryName")),
                    posted_date=(opp.get("PostedDate") or "")[:10] or None,
                )
            )
        return out
