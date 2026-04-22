#!/usr/bin/env python3
"""Repair images referenced in the DB but missing on disk.

For each event where image_local_path is set but the file is absent, this
downloads the original bytes from image_source_url, runs them through the
same hash+optimize pipeline used during extraction, and writes the expected
.webp file. No Claude API calls.

Use when the DB and public/images/ get out of sync (e.g., a CI extraction
run partially failed or the images were migrated to a new format).
"""
from __future__ import annotations

import hashlib
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from src.db import connect  # noqa: E402
from src.fetcher import fetch_bytes, playwright_session  # noqa: E402
from src.images import _generate_srcset_variants, _optimize  # noqa: E402

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"


def main() -> None:
    repaired = 0
    skipped = 0
    failed = 0

    with connect() as conn:
        rows = conn.execute("""
            SELECT e.id, e.title, e.image_source_url, e.image_local_path,
                   b.slug AS business_slug, e.source_page_url
            FROM events e
            JOIN businesses b ON b.id = e.business_id
            WHERE e.image_local_path IS NOT NULL
              AND e.image_source_url IS NOT NULL
        """).fetchall()

    missing = [r for r in rows if not (PUBLIC_DIR / r["image_local_path"]).exists()]
    print(f"Scanned {len(rows)} events with images. {len(missing)} missing on disk.\n")

    # Group missing images by source_page_url so we can batch Playwright sessions
    # (some CDNs, e.g. Hopleaf's Cloudflare-protected one, block plain httpx).
    by_page: dict[str, list] = {}
    for r in missing:
        by_page.setdefault(r["source_page_url"], []).append(r)

    for page_url, items in by_page.items():
        print(f"--- {len(items)} missing image(s) from {page_url}")
        use_playwright = _looks_like_cloudflare(items[0]["image_source_url"])

        if use_playwright:
            print(f"  using Playwright session (Cloudflare-protected CDN)")
            with playwright_session(page_url) as (_, _, _, ctx):
                download = lambda u: ctx.request.get(u).body()
                for r in items:
                    _repair_one(r, download, counters=(repaired, skipped, failed))
                    repaired, skipped, failed = _repair_one._counts
        else:
            download = fetch_bytes
            for r in items:
                _repair_one(r, download, counters=(repaired, skipped, failed))
                repaired, skipped, failed = _repair_one._counts

    print(f"\nDone: repaired={repaired} skipped={skipped} failed={failed}")


def _looks_like_cloudflare(url: str) -> bool:
    # Hopleaf is the known Cloudflare case. Extend if more sites need it.
    return "hopleaf" in url.lower()


def _repair_one(row, download_fn, counters) -> None:
    repaired, skipped, failed = counters
    expected_path = PUBLIC_DIR / row["image_local_path"]
    if expected_path.exists():
        skipped += 1
        _repair_one._counts = (repaired, skipped, failed)
        return

    try:
        raw = download_fn(row["image_source_url"])
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ [{row['id']}] {row['title'][:50]}: fetch failed — {exc}")
        failed += 1
        _repair_one._counts = (repaired, skipped, failed)
        return

    try:
        with Image.open(BytesIO(raw)) as pil:
            width, height = pil.size
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ [{row['id']}] {row['title'][:50]}: decode failed — {exc}")
        failed += 1
        _repair_one._counts = (repaired, skipped, failed)
        return

    digest = hashlib.sha256(raw).hexdigest()[:16]
    expected_stem = Path(row["image_local_path"]).stem
    if digest != expected_stem:
        print(f"  ✗ [{row['id']}] {row['title'][:50]}: hash mismatch "
              f"(expected {expected_stem}, got {digest}) — source image changed")
        failed += 1
        _repair_one._counts = (repaired, skipped, failed)
        return

    optimized, new_w, new_h = _optimize(raw, width, height)
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    expected_path.write_bytes(optimized)
    _generate_srcset_variants(optimized, expected_path, new_w, new_h)
    print(f"  ✓ [{row['id']}] {row['title'][:50]} -> {row['image_local_path']}")
    repaired += 1
    _repair_one._counts = (repaired, skipped, failed)


_repair_one._counts = (0, 0, 0)


if __name__ == "__main__":
    main()
