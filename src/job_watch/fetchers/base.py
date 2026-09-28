"""Shared fetcher interface.

A fetcher turns one employer's config entry into a list of Posting records.
Fetching (network) and parsing (pure) are split so parsing can be tested
against recorded fixtures without touching the network.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from ..config import Employer
from ..http import PoliteClient
from ..models import Posting


class FetcherError(Exception):
    """A fetcher could not produce results for a reason worth reporting."""


class FetcherUnavailable(FetcherError):
    """An optional dependency (e.g. Playwright) isn't installed."""


class ConfigError(FetcherError):
    """The employer's `options` are missing something this fetcher needs."""


class Fetcher(ABC):
    #: value of `type:` in config.yaml
    type_name: ClassVar[str]
    #: option keys that must be present
    required_options: ClassVar[tuple[str, ...]] = ()
    #: hard cap on pages so a misconfigured search can't crawl forever
    max_pages: ClassVar[int] = 50

    def __init__(self, employer: Employer, http: PoliteClient):
        self.employer = employer
        self.http = http
        self.options: dict[str, Any] = employer.options
        missing = [k for k in self.required_options if not self.options.get(k)]
        if missing:
            raise ConfigError(f"{employer.id}: missing option(s) {missing} for type {self.type_name}")

    @abstractmethod
    def fetch(self) -> list[Posting]:
        """Return every current posting this employer lists (pre-filter)."""

    def make_posting(self, **kwargs: Any) -> Posting:
        return Posting(
            employer_id=self.employer.id,
            firm=self.employer.name,
            source=self.type_name,
            **kwargs,
        )


def clean(text: Any) -> str:
    """Collapse whitespace; tolerate None."""
    if text is None:
        return ""
    return " ".join(str(text).split())
