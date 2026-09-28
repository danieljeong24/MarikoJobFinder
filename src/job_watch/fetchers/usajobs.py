"""USAJOBS official Search API (https://developer.usajobs.gov/).

GET https://data.usajobs.gov/api/search
Headers: Host, User-Agent: <your email>, Authorization-Key: <api key>

Credentials come from the environment: USAJOBS_API_KEY and USAJOBS_EMAIL.

options:
  job_category_code: OPM series, e.g. "0810" (Civil Engineering)
  location_name:     e.g. "Las Vegas, Nevada"
  radius_miles:      e.g. 50
  keyword:           optional
  max_low_grade:     drop postings whose lowest GS grade is above this
                     (entry-level civil engineers usually start at GS-5/7/9)
"""

from __future__ import annotations

import os

from ..models import Posting
from .base import ConfigError, Fetcher, clean

API = "https://data.usajobs.gov/api/search"


class UsajobsFetcher(Fetcher):
    type_name = "usajobs"
    results_per_page = 500  # API max

    def fetch(self) -> list[Posting]:
        key = os.environ.get("USAJOBS_API_KEY")
        email = os.environ.get("USAJOBS_EMAIL")
        if not key or not email:
            raise ConfigError(
                "USAJOBS_API_KEY and USAJOBS_EMAIL must be set "
                "(free key: https://developer.usajobs.gov/apirequest/)"
            )
        o = self.options
        params = {"ResultsPerPage": self.results_per_page}
        if o.get("job_category_code"):
            params["JobCategoryCode"] = o["job_category_code"]
        if o.get("location_name"):
            params["LocationName"] = o["location_name"]
        if o.get("radius_miles"):
            params["Radius"] = o["radius_miles"]
        if o.get("keyword"):
            params["Keyword"] = o["keyword"]
        headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": email,  # USAJOBS requires the registered email here
            "Authorization-Key": key,
        }
        postings: list[Posting] = []
        for page in range(1, self.max_pages + 1):
            params["Page"] = page
            data = self.http.get_json(API, params=params, headers=headers)
            batch = self.parse(data)
            postings.extend(batch)
            result = data.get("SearchResult", {})
            pages = int((result.get("UserArea") or {}).get("NumberOfPages") or 1)
            if page >= pages or not result.get("SearchResultItems"):
                break
        return postings

    def parse(self, data: dict) -> list[Posting]:
        max_grade = self.options.get("max_low_grade")
        out = []
        for item in (data.get("SearchResult") or {}).get("SearchResultItems", []) or []:
            d = item.get("MatchedObjectDescriptor") or {}
            grades = (d.get("UserArea") or {}).get("Details") or {}
            low = _to_int(grades.get("LowGrade"))
            if max_grade is not None and low is not None and low > int(max_grade):
                continue
            grade_txt = ""
            if grades.get("LowGrade"):
                grade_txt = f" (GS-{grades.get('LowGrade')}"
                if grades.get("HighGrade") and grades.get("HighGrade") != grades.get("LowGrade"):
                    grade_txt += f"/{grades.get('HighGrade')}"
                grade_txt += ")"
            out.append(
                self.make_posting(
                    title=clean(d.get("PositionTitle")) + grade_txt,
                    location=clean(d.get("PositionLocationDisplay")),
                    url=d.get("PositionURI") or "",
                    external_id=clean(d.get("PositionID") or item.get("MatchedObjectId")) or None,
                    department=clean(
                        " / ".join(filter(None, [d.get("DepartmentName"), d.get("OrganizationName")]))
                    ),
                    posted_date=(d.get("PublicationStartDate") or "")[:10] or None,
                )
            )
        return out


def _to_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
