# Instagram post → event ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest Instagram-scrape JSON (caption + flyer image) for Meeting House Tavern and Atmosphere as event sources, quarantined from the live site and trivially deletable, to evaluate signal quality.

**Architecture:** Add a `source_type` column to `events` as the provenance + deletion lever. Quarantine non-`website` events from the site by filtering the two reader queries against a `PUBLISHED_SOURCE_TYPES` allow-list (no new `status` value, no CHECK-constraint table rebuild). A new `scripts/ingest_instagram.py` treats each post's caption as page text and its flyer as the single image, reuses the existing multimodal `extract_events`, and upserts with `source_type='instagram'` and a namespaced `match_key` so IG rows never merge into live website rows.

**Tech Stack:** Python 3 (stdlib + existing deps: `httpx`, `Pillow`, `anthropic`, `pyyaml`), SQLite. No test framework in this repo (per CLAUDE.md it tests via `scripts/test_extraction.py` and print-logging) — verification uses throwaway temp-DB assertion scripts and `--dry-run` on real data, NOT pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-instagram-ingestion-design.md`

---

## File Structure

- `src/db.py` (modify) — `source_type` column in SCHEMA + idempotent migration; `PUBLISHED_SOURCE_TYPES` constant; `build_match_key` namespacing; `upsert_event` INSERT threading + `setdefault`; published-source filter in `all_active_events` and `all_events_with_business`.
- `scripts/ingest_instagram.py` (create) — relative-date parser, per-post extraction loop, CLI.

---

## Task 1: `source_type` column + migration + upsert_event threading

**Files:**
- Modify: `src/db.py` (SCHEMA events table; `init_db`; `upsert_event`)

- [ ] **Step 1: Add the column to the SCHEMA**

In `src/db.py`, in the `events` `CREATE TABLE`, add the column right after the `status`/`featured` block. Find:

```python
    status             TEXT    NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'expired', 'stale', 'rejected')),
    featured           INTEGER NOT NULL DEFAULT 0,
```

Change to:

```python
    status             TEXT    NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'expired', 'stale', 'rejected')),
    source_type        TEXT    NOT NULL DEFAULT 'website',  -- provenance: 'website' | 'instagram'.
                                -- Deletion lever for channel experiments:
                                -- DELETE FROM events WHERE source_type='instagram'.
    featured           INTEGER NOT NULL DEFAULT 0,
```

- [ ] **Step 2: Add the idempotent migration**

In `init_db`, after the existing `ticket_url` migration `try/except`, append:

```python
        try:
            conn.execute(
                "ALTER TABLE events ADD COLUMN source_type TEXT NOT NULL DEFAULT 'website'"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
```

- [ ] **Step 3: Thread source_type through upsert_event**

In `upsert_event`, after the existing `event.setdefault("ticket_url", None)` line, add:

```python
    event.setdefault("source_type", "website")
```

Then in the INSERT statement, add `source_type` to BOTH the column list and the VALUES list. Find the column list line:

```python
            confidence, raw_extraction, status,
            first_seen_at, last_seen_at, last_extracted_at, match_key
```

Change to:

```python
            confidence, raw_extraction, status, source_type,
            first_seen_at, last_seen_at, last_extracted_at, match_key
```

And the VALUES line:

```python
            :confidence, :raw_extraction, :status,
            :now, :now, :now, :match_key
```

Change to:

```python
            :confidence, :raw_extraction, :status, :source_type,
            :now, :now, :now, :match_key
```

Do NOT add `source_type` to the UPDATE `update_pairs` — provenance is set once at insert and must not be clobbered on re-extraction.

- [ ] **Step 4: Verify migration is idempotent + backfills + INSERT works**

Run:

```bash
cd /Users/justingonder/Development/aville
python3 - <<'EOF'
import tempfile, os
from pathlib import Path
from src import db
p = Path(tempfile.mkdtemp()) / "t.db"
db.init_db(p); db.init_db(p)  # twice → idempotent, no error
with db.connect(p) as c:
    bid = db.upsert_business(c, {"slug":"x","name":"X","category":None,"subcategory":None,"website":None,"address":None})
    # event without source_type → defaults to 'website'
    db.upsert_event(c, bid, {"kind":"recurring","title":"Web Ev","recurrence_pattern":"weekly:monday","start_time":"19:00","source_page_url":"http://x","source_page_hash":"h","confidence":0.9})
    # event with source_type='instagram'
    db.upsert_event(c, bid, {"kind":"recurring","title":"IG Ev","recurrence_pattern":"weekly:tuesday","start_time":"20:00","source_page_url":"http://ig","source_page_hash":"h","confidence":0.9,"source_type":"instagram"})
    rows = c.execute("SELECT title, source_type FROM events ORDER BY title").fetchall()
    print([dict(r) for r in rows])
    assert dict(rows[0]) == {"title":"IG Ev","source_type":"instagram"}, rows[0]
    assert dict(rows[1]) == {"title":"Web Ev","source_type":"website"}, rows[1]
print("OK task 1")
EOF
```

Expected: prints the two rows then `OK task 1` with no AssertionError.

- [ ] **Step 5: Commit**

```bash
git add src/db.py
git commit -m "feat(db): add source_type column for event provenance

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Namespace match_key by source_type

**Files:**
- Modify: `src/db.py` (`build_match_key`)

- [ ] **Step 1: Prefix the key for non-website sources**

In `build_match_key`, the function currently ends with:

```python
    return "|".join(parts)
```

Replace that final `return` with:

```python
    key = "|".join(parts)
    # Namespace non-website provenance so experiment rows (e.g. Instagram) never
    # collide with or silently merge into live website rows under the shared
    # UNIQUE(business_id, match_key) constraint. Website rows keep the bare key.
    source_type = event.get("source_type")
    if source_type and source_type != "website":
        return f"{source_type}|{key}"
    return key
```

(Reads `source_type` from the event dict rather than taking a new parameter — every call site already passes the full event dict, so no call-site changes are needed and pipeline's `seen_keys.add(build_match_key(ev))` stays consistent.)

- [ ] **Step 2: Verify namespacing**

Run:

```bash
cd /Users/justingonder/Development/aville
python3 - <<'EOF'
from src.db import build_match_key
base = {"kind":"recurring","title":"Bingo","recurrence_pattern":"weekly:wednesday","start_time":"19:30"}
web = build_match_key(base)
ig  = build_match_key({**base, "source_type":"instagram"})
print("web:", web)
print("ig :", ig)
assert not web.startswith("instagram|"), web
assert ig == "instagram|" + web, ig
# explicit website source_type behaves like default (no prefix)
assert build_match_key({**base, "source_type":"website"}) == web
print("OK task 2")
EOF
```

Expected: prints both keys then `OK task 2`, no AssertionError.

- [ ] **Step 3: Commit**

```bash
git add src/db.py
git commit -m "feat(db): namespace match_key by non-website source_type

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Quarantine non-published source types from site readers

**Files:**
- Modify: `src/db.py` (`PUBLISHED_SOURCE_TYPES` constant; `all_active_events`; `all_events_with_business`)

- [ ] **Step 1: Add the published-source constant**

In `src/db.py`, just after the `LOCKABLE_FIELDS = [...]` list closes, add:

```python
# Source types that are allowed to appear on the live, published site. Events
# from any other source (e.g. the Instagram-ingestion experiment) are written
# to the DB for review but excluded from the site-builder reader queries below.
# Promote an experimental channel to live by adding its source_type here.
PUBLISHED_SOURCE_TYPES = ("website",)
```

- [ ] **Step 2: Filter `all_active_events`**

In `all_active_events`, find:

```python
           WHERE e.status = 'active'
           ORDER BY
```

Change to (build the IN list from the constant so it stays in sync):

```python
           WHERE e.status = 'active'
             AND e.source_type IN ({published})
           ORDER BY
```

and wrap the query string with a `.format(published=...)`. Concretely, replace the whole `conn.execute(""" … """)` call body so it reads:

```python
def all_active_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in PUBLISHED_SOURCE_TYPES)
    return conn.execute(
        f"""SELECT e.*, b.name AS business_name, b.slug AS business_slug,
                  b.category AS business_category, b.address AS business_address
           FROM events e
           JOIN businesses b ON e.business_id = b.id
           WHERE e.status = 'active'
             AND e.source_type IN ({placeholders})
           ORDER BY
             CASE e.kind WHEN 'dated' THEN 0 ELSE 1 END,
             e.start_datetime,
             b.name,
             e.title""",
        PUBLISHED_SOURCE_TYPES,
    ).fetchall()
```

- [ ] **Step 3: Filter `all_events_with_business`**

Replace the `all_events_with_business` body similarly:

```python
def all_events_with_business(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All active + stale events with business info, for generating per-event static pages."""
    placeholders = ", ".join("?" for _ in PUBLISHED_SOURCE_TYPES)
    return conn.execute(
        f"""SELECT e.*, b.name AS business_name, b.slug AS business_slug,
                  b.category AS business_category, b.address AS business_address,
                  b.website AS business_website
           FROM events e
           JOIN businesses b ON e.business_id = b.id
           WHERE e.status IN ('active', 'stale')
             AND e.source_type IN ({placeholders})
           ORDER BY e.id""",
        PUBLISHED_SOURCE_TYPES,
    ).fetchall()
```

- [ ] **Step 4: Verify quarantine**

Run:

```bash
cd /Users/justingonder/Development/aville
python3 - <<'EOF'
import tempfile
from pathlib import Path
from src import db
p = Path(tempfile.mkdtemp()) / "t.db"
db.init_db(p)
with db.connect(p) as c:
    bid = db.upsert_business(c, {"slug":"x","name":"X","category":None,"subcategory":None,"website":None,"address":None})
    db.upsert_event(c, bid, {"kind":"recurring","title":"Web Ev","recurrence_pattern":"weekly:monday","start_time":"19:00","source_page_url":"http://x","source_page_hash":"h","confidence":0.9})
    db.upsert_event(c, bid, {"kind":"recurring","title":"IG Ev","recurrence_pattern":"weekly:tuesday","start_time":"20:00","source_page_url":"http://ig","source_page_hash":"h","confidence":0.9,"source_type":"instagram"})
    active = [dict(r)["title"] for r in db.all_active_events(c)]
    withbiz = [dict(r)["title"] for r in db.all_events_with_business(c)]
    print("all_active_events:", active)
    print("all_events_with_business:", withbiz)
    assert active == ["Web Ev"], active
    assert withbiz == ["Web Ev"], withbiz
    # sanity: the IG row IS in the DB, just not in the published readers
    total = c.execute("SELECT count(*) FROM events WHERE source_type='instagram'").fetchone()[0]
    assert total == 1, total
print("OK task 3")
EOF
```

Expected: both reader lists contain only `Web Ev`; prints `OK task 3`.

- [ ] **Step 5: Commit**

```bash
git add src/db.py
git commit -m "feat(db): quarantine non-website source types from site readers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Relative-time parser in the ingester

**Files:**
- Create: `scripts/ingest_instagram.py`

- [ ] **Step 1: Create the file with header + parser**

Create `scripts/ingest_instagram.py`:

```python
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
        [--dry-run] [--limit N] [--scraped-on YYYY-MM-DD]

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
```

- [ ] **Step 2: Verify the parser**

Run:

```bash
cd /Users/justingonder/Development/aville
python3 - <<'EOF'
from datetime import date
from scripts.ingest_instagram import parse_relative_time as p
ref = date(2026, 6, 7)
assert p("17 days ago", ref) == date(2026, 5, 21), p("17 days ago", ref)
assert p("a day ago", ref) == date(2026, 6, 6)
assert p("1 day ago", ref) == date(2026, 6, 6)
assert p("yesterday", ref) == date(2026, 6, 6)
assert p("today", ref) == ref
assert p("2 weeks ago", ref) == date(2026, 5, 24)
assert p("an hour ago", ref) == ref
assert p("3 hours ago", ref) == ref
assert p("garbage", ref) is None
assert p(None, ref) is None
print("OK task 4")
EOF
```

Expected: `OK task 4`, no AssertionError.

- [ ] **Step 3: Commit**

```bash
git add scripts/ingest_instagram.py
git commit -m "feat(ingest): Instagram relative-time parser

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Post → event extraction core + CLI

**Files:**
- Modify: `scripts/ingest_instagram.py`

- [ ] **Step 1: Add imports and config loaders**

In `scripts/ingest_instagram.py`, below the `parse_relative_time` function, add:

```python
import base64
import json
from io import BytesIO

import yaml
from PIL import Image

from src.db import connect, init_db, upsert_business, upsert_event
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
```

NOTE: confirm `load_businesses` accepts `include_pending` — it does (per CLAUDE.md). If the signature differs, call it with no args and filter the returned list.

- [ ] **Step 2: Add the per-post extraction function**

Append to `scripts/ingest_instagram.py`:

```python
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


def ingest_post(conn, business: dict, business_id: int, post: dict,
                tag_vocab: list[str], reference: date, dry_run: bool) -> str:
    """Process one IG post. Returns one of: 'skipped-no-image', 'no-event',
    'error:<msg>', or 'inserted:N'/'updated:N' style summary token."""
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
        ev.setdefault("status", "active")
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
            actions.append(f"DRY {ev.get('kind')}: {title} "
                           f"[{ev.get('recurrence_pattern') or ev.get('start_datetime')}]")
        else:
            action = upsert_event(conn, business_id, ev)
            actions.append(f"{action}: {title}")
    return " | ".join(actions)
```

- [ ] **Step 3: Add file driver + CLI `main`**

Append to `scripts/ingest_instagram.py`:

```python
def ingest_file(conn, json_path: Path, slug: str, tag_vocab: list[str],
                reference: date, dry_run: bool, limit: int | None) -> None:
    posts = json.loads(json_path.read_text())
    if limit is not None:
        posts = posts[:limit]
    business = _find_business(slug)
    business_id = None if dry_run else upsert_business(conn, business)
    print(f"\n=== {business['name']} ({slug}) — {len(posts)} post(s) ===")
    counts = {"event": 0, "no-event": 0, "error": 0, "skipped": 0}
    for i, post in enumerate(posts, 1):
        result = ingest_post(conn, business, business_id, post, tag_vocab,
                             reference, dry_run)
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
    return ap.parse_args(argv)


def main(argv=None):
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
                        args.dry_run, args.limit)
    print("\ndone.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify CLI parsing + dry-run on 2 real posts**

First a no-API smoke test of arg parsing:

```bash
cd /Users/justingonder/Development/aville
python3 - <<'EOF'
from scripts.ingest_instagram import parse_args
a = parse_args(["x.json:meeting-house-tavern", "--dry-run", "--limit", "2", "--scraped-on", "2026-06-07"])
assert a.specs == ["x.json:meeting-house-tavern"], a.specs
assert a.dry_run and a.limit == 2 and a.scraped_on == "2026-06-07"
print("OK args")
EOF
```

Expected: `OK args`.

Then a real `--dry-run` on 2 posts (requires `ANTHROPIC_API_KEY`; makes 2 Haiku calls):

```bash
cd /Users/justingonder/Development/aville
python3 scripts/ingest_instagram.py \
    ~/Downloads/meetinghousetavernchi_instagram_posts.json:meeting-house-tavern \
    --dry-run --limit 2 --scraped-on 2026-06-07
```

Expected: prints a per-post line for each of the 2 posts (either a `DRY …:` event line or counted as non-event), a summary line, and `done.`. Confirm nothing was written: 

```bash
sqlite3 data/app.db "SELECT count(*) FROM events WHERE source_type='instagram';"
```

Expected: `0`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_instagram.py
git commit -m "feat(ingest): Instagram post extraction core + CLI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Run the experiment + verify quarantine and teardown

**Files:** none (execution + the resulting `data/app.db` / image commits)

- [ ] **Step 1: Real ingest of both files**

```bash
cd /Users/justingonder/Development/aville
python3 scripts/ingest_instagram.py \
    ~/Downloads/meetinghousetavernchi_instagram_posts.json:meeting-house-tavern \
    ~/Downloads/atmospherebarchicago_instagram_posts.json:atmosphere \
    --scraped-on 2026-06-07
```

Expected: two `===` sections with per-post lines and summaries, then `done.`

- [ ] **Step 2: Inspect what landed**

```bash
sqlite3 data/app.db "SELECT b.slug, e.kind, count(*) FROM events e JOIN businesses b ON e.business_id=b.id WHERE e.source_type='instagram' GROUP BY b.slug, e.kind;"
sqlite3 data/app.db "SELECT title, kind, recurrence_pattern, start_datetime FROM events WHERE source_type='instagram' ORDER BY business_id, kind LIMIT 40;"
```

Eyeball the titles/patterns for signal quality. This is the experiment's actual output — report it to Justin.

- [ ] **Step 3: Verify quarantine (IG events absent from a build)**

```bash
cd /Users/justingonder/Development/aville
python3 - <<'EOF'
from src.db import connect, all_active_events, all_events_with_business
with connect() as c:
    a = [dict(r) for r in all_active_events(c)]
    w = [dict(r) for r in all_events_with_business(c)]
    leak_a = [r["title"] for r in a if r.get("source_type") == "instagram"]
    leak_w = [r["title"] for r in w if r.get("source_type") == "instagram"]
    print("active reader IG leaks:", leak_a)
    print("withbiz reader IG leaks:", leak_w)
    assert not leak_a and not leak_w, "IG events leaked into a published reader!"
print("OK quarantine")
EOF
```

Expected: empty leak lists, `OK quarantine`.

- [ ] **Step 4: Confirm teardown works (dry, then keep the data)**

Verify the deletion lever returns the count to zero WITHOUT actually destroying the experiment — run it inside a rolled-back transaction:

```bash
sqlite3 data/app.db <<'EOF'
BEGIN;
SELECT 'before', count(*) FROM events WHERE source_type='instagram';
DELETE FROM events WHERE source_type='instagram';
SELECT 'after-delete-ig', count(*) FROM events WHERE source_type='instagram';
SELECT 'website-untouched', count(*) FROM events WHERE source_type='website';
ROLLBACK;
SELECT 'after-rollback', count(*) FROM events WHERE source_type='instagram';
EOF
```

Expected: `before` > 0, `after-delete-ig` = 0, `website-untouched` unchanged by the delete, `after-rollback` back to the `before` count.

- [ ] **Step 5: Commit the experiment data**

```bash
git add data/app.db public/images/
git commit -m "data: ingest Instagram posts for MHT + Atmosphere (experiment)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Update handoffs.md**

Add a top-of-file entry to `handoffs.md` summarizing: branch name, what shipped (source_type column, quarantine mechanism, ingester), the experiment results (counts + signal-quality read), the teardown command, and that NO workflow was triggered (experiment is quarantined, not deployed). Note next-session candidates: review IG events, decide promote-vs-delete.

---

## Self-Review

**Spec coverage:**
- §1 source_type column → Task 1 ✓
- §2 quarantine via PUBLISHED_SOURCE_TYPES + reader filters → Task 3 ✓
- §3 match_key namespacing → Task 2 ✓
- §4 ingester (date approx, download, extract_events reuse, default_tags merge, upsert source_type='instagram') → Tasks 4–5 ✓
- §4 CLI (--dry-run, --limit, --scraped-on) → Task 5 ✓
- §5 non-goals (no web search, no deploy, no new status) → respected; Task 6 explicitly does not trigger a workflow ✓
- Verification section (idempotent migration, dry-run, real run, teardown) → Tasks 1–6 verification steps ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every verify step shows the command + expected output. The one flagged uncertainty (`load_businesses(include_pending=...)` signature) has an explicit fallback instruction. ✓

**Type/name consistency:** `parse_relative_time(text, reference)`, `build_page_image(img_url)`, `ingest_post(...)`, `ingest_file(...)` signatures consistent across tasks. `PageImage` field names match `src/images.py:48` (index, source_url, local_path, media_type, b64, caption, section_header, link_url, width, height). `source_type` string `'instagram'` used consistently. `PUBLISHED_SOURCE_TYPES` referenced consistently. ✓
