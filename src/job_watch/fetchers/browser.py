"""Optional Playwright renderer for career pages that only render via JavaScript.

Playwright is imported lazily so the rest of the tool works without it.
Install with:  uv sync --extra browser  &&  uv run playwright install chromium
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

from ..http import PoliteClient
from .base import FetcherUnavailable


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def render(
    http: PoliteClient,
    url: str,
    wait_selector: str | None = None,
    timeout_ms: int = 30000,
) -> str:
    """Load ``url`` in headless Chromium and return the rendered HTML.

    Uses the PoliteClient's robots.txt check, delay and User-Agent so
    browser-rendered sites are treated the same as everything else.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise FetcherUnavailable(
            "needs Playwright: uv sync --extra browser && uv run playwright install chromium"
        ) from exc

    http._check_robots(url)
    http._throttle(url)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=http.settings.user_agent)
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            else:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            html = page.content()
        finally:
            browser.close()
    http._last_request[urlsplit(url).netloc] = time.monotonic()
    return html
