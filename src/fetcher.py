"""Plain HTTP fetching.

Squarespace sites render fine with plain httpx. Sites behind Cloudflare or
with JS-rendered content need Playwright. Use playwright_session() as a
context manager when image downloads also need the browser session (e.g.
Cloudflare-protected image CDNs).
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager

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


@contextmanager
def playwright_session(url: str, timeout: float = 60.0):
    """Context manager: fetch a JS-rendered page and keep the browser open.

    Yields (html, content_hash, status_code, browser_context) so callers can
    use browser_context.request.get(url).body() to download images within the
    same authenticated session. Essential for Cloudflare-protected sites where
    image CDN requests also require the cf_clearance cookie.

    Usage:
        with playwright_session(page_url) as (html, h, status, ctx):
            images = discover_and_download(html, slug, pub,
                                           base_url=page_url,
                                           download_fn=lambda u: ctx.request.get(u).body())
    """
    from playwright.sync_api import sync_playwright  # lazy import

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        pw_page = ctx.new_page()
        pw_page.set_extra_http_headers({"User-Agent": USER_AGENT})
        pw_page.goto(url, timeout=timeout * 1000, wait_until="load")
        pw_page.wait_for_timeout(5000)
        html = pw_page.content()
        content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        try:
            yield html, content_hash, 200, ctx
        finally:
            browser.close()


def fetch_html_playwright(url: str, timeout: float = 60.0) -> tuple[str, str, int]:
    """Fetch fully JS-rendered HTML using a headless Chromium browser.

    Same return signature as fetch_html(). Use when image downloads don't
    need the browser session. For Cloudflare-protected image CDNs, use
    playwright_session() instead to keep the browser open during downloads.
    """
    with playwright_session(url, timeout=timeout) as (html, content_hash, status, _ctx):
        return html, content_hash, status


def fetch_bytes(url: str, timeout: float = 30.0) -> bytes:
    """For downloading images."""
    with httpx.Client(follow_redirects=True, timeout=timeout,
                      headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
