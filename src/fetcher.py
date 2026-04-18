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


def fetch_bytes(url: str, timeout: float = 30.0) -> bytes:
    """For downloading images."""
    with httpx.Client(follow_redirects=True, timeout=timeout,
                      headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
