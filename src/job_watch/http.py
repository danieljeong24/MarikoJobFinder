"""A polite HTTP client: real User-Agent, per-host delay, robots.txt, retries."""

from __future__ import annotations

import logging
import random
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import Settings

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class RobotsDisallowed(Exception):
    """robots.txt forbids fetching this URL."""


class PoliteClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._client = httpx.Client(
            headers={
                "User-Agent": settings.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=settings.timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._sleep = time.sleep

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- public API ---------------------------------------------------------

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def get_json(self, url: str, **kwargs):
        return self.get(url, **kwargs).json()

    def post_json(self, url: str, **kwargs):
        return self.post(url, **kwargs).json()

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        self._check_robots(url)
        attempt = 0
        while True:
            self._throttle(url)
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt >= self.settings.max_retries:
                    raise
                wait = self._backoff(attempt)
                log.info("%s %s failed (%s); retrying in %.1fs", method, url, exc, wait)
            else:
                if resp.status_code not in RETRY_STATUSES or attempt >= self.settings.max_retries:
                    resp.raise_for_status()
                    return resp
                wait = _retry_after(resp) or self._backoff(attempt)
                log.info("%s %s -> %s; retrying in %.1fs", method, url, resp.status_code, wait)
            attempt += 1
            self._sleep(wait)

    # -- internals ----------------------------------------------------------

    def _backoff(self, attempt: int) -> float:
        base = self.settings.backoff_base_seconds * (2**attempt)
        return base + random.uniform(0, base / 4)

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self.settings.request_delay_seconds - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = time.monotonic()

    def _check_robots(self, url: str) -> None:
        if not self.settings.respect_robots_txt:
            return
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        if parser is not None and not parser.can_fetch(self.settings.user_agent, url):
            raise RobotsDisallowed(f"robots.txt at {origin} disallows {parts.path}")

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        parser = RobotFileParser(robots_url)
        try:
            self._throttle(robots_url)
            resp = self._client.get(robots_url)
        except httpx.HTTPError as exc:
            log.info("could not fetch %s (%s); assuming allowed", robots_url, exc)
            return None
        if resp.status_code in (401, 403):
            # Same convention as urllib.robotparser: auth-walled robots = disallow all.
            parser.disallow_all = True
        elif resp.status_code >= 400:
            parser.allow_all = True
        else:
            parser.parse(resp.text.splitlines())
        return parser


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(float(value), 300.0)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        return max(0.0, min(dt.timestamp() - time.time(), 300.0))
    except (TypeError, ValueError):
        return None
