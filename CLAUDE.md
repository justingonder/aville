**Note:** When orienting to this project, cross-reference claims in this document against the actual code. Where this document and the code disagree, the code is authoritative; flag the discrepancy to the user.

Four components, each in its own file under `src/`:
- `fetcher.py` — plain httpx, works for all Squarespace sites we've seen
- `images.py` — finds content images, filters noise, downloads to public/,
  captures section_header + caption per image
- `extractor.py` — multimodal Claude call, enforces structured JSON output
- `site_builder.py` — Jinja → public/index.html

Pipeline orchestrator is `src/pipeline.py`. Entry points are in `scripts/`.

## Design decisions that matter

**Single `events` table with `kind` discriminator** (not two tables).
  - Considered splitting recurring vs. dated into separate tables; decided
    unified was simpler for v1 and makes tag faceting easier.
  - If recurring and dated events start diverging substantially, revisit.

**Claude Haiku 4.5, `temperature=0.0`** (explicitly set in `extractor.py`).
  - Haiku is plenty capable for this extraction task. Sonnet is 10x more
    expensive with marginal quality gain for our use case.
  - Temperature is set to 0.0, which stabilizes structured fields and reduces
    run-to-run variance in `description` and `suggested_new_tags`.

**Per-image caption extraction, not whole-section dumps.**
  - `images.py` builds each image's `caption` by walking forward from the
    `<img>` tag in document order until it hits the next image, heading,
    or style/script/nav/footer boundary.
  - Also captures the most recent heading as `section_header` (e.g.,
    "WEEKLY EVENTS") to give Claude recurrence hints.
  - This was a fix for an earlier bug where all captions in a section got
    smooshed together, causing Claude to misattribute day/time.

**Business-level `default_tags`** in `config/businesses.yaml`.
  - Tags that apply to every event at a business (e.g., an LGBTQ+ 21+ bar
    gets `[lgbtq, 21-plus]` on every event automatically).
  - Merged into Claude's tag output in `pipeline.py`. Test script doesn't
    merge them, which can be confusing — output of `test_extraction.py`
    won't match what actually lands in the DB.

**Controlled tag vocabulary** in `config/tags.yaml`.
  - Claude must pick from this list (`tags` field). Can propose new ones
    via `suggested_new_tags`. Taxonomy is deliberately a living artifact,
    not finalized.

**SQLite, one file, committed to git.**
  - `data/app.db` is tracked in git as of 2026-04-18. The Actions workflow
    commits the updated DB back to main after each run.
  - Change detection uses `source_page_hash`. Skip extraction if hash
    matches last run (cost-saving; not yet implemented).
  - Events that disappear between runs get `status='stale'`. No auto-expiry
    to `expired` yet.

## What is NOT in scope for v1

- Instagram/Facebook integration (deferred after research — see earlier
  conversation; requires Meta App Review + per-business opt-in)
- User-submitted events (spam moderation is its own project)
- Admin UI (edit YAML, re-run; use `sqlite3` CLI for ad-hoc DB edits)
- JavaScript-rendered site support (add Playwright when a business site
  needs it; not required for any current business)
- Calendar views, search, multi-page site

## Conventions

- **No frameworks.** Procedural Python, stdlib-preferred. Dependencies are
  listed in `requirements.txt`; don't add more without a reason.
- **Type hints** on function signatures where useful; not religious about it.
- **Print statements** for pipeline logging, not `logging` module. v1 scale
  doesn't need structured logs.
- **Test against one URL first.** `scripts/test_extraction.py` exists
  specifically for iterating on the prompt or config without touching the DB.
- **Config over code.** Per-business behavior (hints, default_tags) goes in
  YAML, not in prompts or source files.

## Where things live

- Prompt: `src/prompts.py` (SYSTEM_PROMPT). Changes here affect every business.
- Per-business hints: `config/businesses.yaml` (`hints` field, per page).
  Changes here affect only that business.
- Tag vocabulary: `config/tags.yaml`.
- Schema: `src/db.py` (SCHEMA constant). Migrations: there aren't any yet;
  delete `data/app.db` to start over.
- HTML template: `templates/index.html` + `templates/_event_card.html`.

## Gotchas

- **Namecheap SSH uses port 21098**, not 22. The Actions workflow handles this.
- **Squarespace inlines `<style>` blocks** between content elements. The caption
  walker in `images.py` treats these as boundaries so CSS doesn't leak in.
  If you add support for another site builder, watch for similar junk.
- **Dates without years.** Prompt instructs Claude to pick the nearest future
  date. Working as intended, but worth re-checking around year boundaries.
- **Run-to-run variance** in Claude's output. The system prompt + controlled
  vocab + `temperature=0.0` pin down the structured fields. `description` and
  `notes` fields may still vary slightly. Don't rely on exact string match in
  tests.

## Open questions / things to decide later

- When to promote `suggested_new_tags` to the real vocabulary
  (current approach: manual review, no automation).
- Whether to split recurring vs. dated events into separate tables
  (current: one table with `kind` discriminator).
- How to handle flyers that advertise multiple sub-events on one image
  (e.g., MHT's "Trivia Is a Drag" flyer has a pre-event boozy bingo).
  Currently: one event per flyer, note field captures the sub-event.
- What to do about stale events — currently they linger in the DB with
  `status='stale'` forever. Probably want a rule like "stale for 14 days
  → expired".
- Whether to ever pursue Instagram/Facebook (no current plan; revisit if
  the Chamber becomes a partner and provides business introductions).
- Image optimization. Scraped images are stored at their original source dimensions
  and file sizes — a 1.2 MB webp flyer is not uncommon. Site loads noticeably
  slowly on first visit. Need to add an image-resizing step to the pipeline
  (likely in src/images.py, right after download_and_validate). Target: resize
  to max 1200px wide, convert to webp at ~80% quality. Pillow handles this in
  a few lines.

## Deployment

Extraction runs on GitHub Actions daily at 11:00 UTC / 6:00 AM Chicago time. Deploys to aville.net via rsync to Namecheap shared hosting.

**Workflow status as of 2026-04-18:** Several bugs were fixed this session
(see Drift log). The deploy step is currently in a verbose debug state —
it prints SSH_KEY length and boundary chars before attempting the connection.
Once deployment is confirmed working end-to-end, remove the diagnostic echo
block from the "Deploy to Namecheap" step in `.github/workflows/scheduled.yml`
(the five lines between `run: |` and `set -e`).

## Quick reference

Run the pipeline:           `python scripts/run_extraction.py`
Test a single URL:          `python scripts/test_extraction.py <slug> <url>`
Rebuild the site:           `python scripts/build_site.py`
Wipe and start over:        `rm data/app.db && python scripts/init_db.py`
See active events:          `sqlite3 data/app.db "SELECT title, kind, recurrence_pattern FROM events WHERE status='active'"`

## Drift log

_Record of checks where CLAUDE.md was verified against actual code state._

- **2026-04-18** — Verified two items:
  - `temperature=0.0` **was already set** in `extractor.py` (line 95). CLAUDE.md
    had incorrectly said it was not set. Fixed above.
  - `source_page_hash` change-detection (skip extraction on unchanged pages)
    **still not implemented** — hash is stored in the DB but never compared
    before extraction runs. Intentionally left as-is (not in scope today).
- **2026-04-18** — Workflow bugs fixed this session:
  - Removed invalid `if: ${{ secrets.NAMECHEAP_SSH_HOST != '' }}` conditional
    (GitHub Actions does not allow secrets in `if:` expressions).
  - Added `set -e`, input validation, and SSH connection test to deploy step.
  - Fixed `ssh-keyscan` to pass `-p 21098` (Namecheap's non-standard SSH port).
  - Removed `data/app.db` from `.gitignore`; DB is now committed to git so
    Actions runs have cross-run change-detection history.
  - Added temporary SSH_KEY diagnostic echoes to deploy step — remove once
    deployment is confirmed working.