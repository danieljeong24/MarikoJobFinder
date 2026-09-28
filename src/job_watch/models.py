"""Common record every fetcher produces."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit


@dataclass
class Posting:
    """A single job posting, normalized across all sources.

    ``external_id`` is the ATS's own id when it has one; otherwise the key
    falls back to the normalized URL.
    """

    employer_id: str
    firm: str
    title: str
    location: str
    url: str
    source: str
    external_id: str | None = None
    department: str = ""
    posted_date: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        ident = self.external_id or normalize_url(self.url) or self.title
        raw = f"{self.employer_id}|{ident}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


_TRACKING_PARAMS = {"src", "source", "ref", "referrer", "gh_src", "lever-source", "mode"}


def normalize_url(url: str) -> str:
    """Drop fragments and tracking params so they don't create duplicate rows."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = "&".join(
        sorted(
            p
            for p in parts.query.split("&")
            if p
            and not p.split("=", 1)[0].lower().startswith("utm_")
            and p.split("=", 1)[0].lower() not in _TRACKING_PARAMS
        )
    )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))
