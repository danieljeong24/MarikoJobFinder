"""Oracle Taleo Enterprise career sections (*.taleo.net).

The job list page is a JS shell; results come from a JSON endpoint:

POST https://{host}/careersection/rest/jobboard/searchjobs?lang=en&portal={portal}

options:
  host:     e.g. hdr.taleo.net
  section:  career section code in the URL, e.g. "ex" in /careersection/ex/jobsearch.ftl
  portal:   numeric portal id. Optional: if omitted it is read from the
            jobsearch.ftl page (it's also visible in the browser's network tab)
  keyword:  optional server-side keyword (e.g. "Las Vegas")
  title_column / location_column / date_column:
            index into each requisition's `column` array (defaults 0 / 1 / 2;
            the order depends on how the employer configured the section)
"""

from __future__ import annotations

import json
import re

from ..models import Posting
from .base import Fetcher, FetcherError, clean

DEFAULT_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "tz": "GMT-07:00",
    "tzname": "America/Los_Angeles",
}


class TaleoFetcher(Fetcher):
    type_name = "taleo"
    required_options = ("host", "section")

    def _portal(self) -> str:
        if self.options.get("portal"):
            return str(self.options["portal"])
        o = self.options
        page = self.http.get(f"https://{o['host']}/careersection/{o['section']}/jobsearch.ftl?lang=en").text
        m = re.search(r"portal=(\d+)", page) or re.search(r"portal['\"]?\s*[:=]\s*['\"]?(\d+)", page)
        if not m:
            raise FetcherError("could not discover Taleo portal id; set options.portal")
        return m.group(1)

    def fetch(self) -> list[Posting]:
        o = self.options
        url = f"https://{o['host']}/careersection/rest/jobboard/searchjobs?lang=en&portal={self._portal()}"
        headers = dict(DEFAULT_HEADERS)
        headers["Referer"] = f"https://{o['host']}/careersection/{o['section']}/jobsearch.ftl?lang=en"
        postings: list[Posting] = []
        for page in range(1, self.max_pages + 1):
            data = self.http.post_json(url, json=self._body(page), headers=headers)
            batch = self.parse(data)
            postings.extend(batch)
            paging = data.get("pagingData") or {}
            total = int(paging.get("totalCount") or 0)
            size = int(paging.get("pageSize") or 25)
            if not batch or page * size >= total:
                break
        return postings

    def _body(self, page: int) -> dict:
        return {
            "multilineEnabled": False,
            "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
            "fieldData": {
                "fields": {"KEYWORD": self.options.get("keyword", ""), "LOCATION": "", "CATEGORY": ""},
                "valid": True,
            },
            "filterSelectionParam": {"searchFilterSelections": []},
            "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
            "pageNo": page,
        }

    def parse(self, data: dict) -> list[Posting]:
        o = self.options
        ti, li, di = (int(o.get(k, d)) for k, d in
                      (("title_column", 0), ("location_column", 1), ("date_column", 2)))
        out = []
        for req in data.get("requisitionList", []) or []:
            cols = req.get("column") or []
            contest = req.get("contestNo") or req.get("jobId")
            out.append(
                self.make_posting(
                    title=clean(_col(cols, ti)),
                    location=_location(_col(cols, li)),
                    url=f"https://{o['host']}/careersection/{o['section']}/jobdetail.ftl?job={contest}&lang=en",
                    external_id=str(req.get("jobId") or contest),
                    posted_date=clean(_col(cols, di)) or None,
                )
            )
        return out


def _col(cols: list, i: int) -> str:
    return cols[i] if 0 <= i < len(cols) and cols[i] is not None else ""


def _location(raw: str) -> str:
    """Taleo encodes multi-location cells as a JSON array string."""
    raw = raw or ""
    if raw.startswith("["):
        try:
            return " / ".join(clean(x) for x in json.loads(raw))
        except ValueError:
            pass
    return clean(raw)
