#!/usr/bin/env python3
"""Instagram post → event ingestion (experiment).

Treats each scraped Instagram post's caption as page text and its flyer image
as the single image, runs them through the existing multimodal extractor, and
writes events with source_type='instagram'. These rows are quarantined from the
live site (see PUBLISHED_SOURCE_TYPES in src/db.py) and deletable in one query:

    DELETE FROM events WHERE source_type='instagram';

Design: docs/superpowers/specs/2026-06-07-instagram-ingestion-design.md

Usage:
    python3 scripts/ingest_instagram.py <file.json>:<slug> [<file.json>:<slug> ...]
        [--dry-run] [--limit N] [--scraped-on YYYY-MM-DD] [--quarantine]

    --quarantine lands NEW events as status='rejected' (off the live site) for
    review-then-promote, instead of the default status='active'. Existing rows
    keep their current status, so re-scrapes never un-publish a promoted event.

Example:
    python3 scripts/ingest_instagram.py \\
        ~/Downloads/meetinghousetavernchi_instagram_posts.json:meeting-house-tavern \\
        ~/Downloads/atmospherebarchicago_instagram_posts.json:atmosphere
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def parse_relative_time(text: str | None, reference: date) -> date | None:
    """Convert Instagram's relative 'time' field to an absolute date.

    Handles 'N days ago', 'N day ago', 'a day ago', 'yesterday', 'today',
    'N weeks ago', 'a week ago', 'N hours/minutes ago' (→ reference day),
    'an hour ago'. Returns None for anything unrecognized (e.g. absolute dates
    we don't bother parsing — caller falls back to the reference date).
    """
    if not text:
        return None
    t = text.strip().lower()
    if t in ("today", "just now", "now"):
        return reference
    if t in ("yesterday",):
        return reference - timedelta(days=1)
    # hours / minutes ago → same calendar day as reference
    if re.search(r"\b(hour|hours|minute|minutes|min|mins|second|seconds)\b", t):
        return reference
    m = re.match(r"(?:a|an|\d+)\s+(day|days|week|weeks|month|months)\s+ago", t)
    if not m:
        return None
    num_token = t.split()[0]
    n = 1 if num_token in ("a", "an") else int(num_token)
    unit = m.group(1)
    if unit.startswith("day"):
        return reference - timedelta(days=n)
    if unit.startswith("week"):
        return reference - timedelta(weeks=n)
    if unit.startswith("month"):
        return reference - timedelta(days=30 * n)
    return None


import base64
import json
from io import BytesIO

from dotenv import load_dotenv
from PIL import Image

from src.db import build_match_key, connect, init_db, upsert_business, upsert_event
from src.extractor import extract_events
from src.fetcher import fetch_bytes
from src.images import PageImage, store_event_image_from_url
from src.pipeline import load_businesses, load_tag_vocab

PUBLIC_DIR = ROOT / "public"


def _find_business(slug: str) -> dict:
    """Return the businesses.yaml entry for slug, or raise."""
    for biz in load_businesses(include_pending=True):
        if biz.get("slug") == slug:
            return biz
    raise SystemExit(f"business slug not found in businesses.yaml: {slug}")


def build_page_image(img_url: str) -> PageImage:
    """Download the flyer once (in-memory) and wrap it as the single PageImage
    the extractor will show Claude. media_type is image/jpeg (picnob serves jpg
    thumbnails even for video posts)."""
    raw = fetch_bytes(img_url)
    with Image.open(BytesIO(raw)) as pil:
        width, height = pil.size
    return PageImage(
        index=1,
        source_url=img_url,
        local_path="",  # filled at persist time (real runs); empty in dry-run
        media_type="image/jpeg",
        b64=base64.b64encode(raw).decode("ascii"),
        caption="",       # caption goes in page_text instead (whole post)
        section_header="",
        link_url=None,
        width=width,
        height=height,
    )


def resolve_status(conn, business_id, event: dict, quarantine: bool) -> str:
    """Decide the `status` to write for an ingested IG event.

    Default (not quarantine): 'active' — the historical behavior, events go live
    on the next build (the IG channel is in PUBLISHED_SOURCE_TYPES).

    Quarantine: brand-new events land 'rejected' so they stay off the live site
    until a human reviews and promotes them in the admin UI. Events that already
    exist (matched by build_match_key) keep their CURRENT status, so a re-scrape
    never clobbers a manual promote/demote — promoting (set 'active' + lock the
    `status` field) is then durable across future runs via upsert_event's
    locked-field skip. In a dry run there is no DB to consult, so everything is
    reported as a new 'rejected' row.
    """
    if not quarantine:
        return "active"
    if conn is None or business_id is None:  # dry-run: treat as new
        return "rejected"
    row = conn.execute(
        "SELECT status FROM events WHERE business_id = ? AND match_key = ?",
        (business_id, build_match_key(event)),
    ).fetchone()
    return row["status"] if row else "rejected"


def ingest_post(conn, business: dict, business_id, post: dict,
                tag_vocab: list[str], reference: date, dry_run: bool,
                quarantine: bool = False) -> str:
    """Process one IG post. Returns a short result token: 'skipped-no-image',
    'no-event', 'error:<msg>', or a ' | '-joined list of per-event actions."""
    caption = (post.get("caption") or "").strip()
    img_url = post.get("imgUrl")
    link = post.get("link") or ""
    if not img_url:
        return "skipped-no-image"

    post_date = parse_relative_time(post.get("time"), reference) or reference

    # The hints channel carries the IG framing + approximate date so Claude can
    # resolve "tonight / this Saturday" and skip non-event posts.
    hints = (
        f"This text is the caption of an Instagram post from {business['name']} "
        f"(@instagram), posted on approximately {post_date.isoformat()} "
        f"({post_date.strftime('%A, %B %-d, %Y')}). The attached image is the "
        f"post's photo or flyer. Resolve any relative dates ('tonight', "
        f"'this Saturday', 'next Friday') against the post date. If this post is "
        f"NOT advertising an event, happy hour, or recurring special (e.g. it is "
        f"a memorial, a general vibe photo, a staff shout-out, or a repost with "
        f"no event), return an empty list."
    )
    page = {"url": link or f"instagram-post-{post.get('shortcode','')}",
            "kind": "events", "hints": hints}

    try:
        page_img = build_page_image(img_url)
    except Exception as exc:  # noqa: BLE001
        return f"error:image:{exc}"

    try:
        events = extract_events(
            business=business,
            page=page,
            page_text=caption,
            images=[page_img],
            tag_vocab=tag_vocab,
        )
    except Exception as exc:  # noqa: BLE001
        return f"error:extract:{exc}"

    if not events:
        return "no-event"

    # Persist the flyer to public/ once (real runs only) so every IG event can
    # carry its image even if Claude omitted source_image_index.
    local_path = ""
    src_url = img_url
    if not dry_run:
        try:
            src_url, local_path = store_event_image_from_url(
                img_url, business["slug"], PUBLIC_DIR)
        except Exception as exc:  # noqa: BLE001
            print(f"      image-persist failed (event keeps CDN url only): {exc}")

    default_tags = business.get("default_tags") or []
    actions = []
    for ev in events:
        ev.setdefault("description", None)
        ev.setdefault("recurrence_pattern", None)
        ev.setdefault("start_time", None)
        ev.setdefault("end_time", None)
        ev.setdefault("start_datetime", None)
        ev.setdefault("end_datetime", None)
        ev.setdefault("price_info", None)
        ev.setdefault("performers", [])
        ev["source_page_url"] = page["url"]
        ev["source_page_hash"] = post.get("shortcode") or ""
        ev["source_type"] = "instagram"
        # Quarantine routes NEW events to 'rejected' (held off the live site for
        # review); existing rows keep their current status. source_type must be
        # set first — build_match_key namespaces IG rows by it.
        ev["status"] = resolve_status(conn, business_id, ev, quarantine)
        # Force-attach the single flyer if Claude didn't map it.
        if not ev.get("image_source_url"):
            ev["image_source_url"] = src_url
        if local_path and not ev.get("image_local_path"):
            ev["image_local_path"] = local_path
        if not ev.get("external_link"):
            ev["external_link"] = link or None
        if default_tags:
            ev["tags"] = list(dict.fromkeys(list(ev.get("tags") or []) + default_tags))
        ev.setdefault("raw_extraction", {**ev, "_ig_shortcode": post.get("shortcode")})
        title = ev.get("title", "(no title)")
        if dry_run:
            actions.append(f"DRY {ev.get('kind')} [{ev['status']}]: {title} "
                           f"[{ev.get('recurrence_pattern') or ev.get('start_datetime')}]")
        else:
            action = upsert_event(conn, business_id, ev)
            actions.append(f"{action} [{ev['status']}]: {title}")
    return " | ".join(actions)


def ingest_file(conn, json_path: Path, slug: str, tag_vocab: list[str],
                reference: date, dry_run: bool, limit: int | None,
                quarantine: bool = False) -> None:
    posts = json.loads(json_path.read_text())
    if limit is not None:
        posts = posts[:limit]
    business = _find_business(slug)
    business_id = None if dry_run else upsert_business(conn, business)
    print(f"\n=== {business['name']} ({slug}) — {len(posts)} post(s) ===")
    counts = {"event": 0, "no-event": 0, "error": 0, "skipped": 0}
    for i, post in enumerate(posts, 1):
        result = ingest_post(conn, business, business_id, post, tag_vocab,
                             reference, dry_run, quarantine)
        if result == "no-event":
            counts["no-event"] += 1
        elif result.startswith("skipped"):
            counts["skipped"] += 1
        elif result.startswith("error"):
            counts["error"] += 1
            print(f"  [{i:>2}] {result}")
        else:
            counts["event"] += 1
            print(f"  [{i:>2}] {result}")
    print(f"  summary: {counts['event']} with events, "
          f"{counts['no-event']} non-event, {counts['skipped']} skipped, "
          f"{counts['error']} errors")


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Ingest Instagram posts as events.")
    ap.add_argument("specs", nargs="+", metavar="FILE.json:slug",
                    help="One or more <json_path>:<business_slug> pairs.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Extract + print, no image persist, no DB write.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap posts processed per file.")
    ap.add_argument("--scraped-on", default=None, metavar="YYYY-MM-DD",
                    help="Reference date for relative-time math (default: today).")
    ap.add_argument("--quarantine", action="store_true",
                    help="Land NEW events as status='rejected' (off the live site) "
                         "for review-then-promote. Existing rows keep their current "
                         "status, so a re-scrape never un-publishes a promoted event.")
    return ap.parse_args(argv)


def main(argv=None):
    load_dotenv()  # pull ANTHROPIC_API_KEY from .env, like the other entry-point scripts
    args = parse_args(argv or sys.argv[1:])
    if args.scraped_on:
        reference = date.fromisoformat(args.scraped_on)
    else:
        reference = date.today()
    pairs = []
    for spec in args.specs:
        if ":" not in spec:
            raise SystemExit(f"expected FILE.json:slug, got: {spec}")
        path_str, slug = spec.rsplit(":", 1)
        path = Path(path_str).expanduser()
        if not path.exists():
            raise SystemExit(f"file not found: {path}")
        pairs.append((path, slug))

    tag_vocab = load_tag_vocab()
    if not args.dry_run:
        init_db()
    with connect() as conn:
        for path, slug in pairs:
            ingest_file(conn, path, slug, tag_vocab, reference,
                        args.dry_run, args.limit, args.quarantine)
    print("\ndone.")


if __name__ == "__main__":
    main()
