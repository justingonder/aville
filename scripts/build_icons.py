"""Generate favicon and app icon assets from the tank SVG symbols.

Uses Playwright (already a project dependency) to render SVGs to PNG,
then Pillow to assemble the ICO and cream-background app icons.

Output files (all in public/):
  favicon.svg          — tank symbol, scalable, transparent bg
  favicon.ico          — tank-mini at 16/32/48px, transparent bg
  apple-touch-icon.png — tank-mini centered in 180×180 cream square
  icon-192.png         — same, 192×192
  icon-512.png         — same, 512×512
"""
from __future__ import annotations
import io
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public"

TANK_SVG = """\
<?xml version="1.0" encoding="UTF-8"?>
<svg viewBox="0 0 60 48" xmlns="http://www.w3.org/2000/svg">
  <rect x="28" y="2" width="4" height="3" fill="#2a2620"/>
  <polygon points="10,16 30,4 50,16" fill="#2a2620"/>
  <line x1="10" y1="16" x2="50" y2="16" stroke="#1a1812" stroke-width="1"/>
  <rect x="9" y="16" width="42" height="26" fill="#1f4c7a"/>
  <rect x="9" y="27" width="42" height="4" fill="#e8b84a"/>
  <rect x="21" y="16" width="5" height="26" fill="#e8b84a"/>
  <line x1="9" y1="16" x2="51" y2="16" stroke="#1a1812" stroke-width="1"/>
  <line x1="9" y1="42" x2="51" y2="42" stroke="#1a1812" stroke-width="1"/>
  <rect x="7" y="42" width="46" height="2.5" fill="#2a2620"/>
</svg>"""

TANK_MINI_SVG = """\
<?xml version="1.0" encoding="UTF-8"?>
<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
  <polygon points="4,14 24,2 44,14" fill="#2a2620"/>
  <line x1="4" y1="14" x2="44" y2="14" stroke="#1a1812" stroke-width="1.2"/>
  <rect x="22" y="0" width="4" height="3" fill="#2a2620"/>
  <rect x="3" y="14" width="42" height="28" fill="#1f4c7a"/>
  <rect x="3" y="26" width="42" height="4.5" fill="#e8b84a"/>
  <rect x="16" y="14" width="5" height="28" fill="#e8b84a"/>
  <line x1="3" y1="14" x2="45" y2="14" stroke="#1a1812" stroke-width="1.2"/>
  <line x1="3" y1="42" x2="45" y2="42" stroke="#1a1812" stroke-width="1.2"/>
</svg>"""

CREAM = "#fffdf5"


def _render_svg(page, svg: str, width: int, height: int) -> Image.Image:
    """Render an SVG string to a PIL RGBA image at the given pixel size."""
    tmp = OUT / "_icon_tmp.svg"
    tmp.write_text(svg, encoding="utf-8")
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"file://{tmp}", wait_until="load")
    png_bytes = page.screenshot(type="png")
    tmp.unlink(missing_ok=True)
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def _with_cream_bg(img: Image.Image, size: int, pad: float = 0.10) -> Image.Image:
    """Center img (RGBA) on a cream opaque square with padding."""
    canvas = Image.new("RGB", (size, size), CREAM)
    inner = int(size * (1 - 2 * pad))
    fg = img.resize((inner, inner), Image.LANCZOS)
    offset = (size - inner) // 2
    canvas.paste(fg, (offset, offset), fg)
    return canvas


def main() -> None:
    from playwright.sync_api import sync_playwright

    # favicon.svg — just write the source directly (no rendering needed)
    (OUT / "favicon.svg").write_text(TANK_SVG, encoding="utf-8")
    print("  favicon.svg written")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Transparent background so the SVG renders against nothing
        ctx = browser.new_context(viewport={"width": 512, "height": 512})
        page = ctx.new_page()

        # We need a minimal HTML wrapper so the SVG fills the viewport
        def render(svg: str, size: int) -> Image.Image:
            html = (
                f'<!DOCTYPE html><html><head>'
                f'<style>*{{margin:0;padding:0}}body{{width:{size}px;height:{size}px;overflow:hidden;background:transparent}}'
                f'svg{{width:{size}px;height:{size}px}}</style>'
                f'</head><body>{svg}</body></html>'
            )
            tmp = OUT / "_icon_tmp.html"
            tmp.write_text(html, encoding="utf-8")
            ctx.set_default_navigation_timeout(10000)
            page.goto(f"file://{tmp}", wait_until="load")
            page.set_viewport_size({"width": size, "height": size})
            png_bytes = page.screenshot(
                type="png",
                clip={"x": 0, "y": 0, "width": size, "height": size},
                omit_background=True,
            )
            tmp.unlink(missing_ok=True)
            return Image.open(io.BytesIO(png_bytes)).convert("RGBA")

        # favicon.ico: tank-mini at 16/32/48, transparent bg
        ico_frames = [render(TANK_MINI_SVG, s) for s in (16, 32, 48)]
        ico_frames[0].save(
            OUT / "favicon.ico",
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48)],
            append_images=ico_frames[1:],
        )
        print("  favicon.ico written (16/32/48)")

        # Hi-res base for app icons
        base = render(TANK_MINI_SVG, 512)

        _with_cream_bg(base, 180).save(OUT / "apple-touch-icon.png", "PNG")
        print("  apple-touch-icon.png written (180×180)")

        _with_cream_bg(base, 192).save(OUT / "icon-192.png", "PNG")
        print("  icon-192.png written (192×192)")

        _with_cream_bg(base, 512).save(OUT / "icon-512.png", "PNG")
        print("  icon-512.png written (512×512)")

        browser.close()

    print("Icons done.")


if __name__ == "__main__":
    main()
