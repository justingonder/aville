#!/usr/bin/env python3
"""Generate static map PNGs for each business in config/businesses.yaml.

Output: public/images/maps/{slug}.png — 800x540, zoom 16, OSM tiles, riso-red marker.
Idempotent: skips files that already exist unless --force.

Tile attribution: "© OpenStreetMap contributors" baked into the bottom-right of each map.
OSM tile usage policy: <https://operations.osmfoundation.org/policies/tiles/>.
We send a descriptive User-Agent and only fetch ~6-9 tiles per business — well within fair use
for one-off generation. Maps are committed to git so this script does not run on every build.

Usage:
    python3 scripts/build_business_maps.py            # generate any missing maps
    python3 scripts/build_business_maps.py --force    # regenerate all
    python3 scripts/build_business_maps.py the-sofo-tap   # one business
"""
from __future__ import annotations

import argparse
import io
import math
import sys
import time
from pathlib import Path

import httpx
import yaml
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
BUSINESSES_YAML = REPO_ROOT / "config" / "businesses.yaml"
OUT_DIR = REPO_ROOT / "public" / "images" / "maps"

WIDTH, HEIGHT = 800, 540
ZOOM = 18
TILE_PX = 256
MARKER_RED = (184, 68, 53)        # --riso-red
MARKER_OUTLINE = (255, 255, 255)
MARKER_R = 9
TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "AvilleNet/1.0 (+https://aville.net; map static-image generator)"


def deg2px(lat: float, lng: float, zoom: int) -> tuple[float, float]:
    """Convert lat/lng to global pixel coordinates at the given zoom."""
    n = 2.0 ** zoom
    x = (lng + 180.0) / 360.0 * n * TILE_PX
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n * TILE_PX
    return x, y


def render_map(lat: float, lng: float, client: httpx.Client) -> Image.Image:
    """Stitch OSM tiles around (lat, lng) into a WIDTH x HEIGHT image."""
    cx, cy = deg2px(lat, lng, ZOOM)
    tl_x = cx - WIDTH / 2
    tl_y = cy - HEIGHT / 2

    x0 = int(tl_x // TILE_PX)
    y0 = int(tl_y // TILE_PX)
    x1 = int((tl_x + WIDTH) // TILE_PX)
    y1 = int((tl_y + HEIGHT) // TILE_PX)

    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#e8dec4")
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            url = TILE_URL_TEMPLATE.format(z=ZOOM, x=tx, y=ty)
            r = client.get(url, timeout=30.0)
            r.raise_for_status()
            tile = Image.open(io.BytesIO(r.content)).convert("RGB")
            px = int(tx * TILE_PX - tl_x)
            py = int(ty * TILE_PX - tl_y)
            canvas.paste(tile, (px, py))

    draw = ImageDraw.Draw(canvas)
    cx_img, cy_img = WIDTH // 2, HEIGHT // 2
    r = MARKER_R
    draw.ellipse(
        (cx_img - r - 2, cy_img - r - 2, cx_img + r + 2, cy_img + r + 2),
        fill=MARKER_OUTLINE,
    )
    draw.ellipse(
        (cx_img - r, cy_img - r, cx_img + r, cy_img + r),
        fill=MARKER_RED,
    )

    attribution = "© OpenStreetMap contributors"
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial.ttf", 11
        )
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), attribution, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = 4
    box_x = WIDTH - tw - pad * 2 - 4
    box_y = HEIGHT - th - pad * 2 - 4
    draw.rectangle(
        (box_x, box_y, box_x + tw + pad * 2, box_y + th + pad * 2),
        fill=(255, 255, 255, 200),
    )
    draw.text((box_x + pad, box_y + pad - 1), attribution, fill=(60, 60, 60), font=font)
    return canvas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="Regenerate existing maps")
    ap.add_argument("slug", nargs="?", help="Optional: target a single business slug")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(BUSINESSES_YAML) as f:
        data = yaml.safe_load(f)
    businesses = data.get("businesses", []) or []

    if args.slug:
        businesses = [b for b in businesses if b.get("slug") == args.slug]
        if not businesses:
            print(f"Unknown business slug: {args.slug}", file=sys.stderr)
            return 1

    n_done = n_skip = n_no_coords = 0
    headers = {"User-Agent": USER_AGENT, "Accept": "image/png,image/*"}
    with httpx.Client(headers=headers) as client:
        for biz in businesses:
            slug = biz.get("slug")
            if not slug:
                continue
            out = OUT_DIR / f"{slug}.webp"
            if out.exists() and not args.force:
                n_skip += 1
                continue
            lat = biz.get("lat")
            lng = biz.get("lng")
            if lat is None or lng is None:
                print(f"  skip {slug}: no lat/lng")
                n_no_coords += 1
                continue
            print(f"  rendering {slug} ({lat}, {lng})…")
            img = render_map(float(lat), float(lng), client)
            img.save(out, format="WEBP", quality=88, method=6)
            print(f"    wrote {out.relative_to(REPO_ROOT)} ({out.stat().st_size // 1024} KB)")
            n_done += 1
            time.sleep(0.5)

    print(
        f"\nDone. {n_done} written, {n_skip} skipped (already exist), "
        f"{n_no_coords} skipped (no coords)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
