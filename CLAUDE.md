# CLAUDE.md

Context for Claude Code sessions in this project. Read this first before making changes.

## Project purpose

An event aggregator for Andersonville, Chicago. Pulls events, happy hours,
and specials from a curated list of local business websites and publishes
them as a static site at aville.net. Owner: Justin Gonder. See README.md
for the full architecture diagram and setup instructions.

## Current scope (deliberately small)

- ~17 businesses as of 2026-04-20 (actively growing via discovery sessions), mix of website structures
- Websites only — no Instagram/Facebook for v1
- Static HTML output deployed to Namecheap shared hosting
- Daily extraction via GitHub Actions
- Goal for v1: a shareable link to show friends and the Chamber of Commerce

Resist scope creep. If a change would require a framework, a database
upgrade, or new infrastructure, pause and confirm with Justin before
proceeding.

## User Stories

Two core usage patterns that should inform design decisions:

### The Planner
A visitor thinking about their weekend. They want to browse what's on, find a few options, and share them with friends to decide what to do. Key needs: upcoming events grouped by time (today / this weekend / coming up), per-event shareable links with rich link previews so iMessage/Slack shows the flyer, and a path from the shared link back to the full site.

### Already Out
A visitor already in the neighborhood — likely on mobile — wondering "What else is going on right now?" Key needs: time-aware view showing only what's currently happening (evaluated in Chicago time regardless of visitor location), fast load on mobile, minimal friction.

**Timezone note:** All events are in Chicago. "Happening now" logic must always evaluate against `America/Chicago` time via the `Intl` API in JS — never the visitor's device timezone.

**Late-night / midnight-crossing events:** Andersonville nightlife regularly runs past midnight (bars open until 2–3am). A recurring event like "weekly:monday, 17:00–02:00" spans into Tuesday morning. The `isHappeningNow` JS handles this with a `prevDay` check: if an event's `end_time < start_time` (crosses midnight), the post-midnight tail is checked against the **previous** calendar day's recurrence match, not the current day. Example: at 1:30am Tuesday, `prevDay = Monday`, which matches `weekly:monday` → event is live. At 1:30am Monday, `prevDay = Sunday`, which does NOT match `weekly:monday` → not live (event hasn't started yet that day). This matters a lot for this neighborhood — when touching `isHappeningNow`, always test both the "before start" and "post-midnight" cases for a late-night event.

**Featured events:** A `featured` column (INTEGER 0/1) in the `events` table allows manually elevating specific events to a spotlight section at the top of the page. Hook for future mega-event support (e.g., Midsommarfest). Set manually via `sqlite3` — the extraction pipeline never touches this field.

**Series end dates (`ends_on`):** A recurring event tied to a broadcast calendar (TV viewing parties, sports watch parties) has no natural end date in the source data — the business just advertises "Fridays at 7pm" without mentioning the season wraps in N weeks. The `ends_on` column (TEXT, ISO date) lets you manually set the last occurrence date. `site_builder.py::_is_ended_series()` filters events where `ends_on < build_date` out of the `recurring` list (so they disappear from Today, This Weekend, AND the Regulars section in one shot). Per-event detail pages at `/event/{id}/` still render so share links don't break. The extraction pipeline never touches this field. Use `scripts/list_series_candidates.py` to surface recurring events that look like they might need a manual end date (heuristic: `tv-viewing-party` tag + title keywords like "viewing party", "watch party", "rpdr"; trivia nights are explicitly excluded since themed trivia is evergreen). Set dates with: `sqlite3 data/app.db "UPDATE events SET ends_on='YYYY-MM-DD' WHERE id=N;"`. Use the event's last real occurrence date — the filter is `ends_on < build_date` (strict less-than), so the event still shows on its final day.

**Spotlight priority:** manually featured → happening now → hidden (controlled by `data-show-when-empty` attribute on `#spotlight`, making it easy to toggle the empty-state behavior without code changes).

---

## Audience and conventions

This site is for Andersonville / Chicago residents. When making presentation
choices, default to American / Midwest conventions:

- 12-hour time with lowercase am/pm (`7pm`, not `19:00` or `7:00 PM`)
- Day-first names (`Saturday, April 18`), not ISO dates on the site
- Imperial units where relevant
- Casual-but-not-slangy tone in any microcopy

The underlying database should store structured/unambiguous formats (ISO
dates, 24-hour times) — convert to human format at the template layer only.
This keeps querying, sorting, and debugging clean.

---

**Note:** When orienting to this project, cross-reference claims in this document against the actual code. Where this document and the code disagree, the code is authoritative; flag the discrepancy to the user.

**Session continuity:** At the start of each session, read `handoffs.md` for recent context. Update `handoffs.md` at natural stopping points during a long session — don't wait until the end. At a minimum, always update it before closing or when context is running long. Append a new entry to the top of `handoffs.md` following the structure already in the file. In the "Next session candidates" section, list items in priority order — most urgent or valuable first. Also include a one-line workflow note: which workflow should be triggered (if any) based on what changed this session, using the decision rule in the Deployment section. If a workflow was triggered during the session, note which one and whether it succeeded.

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

**Business flyer images committed to git** (as of 2026-04-21).
  - `public/images/<business-slug>/*.webp` (and srcset variants) are tracked
    in git. Each extraction run commits any newly downloaded images alongside
    the DB update.
  - Rationale: (a) a fresh checkout can build the full site without
    extraction, (b) build assertions (`CHECK_IMAGES=1`) need the files
    present in CI, (c) historical flyers persist even when a source page
    stops advertising the event or the CDN rotates the image.
  - Build-artifact OGs are gitignored: `public/images/og/` (per-event OGs,
    regenerated when missing) and `public/images/og-home.jpg` (regenerated
    every build).
  - Rsync no longer excludes `images/` — the repo has everything CI needs.
  - Repair tool: `scripts/repair_missing_images.py` re-downloads missing
    files by their DB-recorded `image_source_url`, verifying the SHA256
    hash matches the expected filename. Use when the DB and disk get out
    of sync (e.g., partial extraction failure).

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
- Schema: `src/db.py` (SCHEMA constant). Migrations run: `ADD COLUMN featured INTEGER` (2026-04-19), `ADD COLUMN performers TEXT` (2026-04-21), `ADD COLUMN ends_on TEXT` (2026-04-21), `ADD COLUMN price_short TEXT` (2026-04-29 — short-form happy-hours card price; nullable; Phase 1 falls back to `price_info[:14]`, Phase 2 will backfill via Haiku). If the schema gets out of sync, delete `data/app.db` to start over.
- HTML templates: `templates/index.html` (main page), `templates/_event_card.html` (card partial), `templates/_event_detail.html` (per-event static page with OG tags), `templates/_tower.html` (water tower SVG macro, `cork`/`og` variants).
- CSS: `styles/index.css` and `styles/event.css` (source files). At build time, `_publish_css()` in `site_builder.py` hashes content and writes `public/{name}.{hash8}.css`. Never edit `public/*.css` directly — edit the source in `styles/`.
- Favicon/icons: `scripts/build_icons.py` (Playwright-based, run manually when icon source changes). Outputs: `favicon.svg`, `favicon.ico`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, `site.webmanifest` in `public/`.
- Static business maps: `scripts/build_business_maps.py` (httpx + Pillow, no new pip deps; hand-rolled OSM tile stitcher). Run manually when a business's `lat`/`lng` changes or a new business is added. Generates 800×540 WebP at zoom 19 with riso-red marker + "© OpenStreetMap contributors" attribution, output to `public/images/maps/{slug}.webp`. Idempotent (skips files that already exist; `--force` regenerates; optional positional `slug` arg targets one business). Sends a descriptive User-Agent and waits 0.5s between businesses to respect the OSM tile usage policy. Maps are committed to git (static content — businesses don't move) and consumed by `templates/_event_detail.html` in the venue card.

## Gotchas

- **Namecheap SSH uses port 21098**, not 22. The Actions workflow handles this.
- **Squarespace inlines `<style>` blocks** between content elements. The caption
  walker in `images.py` treats these as boundaries so CSS doesn't leak in.
  If you add support for another site builder, watch for similar junk.
- **`SKIP_FILENAME_PATTERNS` checks filename only, not the full URL.** The pattern
  matches `logo`, `icon`, `favicon`, etc. against the last path segment of the URL
  (before query string), not the whole URL string. A Cloudinary path like
  `/saas/logos/image_xxx.webp` would falsely match "logo" in the directory name if
  checked against the full URL. Fixed 2026-04-19; if you touch image filtering, keep
  this check scoped to filename.
- **Dated events: `start_time` vs. `start_datetime`** — recurring events store time in the `start_time` column (used directly by the JS `data-start-time` attribute). Dated events store time inside `start_datetime` (ISO string). The card template extracts the time from `start_datetime` via `chicago_time_str()` in `site_builder.py` and emits it as `data-start-time`. If you add new time-dependent spotlight logic, always verify it works for both kinds.
- **Spotlight: events without a known `start_time` are excluded from "happening now."** If `start_time` (or the time component of `start_datetime`) is null, `isHappeningNow` returns `false`. We'd rather show nothing than a false positive. This affects Chicago Magic Lounge shows until times are manually set.
- **Scheduled extraction vs. local pushes race condition** — the Actions workflow does `git pull --rebase origin main` before pushing the updated DB, so concurrent local pushes during a run won't cause the DB commit to fail.
- **Playwright user-agent triggers anti-bot protection** on some sites — `playwright_session()` now uses a real Chrome UA (`PLAYWRIGHT_USER_AGENT` in `fetcher.py`) instead of the `AvilleBot` string. The bot UA is still used by plain httpx `fetch_html` calls, but Playwright needs the real UA so sites don't fingerprint it as a headless bot. Discovered 2026-04-20 when Nobody's Darling returned empty results despite Playwright fetching the page.
- **Businesses in `config/businesses_pending.yaml`** are NOT scraped by the pipeline until promoted to `businesses.yaml`. The test script (`scripts/test_extraction.py`) accepts `include_pending=True` via `load_businesses()` so you can test pending entries without promoting them. Discovery state tracked in `docs/business-discovery/progress.json`.

## Business discovery workflow

When adding new businesses, process **one at a time** — don't batch-research many and process later. The cycle per business:

1. **Research** — WebFetch/WebSearch to find URL, platform, events/specials available
2. **Write YAML** — add entry to `config/businesses_pending.yaml` with hints
3. **Test** — `python3 scripts/test_extraction.py <slug> <url>`
4. **Troubleshoot** — if empty or wrong output, adjust hints or `use_playwright`, retry
5. **Document** — update `_test_extraction` and `_confidence` in the YAML entry; update `docs/business-discovery/progress.json`
6. **Commit** — one commit per accepted business

Only after that cycle completes, move to the next candidate. This keeps context clean and results properly recorded.
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
- **Holiday-events representation** — events tied to specific holidays
  (Mother's Day markets, Pride events, Christmas pop-ups, etc.) probably
  want different surfacing rules than ordinary dated events: they're
  worth highlighting earlier (people plan ahead for holidays), they
  often have a "season" feel (Pride = month of June), and a generic
  "holiday" tag may be too coarse. Flagged 2026-04-24 when a Mother's
  Day market flyer triggered the question. Revisit once we have a few
  more holiday-tied events in the DB to look at concretely.

### Lower priority / future pipeline improvements

- **Mobile LCP structural ceiling — pre-Midsommarfest critical** _(high priority before launch)_ — Mobile Lighthouse LCP plateaued at ~3.8s on Slow 4G after shipping image+caching wins (2026-04-22 session). Root cause is structural: the LCP element is the spotlight clone built by the JS IIFE at the end of `templates/index.html` (after the entire 251 KB body parses). The browser can't start fetching the LCP image until JS runs and inserts the cloned `<img>`. Cloudflare HTML caching saved ~700ms on the HTML round-trip but the JS-built LCP path is the next ceiling.

  **Why this matters for Midsommarfest:** Lighthouse's Slow 4G profile is exactly the cell-tower congestion scenario — thousands of phones in a few-block radius. Real users at the festival will see worse than the synthetic 3.8s. If LCP slips past ~5s on real devices, bounce rate spikes and the launch impression suffers.

  **Three fix paths, ranked by impact + cost:**
  1. **Lazy-render below-fold cards** (best, expensive): initial HTML emits only the spotlight + first 6–12 cards; the rest hydrate via IntersectionObserver as the user scrolls. Cuts initial HTML from 251 KB → ~50 KB → faster parse → faster everything. Requires careful work because existing JS (`isHappeningNow`, search/filter, share-leaderboard tracking) currently queries `document.querySelectorAll('.f[...]')` over the full DOM. A lazy-render pass needs to either (a) keep all cards in DOM but defer image loading + heavy work, or (b) maintain an in-memory index of all events and re-render on scroll.
  2. **Build-time spotlight prerender** (medium impact, UX cost): pre-compute "happening now" at build time, render in static HTML so the LCP image is eager-discoverable from initial parse. LCP could drop to ~1.5–2s. Cost: spotlight is stale by up to 24h since extraction runs daily — bad for the "Already Out" persona who wants real-time. Could mitigate with hourly rebuilds (24× the API cost) or a spotlight-only sub-build that doesn't re-extract.
  3. **Inline the most-likely LCP image as base64 in HTML** (clever, fragile): predict the live event at build time, inline its image bytes. Eliminates the request entirely. Predicted-wrong = wasted bytes but no visual harm (JS still picks the right event). Edge cache holds for an hour so prediction accuracy degrades over the cache window.

  Discovered 2026-04-22. Decision deferred to closer to Midsommarfest launch — revisit before shipping the festival announcement.

- **Flyer-ingestion pipeline** _(implemented 2026-04-27 on branch `flyer-ingestion-design` — pending end-to-end validation against a real walk batch)_ — Standalone CLI (`scripts/ingest_flyer.py`) that takes phone-camera photos of paper flyers, uses each flyer as a SEED for a web search, finds an authoritative source via Claude's `web_search_20250305` tool ranked against `config/web_search_allowlist.yaml`, and runs the existing `extract_events()` pipeline on that source — with the flyer photo as multimodal cross-verification (`cross_verify_image` kwarg, see `src/extractor.py`). Per-photo 7-step pipeline (seed → resolve business → DB dedup → web search → auto-add new business → full extraction → upsert/enrich). Dedup-match prompt offers `[s]kip / [e]nrich / [p]roceed-as-new / [q]uit`. New businesses are auto-added with `extract_business_metadata.py` + `geocode_businesses.py` invoked as subprocesses. Sidecar log per run at `<dir>/.ingest_log.json` for resumability + per-walk summary. Flags: `--dir`, `--source-url` (manual override), `--dry-run`, `--seed-only`, `--force`. Spec: `docs/superpowers/specs/2026-04-24-flyer-ingestion-pipeline-design.md`. Plan: `docs/superpowers/plans/2026-04-27-flyer-ingestion-pipeline.md`. Unit tests: `scripts/test_ingest_helpers.py`, `scripts/test_web_search.py`, `scripts/test_seed_extraction.py`, `scripts/test_extract_events_compat.py` (17 helper assertions all green).

  **Known follow-ups from end-to-end smoke (2026-04-27):**
  1. **Web search prompt sometimes returns listing pages instead of specific event pages.** Live test on the Guesthouse "Wander Home Holiday Market" flyer returned `eventbrite.com/d/il--chicago/free--events/mothers-day/` (Eventbrite *discover* page with many events) rather than the specific event URL. Fix: tighten `search_for_event` prompt in `src/web_search.py` to explicitly prefer specific-event-page URLs over search/listing/discover URLs. Lower priority since the user can fall back to `--source-url <real_event_url>` and re-run that one photo.
  2. **`extract_events` `max_tokens=4096` can truncate JSON when the source page has many events.** The truncation is caught gracefully (`_extract_json_array` raises ValueError → `failed:extract-error` outcome surfaces in walk summary). Fix: bump `max_tokens` (8192 should cover any realistic page) OR trim the page text more aggressively before sending to Claude OR add a prompt instruction to extract only the seed-matching event. Track in `src/extractor.py::extract_events`.

- **Design handoff session 3 — Phase 1** _(shipped 2026-04-29 on branch `design-handoff-session3-phase1`, PR #4 against `main` — pending review/merge + browser visual review at peak HH and mixed-live windows)_ — Three coordinated design features lifted from designer's handoff package at `/Users/jgonder/Downloads/design_handoff_session3/`:

  1. **Happy-hours sidebar card (A.1.B "clock strip")** — homepage sidebar component listing today's happy hours sorted by start time, with `.live` modifier for currently-active rows (yellow clock pill, red dot prefix). Server-rendered via `_select_today_happy_hours()` in `src/site_builder.py` from active recurring events tagged `happy-hour` whose recurrence pattern matches today. Client-side spotlight JS (`templates/index.html` IIFE) implements the **three-state interplay** with the main-column "Happening Now": (a) mixed-live → spotlight gets non-HH cards only, sidebar visible with `.live` rows highlighted; (b) HH-only-live → all-cards in spotlight, sidebar hidden so data isn't shown twice; (c) nothing-live → both hidden. Suppression set switched from `nowIds` to `spotlightIds` so HH cards filtered OUT of spotlight remain visible in the Regulars section.
  2. **Stamped-dateline breadcrumb (B.1.B)** — new partial `templates/_breadcrumb.html` rendered above the masthead on home / business / event / business-directory pages. Replaces the old inline `.crumbs` markup in `.top-row` on biz/event templates. 3-step responsive dateline (full ≥900px → compact 640–899px → hidden <640px) via nested `<span class="dl-extra">` / `<span class="dl-sep">`. `data-short` attribute on parent crumbs for sub-720px collapse via JS IIFE inlined on each page. The `.here.home` modifier suppresses the yellow underline on the homepage's single-item trail.
  3. **Editorial business hero (C.1)** — replaces `<header class="masthead-biz">` block in `templates/_business_detail.html`. Magazine-style: kicker line (mono blue uppercase: `{type} · {street_address} · Andersonville`), 88px Fraunces 900 italic h1, optional italic lede (Phase 1: only if `tagline` or `vibe_quote` set, neither populated yet), action row with Call / Website ↗ / Map ↗ buttons + `Open until X` yellow live pill (server-computed from `biz.hours[<3-letter-day>]`), tag chips (first chip blue `.hl`), 3-up image strip. **Hero strip placeholder fallback:** when `branding_images` < 3, fill remaining cells with typographic blue panel (Fraunces italic pull quote + mono `— hero photo placeholder` annotation). Phase 1 ships with 0 curated `branding_images` — every business renders 3 placeholders by design (deliberately calls out the gap; pressures curation).

  **5 helpers added to `src/site_builder.py`** with 36-assertion test file at `scripts/test_session3_helpers.py`:
  - `_format_clock_pill(start, end)` — `'16:00','18:00'` → `'4–6'` (en-dash; drops `:00` minutes).
  - `_format_window_meta(pattern)` — `'daily'` → `'Daily'`; `'weekly:M-F days'` → `'M–F'`; `'weekly:tue-fri'` → `'Tue–Fri'`; `'weekly:sun'` → `'Sundays'`.
  - `_select_today_happy_hours(events, build_date)` — filter + sort + enrich.
  - `_format_open_until(hours_str, now)` — Chicago-time-aware; midnight-cross handling; returns `None` when closed.
  - `_derive_business_type(category, display_type)` — maps category → spec-allowed type (`Bar`/`Restaurant`/`Cafe`/`Shop`/`Venue`/`Service`); `display_type` overrides; raises ValueError on invalid (build fails loudly on YAML typos). Mapping: `bar→Bar`, `restaurant→Restaurant`, `cafe→Cafe`, `theater→Venue`, `museum→Venue`.

  **New optional YAML fields on businesses** (Phase 1 consumes only the first two; Phase 2 backfills the rest):
  - `display_type` — override capitalized `category`. Allowed: `Bar`/`Restaurant`/`Cafe`/`Shop`/`Venue`/`Service`.
  - `short_name` — breadcrumb `data-short` value (collapse below 720px). Currently set on `chicago-magic-lounge` only (`"Magic Lounge"`).
  - `tagline`, `vibe_quote`, `about`, `press[]`, `branding_images[]`, `socials{}` — Phase 2 fields.

  Spec: `docs/superpowers/specs/2026-04-28-design-handoff-session3.md` (10 locked decisions D1–D10). Plan: `docs/superpowers/plans/2026-04-28-design-handoff-session3-phase1.md`.

  **Phase 2 (deferred — separate plan):** Editorial copy backfill via Claude Haiku script analogous to `extract_business_metadata.py` (drafts `tagline`, `vibe_quote`, `about` for 23 venues; user reviews/edits). Manual: `press[]`, `socials{}`, `branding_images[]`. `price_short` column backfill for happy-hours card. Live JS recompute of "Open until X" pill (today server-rendered, goes stale within a day).

  **Known low-priority follow-ups from final code review:**
  1. Two near-duplicate `_DAY_ORDER` / `DAY_ORDER` constants exist in `src/site_builder.py` (lines 30 and ~580). Maintenance hazard.
  2. `.top .crumbs` rules in `event.css` (~lines 49–50, 293–294) are dead CSS now that the inline `.top-row .crumbs` was removed.
  3. Happening Now count text shows total `nowCards.length` including HH cards even though they're routed to the sidebar — slightly misleading in mixed-live state.
  4. `price_short` column not in `upsert_event` INSERT/UPDATE (intentional Phase 2 deferral; document the touch-up needed when the backfill ships).

- **Transient fetch retries** _(low priority)_ — `fetch_html()` /
  `fetch_bytes()` in `src/fetcher.py` have no retry on transient network
  errors. Observed 3 `[Errno 104] Connection reset by peer` failures on
  `atmospherebar.com` out of 478 total fetches (99.4% success). When a
  fetch fails mid-run, pipeline.py logs it to `fetch_log` and skips the
  page; existing events retain their old `image_local_path`. With
  `public/images/` now tracked in git, this no longer breaks CI — the
  committed flyers satisfy the build assertion. Revisit if failure rate
  climbs or a specific page starts failing repeatedly. Likely fix: catch
  `httpx.RequestError` and retry 2-3× with exponential backoff.

- **Post-extraction day-of-week validation** _(low priority)_ — Claude
  sometimes miscalculates what day of the week a date falls on, producing
  a wrong `recurrence_pattern` (e.g., calling a Sunday "Saturday"). Add a
  post-extraction validation step that checks each recurring event's first
  observed date against the `recurrence_pattern` day and flags mismatches
  for review rather than silently writing wrong data to the DB. Discovered
  2026-04-19 when BEARAOKE was extracted as `weekly:saturday` but is
  actually Sunday nights.

- **`LocalBusiness` schema + per-business landing pages + breadcrumbs** _(shipped 2026-04-23 on branch `per-business-pages`, PR #1)_ — 23 canonical entity pages at `/business/{slug}/` with full `LocalBusiness` JSON-LD (address, geo, telephone, priceRange, openingHoursSpecification from the existing `hours:` block, sameAs, representative flyer `image`, up to 10 upcoming events) and `BreadcrumbList` JSON-LD. Event detail pages gain a visible 3-level breadcrumb (`Home › Business › Event`) and matching `BreadcrumbList` JSON-LD. Every business-name mention on event cards + detail pages (top-bar crumb, "More at …" back-link, facts-strip Venue cell, sidebar Venue card + "More at …" anchor) now links to `/business/{slug}/` instead of the external site. Homepage venue sidebar also linked. Directory landing at `/business/` with `ItemList` JSON-LD lists all 23 venues alphabetically. Markdown sibling at `/business/{slug}/index.md` and `/business/index.md`. See `docs/superpowers/specs/2026-04-23-per-business-landing-pages-design.md` and the implementation plan alongside it.

  Two one-time CLI scripts feed the metadata: `scripts/extract_business_metadata.py` (Claude Haiku, pulls `{description, telephone, price_range, same_as}` from each homepage, ~$0.05 total) and `scripts/geocode_businesses.py` (free Nominatim, populates top-level `lat`/`lng`). Both use a surgical text-level YAML editor that preserves the file's comment header and field ordering — `yaml.safe_dump` would have destroyed both. Re-runnable safely (idempotent skip unless `--force`). Both support a positional slug argument to target a single business. The build itself never writes back to `businesses.yaml`.

- **All-day specials missing startDate in Event JSON-LD** _(low priority)_ — recurring events without a `start_time` (e.g. all-day drink specials like "Tuesday Seasonal Frozen Cocktail Special") emit no `startDate`, so Google's Rich Results Test flags them as missing the required field. ~14/101 active recurring events are affected. Likely fix: when `start_time` is null, default to the business's opening time (and `end_time` to closing time) from the existing `hours:` block in `config/businesses.yaml`. The `_apply_hours_cap()` plumbing in `pipeline.py` already reads hours; extend it to also infer `start_time` for all-day specials. Watch for events that genuinely span the whole day (where defaulting to open-to-close is right) vs. events where missing time means "we don't know" (where guessing is wrong). Discovered 2026-04-22 testing event 23 in Rich Results.

- **Nav-link discovery for new special pages** _(low priority)_ — businesses
  occasionally publish one-off event pages at new URLs (e.g., SoFo Tap's
  `/events-2` for IML 2026) that we only find out about manually. Two
  complementary mitigations: (a) fetch each business's homepage each run
  and parse nav links, alerting on any new URLs not already in
  `businesses.yaml`; (b) fetch `sitemap.xml` for each business and diff
  against known pages. Either approach would catch new pages automatically
  without requiring manual discovery.

- **Schema.org JSON-LD structured data** _(done 2026-04-20, expanded 2026-04-22)_ — `WebSite` + `ItemList` blocks in `templates/index.html`; `Event` block in `templates/_event_detail.html`. Event schema includes name, description, startDate/endDate (recurring events get the next upcoming occurrence via `_event_schema_dates()` + `_next_occurrence_date()` in `site_builder.py`, rolled forward each daily build; recurring events without a `start_time` emit no startDate), location (Place with business address), organizer (Organization with `name` + `url` from `businesses.website`), `performer` (array of Person from `events.performers`), `offers` (Offer with strict numeric-only price parsing — "Free"/"no cover" → 0, single `$NN(.NN)?` → that price), image, url. Uses Jinja2 `tojson` filter to escape all user-supplied strings. Validated against Google Rich Results Test 2026-04-22.

- **Social sharing image (og:image)** _(done 2026-04-21)_ — per-event pages use `summary_large_image` with `public/images/og/{id}.jpg`. Homepage uses `summary_large_image` with `public/images/og-home.jpg`, generated each build by `_build_og_images()` in `site_builder.py` from `templates/_og_image_home.html` (Playwright screenshot at 1200×630).

- **Performers** _(added 2026-04-21)_ — `performers TEXT` column stores a JSON array: `[{"name": "...", "role": "..."}]`. Role vocabulary: `host`, `dj`, `headliner`, `featured`, `performer`, `drag`. Extracted by Claude from flyer text ("Hosted by:", "Featuring:", DJ credits). Displayed inline on event cards (dot-separated) and structured in the detail page aside. Existing events have empty performers until next extraction run.

- **Business hours capping** _(added 2026-04-21)_ — `hours:` block in `config/businesses.yaml` per business (format: `mon: "HH:MM-HH:MM"`, null for closed). `_apply_hours_cap()` in `pipeline.py` infers null `end_time` from closing time and caps events that exceed it. Midnight-crossing closes (e.g. `02:00`) handled by treating times < 8am as next-day (+1440 mins). 10 bars/restaurants populated.

- **Cache headers** _(added 2026-04-21, HTML caching expanded 2026-04-22)_ — `public/.htaccess` sets `Cache-Control: max-age=31536000, immutable` for hash-versioned CSS (`*.{hash8}.css`) and content-addressed images (`[a-f0-9]{16}(-NNNw)?.webp`). 7-day TTL for icons and OG images. **HTML now caches at Cloudflare edge for 1h + browser for 5min** (`public, max-age=300, s-maxage=3600`). Cloudflare-side requires a Cache Rule (Cloudflare dashboard → Caching → Cache Rules) matching URI path ends with `/` OR `.html`, set to "Eligible for cache" with Edge TTL "Use cache-control header if present, bypass if not" and Browser TTL "Respect origin TTL". Rule is active on aville.net as of 2026-04-22. The daily extraction + site-rebuild workflows already do `purge_everything:true` after deploy, so cache invalidation is automatic. Cut HTML round-trip latency from ~1,178ms → ~500ms in PageSpeed Mobile.

- **WebP compression tuning** _(added 2026-04-22)_ — `WEBP_QUALITY = 75` and `WEBP_METHOD = 6` in `src/images.py` (was q=82, default method). Method 6 is the slowest WebP encode setting but produces ~10% smaller files at the same quality; fine for a daily pipeline. The one-time bulk re-encode of existing 740 files via `scripts/reencode_webps.py` shrunk total image bundle 57 MB → 33 MB (42.7% savings). Visual difference at q=82→75 is imperceptible for these flyer images. New extractions produce q=75 originals naturally; the script is for catching up the existing inventory and can be re-run safely (it skips files that would grow).

- **Build assertions** _(added 2026-04-21)_ — `_assert_build()` runs at end of `build_site()`. Always checks that CSS `<link>` hrefs in `index.html` exist on disk. Checks image `src` paths only when `CHECK_IMAGES=1` (set by extraction workflow's build step). Exits non-zero with a clear error list.

- **AI agent / LLM discovery (Tier 1)** _(added 2026-04-23)_ — Four coordinated pieces landed in one session to make the site discoverable and consumable by LLM agents:
  1. **`/llms.txt`** — orientation page following the llmstxt.org convention (H1 title, blockquote summary, linked sections pointing to the sitemap, `/index.md`, per-event pages, structured data, venue list). Generated by `_build_llms_txt()` in `src/site_builder.py`, rebuilt every build so the venue list stays current.
  2. **Content Signals in `robots.txt`** — `Content-Signal: ai-train=yes, search=yes, ai-input=yes` (opt-in to training, search, and real-time AI retrieval — the site's purpose is discovery, so we want agents citing and ingesting it). `robots.txt` is regenerated at every build by `_build_sitemap()`.
  3. **Link response headers (RFC 8288)** in `public/.htaccess` for `*.html`: `</sitemap.xml>; rel="sitemap"`, `</llms.txt>; rel="describedby"`, `<index.md>; rel="alternate"; type="text/markdown"`. The alternate Link uses a relative URI-ref so it resolves per-request — browsers/agents loading `/event/123/index.html` see it resolve to `/event/123/index.md`. Also `.htaccess` now sets `Content-Type: text/markdown; charset=utf-8` for all `*.md` files.
  4. **Build-time markdown siblings** — `templates/index.md` and `templates/_event.md` Jinja templates render `/index.md` (homepage: tonight/weekend/later/regulars, with links to canonical event URLs) and `/event/{id}/index.md` (per-event: title, when, venue+address, price, performers, tags, description, external link). Wired into `build_site()`: `_build_event_pages()` now writes `index.html` + `index.md` side-by-side per event page. In-HTML `<link rel="alternate" type="text/markdown">` tags also added to both `templates/index.html` and `templates/_event_detail.html` for agents that parse DOM instead of inspecting Link headers. Event detail template has `<base href="/">` so the alternate uses an absolute path (`/event/{{ e.id }}/index.md`) rather than a relative one.

  Why these and not the other items on Cloudflare's agent-readiness checklist: API catalog / OAuth discovery / OAuth Protected Resource / MCP Server Card / Agent Skills index / WebMCP all assume the site exposes an API, protected resources, an MCP server, or interactive tools — this site is pure read-only static content, so those don't apply. Markdown-for-Agents (Accept-based negotiation via Cloudflare Worker) was skipped in favor of the cheaper build-time `.md` siblings approach, which works without Workers and without an additional runtime dependency (see lower-priority entry below if we ever want dynamic negotiation on top).

  New `.gitignore` entries: `public/index.md`, `public/llms.txt` (build artifacts, same treatment as `public/index.html`). Per-event `index.md` files sit inside `public/event/` which is already untracked as a whole.

- **AI / LLM discovery Tier 2 — deferred items** _(low-medium priority)_ — follow-ups that would deepen agent-readiness on top of the Tier 1 bundle. In rough order of value:
  - **ICS calendar feeds** — per-event `.ics` file (huge for "add to calendar" flows from assistants and iMessage), plus a site-wide feed. Data is all in the DB; could render at build time with a small `_build_ics()` helper using stdlib `icalendar`-free string formatting. RFC 5545 is forgiving.
  - **JSON Feed or RSS of upcoming events** — machine-readable feed at `/feed.json` (JSON Feed 1.1 is cleaner than RSS; both work for LLM ingestion). One URL, all dated+recurring events the site currently surfaces, auto-updates with every build.
  - **Markdown-for-Agents via Cloudflare Worker** — dynamic content-negotiation: requests with `Accept: text/markdown` get the `.md` served with `Content-Type: text/markdown`, browsers still get HTML. Today the static `.md` siblings cover the same goal through `<link rel="alternate">` + Link header discovery, but a Worker would let agents that blindly send `Accept: text/markdown` against the HTML URL get the right content without having to follow the alternate. Requires Cloudflare Workers setup — an additional runtime dependency — so only worth doing if we see agents ignoring the alternate links in practice. Docs: https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/
  - **Read-only MCP server for events** — small HTTP endpoint exposing `list_events_happening_now`, `list_events_by_day`, `find_events_by_tag`, `get_business_info`. Could live as a Cloudflare Worker that queries a deployed SQLite or reads a pre-baked JSON bundle. Once it exists, publish an MCP Server Card at `/.well-known/mcp/server-card.json` to satisfy Cloudflare's `isitagentready.com` check. Meaningful work — defer until there's a concrete use case (e.g., a local assistant integration).
  - **Machine-readable sitemap-of-markdown** — optional future nicety: a `/sitemap-md.xml` that only lists `.md` URLs, so a crawler scoped to markdown can enumerate cleanly. Very low priority; the existing sitemap plus the `<link rel="alternate">` convention already advertises the same information.

- **Per-business page polish — deferred follow-ups** _(low priority, noted 2026-04-23 at PR #1 time)_ — small items we deliberately left out of the per-business-pages v1 ship:
  - **Per-business OG social-share images** — every business page currently uses `og-home.jpg` as its `og:image`, so every iMessage/Slack share of a business URL looks identical. `_business_schema()` already picks the most recent flyer with an image as `schema["image"]` for the LocalBusiness JSON-LD; the same source would work for the OG meta tag. Cheap follow-up.
  - **Shared spotlight-JS module** — the "Happening right now" IIFE is duplicated between `templates/index.html` and `templates/_business_detail.html`. They are already slightly divergent (homepage has "starting soon" + display-hide on original cards; business page has only the live-card + clone dedup). Worth extracting to `public/spotlight.js` if a third page ever needs the logic or if the implementations drift further.
  - **Homepage "See all venues →" link** pointing at `/business/` — the venue sidebar shows 20+ individual venues but no direct path to the new directory landing. A single line in the sidebar header would close the gap.
  - **Plan doc masthead-guard footnote** — the implementation plan's Task 6 listed `{% if biz.metadata and biz.metadata.description %}` as the guard around the masthead address paragraph. The committed template uses `{% if biz.address %}` (correct). If anyone re-runs this plan, the guard needs to be `biz.address` or future agents will re-introduce the bug.

- **Carol's Pub extraction URL** — Use `https://www.carolspub.com/` (homepage), NOT `/music.html`. The music page shows the full historical archive from Feb 2025 onward, causing the pipeline to extract only stale past events. The homepage shows only the upcoming schedule. Fixed 2026-04-20.

## Business notes

Per-business context that isn't derivable from the config or site structure alone.

### Replay Andersonville (`replay-andersonville`)

- **Multiple locations** — Replay has Andersonville (5358 N Clark St) and Lakeview
  locations. The WordPress site serves both under the same domain. Always scope
  extraction to Andersonville only; ignore Lakeview references.
- **Events page** (`replaychicago.com/andersonville/events/`) — Uses `use_playwright: true`. The page is built with Elementor; static HTML contains only logo images. Event card images (from `wp-content/uploads/`) are JavaScript-rendered and only appear after Playwright executes the page. Plain httpx returns 0 event images. Primary source for named events (Karaoke, Trivia, Drag, Brunch, one-off specials).
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
- **"The 80s" recurrence** — the flyer says "last Friday of every month". Stored as
  `monthly:last-friday` (supported pattern as of 2026-04-19). Was previously incorrectly
  stored as `monthly:4th-friday`; corrected directly in the DB.
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

### Hopleaf Bar (`hopleaf`)

- **Platform:** WordPress, Cloudflare-protected. Requires `use_playwright: true` for both page HTML and CDN image downloads (Cloudflare blocks plain httpx — returns 403 even on images). The `playwright_session()` context manager keeps the browser alive during image discovery so the `cf_clearance` cookie is used for CDN requests.
- **Events source:** Home page only (`hopleafbar.com/`). Events are blog posts with flyer images. Hopleaf has no recurring entertainment — everything is a dated one-off (Zwanze Day, Orval Day, TipoPils Day, tap takeovers, brewery anniversaries).
- **Section header drift:** This WordPress layout shifts headings by one post — each image's nearest `section_header` is from the *previous* blog post, not its own. Image filenames are reliable: `TipoPils` → TipoPils Day, `ZAWNZE` → Zwanze Day (Cantillon lambic, **not** Orval), `OrvalDay` → Orval Day. Hints instruct Claude to use filenames as primary identifiers.
- **Past events:** Claude includes past events in output despite the hint (acknowledges them as past in `notes` but still returns them). Pipeline's past-event stale marking catches them — they land as `status='stale'` immediately.
- **Upcoming Events page** (`hopleafbar.com/upcoming-events/`) — not yet scraped. Low priority since the home page covers upcoming events adequately.

### SoFo Tap (`sofo-tap`)

- **Platform:** Squarespace. Owned by same company as Meeting House Tavern.
- **Three pages scraped:**
  - `/specials` — server-side rendered, no Playwright. Happy hour text + a specials promo image (`SFT_WebSpecials` filename). Each day's special extracted as a separate recurring event.
  - `/events` — `use_playwright: true`. Squarespace calendar is JavaScript-rendered; static HTML returns empty event list. Known recurring events: GRRR (Fri), DILF, KOK, Bear Trap, Doggy Days (Sat afternoon), Sunday Funday (Sun afternoon), Bearaoke (Sun night), Nerd Bear Trivia (Wed).
  - `/events-2` — server-side rendered, no Playwright. Special IML 2026 (International Mr. Leather, Memorial Day weekend) page with 4 dated one-off events. Eventbrite-ticketed; no prices on page.
- **Cloudinary image URLs:** SoFo Tap serves flyer images from Cloudinary (`res.cloudinary.com`) via paths like `/saas/logos/image_xxx.webp`. The `saas/logos/` directory name previously matched the `logo` pattern in `SKIP_FILENAME_PATTERNS` and silently dropped all flyers. Fixed 2026-04-19: pattern now checked against filename only, not the full URL path. See Gotchas below.
- **Duplicate risks managed:**
  - `Daily Specials` catch-all (recurrence: daily) — hint explicitly says not to extract it.
  - Sunday Happy Hour ($3 shots + hot dogs) duplicated SUNDAY FUNDAY. Deleted from DB; hint updated: extract Sunday *drink* specials only, not the hot dog food component.
- **Day-of-week anchors in hints** — BEARAOKE is Sunday (not Saturday). Extraction model miscalculated once; explicit hint anchors added to prevent recurrence.

### Chicago Magic Lounge (`chicago-magic-lounge`)

- **Platform:** Squarespace, server-side rendered. No Playwright needed.
- **Show structure:** Recurring shows by day of week — Mon (Close-Up Show), Tue (Showcase), Wed (Intimo, Luis Carreon solo), Thu–Sun (Signature Show), Daily at 5pm (Performance Bar, non-ticketed). Performers rotate weekly; the show titles/schedules are stable.
- **No times or prices on site:** Show times and ticket prices are handled by ThunderTix (external ticketing, returns 403 — can't scrape). Leave `start_time` and `price_info` null for show events. **After each extraction, set times manually via sqlite3** — check chicagomagiclounge.com for current show times and update with: `UPDATE events SET start_time='HH:MM' WHERE business_id=... AND title LIKE '...'`.
- **Ticketing:** ThunderTix at `chicagomagicloungellc.thundertix.com` — returns 403 to plain httpx. Not scraped.
- **Classes page:** `/classes` has dated Chicago Magic College workshop series. Extract with start/end dates, price, and instructor details.
- **Future show:** "52 Lovers" scheduled Wednesdays from July 1, 2026. Extract if visible as a future recurring event.

## Deployment

Extraction runs on GitHub Actions daily at 11:00 UTC / 6:00 AM Chicago time. Deploys to aville.net via rsync to Namecheap shared hosting.

> **⚠️ TEMPORARY (2026-05-01): Site is parked.** Justin is bidding on `aville.com` and didn't want the seller seeing the polished site. `aville.net` currently serves a bland "Under construction" page (`park/index.html`); all event/business URLs return 404. The daily 11:00 UTC scheduled run will redeploy the real site automatically — that's the easiest restore path (do nothing, wait for tomorrow morning). For an immediate restore, run `gh workflow run "Site rebuild"`. To re-park, run `gh workflow run "Park site (temporary takedown)"`. See the 2026-05-01 evening entry in `handoffs.md` for the full procedure.

### Triggering workflow runs manually

Three workflows exist:
- **"Scheduled extraction + deploy"** (`.github/workflows/scheduled.yml`) — full pipeline: fetch, extract, build, deploy. Burns API credits.
- **"Site rebuild"** (`.github/workflows/site-rebuild.yml`) — build + deploy only, no extraction. Use this for template/CSS/site_builder.py changes.
- **"Park site (temporary takedown)"** (`.github/workflows/park-site.yml`) — wipes the server and deploys `park/index.html`. Manual-only. Idempotent. Added 2026-05-01.

**Decision rule — which workflow to trigger after a session:**
- Pipeline code, prompts, config, extraction logic changed → run **Scheduled extraction + deploy**
- Only templates, CSS, or `site_builder.py` changed → run **Site rebuild**
- Docs-only changes → no workflow needed

**`gh` CLI status as of 2026-04-19:** Installed and authenticated. Trigger runs with:
```bash
gh workflow run "Site rebuild"
gh workflow run "Scheduled extraction + deploy"
```
To watch the run: `gh run watch <run-id>` (the run URL is printed after `gh workflow run`).

**Important:** Always `git push` before triggering a workflow run. `gh workflow run` dispatches against the current HEAD of the remote — if your commits haven't been pushed yet, the workflow runs on old code and deploys stale output.

### Analytics

Analytics is **Plausible** (privacy-friendly, no cookies). Dashboard: https://plausible.io/aville.net

The tracking script lives in the `<head>` of `templates/index.html` and `templates/_event_detail.html`. It uses `async` (not `defer`) and `data-domain="aville.net"`. Do not add it to partials (`_event_card.html`) or any non-public pages.

**Gotcha:** Plausible's v2 custom scripts (`pa-xxx.js`) require `async`. Using `defer` causes Plausible's verification check to fail silently — the script loads but the domain detection doesn't work. Don't change it.

**Custom events:** Plausible supports custom event tracking via `plausible('event-name', { props: { key: 'value' } })`. Call this anywhere in JS to track interactions. No additional script changes needed — the init block already sets up the `window.plausible` queue.

Currently instrumented:
- `Share` — fires on every share button click with `{ event_slug, business }`. Present in both `index.html` and `_event_detail.html`. Dashboard: group by `event_slug` or `business` to see share leaderboard.

## Quick reference

**Always use `python3`, not `python` — `python` is not aliased on this machine.**

Run the pipeline:           `python3 scripts/run_extraction.py`
Test a single URL:          `python3 scripts/test_extraction.py <slug> <url>`
Rebuild the site:           `python3 scripts/build_site.py`
Wipe and start over:        `rm data/app.db && python3 scripts/init_db.py`
See active events:          `sqlite3 data/app.db "SELECT title, kind, recurrence_pattern FROM events WHERE status='active'"`
List series candidates:     `python3 scripts/list_series_candidates.py`

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

- **2026-04-23** — Per-business landing pages shipped on branch `per-business-pages` (PR #1), covering three things that the previous state of CLAUDE.md listed as separate high-priority future items:
  - The "LocalBusiness schema + per-business landing pages + breadcrumbs" entry has been updated from "future work" to "shipped 2026-04-23" in-place.
  - The "Per-business markdown pages" item in the AI/LLM Tier 2 deferred list has been removed since it's now part of the shipped work.
  - A new "Per-business page polish — deferred follow-ups" entry has replaced it, capturing the small items that were deliberately out-of-scope for v1 (per-business OG images, shared spotlight JS, homepage "See all venues" link).
  - Also: switched project workflow from direct-to-main commits to feature branches (per user request). This is saved as a feedback memory and applies to all future non-trivial work on this repo.

- **2026-04-27** — Flyer-ingestion pipeline brainstorm started (paused mid-design). New entry "Flyer-ingestion pipeline" added at the top of the Lower-priority section pointing at the DRAFT spec at `docs/superpowers/specs/2026-04-24-flyer-ingestion-pipeline-design.md`. New "Holiday-events representation" entry added to "Open questions / things to decide later". South Andersonville geographic clarification (Clark between Lawrence and Foster counts as Andersonville for aville.net) saved as a project memory. Branch `flyer-ingestion-design` carries these doc updates.

- **2026-04-29** — Design Handoff Session 3 — Phase 1 shipped on branch `design-handoff-session3-phase1`, PR #4 opened against `main`. Three features (happy-hours sidebar A.1.B, stamped-dateline breadcrumb B.1.B, editorial business hero C.1) lifted from designer's package at `/Users/jgonder/Downloads/design_handoff_session3/`. 16 commits. Approach: full superpowers brainstorm → spec → 14-task plan → subagent-driven execution with two-stage review per task. Lighter-touch reviews on TDD helper tasks (Tasks 2–6); full reviews on integration tasks (7, 8, 11, 12). Final cumulative review caught 3 bugs per-task reviews missed (day-key mismatch on "Open until X" pill, `.kicker::before` red bar inheritance, missing `#regulars` anchor). 5 new helpers in `src/site_builder.py` with 36 unit tests. New `price_short` column on events. New optional YAML fields on businesses: `display_type`, `short_name`, `tagline`, `vibe_quote`, `about`, `press`, `branding_images`, `socials` (Phase 1 consumes only `display_type` and `short_name`). The "Design handoff session 3 — Phase 1" entry was added to the Lower priority / future pipeline improvements section and the schema migrations line was updated to include `ADD COLUMN price_short TEXT`. Phase 2 (editorial copy backfill via Haiku script) deferred to a separate plan. Pre-existing bug surfaced this session: `git add -A` is unsafe in this repo because of recurring untracked files — caught and reverted before push.

- **2026-05-03** — Big shipping day across two design handoffs and a static-maps system. Full chronology in the day's `handoffs.md` entry. Items relevant to long-term project state:
  - **Tower SVG dark-surface refactor** (PR #8): `templates/_tower.html` macro lost its `variant` parameter; the four ink-toned elements (roof polygon, finial, rail rect, scaffolding strokes) now read off CSS custom properties `--tower-ink` and `--tower-roof`. Light-surface defaults + `footer .tower, .tower-on-dark` override added to both `styles/index.css` and `styles/event.css`. The OG image template (`_og_image.html`) preserves its previous muted-roof aesthetic via a scoped `.banner .tower { --tower-ink: #e8dec4; --tower-roof: #4a4338; }` rule. New dark-surface placements should reuse this pattern instead of re-introducing hex.
  - **Refinement audit — four passes** (PRs #12, #14, #15, #16): tetris span variation in `_event_card.html` (image cards now use `s3/s4/s5` array keyed by `e.id % 12`); decoration scaling (tape/pin gated on `e.id % 10 < 7` so ~30% bare); ribbon nav functional anchors with non-functional placeholders removed (Drag/Live music/Food/About are gone from the markup — re-add only when destinations exist); breadcrumb home-detection in `_breadcrumb.html` (`is_home` adds `.crumbs.home` class so the trail-only-wordmark dupe row is hidden on home); `.here` highlighter gradient pinned to baseline (`to top` 0/35%) so it doesn't clip ascenders; HH live-row red inset accent; HH count "X today" instead of "X listed" + dropped misleading red bullet; sidebar `.side.ad` rotation moved from inline style to CSS rule; footer restructured with brand voice line in the brand column (Fraunces italic 17px, no opacity); `_recurrence_sort_key()` adds `start_time` as secondary sort so regulars within a day land in chronological order; three event-detail elements demoted from italic-900 to italic-700 (`.facts dd`, `.venue-name`, `.miniev .dt` — all under the spec's 26px threshold); card share button hide-until-hover with `@media (hover: none)` touch fallback; `.f.s3 .img` halved dot tile size for denser texture on small spans. Removed `--riso-blue-2` and `--riso-yellow-2` from `:root` (defined but never used). Audit-claim corrections worth remembering: marquee was already enabled, regulars were already grouped by day, sidebar tape colors were already correct, poster fallback was already implemented.
  - **Static OSM maps per business** (PR #17): `scripts/build_business_maps.py` (hand-rolled tile stitcher, no new pip deps) generates 800×540 WebP at zoom 19 to `public/images/maps/{slug}.webp` with riso-red marker centered on the venue's `lat`/`lng`. 23 maps committed (~1.1 MB total). The venue card on event detail pages (`_event_detail.html` line ~233) now renders `<img src="/images/maps/{slug}.webp">` instead of the cork-grid + ★ placeholder. CSS placeholder (`.map::before` grid, `.map::after` ★, `.map .pin-label`) removed; `.map` keeps its frame + aspect-ratio + `.map img` rule. Deferred audit items still on the table: §14 classifieds copy, §17 mono-on-cork at 9–10px, §18 mobile rework, §19 perf (font subsetting, spotlight image preload race).