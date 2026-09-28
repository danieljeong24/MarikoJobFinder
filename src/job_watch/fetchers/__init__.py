"""Fetcher registry: maps a config `type:` to its fetcher class."""

from __future__ import annotations

from ..config import Employer
from ..http import PoliteClient
from .base import ConfigError, Fetcher, FetcherError, FetcherUnavailable
from .greenhouse import GreenhouseFetcher
from .html import HtmlFetcher
from .icims import IcimsFetcher
from .lever import LeverFetcher
from .neogov import NeogovFetcher
from .oracle_hcm import OracleHcmFetcher
from .rss import RssFetcher
from .smartrecruiters import SmartRecruitersFetcher
from .taleo import TaleoFetcher
from .ultipro import UltiproFetcher
from .usajobs import UsajobsFetcher
from .workday import WorkdayFetcher

REGISTRY: dict[str, type[Fetcher]] = {
    cls.type_name: cls
    for cls in (
        WorkdayFetcher,
        GreenhouseFetcher,
        LeverFetcher,
        IcimsFetcher,
        UsajobsFetcher,
        RssFetcher,
        HtmlFetcher,
        NeogovFetcher,
        TaleoFetcher,
        OracleHcmFetcher,
        SmartRecruitersFetcher,
        UltiproFetcher,
    )
}


def get_fetcher(employer: Employer, http: PoliteClient) -> Fetcher:
    cls = REGISTRY.get(employer.type)
    if cls is None:
        raise ConfigError(
            f"{employer.id}: unknown type {employer.type!r} (known: {', '.join(sorted(REGISTRY))})"
        )
    return cls(employer, http)


def needs_browser(employer: Employer) -> bool:
    return bool(employer.options.get("render_js"))


__all__ = [
    "REGISTRY",
    "ConfigError",
    "Fetcher",
    "FetcherError",
    "FetcherUnavailable",
    "get_fetcher",
    "needs_browser",
]
