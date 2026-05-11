"""Find content images on a page, download them, cache locally.

Heuristics to skip noise:
  - images in <nav>, <header>, <footer>
  - filenames containing 'logo', 'icon', 'favicon'
  - images smaller than MIN_DIMENSION x MIN_DIMENSION (we check post-download)

For each surviving image we capture two pieces of context:
  - section_header: the most recent <h1>..<h6> heading before the image
    (e.g., "WEEKLY EVENTS"). Gives Claude a strong recurrence hint.
  - caption: text that appears AFTER this image in document order, up
    until the next image or the next heading. This is the single caption
    for this one image, not the whole section dumped in.

The old approach ("grab text from the enclosing container") conflated all
captions in a section into one blob, which caused Claude to pair images
with the wrong day/time.
"""
from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import urljoin
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image

from .fetcher import fetch_bytes

MIN_DIMENSION = 300
MAX_OPTIMIZE_DIMENSION = 1200
WEBP_QUALITY = 75
WEBP_METHOD = 6
SRCSET_WIDTHS = [400, 800]
SKIP_FILENAME_PATTERNS = re.compile(r"logo|icon|favicon|avatar|sprite|venue-\d", re.I)
SKIP_PARENTS = {"nav", "header", "footer"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# Squarespace sites inline <style> blocks between content; treat as boundaries
# so their CSS text doesn't leak into captions.
CAPTION_BOUNDARY_TAGS = {"img", "style", "script"} | HEADING_TAGS | SKIP_PARENTS
CAPTION_MAX_CHARS = 400


@dataclass
class PageImage:
    index: int                 # 1-based position in the list we send to Claude
    source_url: str            # original URL
    local_path: str            # relative to public/, e.g. "images/mht/abc.png"
    media_type: str            # "image/png" etc.
    b64: str                   # base64-encoded bytes, ready for API
    caption: str               # text between this img and the next img/heading
    section_header: str        # most recent heading before this img
    link_url: str | None       # if image is wrapped in <a href>, the href
    width: int
    height: int


def _optimize(raw: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    """Resize to MAX_OPTIMIZE_DIMENSION on longer side and re-encode as webp.

    Does not upscale. Returns (optimized_bytes, new_width, new_height).
    """
    scale = min(1.0, MAX_OPTIMIZE_DIMENSION / max(width, height))
    new_w, new_h = round(width * scale), round(height * scale)
    with Image.open(BytesIO(raw)) as pil:
        resized = pil.resize((new_w, new_h), Image.LANCZOS) if scale < 1.0 else pil
        buf = BytesIO()
        resized.save(buf, format="webp", quality=WEBP_QUALITY, method=WEBP_METHOD)
    return buf.getvalue(), new_w, new_h


def _generate_srcset_variants(optimized: bytes, abs_path: Path, width: int, height: int) -> None:
    """Write 400w and 800w WebP variants alongside the main image. Skips upscaling."""
    stem = abs_path.stem
    parent = abs_path.parent
    for w in SRCSET_WIDTHS:
        if w >= width:
            continue
        variant_path = parent / f"{stem}-{w}w.webp"
        if variant_path.exists():
            continue
        new_h = round(height * w / width)
        with Image.open(BytesIO(optimized)) as pil:
            buf = BytesIO()
            pil.resize((w, new_h), Image.LANCZOS).save(buf, format="webp", quality=WEBP_QUALITY, method=WEBP_METHOD)
        variant_path.write_bytes(buf.getvalue())


def _section_header(img: Tag) -> str:
    """Most recent heading (h1..h6) that appears before this image."""
    prev = img.find_previous(list(HEADING_TAGS))
    if not prev:
        return ""
    text = prev.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def _caption(img: Tag) -> str:
    """Text following this image, stopping at the next image or heading.

    Walks the document in order starting just after `img`. This isolates
    one image's caption from its neighbors'.
    """
    pieces: list[str] = []
    for element in img.next_elements:
        if isinstance(element, Tag):
            if element.name in CAPTION_BOUNDARY_TAGS:
                break
        elif isinstance(element, NavigableString):
            # Defensive: skip text inside ancestors we consider boundaries.
            bad_ancestor = False
            for parent in element.parents:
                name = getattr(parent, "name", None)
                if name in CAPTION_BOUNDARY_TAGS:
                    bad_ancestor = True
                    break
            if bad_ancestor:
                continue
            text = str(element).strip()
            if text:
                pieces.append(text)
    caption = " ".join(pieces).strip()
    caption = re.sub(r"\s+", " ", caption)
    if len(caption) > CAPTION_MAX_CHARS:
        caption = caption[:CAPTION_MAX_CHARS] + "…"
    return caption


def _has_disallowed_parent(tag: Tag) -> bool:
    for parent in tag.parents:
        if getattr(parent, "name", None) in SKIP_PARENTS:
            return True
    return False


def _enclosing_link(tag: Tag) -> str | None:
    for parent in tag.parents:
        if getattr(parent, "name", None) == "a" and parent.get("href"):
            return parent["href"]
    return None


def discover_and_download(
    html: str,
    business_slug: str,
    public_dir: Path,
    *,
    base_url: str = "",
    download_fn=None,
) -> list[PageImage]:
    """Discover images in HTML and download them to public_dir.

    base_url: source page URL, used to resolve relative <a href> links to
    absolute URLs. If empty, relative links are left as-is.
    download_fn: callable(url) -> bytes. Defaults to fetch_bytes (plain httpx).
    Pass a Playwright-backed function for Cloudflare-protected sites where the
    browser session (cf_clearance cookie) is required to download images.
    """
    if download_fn is None:
        download_fn = fetch_bytes
    soup = BeautifulSoup(html, "lxml")
    out: list[PageImage] = []
    seen_urls: set[str] = set()

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif base_url and not src.startswith(("http://", "https://")):
            src = urljoin(base_url, src)
        # Check pattern against filename only — not the full URL path — so that
        # directory names like /saas/logos/ don't falsely match "logo".
        url_filename = src.split("?")[0].rsplit("/", 1)[-1]
        if SKIP_FILENAME_PATTERNS.search(url_filename):
            continue
        if _has_disallowed_parent(img):
            continue
        if src in seen_urls:
            continue
        seen_urls.add(src)

        try:
            raw = download_fn(src)
        except Exception as exc:  # noqa: BLE001
            print(f"  [image skipped] {src[:80]}… -> {exc}")
            continue

        # Validate + measure
        try:
            with Image.open(BytesIO(raw)) as pil:
                width, height = pil.size
                fmt = (pil.format or "").lower()
        except Exception:
            continue
        if width < MIN_DIMENSION or height < MIN_DIMENSION:
            continue

        digest = hashlib.sha256(raw).hexdigest()[:16]
        optimized, width, height = _optimize(raw, width, height)
        rel_path = f"images/{business_slug}/{digest}.webp"
        abs_path = public_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        if not abs_path.exists():
            abs_path.write_bytes(optimized)
        _generate_srcset_variants(optimized, abs_path, width, height)

        b64 = base64.standard_b64encode(optimized).decode("ascii")

        out.append(PageImage(
            index=len(out) + 1,
            source_url=src,
            local_path=rel_path,
            media_type="image/webp",
            b64=b64,
            caption=_caption(img),
            section_header=_section_header(img),
            link_url=urljoin(base_url, _enclosing_link(img)) if _enclosing_link(img) else None,
            width=width,
            height=height,
        ))

    return out


def store_event_image_from_url(
    url: str,
    business_slug: str,
    public_dir: Path,
) -> tuple[str, str]:
    """Download an image, optimize it, write 400w/800w srcset variants.

    Used by the admin UI when a user pastes an image URL for an event whose
    image came from somewhere other than the business's own pages (a flyer
    on a different aggregator, a press photo, etc.). Produces the same
    on-disk layout as the pipeline so display code needs no special-casing.

    Returns (source_url, image_local_path). image_local_path is relative to
    public_dir, e.g. 'images/kopi-cafe/abc123.webp'.

    Raises ValueError if the fetched bytes aren't a decodable image.
    """
    raw = fetch_bytes(url)
    try:
        with Image.open(BytesIO(raw)) as pil:
            width, height = pil.size
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"could not decode image from {url}: {exc}")
    optimized, width, height = _optimize(raw, width, height)
    digest = hashlib.sha256(optimized).hexdigest()[:16]
    rel_path = f"images/{business_slug}/{digest}.webp"
    abs_path = public_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    if not abs_path.exists():
        abs_path.write_bytes(optimized)
    _generate_srcset_variants(optimized, abs_path, width, height)
    return url, rel_path


def page_text(html: str) -> str:
    """Strip HTML and return text, for context."""
    soup = BeautifulSoup(html, "lxml")
    for el in soup(["script", "style", "nav", "header", "footer"]):
        el.decompose()
    text = soup.get_text("\n", strip=True)
    # Collapse runs of blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:8000]  # cap so we don't blow context on very long pages
