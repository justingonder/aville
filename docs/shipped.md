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

Active follow-ups (still deferred Phase 2 work; integration touch-ups) remain in
`CLAUDE.md`.

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
