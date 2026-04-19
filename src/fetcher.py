"""Plain HTTP fetching.

Squarespace sites (both test sites are Squarespace) render fine with plain
httpx. If you add a business whose content only shows up after JS runs, swap
in playwright here. Keep the interface the same so callers don't care.
"""
from __future__ import annotations

import hashlib
import httpx

USER_AGENT = (
    "AndersonvilleHappeningsBot/0.1 (+https://example.com/andersonville-happenings; "
    "contact: justin@example.com) "
    "Python httpx"
)


def fetch_html(url: str, timeout: float = 30.0) -> tuple[str, str, int]:
    """Return (html, content_hash, status_code). Raises on non-2xx."""
    with httpx.Client(follow_redirects=True, timeout=timeout,
                      headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text
        content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        return html, content_hash, resp.status_code


def fetch_html_playwright(url: str, timeout: float = 30.0) -> tuple[str, str, int]:
    """Fetch fully JS-rendered HTML using a headless Chromium browser.

    Same return signature as fetch_html(). Use for pages where meaningful
    content (modals, dynamic sections) is injected by JavaScript after load.
    Waits for networkidle before capturing HTML so JS-rendered content is
    present in the DOM.
    """
    from playwright.sync_api import sync_playwright  # lazy import

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            pw_page = browser.new_page()
            pw_page.set_extra_http_headers({"User-Agent": USER_AGENT})
            pw_page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            html = pw_page.content()
        finally:
            browser.close()

    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return html, content_hash, 200


def fetch_bytes(url: str, timeout: float = 30.0) -> bytes:
    """For downloading images."""
    with httpx.Client(follow_redirects=True, timeout=timeout,
                      headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
