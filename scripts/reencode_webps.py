#!/usr/bin/env python3
"""One-time bulk re-encode of public/images/*.webp at lower quality.

Walks public/images/<business>/*.webp (skips og/) and re-saves each
file at WEBP_QUALITY + WEBP_METHOD from src.images.py. Skips files
that grew (defensive — keep the smaller version).

This is double-lossy on already-WebP-encoded files but the visual
difference at q=82 → q=75 is imperceptible for these flyer images.
The next extraction run produces fresh originals at the new quality
naturally; this script just shrinks the existing inventory.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from src.images import WEBP_METHOD, WEBP_QUALITY  # noqa: E402

PUBLIC_IMAGES = Path(__file__).resolve().parent.parent / "public" / "images"


def main() -> None:
    files = [
        p for p in PUBLIC_IMAGES.rglob("*.webp")
        if "og" not in p.parts
    ]
    print(f"Re-encoding {len(files)} files at quality={WEBP_QUALITY} method={WEBP_METHOD}")

    total_before = 0
    total_after = 0
    shrunk = 0
    grew_kept = 0
    failed = 0

    for i, path in enumerate(files, 1):
        before = path.stat().st_size
        total_before += before
        try:
            with Image.open(path) as im:
                buf = BytesIO()
                im.save(buf, format="webp", quality=WEBP_QUALITY, method=WEBP_METHOD)
            new_bytes = buf.getvalue()
        except Exception as e:
            print(f"  [{i}/{len(files)}] FAIL {path.relative_to(PUBLIC_IMAGES)}: {e}")
            failed += 1
            total_after += before
            continue

        if len(new_bytes) >= before:
            grew_kept += 1
            total_after += before
            continue

        path.write_bytes(new_bytes)
        total_after += len(new_bytes)
        shrunk += 1

        if i % 50 == 0:
            print(f"  [{i}/{len(files)}] processed")

    saved = total_before - total_after
    pct = (saved / total_before * 100) if total_before else 0
    print()
    print(f"Done. {shrunk} shrunk, {grew_kept} kept (would grow), {failed} failed")
    print(f"Before: {total_before / 1024:,.0f} KiB")
    print(f"After:  {total_after / 1024:,.0f} KiB")
    print(f"Saved:  {saved / 1024:,.0f} KiB ({pct:.1f}%)")


if __name__ == "__main__":
    main()
