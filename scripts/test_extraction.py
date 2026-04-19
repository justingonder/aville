#!/usr/bin/env python3
"""Run extraction against a single URL and print the JSON to stdout.

Does NOT write to the database or move anything into public/. Intended for
quickly iterating on the prompt and seeing what Claude returns.

Usage:
    python scripts/test_extraction.py <business-slug> <page-url>

The <business-slug> must match one in config/businesses.yaml so we pick up
the right hints, category, and page kind.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.extractor import extract_events  # noqa: E402
from src.fetcher import fetch_html, playwright_session  # noqa: E402
from src.images import discover_and_download, page_text  # noqa: E402
from src.pipeline import load_businesses, load_tag_vocab, PUBLIC_DIR  # noqa: E402


def main(slug: str, url: str) -> None:
    load_dotenv()
    businesses = {b["slug"]: b for b in load_businesses()}
    if slug not in businesses:
        print(f"Unknown slug '{slug}'. Known: {', '.join(businesses)}", file=sys.stderr)
        sys.exit(2)
    biz = businesses[slug]
    page = next((p for p in biz["pages"] if p["url"] == url), None)
    if page is None:
        # Allow ad-hoc URLs not in config, default kind to "home"
        page = {"url": url, "kind": "home", "hints": ""}

    print(f"[1/3] fetching {url} …", file=sys.stderr)
    if page.get("use_playwright"):
        print(f"      (using Playwright — browser session kept open for image downloads)",
              file=sys.stderr)
        with playwright_session(url) as (html, _, _, ctx):
            print(f"[2/3] downloading images (cached to public/) …", file=sys.stderr)
            images = discover_and_download(
                html, biz["slug"], PUBLIC_DIR,
                download_fn=lambda u: ctx.request.get(u).body(),
            )
    else:
        html, _, _ = fetch_html(url)
        print(f"[2/3] downloading images (cached to public/) …", file=sys.stderr)
        images = discover_and_download(html, biz["slug"], PUBLIC_DIR)

    print(f"      kept {len(images)} image(s)", file=sys.stderr)
    for img in images:
        print(f"        #{img.index} {img.width}x{img.height}  {img.source_url[:90]}",
              file=sys.stderr)
        print(f"            section: {img.section_header!r}", file=sys.stderr)
        print(f"            caption: {img.caption!r}", file=sys.stderr)

    print(f"[3/3] calling Claude …", file=sys.stderr)
    events = extract_events(
        business=biz,
        page=page,
        page_text=page_text(html),
        images=images,
        tag_vocab=load_tag_vocab(),
    )

    # Apply business-level default_tags, matching what the pipeline does
    default_tags = biz.get("default_tags") or []
    if default_tags:
        for ev in events:
            ev["tags"] = list(dict.fromkeys(list(ev.get("tags") or []) + default_tags))

    print(json.dumps(events, indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_extraction.py <business-slug> <page-url>",
              file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
