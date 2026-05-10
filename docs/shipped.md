# Shipped features — implementation notes

Detailed implementation notes for shipped features that previously lived inline in
`CLAUDE.md`. Extracted on 2026-05-05 to keep the always-loaded project brief lean.
Read this when modifying or revisiting any of these systems — the rationale, the
gotchas, and the why-it-works-this-way are here, not in `CLAUDE.md`.

Each section preserves the original prose verbatim. Dates reference when the work
was shipped, not when the entry was extracted to this file.

---

## Mobile LCP — three fix paths considered (deferred, 2026-04-22)

Mobile Lighthouse LCP plateaued at ~3.8s on Slow 4G after shipping image+caching wins
(2026-04-22 session). Root cause is structural: the LCP element is the spotlight clone
built by the JS IIFE at the end of `templates/index.html` (after the entire 251 KB body
parses). The browser can't start fetching the LCP image until JS runs and inserts the
cloned `<img>`. Cloudflare HTML caching saved ~700ms on the HTML round-trip but the
JS-built LCP path is the next ceiling.

**Why this matters for Midsommarfest:** Lighthouse's Slow 4G profile is exactly the
cell-tower congestion scenario — thousands of phones in a few-block radius. Real users
at the festival will see worse than the synthetic 3.8s. If LCP slips past ~5s on real
devices, bounce rate spikes and the launch impression suffers.

**Three fix paths, ranked by impact + cost:**

1. **Lazy-render below-fold cards** (best, expensive): initial HTML emits only the
   spotlight + first 6–12 cards; the rest hydrate via IntersectionObserver as the user
   scrolls. Cuts initial HTML from 251 KB → ~50 KB → faster parse → faster everything.
   Requires careful work because existing JS (`isHappeningNow`, search/filter,
   share-leaderboard tracking) currently queries `document.querySelectorAll('.f[...]')`
   over the full DOM. A lazy-render pass needs to either (a) keep all cards in DOM but
   defer image loading + heavy work, or (b) maintain an in-memory index of all events
   and re-render on scroll.
2. **Build-time spotlight prerender** (medium impact, UX cost): pre-compute "happening
   now" at build time, render in static HTML so the LCP image is eager-discoverable from
   initial parse. LCP could drop to ~1.5–2s. Cost: spotlight is stale by up to 24h since
   extraction runs daily — bad for the "Already Out" persona who wants real-time. Could
   mitigate with hourly rebuilds (24× the API cost) or a spotlight-only sub-build that
   doesn't re-extract.
3. **Inline the most-likely LCP image as base64 in HTML** (clever, fragile): predict
   the live event at build time, inline its image bytes. Eliminates the request entirely.
   Predicted-wrong = wasted bytes but no visual harm (JS still picks the right event).
   Edge cache holds for an hour so prediction accuracy degrades over the cache window.

Discovered 2026-04-22. Decision deferred to closer to Midsommarfest launch — revisit
before shipping the festival announcement.

---

## Flyer-ingestion pipeline (2026-04-27)

Standalone CLI (`scripts/ingest_flyer.py`) that takes phone-camera photos of paper flyers,
uses each flyer as a SEED for a web search, finds an authoritative source via Claude's
`web_search_20250305` tool ranked against `config/web_search_allowlist.yaml`, and runs the
existing `extract_events()` pipeline on that source — with the flyer photo as multimodal
cross-verification (`cross_verify_image` kwarg, see `src/extractor.py`). Per-photo 7-step
pipeline (seed → resolve business → DB dedup → web search → auto-add new business → full
extraction → upsert/enrich). Dedup-match prompt offers `[s]kip / [e]nrich / [p]roceed-as-new
/ [q]uit`. New businesses are auto-added with `extract_business_metadata.py` +
`geocode_businesses.py` invoked as subprocesses. Sidecar log per run at
`<dir>/.ingest_log.json` for resumability + per-walk summary. Flags: `--dir`,
`--source-url` (manual override), `--dry-run`, `--seed-only`, `--force`.

- Spec: `docs/superpowers/specs/2026-04-24-flyer-ingestion-pipeline-design.md`
- Plan: `docs/superpowers/plans/2026-04-27-flyer-ingestion-pipeline.md`
- Unit tests: `scripts/test_ingest_helpers.py`, `scripts/test_web_search.py`,
  `scripts/test_seed_extraction.py`, `scripts/test_extract_events_compat.py`
  (17 helper assertions all green).

Implemented 2026-04-27 on branch `flyer-ingestion-design`; pending end-to-end validation
against a real walk batch. Active follow-ups remain in `CLAUDE.md`.

---

## Design handoff session 3 — Phase 1 (2026-04-29) + Phase 2 (2026-05-04)

Three coordinated design features lifted from designer's handoff package at
`/Users/jgonder/Downloads/design_handoff_session3/`:

1. **Happy-hours sidebar card (A.1.B "clock strip")** — homepage sidebar component listing
   today's happy hours sorted by start time, with `.live` modifier for currently-active
   rows (yellow clock pill, red dot prefix). Server-rendered via
   `_select_today_happy_hours()` in `src/site_builder.py` from active recurring events
   tagged `happy-hour` whose recurrence pattern matches today. Client-side spotlight JS
   (`templates/index.html` IIFE) implements the **three-state interplay** with the
   main-column "Happening Now": (a) mixed-live → spotlight gets non-HH cards only,
   sidebar visible with `.live` rows highlighted; (b) HH-only-live → all-cards in
   spotlight, sidebar hidden so data isn't shown twice; (c) nothing-live → both hidden.
   Suppression set switched from `nowIds` to `spotlightIds` so HH cards filtered OUT of
   spotlight remain visible in the Regulars section.
2. **Stamped-dateline breadcrumb (B.1.B)** — new partial `templates/_breadcrumb.html`
   rendered above the masthead on home / business / event / business-directory pages.
   Replaces the old inline `.crumbs` markup in `.top-row` on biz/event templates. 3-step
   responsive dateline (full ≥900px → compact 640–899px → hidden <640px) via nested
   `<span class="dl-extra">` / `<span class="dl-sep">`. `data-short` attribute on parent
   crumbs for sub-720px collapse via JS IIFE inlined on each page. The `.here.home`
   modifier suppresses the yellow underline on the homepage's single-item trail.
3. **Editorial business hero (C.1)** — replaces `<header class="masthead-biz">` block in
   `templates/_business_detail.html`. Magazine-style: kicker line (mono blue uppercase:
   `{type} · {street_address} · Andersonville`), 88px Fraunces 900 italic h1, optional
   italic lede (Phase 1: only if `tagline` or `vibe_quote` set, neither populated yet),
   action row with Call / Website ↗ / Map ↗ buttons + `Open until X` yellow live pill
   (server-computed from `biz.hours[<3-letter-day>]`), tag chips (first chip blue `.hl`),
   3-up image strip. **Hero strip placeholder fallback:** when `branding_images` < 3,
   fill remaining cells with typographic blue panel (Fraunces italic pull quote + mono
   `— hero photo placeholder` annotation). Phase 1 ships with 0 curated `branding_images`
   — every business renders 3 placeholders by design (deliberately calls out the gap;
   pressures curation).

**Approach (Phase 1):** full superpowers brainstorm → spec → 14-task plan → subagent-driven
execution with two-stage review per task. Lighter-touch reviews on TDD helper tasks (Tasks
2–6); full reviews on integration tasks (7, 8, 11, 12). Final cumulative review caught 3
bugs per-task reviews missed (day-key mismatch on "Open until X" pill, `.kicker::before`
red bar inheritance, missing `#regulars` anchor). 16 commits total.

**5 helpers added to `src/site_builder.py`** with 36-assertion test file at
`scripts/test_session3_helpers.py`:

- `_format_clock_pill(start, end)` — `'16:00','18:00'` → `'4–6'` (en-dash; drops `:00`
  minutes).
- `_format_window_meta(pattern)` — `'daily'` → `'Daily'`; `'weekly:M-F days'` → `'M–F'`;
  `'weekly:tue-fri'` → `'Tue–Fri'`; `'weekly:sun'` → `'Sundays'`.
- `_select_today_happy_hours(events, build_date)` — filter + sort + enrich.
- `_format_open_until(hours_str, now)` — Chicago-time-aware; midnight-cross handling;
  returns `None` when closed.
- `_derive_business_type(category, display_type)` — maps category → spec-allowed type
  (`Bar`/`Restaurant`/`Cafe`/`Shop`/`Venue`/`Service`); `display_type` overrides; raises
  ValueError on invalid (build fails loudly on YAML typos). Mapping: `bar→Bar`,
  `restaurant→Restaurant`, `cafe→Cafe`, `theater→Venue`, `museum→Venue`.

**New optional YAML fields on businesses** (Phase 1 consumes only the first two; Phase 2
backfills the rest):

- `display_type` — override capitalized `category`. Allowed:
  `Bar`/`Restaurant`/`Cafe`/`Shop`/`Venue`/`Service`.
- `short_name` — breadcrumb `data-short` value (collapse below 720px). Currently set on
  `chicago-magic-lounge` only (`"Magic Lounge"`).
- `tagline`, `vibe_quote`, `about`, `press[]`, `branding_images[]`, `socials{}` — Phase 2
  fields.

Spec: `docs/superpowers/specs/2026-04-28-design-handoff-session3.md` (10 locked decisions
D1–D10). Plan: `docs/superpowers/plans/2026-04-28-design-handoff-session3-phase1.md`.

**Phase 2 (shipped 2026-05-04 as PRs #19 + #20):** Two backfill scripts:

- `scripts/backfill_price_short.py` — compresses `events.price_info` to ≤14-char
  `price_short` via Haiku (creative compression for long lists, e.g. multi-special string
  → `"6 specials"`). Idempotent. PR #19 also restores the HH card price column lost in
  PR #6's overflow hotfix; layout fix moves the price onto the meta-row line via flex
  `space-between` so long biz names don't push the card past its width. Empty-state
  renders `→` sentinel (template-side enrichment in `_select_today_happy_hours`; DB
  stores null).
- `scripts/backfill_editorial_copy.py` — drafts `tagline`, `vibe_quote`, `about` for each
  business via Haiku. New `EDITORIAL_COPY_PROMPT` in `src/prompts.py` with
  anti-fabrication + anti-marketing-voice rules. `_business_detail.html` `.biz-description`
  section now renders `biz.about` (split on `\n\n` for `<p>` per paragraph) with fallback
  to `biz.metadata.description`; the short metadata description is preserved for
  `<meta name="description">` and `og:description`.

**Phase 2 details:**

- `backfill_price_short.py` ran fast-path passthrough when `price_info` is already short
  enough; hard-truncate at 14 chars as a final safety net. Backfilled 13 of 22 active
  happy-hour rows; the other 9 have empty `price_info`.
- `backfill_editorial_copy.py` ran across all 23 businesses (~$0.50 in Haiku calls). YAML
  written as flat top-level fields per business: single-quoted strings for `tagline` and
  `vibe_quote`, literal-block `|` for `about` (paragraph breaks survive). Comment-preserving
  raw-text editor matches `extract_business_metadata.py`'s pattern.
- 8 `vibe_quote`s flagged for hand-editing in PR #20's description: Atmosphere, Bar Roma,
  Eli Tea Bar, Elixir, Nobody's Darling, Ranalli's, Sweet Hearts Bar, Uvae. Direct YAML
  edit is the workflow — `''` to escape apostrophes inside single-quoted strings;
  literal-block `|` indent rules apply for `about`. Validate with
  `python3 -c "import yaml; yaml.safe_load(open('config/businesses.yaml'))"`.

Active follow-ups (still deferred Phase 2 work; integration touch-ups) remain in
`CLAUDE.md`.

---

## Tower SVG dark-surface refactor (PR #8, 2026-05-03)

`templates/_tower.html` macro lost its `variant` parameter; the four ink-toned elements
(roof polygon, finial, rail rect, scaffolding strokes) now read off CSS custom properties
`--tower-ink` and `--tower-roof`. Light-surface defaults + `footer .tower, .tower-on-dark`
override added to both `styles/index.css` and `styles/event.css`. The OG image template
(`_og_image.html`) preserves its previous muted-roof aesthetic via a scoped
`.banner .tower { --tower-ink: #e8dec4; --tower-roof: #4a4338; }` rule. New dark-surface
placements should reuse this pattern instead of re-introducing hex.

**Known visual nuance:** the old `tower('og')` variant set `opacity=".5"` on two specific
tank-edge stroke lines for a soft etched feel. Not replicated in the CSS-variable approach
(would require fragile `:nth-of-type` selectors). Per-event OG images look slightly bolder
around tank edges than before. Easy to add back via CSS if the visual diff matters.

---

## Refinement audit — four PR batches (PRs #12, #14, #15, #16; 2026-05-03)

Pulled the second design handoff (`Aville Refinement Audit.html`) — a 20-section audit of
the live site against the Bulletin v2 + Session 3 + wordmark + tower handoffs. Triaged
with the user, batched by leverage, shipped four focused PRs:

- **Batch 1 (PR #12):** tetris span variation in `_event_card.html` (image cards now use
  `s3/s4/s5` array keyed by `e.id % 12`); decoration scaling (tape/pin gated on
  `e.id % 10 < 7` so ~30% bare); masthead + posted tightening (drop "Updated X" line from
  issue block, drop "Last sweep" from posted mono, tagline 20→22px italic 500, stamp tilt
  -2.5°→-3° + chunky red shadow); cap rotations to ±1.2° on rot-d/rot-e.
- **Batch 2 (PR #14):** ribbon nav wired (`#today`, `#weekend`, `#regulars`,
  `#happy-hours-card`) with the four non-functional placeholders (Drag/Live music/Food/About)
  removed from the markup — re-add only when destinations exist. Active "Tonight" pill
  inset 3px. Scroll-fade indicators promoted out of mobile-only. Marquee CTA mobile
  `white-space:nowrap`. Breadcrumb home-detection in `_breadcrumb.html` (`is_home` adds
  `.crumbs.home` class so the trail-only-wordmark dupe row is hidden on home). `.here`
  highlighter gradient pinned to baseline (`to top` 0/35%) so it doesn't clip ascenders.
  HH live-row red inset accent; HH count "X today" instead of "X listed" + dropped
  misleading red bullet. Sidebar `.side.ad` rotation moved from inline style to CSS rule.
- **Batch 3 (PR #15):** footer restructure — brand voice line ("A neighborhood thing,
  updated daily…") pulled out of the right-aligned `.sub` and into the brand column under
  the mini-mark, restyled as Fraunces italic 17px in full-opacity cork. Grid drops 3→2
  columns; nav right-aligned with new About + How this works anchors to classifieds
  paragraphs; nav opacity .75→.7, bottom bar .85→.92. Removed unused `--riso-blue-2` and
  `--riso-yellow-2` tokens (audit's "currently used for hover states" claim was wrong —
  verified via repo grep). Regulars sort: `_recurrence_sort_key()` already grouped by
  day-of-week (audit's "interleaved" claim was wrong); added `start_time` as secondary
  sort key. Regulars tape width `clamp(80px, 14%, 140px)`.
- **Batch 4 (PR #16):** italic-900 voice cleanup — three event-detail elements running
  italic 900 below the spec's 26px threshold demoted to italic 700 (`.facts dd`,
  `.venue-name`, `.miniev .dt`). Card share button hide-until-hover with `.f:hover` /
  `:focus`; `@media (hover: none)` keeps it visible on touch. `.f.s3 .img` halved dot tile
  size for denser texture on small spans.

**Audit-claim corrections worth remembering** (so future sessions don't waste cycles
re-auditing these):

- §1 Wordmark — already shipped 2026-04-21, audit acknowledged.
- §3 Tower — shipped earlier in this same session, audit acknowledged.
- §5 Marquee — audit said "currently shipping without it"; `config/marquee.yaml` is
  `enabled: true`. Marquee renders.
- §9 Poster fallback — already implemented in `_event_card.html` `{% else %}` branch.
- §10 Sidebar tape colors — already correctly mapped in CSS (search→yellow, ad→blue,
  info→cream, venues→red).
- §12 Regulars — already grouped by day-of-week server-side (audit reported "interleaved").
- §16 `--riso-blue-2`/`--riso-yellow-2` — defined in `:root` but never used; audit's
  hover-state claim was wrong.

**Deferred audit items still on the table:** §14 classifieds copy (content decision —
ship seeded items, hide section, or add a publisher-voice line); §17 mono-on-cork at
9–10px (impressionistic complaint; most small mono is on cards not cork; defer until
eyeballed live); §18 mobile (single-column flyer grid vs. shrunk-type 2-col — design call
worth a brainstorm with the phone view); §19 perf (Rubik Mono One subsetting, font
self-host, spotlight image preload race — measure first).

---

## Static OSM maps per business (PR #17, 2026-05-03)

`scripts/build_business_maps.py` (hand-rolled tile stitcher using `httpx` + `Pillow`, no
new pip deps) generates 800×540 WebP at zoom 19 to `public/images/maps/{slug}.webp` with
riso-red marker centered on the venue's `lat`/`lng` (already in `config/businesses.yaml`
from the prior `geocode_businesses.py` pass). 23 maps committed (~1.1 MB total at q=88,
method=6). Sends a descriptive User-Agent + 0.5s gap between businesses to respect the OSM
tile policy. Bakes "© OpenStreetMap contributors" attribution into each image.

The venue card on event detail pages (`_event_detail.html` line ~233) now renders
`<img src="/images/maps/{slug}.webp">` instead of the cork-grid + ★ placeholder. CSS
placeholder (`.map::before` grid, `.map::after` ★, `.map .pin-label`) removed; `.map`
keeps its frame + aspect-ratio + `.map img` rule. Iterated on zoom three times during
review (16 → 17 → 18 → 19) to find the venue-block-detail level. Maps are static content —
businesses don't move — so committed once and skipped on subsequent runs (analogous to
`scripts/build_icons.py` for favicons).

**Aesthetic note:** OSM tiles are colorful (parks green, water blue, multi-tone streets).
Doesn't perfectly match the cork/riso palette. Could be tuned via a CSS `filter:` if it
reads as visually loud — easy follow-up. Business-detail pages don't have inline maps yet;
same `<img>` pattern would drop straight in if we ever want a map next to the editorial
hero.

---

## LocalBusiness schema + per-business landing pages + breadcrumbs (2026-04-23)

23 canonical entity pages at `/business/{slug}/` with full `LocalBusiness` JSON-LD
(address, geo, telephone, priceRange, openingHoursSpecification from the existing
`hours:` block, sameAs, representative flyer `image`, up to 10 upcoming events) and
`BreadcrumbList` JSON-LD. Event detail pages gain a visible 3-level breadcrumb
(`Home › Business › Event`) and matching `BreadcrumbList` JSON-LD. Every business-name
mention on event cards + detail pages (top-bar crumb, "More at …" back-link, facts-strip
Venue cell, sidebar Venue card + "More at …" anchor) now links to `/business/{slug}/`
instead of the external site. Homepage venue sidebar also linked. Directory landing at
`/business/` with `ItemList` JSON-LD lists all 23 venues alphabetically. Markdown sibling
at `/business/{slug}/index.md` and `/business/index.md`. See
`docs/superpowers/specs/2026-04-23-per-business-landing-pages-design.md` and the
implementation plan alongside it.

Two one-time CLI scripts feed the metadata: `scripts/extract_business_metadata.py`
(Claude Haiku, pulls `{description, telephone, price_range, same_as}` from each homepage,
~$0.05 total) and `scripts/geocode_businesses.py` (free Nominatim, populates top-level
`lat`/`lng`). Both use a surgical text-level YAML editor that preserves the file's
comment header and field ordering — `yaml.safe_dump` would have destroyed both.
Re-runnable safely (idempotent skip unless `--force`). Both support a positional slug
argument to target a single business. The build itself never writes back to
`businesses.yaml`.

---

## Schema.org JSON-LD structured data (2026-04-20, expanded 2026-04-22)

`WebSite` + `ItemList` blocks in `templates/index.html`; `Event` block in
`templates/_event_detail.html`. Event schema includes name, description, startDate/endDate
(recurring events get the next upcoming occurrence via `_event_schema_dates()` +
`_next_occurrence_date()` in `site_builder.py`, rolled forward each daily build; recurring
events without a `start_time` emit no startDate), location (Place with business address),
organizer (Organization with `name` + `url` from `businesses.website`), `performer` (array
of Person from `events.performers`), `offers` (Offer with strict numeric-only price parsing
— "Free"/"no cover" → 0, single `$NN(.NN)?` → that price), image, url. Uses Jinja2
`tojson` filter to escape all user-supplied strings. Validated against Google Rich Results
Test 2026-04-22.

---

## Social sharing image / og:image (2026-04-21)

Per-event pages use `summary_large_image` with `public/images/og/{id}.jpg`. Homepage uses
`summary_large_image` with `public/images/og-home.jpg`, generated each build by
`_build_og_images()` in `site_builder.py` from `templates/_og_image_home.html`
(Playwright screenshot at 1200×630).

---

## Performers column (2026-04-21)

`performers TEXT` column stores a JSON array: `[{"name": "...", "role": "..."}]`. Role
vocabulary: `host`, `dj`, `headliner`, `featured`, `performer`, `drag`. Extracted by
Claude from flyer text ("Hosted by:", "Featuring:", DJ credits). Displayed inline on
event cards (dot-separated) and structured in the detail page aside. Existing events have
empty performers until next extraction run.

---

## Business hours capping (2026-04-21)

`hours:` block in `config/businesses.yaml` per business (format: `mon: "HH:MM-HH:MM"`,
null for closed). `_apply_hours_cap()` in `pipeline.py` infers null `end_time` from
closing time and caps events that exceed it. Midnight-crossing closes (e.g. `02:00`)
handled by treating times < 8am as next-day (+1440 mins). 10 bars/restaurants populated.

---

## Cache headers (2026-04-21, HTML caching expanded 2026-04-22)

`public/.htaccess` sets `Cache-Control: max-age=31536000, immutable` for hash-versioned
CSS (`*.{hash8}.css`) and content-addressed images (`[a-f0-9]{16}(-NNNw)?.webp`). 7-day
TTL for icons and OG images. **HTML now caches at Cloudflare edge for 1h + browser for
5min** (`public, max-age=300, s-maxage=3600`). Cloudflare-side requires a Cache Rule
(Cloudflare dashboard → Caching → Cache Rules) matching URI path ends with `/` OR
`.html`, set to "Eligible for cache" with Edge TTL "Use cache-control header if present,
bypass if not" and Browser TTL "Respect origin TTL". Rule is active on aville.net as of
2026-04-22. The daily extraction + site-rebuild workflows already do
`purge_everything:true` after deploy, so cache invalidation is automatic. Cut HTML
round-trip latency from ~1,178ms → ~500ms in PageSpeed Mobile.

---

## WebP compression tuning (2026-04-22)

`WEBP_QUALITY = 75` and `WEBP_METHOD = 6` in `src/images.py` (was q=82, default method).
Method 6 is the slowest WebP encode setting but produces ~10% smaller files at the same
quality; fine for a daily pipeline. The one-time bulk re-encode of existing 740 files via
`scripts/reencode_webps.py` shrunk total image bundle 57 MB → 33 MB (42.7% savings).
Visual difference at q=82→75 is imperceptible for these flyer images. New extractions
produce q=75 originals naturally; the script is for catching up the existing inventory
and can be re-run safely (it skips files that would grow).

---

## Build assertions (2026-04-21)

`_assert_build()` runs at end of `build_site()`. Always checks that CSS `<link>` hrefs in
`index.html` exist on disk. Checks image `src` paths only when `CHECK_IMAGES=1` (set by
extraction workflow's build step). Exits non-zero with a clear error list.

---

## AI agent / LLM discovery — Tier 1 (2026-04-23)

Four coordinated pieces landed in one session to make the site discoverable and consumable
by LLM agents:

1. **`/llms.txt`** — orientation page following the llmstxt.org convention (H1 title,
   blockquote summary, linked sections pointing to the sitemap, `/index.md`, per-event
   pages, structured data, venue list). Generated by `_build_llms_txt()` in
   `src/site_builder.py`, rebuilt every build so the venue list stays current.
2. **Content Signals in `robots.txt`** — `Content-Signal: ai-train=yes, search=yes,
   ai-input=yes` (opt-in to training, search, and real-time AI retrieval — the site's
   purpose is discovery, so we want agents citing and ingesting it). `robots.txt` is
   regenerated at every build by `_build_sitemap()`.
3. **Link response headers (RFC 8288)** in `public/.htaccess` for `*.html`:
   `</sitemap.xml>; rel="sitemap"`, `</llms.txt>; rel="describedby"`,
   `<index.md>; rel="alternate"; type="text/markdown"`. The alternate Link uses a
   relative URI-ref so it resolves per-request — browsers/agents loading
   `/event/123/index.html` see it resolve to `/event/123/index.md`. Also `.htaccess` now
   sets `Content-Type: text/markdown; charset=utf-8` for all `*.md` files.
4. **Build-time markdown siblings** — `templates/index.md` and `templates/_event.md`
   Jinja templates render `/index.md` (homepage: tonight/weekend/later/regulars, with
   links to canonical event URLs) and `/event/{id}/index.md` (per-event: title, when,
   venue+address, price, performers, tags, description, external link). Wired into
   `build_site()`: `_build_event_pages()` now writes `index.html` + `index.md` side-by-side
   per event page. In-HTML `<link rel="alternate" type="text/markdown">` tags also added
   to both `templates/index.html` and `templates/_event_detail.html` for agents that parse
   DOM instead of inspecting Link headers. Event detail template has `<base href="/">` so
   the alternate uses an absolute path (`/event/{{ e.id }}/index.md`) rather than a
   relative one.

Why these and not the other items on Cloudflare's agent-readiness checklist: API catalog /
OAuth discovery / OAuth Protected Resource / MCP Server Card / Agent Skills index /
WebMCP all assume the site exposes an API, protected resources, an MCP server, or
interactive tools — this site is pure read-only static content, so those don't apply.
Markdown-for-Agents (Accept-based negotiation via Cloudflare Worker) was skipped in favor
of the cheaper build-time `.md` siblings approach, which works without Workers and without
an additional runtime dependency (Tier 2 entry in `CLAUDE.md` if we ever want dynamic
negotiation on top).

New `.gitignore` entries: `public/index.md`, `public/llms.txt` (build artifacts, same
treatment as `public/index.html`). Per-event `index.md` files sit inside `public/event/`
which is already untracked as a whole.

---

## Local admin UI · `scripts/admin.py` (2026-05-09)

Single-user, localhost-only Flask app for editing `config/businesses.yaml`,
`config/businesses_pending.yaml`, `config/tags.yaml`, and `data/app.db` through
form views with field-level validation, a diff preview, and an auto-commit per
save. Bound to `127.0.0.1:5050`; every route 403s on a non-loopback request.
Runs with `python3 scripts/admin.py`.

### Why it exists

Built because Justin was avoiding TODO items (editorial blurb edits, missing
event times, vocabulary cleanup) out of fear of corrupting hand-edited YAML or
the SQLite DB. Admin gives form-driven editing with type-safe inputs (HTML5
`<input type="time">`, `<input type="date">`, multi-select from controlled
vocab, recurrence pattern datalist), a unified-diff preview before write, and
a per-save git commit so anything is one `git reset --hard HEAD~1` away.

Not in scope, deliberately: event create/delete (pipeline owns it), business
create (discovery workflow owns it), running extraction from the UI
(`gh workflow run` exists), pushing to remote (manual, intentional), auth /
network exposure (localhost only by hard guard).

### Six surfaces

- `/` — dashboard with counts (active events, missing-time, featured, series
  candidates, pending businesses, suggested tags).
- `/businesses/`, `/businesses/<slug>` — list + detail edit for
  `businesses.yaml`. Form covers name/category/website/address/lat/lng,
  `default_tags` (multi-select from `tags.yaml`), per-day hours inputs, JSON
  textarea for pages, structured editorial fields (`tagline`, `vibe_quote`,
  `about`, `metadata.{description, telephone, price_range, same_as}`).
- `/pending/`, `/pending/<slug>` — same form for `businesses_pending.yaml`,
  plus a **Promote** action that moves the entry into `businesses.yaml`,
  strips `_discovery_notes`/`_test_extraction`/`_confidence`, and commits both
  files in one shot.
- `/events/?filter=...&business=<slug>` — filterable event list (active /
  missing-time / featured / stale / all).
- `/events/<id>` — detail edit scoped to hand-edit fields: title, description,
  recurrence, start/end time, dated start/end datetime, price, tags,
  performers (JSON), featured, `ends_on`, status. Recurrence has a `<datalist>`
  populated from distinct `recurrence_pattern` values currently in the DB.
- `/tags/` — vocab editor (add/remove per category) plus a "Suggested new
  tags" queue surfacing distinct values from
  `raw_extraction.suggested_new_tags` across active events with counts and
  one-click promote-to-category.
- `/series-candidates/` — calls the refactored
  `scripts.list_series_candidates.find_candidates(conn)` and renders a date
  picker per row to set `ends_on`.

### Save pipeline

Every surface routes through the same flow:

1. **Validate.** HH:MM 24-hour time format (`RE_TIME`), recurrence regex
   (`RE_RECURRENCE` permits `daily | weekly:<csv-or-range> |
   monthly:<ordinal-day>`), ISO date (`%Y-%m-%d`), ISO datetime, JSON
   structure (lists/dicts as expected), tag-vocab membership for *newly added*
   tags only — pre-existing drift round-trips unchanged with a warning.
2. **Diff preview.** `difflib.unified_diff` for YAML (full file diff with
   per-line add/del/header coloring); field-by-field old/new HTML table for
   events.
3. **Atomic write.** `.tmp` + `os.rename` for YAML; SQLite transaction for the
   DB.
4. **`git commit --only <file> -m "admin: ..."`.** Per-save commit scoped to a
   single file via `--only` so any unrelated changes already staged elsewhere
   stay staged. Falls back to a no-op message if `git diff -- <file>` is empty
   (handles "Save" clicks with no actual changes gracefully).
5. **No auto-push, ever.** User pushes manually when ready; preserves the
   batch-then-`gh workflow run` rhythm.

### Round-trip preservation (the hard part)

Every business in `config/businesses.yaml` (25) and every active event in
`data/app.db` (149) round-trips byte-clean as a no-op preview — meaning a
subsequent real save only shows actual user-intended changes in `git diff`.
Achieved through a stack of small fixes:

- **`ruamel.yaml` in round-trip mode** (`YAML(typ="rt")`) with
  `preserve_quotes = True`, `width = 4096`, and a custom `None`-representer
  that emits explicit `null` (so `telephone: null` survives — ruamel's default
  is empty, which would clobber the existing convention).
- **Per-key scalar-style preservation.** Helper `_styled(old, new)` re-wraps a
  new string in the same `DoubleQuotedScalarString` /
  `SingleQuotedScalarString` / `LiteralScalarString` class as the value it's
  replacing, so editing `tagline: 'foo'` doesn't lose the single quotes,
  `hours.mon: "16:00-22:00"` keeps double quotes, and
  `about: |\n  Multi-paragraph...` keeps the literal block style.
- **Mutate sub-mappings/sequences in place** rather than replacing them.
  Example: `b["hours"]` is updated by writing to its existing keys, not by
  assigning a fresh Python dict, so ruamel keeps the per-key style metadata.
- **Set-equality short-circuit on `default_tags` and event `tags`.** HTML
  multi-select submits options in DOM (alphabetical) order, but the original
  YAML/JSON order may be arbitrary. If membership is unchanged, the existing
  list is preserved as-is so a no-op edit doesn't reorder.
- **No-op-skip on `pages` and `metadata.same_as` JSON textareas.** A folded
  scalar like `hints: >` or a single-quoted URL like
  `'https://www.facebook.com/...'` round-trips through `json.dumps` →
  `json.loads` losing its style. So we deserialize the submitted JSON,
  canonical-compare it against the existing list (also via
  `json.dumps`/`loads` to drop ruamel comments), and only replace the
  CommentedSeq when it actually differs.
- **`about: |` chomp preservation.** A YAML literal-block scalar's trailing
  newline determines `|` vs `|-`. The HTML textarea strips trailing newlines,
  so we re-append `\n` when the original was a `LiteralScalarString` to keep
  `|` (rather than flipping to `|-` on every save).
- **Explicit-null retention in `_set_or_delete`.** When the form submits an
  empty value for a key that was originally `key: null`, we keep it as
  `None` (which renders as `null`) rather than deleting the key. Preserves
  the convention used by JSON-LD generators that expect specific keys to be
  present even when empty.
- **Timezone-suffix preservation on dated events.** `start_datetime` /
  `end_datetime` in the DB are stored with a `-05:00` (Chicago CDT) suffix.
  HTML5 `<input type="datetime-local">` strips that. On save, `_to_iso(s,
  original)` extracts the original tz suffix and re-applies it, so a no-op
  edit on a Chicago-tz event round-trips byte-identical and a real edit keeps
  the same offset.
- **Vocab-drift permissiveness.** Existing `default_tags` or event `tags` not
  in `tags.yaml` are surfaced in the form as already-selected options (via
  `_merge_unknown(vocab, present)`) and a yellow warning banner. They round-
  trip unchanged; only newly *added* tags get vocabulary-validated. Without
  this, every save on a business with drift would silently drop the unknown
  tags.

### File mtime check

GET stamps the YAML file's `mtime` into a hidden form field. On save, the
handler re-reads `mtime` and compares; if the file changed underneath the
session, the save is refused with a clear error rather than clobbering. Not
needed for SQLite (handled by transaction semantics).

### Dependencies added

- `flask>=3.0.0` — only used by the admin; not imported anywhere in the
  pipeline.
- `ruamel.yaml>=0.18.0` — only used by the admin. The pipeline still uses
  `pyyaml` for read-only loads of `config/*.yaml`. Both can coexist.

The admin doesn't deploy: nothing in `public/` references it, the rsync
deploy step doesn't pick it up. Future maintainers running just the pipeline
in a fresh venv will install both deps but not exercise either.

### Refactor: `scripts/list_series_candidates.py`

Extracted the inner candidate-finding loop into a top-level
`find_candidates(conn, extra_keywords=None, include_already_set=False)` so
the admin can `from scripts.list_series_candidates import find_candidates`.
The CLI behavior of running the script directly is unchanged — `main()`
delegates to the new function.

### Smoke-test approach

Verified during build with a hands-off harness (no commits made):

1. GET each list route and confirm 200.
2. For each business slug: GET its edit page, parse out every `<input>` /
   `<textarea>` / selected `<option>`, POST them back unchanged with
   `action=preview`. Diff div should be empty. Iterated until all 25
   round-trip clean.
3. Same for every active event (149). All clean.
4. Spot-check a real edit (changing `tagline`) — diff shows the single
   intended line change, single-quote style preserved.
5. Validation paths: bad time `25:99` → "hours range must be HH:MM-HH:MM",
   bad recurrence `every-other-tuesday` → clear error.

No real save was triggered during smoke testing — Justin needs to commit the
admin code himself to authorize that.
