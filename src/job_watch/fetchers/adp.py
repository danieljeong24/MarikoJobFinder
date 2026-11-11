"""ADP Workforce Now career centers.

The career-center page (workforcenow.adp.com/mascsr/default/mdf/recruitment/
recruitment.html?cid=...) is a JS app that loads its list from:

GET https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions
    ?cid={cid}&ccId={cc_id}&lang=en_US&locale=en_US&$top=20&$skip=0

options:
  cid:    the `cid` GUID from the career-center URL (see the employer's
          "job openings" page, or the browser network tab)
  cc_id:  optional, defaults to 19000101_000001
"""

from __future__ import annotations

from ..models import Posting
from .base import Fetcher, clean

BASE = "https://workforcenow.adp.com/mascsr/default"


class AdpFetcher(Fetcher):
    type_name = "adp"
    required_options = ("cid",)
    page_size = 20

    def _params(self, skip: int) -> dict:
        return {
            "cid": self.options["cid"],
            "ccId": self.options.get("cc_id", "19000101_000001"),
            "lang": "en_US",
            "locale": "en_US",
            "$top": self.page_size,
            "$skip": skip,
        }

    def fetch(self) -> list[Posting]:
        url = f"{BASE}/careercenter/public/events/staffing/v1/job-requisitions"
        postings: list[Posting] = []
        skip = 0
        for _ in range(self.max_pages):
            data = self.http.get_json(url, params=self._params(skip),
                                      headers={"Accept": "application/json"})
            batch = self.parse(data)
            postings.extend(batch)
            skip += len(data.get("jobRequisitions") or [])
            total = int((data.get("meta") or {}).get("totalNumber") or 0)
            if not batch or skip >= total:
                break
        return postings

    def parse(self, data: dict) -> list[Posting]:
        cid = self.options["cid"]
        cc_id = self.options.get("cc_id", "19000101_000001")
        out = []
        for req in data.get("jobRequisitions", []) or []:
            locs = []
            for loc in req.get("requisitionLocations", []) or []:
                addr = loc.get("address") or {}
                city = clean(addr.get("cityName"))
                state = clean((addr.get("countrySubdivisionLevel1") or {}).get("codeValue"))
                text = ", ".join(x for x in (city, state) if x) or clean(
                    (loc.get("nameCode") or {}).get("shortName")
                )
                if text and text not in locs:
                    locs.append(text)
            posted = None
            for f in (req.get("customFieldGroup") or {}).get("dateFields", []) or []:
                if (f.get("nameCode") or {}).get("codeValue") == "PostingDate":
                    posted = (f.get("dateValue") or "")[:10] or None
            item = str(req.get("itemID"))
            out.append(
                self.make_posting(
                    title=clean(req.get("requisitionTitle")),
                    location=" / ".join(locs),
                    url=(f"{BASE}/mdf/recruitment/recruitment.html?cid={cid}&ccId={cc_id}"
                         f"&jobId={item}&lang=en_US"),
                    external_id=item,
                    posted_date=posted,
                )
            )
        return out
