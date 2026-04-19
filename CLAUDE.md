# CLAUDE.md

Context for Claude Code sessions in this project. Read this first before making changes.

## Project purpose

An event aggregator for Andersonville, Chicago. Pulls events, happy hours,
and specials from a curated list of local business websites and publishes
them as a static site at aville.net. Owner: Justin Gonder. See README.md
for the full architecture diagram and setup instructions.

## Current scope (deliberately small)

- Under 10 businesses, mix of website structures
- Websites only — no Instagram/Facebook for v1
- Static HTML output deployed to Namecheap shared hosting
- Daily extraction via GitHub Actions
- Goal for v1: a shareable link to show friends and the Chamber of Commerce

Resist scope creep. If a change would require a framework, a database
upgrade, or new infrastructure, pause and confirm with Justin before
proceeding.

---

**Note:** When orienting to this project, cross-reference claims in this document against the actual code. Where this document and the code disagree, the code is authoritative; flag the discrepancy to the user.

**Session continuity:** At the start of each session, read `handoffs.md` for recent context. At the end of each session where you made changes, append a new entry to the top of `handoffs.md` following the structure already in the file.

Four components, each in its own file under `src/`:
- `fetcher.py` — httpx for plain HTTP fetching; Playwright (headless Chromium) for JS-heavy sites (`use_playwright: true` in config)
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

## Business notes

Per-business context that isn't derivable from the config or site structure alone.

### Replay Andersonville (`replay-andersonville`)

- **Multiple locations** — Replay has Andersonville (5358 N Clark St) and Lakeview
  locations. The WordPress site serves both under the same domain. Always scope
  extraction to Andersonville only; ignore Lakeview references.
- **Events page** (`replaychicago.com/andersonville/events/`) — WordPress image
  cards, one per event. Primary source for named events (Karaoke, Trivia, Drag,
  Brunch, one-off specials). Images from `wp-content/uploads/`.
- **Menu page** (`replaychicago.com/andersonville/menu/`) — embeds a Google Doc
  in an iframe injected by JavaScript. The iframe URL is **not** in the static
  HTML; it requires a browser/Playwright to discover. Do not bother fetching the
  WordPress menu page URL directly — fetch the Google Doc URLs below instead.
- **Daily Specials Google Doc** (the one we scrape):
  `https://docs.google.com/document/d/e/2PACX-1vSnGM52i9A9j54-k7Q3XAh01BATvdyM5XVhK7YuLn6KYDReEsmZ40CabcgvG7QAarXPqnYnrOk9w9TD/pub`
  — auto-updates every 5 minutes. Contains: Mon–Thu 4–6pm food happy hour,
  daily drink specials Tue–Fri, and passing references to the recurring events
  (Karaoke, Trivia, Drag) that are already on the events page.
- **Other menu tabs** (Lunch & Dinner, Brunch, Drinks) also live in the Google
  Doc iframe but have separate URLs not yet discovered. They were not scraped as
  of 2026-04-18 — low priority since they are food/drink menus, not events.
- **Duplicate risk** — the Daily Specials doc references Karaoke (Mon), Trivia
  (Wed), and Dinner and Drag (Fri) in passing. The hints in `businesses.yaml`
  instruct Claude not to re-extract those. If extraction ever produces duplicates,
  check whether the hints are still present and specific enough.

### Atmosphere (`atmosphere`)

- **Platform:** GoDaddy Website Builder. Images are on the `img1.wsimg.com` CDN
  using protocol-relative URLs (`//img1.wsimg.com/...`). A bug fix was applied
  to `images.py` on 2026-04-18 to handle these (prepend `https:`).
- **Home page** — mixes recurring themed nights (Inferno Saturdays, Broadway
  Wednesdays, RPDR Fridays, monthly 80s/90s/Flashback nights) with dated one-off
  flyers. Hints tell Claude to extract recurring only from this page.
- **Upcoming Events page** — dated one-off events only. Images are higher
  resolution than the home page grid (1650×2550 vs 370×572). Dates and times are
  embedded in the flyer images; image filenames also carry a date hint
  (e.g., `04.26.26`) that Claude uses as a cross-check.
- **Daily Drink Specials page** — blank as of 2026-04-18. Included in config so
  it gets checked each run automatically.
- **Duplicate risk** — dated one-off flyers appear on both the home page grid
  and the Upcoming Events page. The home-page hint says "extract recurring only"
  which has kept extraction clean in testing. Watch for regressions if the site
  redesigns its home layout.
- **"The 80s" recurrence** — the flyer says "last Friday of every month" but the
  schema has no `monthly:last-friday` pattern; Claude maps it to `monthly:4th-friday`.
  This will be wrong in 5-Friday months. Known limitation, not worth fixing now.
- **Weekday Drink Specials** — there is a drink specials flyer image on the home
  page (image #15 in the last test run). Claude correctly extracts it as a
  recurring event covering Tue/Wed/Thu with per-day pricing.

### Vincent (`vincent`)

- **Platform:** Wix. All content is JavaScript-rendered.
- **Fetcher:** Uses `use_playwright: true` — headless Chromium via `playwright.sync_api`,
  waits for `load` event plus a 5-second settle delay before capturing HTML. Playwright
  must be installed locally with `playwright install chromium` (done once after
  `pip install -r requirements.txt`).
- **Wait strategy note:** We use `wait_until="load"` + `wait_for_timeout(5000)` rather
  than `"networkidle"` because the Wix site issues continuous background XHR/WebSocket
  traffic that prevents `networkidle` from ever firing within a reasonable timeout.
  The 5-second post-load delay is sufficient for the JS-rendered sections to appear.
- **Event flyers:** Three event flyer images are present in the DOM after the 5-second
  settle, hosted on `static.wixstatic.com` with media hash prefix `15e961`. As of
  2026-04-19: Happy Hour (recurring daily), Easter Brunch (dated, past), Half Off Mussels
  (recurring Tue/Wed). These are served at ~323x484 or ~461x483 px — above the 300px
  `MIN_DIMENSION` threshold, so they pass image filtering.
- **Happy Hour duplication:** Happy Hour appears in both the event flyer (image #6)
  and the footer text ("Happy Hour Daily 4 - 6pm"). The hint instructs Claude to merge
  both sources into one event. This works correctly — Claude references the flyer for
  price details and the footer for time confirmation.
- **Past-event stale marking:** Easter Brunch had a past date (2026-04-05) when first
  scraped on 2026-04-19. The pipeline's past-event stale marking immediately set
  `status='stale'` for it. Happy Hour and Half Off Mussels remain `status='active'`.
- **Hours for context:** Sun–Thu 4pm–10pm, Fri–Sat 4pm–12am.

## Deployment

Extraction runs on GitHub Actions daily at 11:00 UTC / 6:00 AM Chicago time. Deploys to aville.net via rsync to Namecheap shared hosting.

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
- **2026-04-19** — Playwright support for Vincent implemented and verified:
  - `fetch_html_playwright()` added to `fetcher.py`. Initial implementation used
    `wait_until="networkidle"` which proved unreliable for Wix (continuous background
    XHR prevents networkidle from triggering). Fixed to `wait_until="load"` +
    `wait_for_timeout(5000)`. Default timeout raised from 30s to 60s.
  - Vincent now extracts 3 events from JS-rendered flyer images: Happy Hour (recurring),
    Easter Brunch (dated, stale), Half Off Mussels (recurring Tue/Wed).
  - Past-event stale marking confirmed working in pipeline: Easter Brunch (2026-04-05)
    gets `status='stale'` automatically on extraction.
  - Vincent section in CLAUDE.md updated to reflect Playwright reality.
  - "JavaScript-rendered site support not in scope" removed from "What is NOT in scope".

- **2026-04-18** — Workflow bugs fixed this session:
  - Removed invalid `if: ${{ secrets.NAMECHEAP_SSH_HOST != '' }}` conditional
    (GitHub Actions does not allow secrets in `if:` expressions).
  - Added `set -e`, input validation, and SSH connection test to deploy step.
  - Fixed `ssh-keyscan` to pass `-p 21098` (Namecheap's non-standard SSH port).
  - Removed `data/app.db` from `.gitignore`; DB is now committed to git so
    Actions runs have cross-run change-detection history.
  - SSH diagnostic echo block removed 2026-04-19 once deployment was confirmed working.