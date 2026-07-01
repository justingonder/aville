# CLAUDE.md

Context for Claude Code sessions in this project. Read this first before making changes.

## Project purpose

An event aggregator for Andersonville, Chicago. Pulls events, happy hours,
and specials from a curated list of local business websites and publishes
them as a static site at aville.net. Owner: Justin Gonder. See README.md
for the full architecture diagram and setup instructions.

## Current scope (deliberately small)

- ~26 businesses as of 2026-06-04 (actively growing via discovery sessions), mix of website structures
- Websites are the primary source; an experimental Instagram channel also ships events (per-business `instagram_id` field → manual scrape-JSON → `scripts/ingest_instagram.py`, `source_type='instagram'` provenance, quarantine/promote via `PUBLISHED_SOURCE_TYPES`)
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

**Companion files:** Project context that doesn't need to load every session lives in sibling files — read on demand:
- [`handoffs.md`](handoffs.md) — most recent session entries, top-of-file
- [`docs/businesses.md`](docs/businesses.md) — per-business extraction quirks (Replay, Atmosphere, Vincent, Hopleaf, SoFo Tap, Chicago Magic Lounge, Carol's Pub)
- [`docs/drift-log.md`](docs/drift-log.md) — session-by-session reconciliations + structural project changes
- [`docs/shipped.md`](docs/shipped.md) — implementation notes for shipped features (cache rules, JSON-LD, OG images, hours capping, LocalBusiness pages, llms.txt + Tier 1 agent discovery, Phase 1+2 design handoff, flyer-ingestion CLI, etc.)
- [`docs/superpowers/specs/`](docs/superpowers/specs/) + [`plans/`](docs/superpowers/plans/) — design docs for in-flight work

**Where new content goes (keep CLAUDE.md lean):**
- Always-loaded working brief — conventions, audience, gotchas, decision rules, deferred work — stays here.
- Implementation notes for *shipped* features → `docs/shipped.md`. CLAUDE.md gets at most a one-line pointer.
- Per-business idiosyncrasies → `docs/businesses.md`.
- Session reconciliations / structural project changes → `docs/drift-log.md`.
- Open issues, follow-ups, future work → keep terse here; full design context goes in `docs/superpowers/specs/` or PR descriptions.

**Keep README.md current.** `README.md` is the reader-facing onboarding + architecture doc (audience: a human, possibly Justin months from now, or a collaborator). Whenever a change alters something it documents — the architecture/pipeline shape, project layout, scope, business count, setup/quickstart steps, deploy workflows, or required secrets/env vars — update README.md in the same change. Unlike CLAUDE.md (working brief for Claude) it should stay accurate but not exhaustive; cross-reference it against the code, and where they disagree the code wins.

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
  - **Change detection (cost-saving, shipped 2026-07-01).** Before each page's
    Claude call, `pipeline.run()` computes `compute_input_signature(page_text,
    kept_image_urls)` (`src/db.py`) — a hash of exactly what the multimodal
    request would send — and compares it against the last *successful* run via
    `last_good_signature(conn, page_url)` (reads `fetch_log.input_signature`,
    added 2026-07-01). On a match it skips the paid extraction, logs a
    `"skipped: inputs unchanged"` fetch_log row, and leaves existing events
    untouched (no stale-marking). Signatures hash the model *inputs*, NOT raw
    HTML, so volatile page junk (CSRF tokens, cache-busters, Playwright nonces)
    doesn't cause false "changed" hits. Failed extractions store a NULL
    signature so the page keeps retrying. `FORCE_EXTRACT=1` bypasses the skip
    (use after prompt/model changes or when backfilling). The older
    `source_page_hash` column (raw-HTML hash on each event row) is unchanged and
    still stored for audit. Tests: `scripts/test_change_detection.py`.
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

- Full Meta-API Instagram/Facebook integration (deferred — requires Meta App
  Review + per-business opt-in). NB: a lightweight experimental IG channel DID
  ship (manual scrape-JSON → `scripts/ingest_instagram.py` → `source_type='instagram'`
  rows); that is separate from the API integration deferred here.
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
- Neighborhood highlights (featured-header / advisory / curated specials): `config/highlights.yaml` — a timeline of multiple neighborhood-scale events (Midsommarfest, Wine Walk, Halloween, …). The build auto-selects the nearest displayable highlight and resolves its phase (countdown → live → off) via `_highlight_state()` / `_highlight_phase()` / `_resolve_highlight()` / `_load_highlights()` in `site_builder.py`. Each entry carries `starts_on` / `ends_on` / `ends_at` / `countdown_days`, rich header copy (headline, eyebrow, seal, meta), the "regulars may pause" advisory, and a hand-curated specials module. Header renders in the marquee slot (`data-highlight-header`); exact Sunday-night cutoff is a client-side Chicago-time gate in `index.html` + `_happy_hours_page.html`. Edit YAML → **Site rebuild**; `enabled: false` per highlight to retire. Admin curation shipped too (`templates/admin/highlight_*.html`). **Shipped 2026-06-04**, generalizing the old single-event Midsommarfest header. Spec: [`docs/superpowers/specs/2026-06-04-neighborhood-highlights-design.md`](docs/superpowers/specs/2026-06-04-neighborhood-highlights-design.md). Superseded: `config/festival.yaml` + `_festival_state()` never existed in code; [`docs/midsommarfest-timing.md`](docs/midsommarfest-timing.md) is the pre-generalization design (carries a note pointing here).
- Schema: `src/db.py` (SCHEMA constant). Migrations run: `ADD COLUMN featured INTEGER` (2026-04-19), `ADD COLUMN performers TEXT` (2026-04-21), `ADD COLUMN ends_on TEXT` (2026-04-21), `ADD COLUMN price_short TEXT` (2026-04-29 — short-form happy-hours card price; nullable; Phase 1 falls back to `price_info[:14]`, Phase 2 will backfill via Haiku), `ADD COLUMN locked_fields TEXT` (2026-05-10 — JSON array of field names the admin has marked "researched, don't overwrite during extraction"; `upsert_event` skips listed fields on UPDATE and `mark_missing_events_stale` skips events with `status` locked; see `LOCKABLE_FIELDS` constant in `src/db.py`), `ADD COLUMN alternate_sources TEXT` (2026-05-10 — JSON array of `{url, found, added_at}` recording where manual research came from; audit-only, pipeline ignores it), `ADD COLUMN starts_on TEXT` (2026-05-11 — symmetric counterpart to `ends_on`; recurring events with `starts_on > build_date` are filtered from all display buckets; `_is_unstarted_series` + `_series_inactive` in `site_builder.py`), `ADD COLUMN ticket_url TEXT` (2026-05-11 — advance-purchase URL; renders "Buy tickets ↗" on event detail page; in `LOCKABLE_FIELDS` so extraction can't clobber it later), `ADD COLUMN source_type TEXT NOT NULL DEFAULT 'website'` (2026-06-07 — provenance: `'website'` | `'instagram'`; gates site visibility via `PUBLISHED_SOURCE_TYPES`, namespaces `match_key`, and `DELETE FROM events WHERE source_type='instagram'` nukes the IG channel). If the schema gets out of sync, delete `data/app.db` to start over.
- HTML templates: `templates/index.html` (main page), `templates/_event_card.html` (card partial), `templates/_event_detail.html` (per-event static page with OG tags), `templates/_tower.html` (water tower SVG macro, `cork`/`og` variants).
- CSS: `styles/index.css` and `styles/event.css` (source files). At build time, `_publish_css()` in `site_builder.py` hashes content and writes `public/{name}.{hash8}.css`. Never edit `public/*.css` directly — edit the source in `styles/`.
- Favicon/icons: `scripts/build_icons.py` (Playwright-based, run manually when icon source changes). Outputs: `favicon.svg`, `favicon.ico`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, `site.webmanifest` in `public/`.
- Static business maps: `scripts/build_business_maps.py` (httpx + Pillow, no new pip deps; hand-rolled OSM tile stitcher). Run manually when a business's `lat`/`lng` changes or a new business is added. Generates 800×540 WebP at zoom 19 with riso-red marker + "© OpenStreetMap contributors" attribution, output to `public/images/maps/{slug}.webp`. Idempotent (skips files that already exist; `--force` regenerates; optional positional `slug` arg targets one business). Sends a descriptive User-Agent and waits 0.5s between businesses to respect the OSM tile usage policy. Maps are committed to git (static content — businesses don't move) and consumed by `templates/_event_detail.html` in the venue card.
- Local admin UI: `scripts/admin.py` (Flask, runs at `localhost:5050`). Form-driven editing of `businesses.yaml` / `businesses_pending.yaml` / `tags.yaml` / `data/app.db` events with field validation, diff preview, and auto-commit per save (`git commit --only`, no auto-push). Per-field `🔒` locks on events preserve manual research through extraction (see `LOCKABLE_FIELDS` in `src/db.py`). Event-edit form exposes: standard fields + `starts_on` / `ends_on` (series gating), `ticket_url` (renders "Buy tickets ↗" on detail page; lockable), Image source URL (paste a URL → downloaded, optimized to WebP/1200px/srcset variants via `store_event_image_from_url` in `src/images.py`; image columns lockable as a coupled pair), `alternate_sources` (audit-only `URL | what was found` lines), and a "Duplicate event" button that clones a row with " (copy)" appended to title — use this to split a recurring show into per-schedule variants (e.g. CML 7pm weekdays + 7pm/10pm weekends). Dashboard at `/` doubles as a session console: live git/gh status banners (working tree, origin sync, extraction running) + two publish buttons: "Publish & deploy" (full Site rebuild, ~5 min, regenerates OG share-preview images) and "Quick publish (~90s)" (Site rebuild (fast), skips OG, ~30-60s). Run-status polling and computer-freeze recovery via `data/admin_state.json` (gitignored; tracks last workflow choice so the panel re-attaches correctly after a reload). Localhost-bound — refuses non-loopback. Round-trip preserves YAML quote/block styles and ISO datetime tz suffixes. `init_db()` runs on admin startup so admin-only migrations apply cleanly to a DB that hasn't seen an extraction. Day-to-day workflow guide in [`docs/admin-guide.md`](docs/admin-guide.md); full implementation notes in [`docs/shipped.md`](docs/shipped.md). Adds `flask` + `ruamel.yaml` to `requirements.txt` (dev-only — admin doesn't deploy).

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
- **`build_date` is shifted back one day during 00:00-04:00 Chicago time** (`build_site()` in `site_builder.py`). Humans still call Sunday at 00:30 Mon "Sunday night," not Monday — bars run until 2-3am. The shift makes the whole bucketing system perceive late-night builds as "still last night," so "Tonight" lists yesterday's still-going events and "This week" starts at tomorrow. Pair this with `_is_past_today()` which filters events whose `end_time` for build_date has already elapsed (handles midnight-crossing via the same `crosses_midnight = end <= start` check the spotlight JS uses). Conservative on missing data: events without both start_time and end_time are always shown. Side-effect: in the shifted window, "This weekend" is empty and "Next weekend" labels the upcoming Fri-Sun; defensible but watch in real use.
- **Tonight bucket = events that haven't ended yet, not just events that fire today.** A weekly:sunday event with end_time 14:00 disappears from "Tonight" at 14:00 Sunday (built-time check via `_is_past_today`). Static-site staleness applies: the page is rendered at one moment; visitors arriving later see whatever the most-recent build computed. Cloudflare full-purge on every workflow run is what keeps this bounded.
- **`this_week_by_day` (homepage) groups dated + recurring events per day in the Mon-Thu window** (`site_builder.py`, line ~1556). Multi-day recurrences (e.g. `weekly:monday-thursday`) appear once under each day they hit. The original "This week" was dated-only, which silently hid all Monday recurring events on Sunday eve until 2026-05-11. If you add a new section to the homepage, mirror this pattern rather than the dated-only `this_week_events` shape — the latter is preserved only as a counter source.
- **Scheduled extraction vs. local pushes race condition** — the Actions workflow does `git pull --rebase origin main` before pushing the updated DB, so concurrent local pushes during a run won't cause the DB commit to fail. **But** if you hold a *local* commit that edits `data/app.db` (e.g. a manual `UPDATE`) and the bot has pushed a fresh extraction, `git rebase` hits a **binary conflict** on `data/app.db`. Resolve by taking origin's freshly-extracted DB as the base (`git checkout origin/main -- data/app.db`) and **re-applying your targeted change on top** (re-run the `UPDATE`), then `git add` + `git rebase --continue` — never keep either side wholesale, or you lose the extraction or your edit.
- **Built `public/index.html` renders unstyled over `file://`** — assets are referenced root-absolute (`href="/index.HASH.css"`), which `file://` resolves against the filesystem root and can't find. To preview/screenshot a local build, serve it over HTTP: `python3 -m http.server -d public 8731` then load `http://localhost:8731/`. Production serves over HTTP so this only bites local previews — a plain-text render is this bug, not a broken build.
- **Playwright user-agent triggers anti-bot protection** on some sites — `playwright_session()` now uses a real Chrome UA (`PLAYWRIGHT_USER_AGENT` in `fetcher.py`) instead of the `AvilleBot` string. The bot UA is still used by plain httpx `fetch_html` calls, but Playwright needs the real UA so sites don't fingerprint it as a headless bot. Discovered 2026-04-20 when Nobody's Darling returned empty results despite Playwright fetching the page.
- **Businesses in `config/businesses_pending.yaml`** are NOT scraped by the pipeline until promoted to `businesses.yaml`. The test script (`scripts/test_extraction.py`) accepts `include_pending=True` via `load_businesses()` so you can test pending entries without promoting them. Discovery state tracked in `docs/business-discovery/progress.json`.
- **Manual-only businesses have no `pages:` key.** A venue with nothing scrapeable (e.g. Lonesome Rose) is added with NO `pages:` entry — it carries only hand-entered specials, and a 0-event scrape would mark those stale. The pipeline skips scraping such venues but still upserts + renders them. Any code that iterates a business's pages MUST use `biz.get("pages") or []`, never bare `biz["pages"]` (a `KeyError: 'pages'` crash at `pipeline.py:156` took down the daily run on 2026-06-05). All current consumers (`admin.py`, which `del`s the key when empty; `ingest_flyer.py`; backfill/metadata scripts) already follow this.

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
  → expired". Note `stale` still **publishes** (`all_active_events` is
  `status IN ('active','stale')`), though past dated events are filtered from
  homepage buckets by `_is_past_today` regardless of status. ~212 stale past
  dated rows as of 2026-06-08 — the deferred bulk cleanup.
- Whether to deepen the Instagram channel (experimental scrape-JSON ingest
  shipped 2026-06-07; `--quarantine` flag added 2026-06-08 — new events land
  `status='rejected'` for review, existing rows keep their status). Still open:
  live re-scrape cadence + auto-expiry of past IG dated events. Full Meta-API
  integration remains no-plan.
- **Holiday-events representation** — events tied to specific holidays
  (Mother's Day markets, Pride events, Christmas pop-ups, etc.) probably
  want different surfacing rules than ordinary dated events: they're
  worth highlighting earlier (people plan ahead for holidays), they
  often have a "season" feel (Pride = month of June), and a generic
  "holiday" tag may be too coarse. Flagged 2026-04-24 when a Mother's
  Day market flyer triggered the question. Revisit once we have a few
  more holiday-tied events in the DB to look at concretely.

### Lower priority / future pipeline improvements

Implementation notes for shipped features (cache rules, JSON-LD, OG images, hours capping,
LocalBusiness pages, llms.txt + Tier 1 agent discovery, Phase 1+2 design handoff, flyer
ingestion CLI, etc.) live in [`docs/shipped.md`](docs/shipped.md). Read that when revisiting
any of those systems. The list below is genuinely-deferred work + actionable follow-ups
on already-shipped features.

**Pre-launch critical:**

- **Mobile LCP optimization** (Shipped 2026-06-04) — Solved LCP delay by pre-rendering spotlight cards on the server (commit `40015b58`) and preloading the first image-bearing card (LCP candidate) dynamically in the `<head>` of the page using `<link rel="preload" as="image" imagesrcset="...">` for both the homepage and event details pages. See [`docs/shipped.md`](docs/shipped.md).

**Flyer-ingestion pipeline follow-ups** (implemented 2026-04-27; pending end-to-end
validation; full pipeline writeup in `docs/shipped.md`):

1. Web search prompt sometimes returns Eventbrite *discover* listing pages instead of
   specific event URLs (observed 2026-04-27 on Guesthouse "Wander Home Holiday Market"
   flyer → returned `eventbrite.com/d/il--chicago/free--events/mothers-day/`). Tighten
   `search_for_event` prompt in `src/web_search.py` to prefer specific-event-page URLs
   over search/listing/discover URLs. Workaround: pass `--source-url <real_event_url>`.
2. `extract_events` `max_tokens=4096` can truncate JSON on event-dense pages (caught
   gracefully as `failed:extract-error`). Bump to 8192 OR trim page text more aggressively
   OR add a prompt instruction to extract only the seed-matching event.
3. **Multi-board / scene photos confuse seed extraction.** `extract_flyer_seeds` is
   designed for ONE flyer per photo (see `SEED_EXTRACTION_PROMPT` in `src/prompts.py`,
   "Return ONE JSON object"). A photo of two adjacent sandwich boards with storefront
   reflections + neon signage in frame returns `event_title=None, venue_name=None,
   seed_confidence='low'` — the model can't pick which board is "the flyer." Discovered
   2026-05-05 with Minyoli's `20260427_181631.jpg` (Daily Happy Hour board + Monday
   Senior Discount board side-by-side). Workaround used: encode the off-web event as a
   second hint in `businesses.yaml` so it lands via the standard /happy-hour extraction.
   Real fix paths: (a) crop the photo per-board before ingest; (b) extend the seed prompt
   to return an array of seeds per photo; (c) add a `--crop-each-board` mode to
   `ingest_flyer.py` that asks Claude to enumerate distinct flyers and processes each as
   a sub-photo.

**Design handoff Phase 1+2 follow-ups** (shipped 2026-04-29 / 2026-05-04; full writeup in
`docs/shipped.md`):

1. Two near-duplicate `_DAY_ORDER` / `DAY_ORDER` constants in `src/site_builder.py`
   (lines 30 and ~580). Maintenance hazard.
2. Dead `.top .crumbs` rules in `event.css` (~lines 49–50, 293–294) now that the inline
   `.top-row .crumbs` was removed.
3. Happening Now count text shows total `nowCards.length` including HH cards even though
   they're routed to the sidebar — slightly misleading in mixed-live state.
4. `price_short` column not in `upsert_event` INSERT/UPDATE (intentional Phase 2 deferral
   — touch-up needed when the backfill becomes part of the pipeline rather than a one-shot
   script).
5. Still deferred from Phase 2: manual `press[]`, `socials{}`, `branding_images[]`. Live
   JS recompute of "Open until X" pill (today server-rendered, goes stale within a day).

**Pipeline / extraction:**

- **Transient fetch retries** _(low priority)_ — `fetch_html()` / `fetch_bytes()` in
  `src/fetcher.py` have no retry on transient network errors. Observed 3
  `[Errno 104] Connection reset by peer` failures on `atmospherebar.com` out of 478 total
  fetches (99.4% success). Failures are logged and skipped; with `public/images/` tracked
  in git this no longer breaks CI. Likely fix: catch `httpx.RequestError` and retry 2–3×
  with exponential backoff.
- **Post-extraction day-of-week validation** _(low priority)_ — Claude sometimes
  miscalculates what day of the week a date falls on, producing a wrong
  `recurrence_pattern`. Add a check that compares each recurring event's first observed
  date against its `recurrence_pattern` day; flag mismatches rather than silently writing
  wrong data. Discovered 2026-04-19 when BEARAOKE was extracted as `weekly:saturday` but
  is actually Sunday nights.
- **Post-extraction title validation** _(low priority)_ — Claude sometimes extracts the
  recurrence phrase as the event title when the source page has no clean separate title
  (e.g. Kopi Cafe event 236 came in as `title="First Wednesday of the Month"`, which is
  just restating `recurrence_pattern="monthly:1st-wednesday"`). PR #39 added a
  display-layer heuristic (`_title_echoes_recurrence` in `src/site_builder.py`) that
  compacts these in the venues sidebar, but the stored title is still bad data and shows
  up verbatim on event detail pages, OG tags, etc. Add a post-extraction check using the
  same heuristic — flag affected events for hand-edit + lock via the admin UI rather than
  rewriting silently (we don't have a confident substitute title). Discovered 2026-05-10.
  Related to the broader pattern: extraction faithfully echoes whatever surface form the
  source page used, even when it's redundant with structured fields (also see the
  CSV-vs-range recurrence work in PRs #36–#38).
- **All-day specials missing startDate in Event JSON-LD** _(low priority)_ — recurring
  events without a `start_time` (e.g. all-day drink specials) emit no `startDate`, flagged
  by Google's Rich Results Test. ~14/101 active recurring events affected. Likely fix: when
  `start_time` is null, default to the business's opening time from the `hours:` block in
  `config/businesses.yaml`. Extend `_apply_hours_cap()` in `pipeline.py`. Watch for events
  that genuinely span the whole day vs. events where missing time means "we don't know."
- **Nav-link discovery for new special pages** _(low priority)_ — businesses occasionally
  publish one-off event pages at new URLs (e.g., SoFo Tap's `/events-2` for IML 2026).
  Mitigations: (a) parse homepage nav links each run + diff against `businesses.yaml`;
  (b) fetch `sitemap.xml` per business and diff against known pages.

**AI / LLM discovery — Tier 2** _(low-medium priority; Tier 1 shipped 2026-04-23, see
`docs/shipped.md`)_ — follow-ups in rough order of value:

- **ICS calendar feeds** — per-event `.ics` plus a site-wide feed. Big "add to calendar"
  win for assistant flows. Stdlib string formatting works (RFC 5545 is forgiving).
- **JSON Feed of upcoming events** at `/feed.json`. JSON Feed 1.1 is cleaner than RSS for
  LLM ingestion.
- **Markdown-for-Agents via Cloudflare Worker** — dynamic `Accept: text/markdown`
  negotiation. Static `.md` siblings + `<link rel="alternate">` already cover the same
  goal; only worth doing if agents ignore the alternate. Docs:
  https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/
- **Read-only MCP server for events** — `list_events_happening_now`, `list_events_by_day`,
  `find_events_by_tag`, `get_business_info`. Could live as a Cloudflare Worker. Defer until
  there's a concrete use case (e.g. a local assistant integration).
- **Machine-readable sitemap-of-markdown** at `/sitemap-md.xml`. Very low priority; existing
  sitemap + `<link rel="alternate">` convention already covers it.

**Per-business page polish — deferred follow-ups** _(low priority, per-business pages
shipped 2026-04-23):_

- **Per-business OG social-share images** — every business page currently uses
  `og-home.jpg`, so every iMessage/Slack share looks identical. `_business_schema()`
  already picks the most recent flyer with an image; the same source works for the OG meta
  tag.
- **Shared spotlight-JS module** — the "Happening right now" IIFE is duplicated between
  `templates/index.html` and `templates/_business_detail.html`. Worth extracting to
  `public/spotlight.js` if a third page ever needs the logic or implementations drift
  further.
- **Homepage "See all venues →" link** pointing at `/business/` — the venue sidebar shows
  20+ individual venues but no direct path to the directory landing.
- **Plan doc masthead-guard footnote** — Task 6 of the per-business-pages plan listed
  `{% if biz.metadata and biz.metadata.description %}` as the masthead-address guard. The
  committed template uses `{% if biz.address %}` (correct). Don't re-introduce the bug if
  anyone re-runs the plan.

## Business notes

Per-business idiosyncrasies that aren't derivable from `config/businesses.yaml` or
the site structure alone live in [`docs/businesses.md`](docs/businesses.md). Read it
before touching extraction logic for: Replay Andersonville, Atmosphere, Vincent,
Hopleaf, SoFo Tap, Chicago Magic Lounge.

## Deployment

Extraction runs on GitHub Actions daily at 11:00 UTC / 6:00 AM Chicago time. Deploys to aville.net via rsync to Namecheap shared hosting.

The "Park site (temporary takedown)" workflow exists to wipe the server and serve `park/index.html` (used briefly 2026-05-01 → 2026-05-03 during `aville.com` bidding; site is live again as of the weekend). Re-park with `gh workflow run "Park site (temporary takedown)"`; restore by running "Site rebuild" or waiting for the next scheduled run.

### Triggering workflow runs manually

Four workflows exist:
- **"Scheduled extraction + deploy"** (`.github/workflows/scheduled.yml`) — full pipeline: fetch, extract, build, deploy. Burns API credits.
- **"Site rebuild"** (`.github/workflows/site-rebuild.yml`) — build + deploy only, no extraction. Use this for template/CSS/site_builder.py changes. ~5 min wallclock (Playwright install + per-event OG image regeneration via screenshot is most of the cost). **`timeout-minutes` was bumped 5→25 on 2026-06-04** — at ~488 events the clean-checkout OG regen (OGs are gitignored, so CI rebuilds all of them) exceeded the old 5-min cap and the job was canceled before deploy. 25 matches the scheduled deploy. The bumped value is committed but hadn't been exercised by a full run as of that date.
- **"Site rebuild (fast)"** (`.github/workflows/site-rebuild-fast.yml`) — same as Site rebuild but passes `--skip-og` and skips Playwright install. ~30-60s wallclock. Use for content-only edits where the iMessage/Slack share-preview OG can lag a day. Added 2026-05-11. rsync excludes `images/og/` so it doesn't wipe server-side OGs the full workflow has previously deployed. Per-event OG regeneration on the next full run is gated by a `.key` sidecar hash of `(title, business, image, when, variant)` — title/image edits trigger regen automatically, no manual cache-bust needed.
- **"Park site (temporary takedown)"** (`.github/workflows/park-site.yml`) — wipes the server and deploys `park/index.html`. Manual-only. Idempotent. Added 2026-05-01.

**Decision rule — which workflow to trigger after a session:**
- Pipeline code, prompts, config, extraction logic changed → run **Scheduled extraction + deploy**
- Templates, CSS, or `site_builder.py` changed AND the share-preview OG matters (titles, images, dates that would land on iMessage) → run **Site rebuild**
- Pure content edits via admin (data-only DB changes) → run **Site rebuild (fast)** — the OG cache invariant catches title/image changes on the next full run anyway
- Docs-only changes → no workflow needed

**`gh` CLI status as of 2026-04-19:** Installed and authenticated. Trigger runs with:
```bash
gh workflow run "Site rebuild"
gh workflow run "Site rebuild (fast)"
gh workflow run "Scheduled extraction + deploy"
```
To watch the run: `gh run watch <run-id>` (the run URL is printed after `gh workflow run`).

**Important:** Always `git push` before triggering a workflow run. `gh workflow run` dispatches against the current HEAD of the remote — if your commits haven't been pushed yet, the workflow runs on old code and deploys stale output.

### Analytics

Analytics is **Google Analytics (GA4)**, measurement ID `G-2JVRVTGFNE`. Dashboard: https://analytics.google.com/

The `gtag.js` snippet lives in the `<head>` of every standalone page template: `templates/index.html`, `templates/_event_detail.html`, `templates/_happy_hours_page.html`, `templates/_business_detail.html`, `templates/_business_index.html`. Do not add it to true partials (`_event_card.html`, `_breadcrumb.html`, `_tower.html`) or to OG-image templates.

**Custom events:** GA4 custom event tracking via `gtag('event', 'event_name', { param: 'value' })`. Call this anywhere in JS to track interactions — the snippet in `<head>` already defines the global `gtag` function. Guard the call with `if (typeof gtag === 'function')` so pages that load before the async script is ready don't throw.

Currently instrumented:
- `share` — fires on every share button click with `{ event_slug, business }`. Present in both `index.html` and `_event_detail.html`. In GA4, view under Engagement → Events; filter/group by `event_slug` or `business` to see a share leaderboard (custom dimensions must be registered in GA4 admin first if you want them as report dimensions).

## Quick reference

**Always use `python3`, not `python` — `python` is not aliased on this machine.**

Run the pipeline:           `python3 scripts/run_extraction.py`
Test a single URL:          `python3 scripts/test_extraction.py <slug> <url>`
Rebuild the site:           `python3 scripts/build_site.py`
Wipe and start over:        `rm data/app.db && python3 scripts/init_db.py`
See active events:          `sqlite3 data/app.db "SELECT title, kind, recurrence_pattern FROM events WHERE status='active'"`
List series candidates:     `python3 scripts/list_series_candidates.py`

## Drift log

Session-by-session record of CLAUDE.md ↔ code reconciliations and structural project
changes lives in [`docs/drift-log.md`](docs/drift-log.md). Append a new entry there
at the end of any session that changes how the project actually works.