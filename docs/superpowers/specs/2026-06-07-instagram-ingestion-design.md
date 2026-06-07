# Instagram post → event ingestion (experiment)

**Date:** 2026-06-07
**Branch:** `experiment/instagram-ingestion`
**Status:** design approved, pre-implementation
**Scope:** deliberately beyond v1 — an experiment to see what events fall out of
ingesting Instagram-scrape JSON (caption + flyer image) for two businesses:
Meeting House Tavern (`meeting-house-tavern`) and Atmosphere (`atmosphere`).

## Motivation

These two venues keep their Instagram feeds far more current than their websites.
We have two scrape JSON files (60 + 84 posts) with `caption`, `imgUrl` (live picnob
CDN), `time` (relative, e.g. "17 days ago"), `link`, `isVideo`, `shortcode`. The
question: if we treat each post's caption + flyer as an event source and run it
through our existing multimodal extractor, what usable events do we get — and is
the signal-to-noise good enough to pursue?

Because this might produce junk, every ingested row must be **trivially deletable**
and **must not reach the live site** until vetted.

## Non-goals

- No web-search enrichment (the existing `ingest_flyer.py` seeds a web search; here
  the IG post itself is the authoritative source — these venues live on IG).
- No auto-deploy / no site rebuild as part of ingestion.
- No new `status` vocabulary value (avoids a CHECK-constraint table rebuild).
- No change to the regular pipeline's behavior: its events remain `source_type='website'`
  and publish exactly as before.

## Design

### 1. `source_type` column — provenance + deletion lever

Add one column to `events`:

```sql
source_type TEXT NOT NULL DEFAULT 'website'
```

- Added via an idempotent `ALTER TABLE events ADD COLUMN source_type TEXT NOT NULL
  DEFAULT 'website'` in `init_db()` (wrapped in the existing try/except OperationalError
  pattern). Existing ~488 rows auto-backfill to `'website'`.
- IG-ingested rows are written with `source_type='instagram'`.
- **Teardown:** `DELETE FROM events WHERE source_type='instagram';` removes the entire
  experiment and nothing else.
- Threaded into `upsert_event`'s **INSERT only**. Not in the UPDATE set — provenance is
  set once at insert and never clobbered. Add `event.setdefault("source_type", "website")`
  in `upsert_event` so pipeline callers (which don't pass it) keep the default.

### 2. Quarantine via `source_type`, not a new status

The committed `data/app.db` has `CHECK (status IN ('active','expired','stale','rejected'))`
baked into the events table. Adding a literal `'review'` status would require a full
12-step table rebuild (recopy 488 rows + FK + indexes + the UNIQUE constraint) — the kind
of database upgrade CLAUDE.md says to avoid.

Instead, quarantine by source:

- Define a module-level constant in `src/db.py`:
  ```python
  PUBLISHED_SOURCE_TYPES = ("website",)
  ```
- The two site-reader queries — `all_active_events` and `all_events_with_business` —
  gain a `AND e.source_type IN (<published set>)` clause.
- IG rows are `status='active'` (semantically true — they are active events) but invisible
  to the site builder because `'instagram'` is not in the published set.
- **Review** = `SELECT … WHERE source_type='instagram'` (or the admin UI).
- **Promote to live** = a one-line flip: add `'instagram'` to `PUBLISHED_SOURCE_TYPES`.

This keeps the `status` column and its CHECK constraint completely untouched.

### 3. Match-key namespacing

IG events run through the same `upsert_event`, but their `match_key` is namespaced so
they never collide with or silently merge into live website rows (which share
`UNIQUE(business_id, match_key)`).

- `build_match_key` gains an optional `source_type` parameter. When it is anything other
  than the default `'website'`, the returned key is prefixed: `f"{source_type}|{key}"`.
- `upsert_event` passes `event.get("source_type")` into `build_match_key`.
- Effect: IG rows live in their own key namespace. Re-running the ingester updates
  same-identity IG rows rather than duplicating; the same recurring event announced three
  times collapses to one row. Website rows are unaffected (default path, no prefix).

### 4. The ingester — `scripts/ingest_instagram.py`

Procedural, stdlib-preferred, print-logging (matches project conventions). Per JSON file
(mapped to a business slug):

1. **Load** the JSON list. For each post:
2. **Approximate the post date** from the relative `time` field ("N days ago",
   "a day ago", "yesterday") against a reference date (default: today; overridable via
   `--scraped-on YYYY-MM-DD` so the relative offsets stay accurate if the file is processed
   days after scraping). Result is an ISO date, injected into the caption text Claude sees
   so it can resolve "tonight / this Saturday / next Friday."
3. **Download the flyer** via `images.store_event_image_from_url(imgUrl, slug, public_dir)`
   → on-disk WebP + srcset, same layout as the pipeline. Build one `images.PageImage`
   (index=1, the downloaded bytes base64'd, caption=the post caption, link_url=the IG post
   `link`). Videos use their thumbnail `imgUrl` (still a static jpg).
4. **Extract** via `extractor.extract_events(business=…, page=…, page_text=<caption +
   date preamble>, images=[PageImage], tag_vocab=…)`. `source_page_url` = the IG post
   `link`. Non-event posts (memorials, general vibes) → Claude returns `[]` → skipped.
5. **Merge `default_tags`** the way `pipeline.py` does (the test script does NOT, per
   CLAUDE.md). MHT and Atmosphere both carry `[lgbtq, 21-plus]`.
6. **Upsert** through `db.upsert_event` with `source_type='instagram'`, `status='active'`.

Image-download or extraction failures are caught per-post, logged, and skipped — one bad
post never aborts the run.

#### CLI

```
python3 scripts/ingest_instagram.py <file.json>:<slug> [<file.json>:<slug> …]
    --dry-run            extract + print results, no image download to permanent path / no DB write
    --limit N            cap posts processed per file (for iterating)
    --scraped-on DATE    reference date for relative-time math (default: today)
```

Example for this experiment:

```
python3 scripts/ingest_instagram.py \
    ~/Downloads/meetinghousetavernchi_instagram_posts.json:meeting-house-tavern \
    ~/Downloads/atmospherebarchicago_instagram_posts.json:atmosphere
```

Prints a per-file summary: posts seen, events extracted, inserted/updated, skipped
(non-event), errors.

## Files touched

- `src/db.py` — `source_type` column + migration; `PUBLISHED_SOURCE_TYPES` constant;
  `build_match_key` namespacing param; `upsert_event` INSERT threading + setdefault;
  `all_active_events` / `all_events_with_business` published-source filter.
- `scripts/ingest_instagram.py` — new file.
- `docs/superpowers/specs/2026-06-07-instagram-ingestion-design.md` — this doc.

`config/businesses.yaml`, `config/tags.yaml` — read-only (slugs, default_tags, vocab).

## Risks / things to watch

- **Approximate dates.** "N days ago" → a date, but the exact day a one-off event runs may
  be off if the caption is vague. Recurring events (the bulk: trivia, bingo, drag) don't
  depend on the post date. Watch dated one-offs in review.
- **Extractor prompt is tuned for web pages.** A single social caption is a different shape.
  The date preamble + single-image framing should be enough; if extraction quality is poor
  we can add an IG-specific note to `page_text` (not a new prompt — keep it light for the
  experiment).
- **Writing into the real `data/app.db`.** Recoverable: branch is isolated and the DB is
  git-tracked, so `git checkout data/app.db` reverts. Combined with the `source_type` DELETE,
  there are two independent undo paths.

## Verification

- Migration is idempotent (run `init_db()` twice, no error; existing rows show
  `source_type='website'`).
- After a `--limit 5 --dry-run` pass: extracted events print, nothing in DB.
- After a real run: `SELECT count(*) FROM events WHERE source_type='instagram'` > 0;
  `all_active_events` excludes them; a site build shows no IG events.
- Teardown: `DELETE FROM events WHERE source_type='instagram'` returns the count to 0 and
  website event count is unchanged.
