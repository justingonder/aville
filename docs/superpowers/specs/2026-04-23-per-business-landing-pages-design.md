# Per-business landing pages
**Date:** 2026-04-23
**Status:** Approved
**Scope:** New page type at `/business/{slug}/` for each of 23 businesses; HTML + markdown + `LocalBusiness` JSON-LD + breadcrumb wiring + internal-link rewrite + one-time metadata-extraction pipeline.

---

## Goal

Ship canonical entity pages for each business in `config/businesses.yaml`, addressing three audiences with one artifact:

- **SEO** — biggest remaining single win for queries like "bars in Andersonville" or "[venue name] events", plus knowledge-graph matching. Also unlocks Google's SERP breadcrumb rendering on event pages (which currently never fires because there's no middle level to link to).
- **AI/LLM discovery** — agents asking "what does Hopleaf offer?" or "what bars are in Andersonville?" currently have no canonical page to anchor to. Business pages become the entity of record in both HTML and markdown, listed in `/llms.txt`.
- **Human** — a "browse everything at this venue" destination; a natural landing page when clicking a business name from an event card.

---

## Scope

### In scope for v1

- 23 pages at `/business/{slug}/` (one per business in `businesses.yaml`).
- Markdown sibling per page at `/business/{slug}/index.md`.
- Full `LocalBusiness` JSON-LD on each page.
- `BreadcrumbList` JSON-LD on business pages AND event detail pages.
- Internal-link rewrite: business-name links on event cards + event detail pages target `/business/{slug}/` (not the external website).
- "Happening right now at this venue" JS spotlight, reusing homepage `isHappeningNow` logic.
- Historical flyer gallery with a 4-visible + native `<details>` disclosure for the rest.
- New metadata fields on each business: `description`, `telephone`, `price_range`, `sameAs[]`, `lat`/`lng`.
- Business URLs added to `sitemap.xml` and surfaced in `/llms.txt`.

### Out of scope for v1 (deliberate)

- Embedded maps (CWV cost; external map-link sufficient).
- Structured menu data.
- Reservation widgets.
- Per-business OG social-share images (reuse homepage OG in v1; revisit later).
- Per-venue hero imagery (deferred to a Claude Design pass).

---

## URL & navigation

- New canonical URL: `/business/{slug}/` where `slug` comes from the existing `businesses.yaml` slug field. Parallel to `/event/{id}/`.
- **Key link-equity change:** business-name links on event cards (`templates/_event_card.html`) AND event detail pages (`templates/_event_detail.html`) now point to `/business/{slug}/` rather than the external website. The external URL stays prominent on the business page itself as a "Visit [venue name] ↗" CTA. Every event page now flows PageRank to its venue, and vice versa.
- **Breadcrumbs** on event detail pages: `Home › Hopleaf Bar › Zwanze Day 2026`, rendered as a visible crumb strip AND as `BreadcrumbList` JSON-LD. Unlocks Google's SERP breadcrumb treatment, which requires 2+ levels of depth.

---

## Page structure

Top → bottom on `/business/{slug}/`:

1. **Masthead** — H1 venue name, optional tagline, address, quick-action row (tel link, website, map link).
2. **"Happening right now"** — JS-powered, mirrors homepage spotlight. Hidden when no event is live (uses the existing `data-show-when-empty` pattern).
3. **Description** — 2–3 sentence paragraph from `description` field.
4. **What's happening** — two subsections:
   - Upcoming dated events (chronological), reusing the existing event card template.
   - Weekly regulars (day-of-week ordered).
   - Live-now indicators carry through from cards.
5. **Hours** — 7-row table rendered from the existing `hours:` YAML block.
6. **Recent flyers** — historical gallery of stale events at this venue. 4 tiles visible by default; native HTML `<details>` element wraps the remainder ("See N more past events"). Sorted most-recent-first. Each tile links to the preserved `/event/{id}/` detail page (which already renders its "no longer listed" banner).
7. **Footer CTA** — prominent "Visit [venue name] ↗" button to their own website.

---

## Structured data

### `LocalBusiness` JSON-LD (on each business page)

Every populatable field:

- `name` (from YAML)
- `address` (PostalAddress with `streetAddress`, `addressLocality: "Chicago"`, `addressRegion: "IL"`, `postalCode`, `addressCountry: "US"`)
- `geo` (GeoCoordinates, from geocoded `lat`/`lng`)
- `telephone`
- `url` (external website)
- `priceRange`
- `openingHoursSpecification[]` (expanded from the `hours:` block)
- `sameAs[]` (social URLs)
- `image` (fallback: most-recent event flyer at this venue)
- `event[]` (references to upcoming events)

### `BreadcrumbList` JSON-LD

- On business pages: `Home › Business Name`.
- On event detail pages: `Home › Business Name › Event Title` — matched by the visible breadcrumb strip described above.

---

## Data collection (one-time prep)

Two parallel workstreams before the first build:

### Claude metadata extraction

New `scripts/extract_business_metadata.py`. Per business: fetch homepage (reuse existing fetcher + Playwright where configured in `businesses.yaml`), hand HTML to Claude with a structured-output prompt, return `{description, telephone, price_range, sameAs[]}`. Writes into a `metadata:` block inside each business entry in `businesses.yaml`.

- Idempotent: skip businesses that already have a `metadata:` block unless `--force` is passed.
- `description`: 2–3 sentences, neutral tone.
- `price_range`: one of `$`, `$$`, `$$$`, `$$$$`. Inferred from page context; null if unclear.
- `sameAs[]`: absolute URLs to social profiles (Instagram, Facebook, X, Threads, TikTok) found on the page.
- `telephone`: E.164 format if possible; otherwise as-written.

Justin reviews and edits prose over time. First-pass text isn't blocking — pages ship with whatever Claude produces; manual polish happens post-ship.

### Build-time geocoder

New `_geocode(address)` helper in `src/site_builder.py` (or `src/geocoding.py` if it grows). Uses Nominatim (OpenStreetMap): free, TOS-compliant for our scale with caching.

- Writes `lat`/`lng` back into `businesses.yaml` on first resolution.
- Subsequent builds skip the lookup (only re-geocode if `lat`/`lng` unset).
- Includes a required `User-Agent` header per Nominatim TOS.
- Graceful degrade: on failure, skip `geo` from the JSON-LD rather than fail the build.
- Rate limit: 1 req/sec (Nominatim TOS). First run will take ~23 seconds; subsequent runs add no latency.

---

## Markdown sibling + AI discovery

- `/business/{slug}/index.md` with the same content as the HTML page, minus the JS spotlight (agents get the full static listing of current + recurring events).
- `<link rel="alternate" type="text/markdown">` in the business page `<head>` pointing at the markdown sibling.
- Apache `Link` header on `*.html` already covers business pages via the existing catch-all `<FilesMatch "\.html$">` block.
- `/llms.txt` venue list rewritten: each venue becomes a linked entry pointing at `/business/{slug}/`.
- `sitemap.xml` extended with 23 new business URLs.

---

## Build pipeline changes

### New files

- `templates/_business_detail.html`
- `templates/_business.md`
- `scripts/extract_business_metadata.py`
- Possibly `src/geocoding.py` if the geocoder grows beyond one function.

### Edited files

- `templates/_event_card.html` — business-name link target change.
- `templates/_event_detail.html` — business-name link target change + new breadcrumb strip + `BreadcrumbList` JSON-LD.
- `src/site_builder.py`:
  - `_build_business_pages()` — parallels `_build_event_pages()`; renders HTML + markdown per business.
  - `_business_schema()` — builds the `LocalBusiness` JSON-LD dict.
  - `_breadcrumb_schema(crumbs)` — reusable, called on business AND event pages.
  - `_geocode(address)` + YAML write-back.
  - `_build_sitemap()` extension for business URLs.
  - `_build_llms_txt()` update: venue list becomes linked.
  - Wire `_build_business_pages()` into `build_site()`.
- `src/db.py` — add `events_by_business(conn, business_id)` if not already present.

### No schema changes

Businesses remain config-driven; no new tables or columns.

---

## Risks / watchouts

- **Nominatim rate limit** — 1 req/sec per TOS. One-time cost ~23s; subsequent builds skip cached lookups entirely. Include `User-Agent: aville.net/1.0 (justingonder@gmail.com)` per TOS.
- **Link-rewrite blast radius** — changing the business-name link target affects the homepage + every event page. Mitigation: the new destination exists before the rewrite goes live (build business pages first, then flip the links — can be landed in the same commit since it's a single build).
- **Description voice** — Claude drafts tend to sandpaper-smooth. Mitigation: Justin's manual-polish pass is explicitly in the plan, and first-pass text isn't blocking ship.
- **Stale flyer gallery "graveyard"** — mitigated by the 4-visible default + `<details>` disclosure; most visual real estate stays dedicated to current events.
- **Homepage OG as business OG placeholder** — acceptable for v1 but worth tracking as a follow-up.

---

## Follow-ups for later sessions (not in v1)

- Per-business OG social-share images.
- Per-venue hero imagery (Claude Design pass).
- Tag-faceted browsing ("all live-music venues in Andersonville").
- Venue category landing pages (`/category/bars/` etc.) — probably premature before traffic patterns are known.
