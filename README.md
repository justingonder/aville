# A'ville.net

An event aggregator for **Andersonville, Chicago**. It pulls events, happy
hours, and specials from a curated list of local business websites, extracts
structured data with a multimodal Claude call, stores it in SQLite, and
publishes a static site at **https://aville.net**.

No framework, no app server, no managed database. A daily GitHub Actions job
does the extraction and deploys static HTML to Namecheap shared hosting behind
Cloudflare. The owner is Justin Gonder.

> **Status:** live and in active use. This started as a single-page proof of
> concept; it's now a multi-page site (homepage, per-event pages with rich
> share previews, per-business pages, a happy-hours page) covering ~26
> businesses, with a local admin UI for hand-editing, AI/LLM discovery
> surfaces, and four deploy workflows. Scope is still deliberately bounded —
> see [What's intentionally out of scope](#whats-intentionally-out-of-scope).

For day-to-day working context, conventions, and gotchas, read
[`CLAUDE.md`](CLAUDE.md). For session history read [`handoffs.md`](handoffs.md).
Deeper notes live under [`docs/`](docs/).

---

## Architecture

```
   ┌─────────────────────────┐
   │ config/                 │
   │  businesses.yaml        │◄── curated list of sites + per-business hints
   │  tags.yaml              │◄── controlled tag vocabulary
   │  festival/marquee.yaml  │◄── time-boxed featured content
   └────────────┬────────────┘
                │
                ▼
   ┌─────────────────────────┐      ┌────────────────────────┐
   │ fetch                   │─────►│ discover + download    │
   │  httpx (plain)          │      │ images → public/images │
   │  Playwright (JS sites)  │      │ + captions/headers     │
   └────────────┬────────────┘      └───────────┬────────────┘
                │                                │
                ▼                                ▼
         ┌──────────────────────────────────────────┐
         │ extract — Claude Haiku 4.5, vision, T=0.0 │──► structured JSON
         └────────────────────┬─────────────────────┘
                              ▼
                   ┌──────────────────────┐
                   │ upsert → SQLite      │  data/app.db (committed to git)
                   │ (respects locks)     │
                   └──────────┬───────────┘
                              ▼
                   ┌──────────────────────────────────┐
                   │ render static site (Jinja2)       │
                   │  index • event/{id} • business/   │
                   │  happy-hours • OG images • .md     │
                   │  llms.txt • sitemap • robots       │
                   └──────────┬────────────────────────┘
                              ▼
                   ┌──────────────────────┐     ┌───────────────────┐
                   │ rsync → Namecheap    │────►│ Cloudflare purge  │
                   │ public_html (static) │     │ (full)            │
                   └──────────────────────┘     └───────────────────┘
```

**Why this shape:** Namecheap only serves static files — it runs none of the
pipeline. GitHub Actions does all the work (free, scheduled, good logs).
Cloudflare sits in front for caching; every deploy issues a full purge so the
static page never serves stale "happening now" data for long. Both the SQLite
DB and the downloaded flyer images are **committed to git**, so a fresh
checkout can rebuild the entire site without running extraction (and historical
flyers persist even after a source page drops them).

### The pipeline, component by component

Orchestrated by `src/pipeline.py`; entry points live in `scripts/`.

| File | Role |
| --- | --- |
| `src/fetcher.py` | Fetch HTML/bytes. `httpx` for plain sites; headless Chromium (Playwright) for JS-heavy sites (`use_playwright: true`). Uses a real Chrome UA for Playwright to dodge anti-bot fingerprinting. |
| `src/images.py` | Find content images, filter noise (logos/icons/decor), download + optimize to WebP w/ srcset variants, capture each image's `section_header` + `caption` by walking the DOM. |
| `src/extractor.py` | One multimodal Claude call (**Haiku 4.5, temperature 0.0**), enforces structured JSON output. |
| `src/web_search.py` | Optional web-search enrichment for flyer ingestion (find a canonical event URL from a photographed flyer). |
| `src/db.py` | SQLite schema + upserts. Single `events` table with a `kind` discriminator (`recurring` / `dated`). Honors per-field locks. |
| `src/site_builder.py` | Jinja2 → static HTML, OG images, markdown siblings, sitemap, llms.txt. |
| `src/prompts.py` | `SYSTEM_PROMPT` (extraction) + seed-extraction prompt. Changes here affect every business. |

---

## Project layout

```
.
├── config/
│   ├── businesses.yaml          # the sites to scrape (+ hints, default_tags, hours, lat/lng)
│   ├── businesses_pending.yaml  # candidates being researched; NOT scraped until promoted
│   ├── tags.yaml                # controlled tag vocabulary
│   ├── festival.yaml            # time-boxed festival header / advisory / specials (Midsommarfest)
│   ├── marquee.yaml             # marquee slot content
│   └── web_search_allowlist.yaml
├── src/                         # pipeline (see table above)
├── scripts/
│   ├── init_db.py               # create the schema
│   ├── run_extraction.py        # the daily job (fetch → extract → upsert)
│   ├── test_extraction.py       # iterate on prompt/config for ONE url, no DB writes
│   ├── build_site.py            # render public/ from the DB
│   ├── admin.py                 # local Flask admin UI (localhost:5050)
│   ├── ingest_flyer.py          # CLI: photographed flyer → event
│   ├── build_business_maps.py   # static OSM map tiles per business
│   ├── build_icons.py           # favicon / touch-icon / manifest
│   ├── backfill_editorial_copy.py, geocode_businesses.py, ...  # one-off maintenance
│   └── test_*.py                # unit tests for helpers (run with the stdlib runner)
├── templates/                   # Jinja2: index, _event_detail, _business_detail,
│   │                            #   _happy_hours_page, _event_card, _tower, OG images,
│   │                            #   .md siblings, admin/
├── styles/                      # CSS SOURCE (index.css, event.css, happy_hours.css)
│                                #   build hashes these → public/{name}.{hash8}.css
├── data/app.db                  # SQLite — COMMITTED to git
├── public/                      # generated output (committed: flyer images; gitignored: html/css/OG)
│   ├── index.html  index.md  llms.txt  sitemap.xml  robots.txt
│   ├── event/{id}/   business/{slug}/   happy-hours/
│   └── images/<slug>/*.webp     # flyers (committed); images/og/ (build artifact, gitignored)
└── .github/workflows/           # scheduled, site-rebuild, site-rebuild-fast, park-site
```

---

## Quickstart (local)

Requires **Python 3.9+** (CI runs 3.12) and an Anthropic API key.

```bash
# 1. Install
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # needed for JS-rendered sites

# 2. Configure
cp .env.example .env
# edit .env and paste in your ANTHROPIC_API_KEY

# 3. The DB is committed, so you can build immediately:
python3 scripts/build_site.py
open public/index.html             # or: xdg-open / start

# --- to run extraction yourself ---
# 4. Test against a SINGLE url first (no DB writes) — this is how you iterate:
python3 scripts/test_extraction.py meeting-house-tavern \
    https://meetinghousetavern.com/events

# 5. When it looks right, run the full pipeline (writes to data/app.db):
python3 scripts/run_extraction.py

# 6. Rebuild and view:
python3 scripts/build_site.py && open public/index.html
```

> **Always use `python3`** — `python` is not aliased on the project machine.
> To wipe and start fresh: `rm data/app.db && python3 scripts/init_db.py`.

---

## Common tasks

### Editing content — the admin UI

For day-to-day data edits, run the local admin:

```bash
python3 scripts/admin.py            # → http://localhost:5050  (loopback-only)
```

It's a form-driven editor for `businesses.yaml`, `businesses_pending.yaml`,
`tags.yaml`, and individual events in the DB, with validation, diff preview,
and an auto-commit per save. Notable features:

- **Per-field 🔒 locks** on events — mark a field "researched, don't overwrite"
  and extraction will skip it on future runs (`locked_fields`).
- **Image-by-URL** — paste a flyer URL; it's downloaded, optimized to WebP +
  srcset, and attached.
- **Duplicate event** — clone a recurring show into per-schedule variants.
- **Dashboard** doubles as a deploy console: git/gh status banners + "Publish &
  deploy" (full, ~5 min, regenerates share-preview OG images) and "Quick
  publish" (fast, ~30–60s, skips OG).

Full guide: [`docs/admin-guide.md`](docs/admin-guide.md).

### Adding a business

Work **one business at a time** (keeps context and records clean):

1. Research the site (URL, platform, what events/specials it advertises).
2. Add an entry to `config/businesses_pending.yaml` with `hints`.
3. Test: `python3 scripts/test_extraction.py <slug> <url>`.
4. Troubleshoot — adjust `hints` or set `use_playwright: true`; retry.
5. Run `scripts/backfill_editorial_copy.py <slug>` **before** committing.
6. Promote to `businesses.yaml`, update `docs/business-discovery/progress.json`,
   commit (one commit per business).

### Iterating on the extraction prompt

The project lives or dies by extraction quality. Use `test_extraction.py`
(no DB writes) and tune the right knob:

- **Per-business issue** → edit that business's `hints` in `config/businesses.yaml`.
- **Affects everyone** → edit `SYSTEM_PROMPT` in `src/prompts.py`.

Watch for: ambiguous recurrence ("weekends" vs "Fri–Sun"), missing year in
dates (prompt picks the nearest future date — recheck near year boundaries),
decorative images becoming fake events, and multi-event flyers. The test
script does **not** merge business-level `default_tags`, so its output won't
exactly match what lands in the DB.

### Tags

Controlled vocabulary in `config/tags.yaml`. Claude must pick from the list and
may propose additions via `suggested_new_tags`; promote those manually as
patterns emerge.

---

## Deployment

Four GitHub Actions workflows. **Always `git push` before triggering one** —
`gh workflow run` dispatches against the remote HEAD.

| Workflow | What it does | When to run |
| --- | --- | --- |
| **Scheduled extraction + deploy** (`scheduled.yml`) | Full pipeline: fetch → extract → build → deploy. Burns API credits. Runs daily at **11:00 UTC / 6 AM Chicago**. | Pipeline/prompt/config/extraction changes. |
| **Site rebuild** (`site-rebuild.yml`) | Build + deploy only (no extraction). ~5 min — most of it is per-event OG share-image regeneration. | Template/CSS/`site_builder.py` changes where the share preview matters. |
| **Site rebuild (fast)** (`site-rebuild-fast.yml`) | Same, `--skip-og`. ~30–60s. | Content-only edits where the OG can lag a day. |
| **Park site** (`park-site.yml`) | Wipes the server, serves `park/index.html`. Manual, idempotent. | Temporary takedown. Restore with a rebuild. |

```bash
gh workflow run "Site rebuild (fast)"
gh workflow run "Scheduled extraction + deploy"
gh run watch <run-id>
```

Deploy is `rsync -avz --delete` over SSH (**Namecheap uses port 21098**, not 22)
followed by a full Cloudflare cache purge.

### Required GitHub secrets / variables

| Type | Name | Value |
| --- | --- | --- |
| Secret | `ANTHROPIC_API_KEY` | Anthropic API key |
| Secret | `NAMECHEAP_SSH_HOST` | e.g. `server123.web-hosting.com` |
| Secret | `NAMECHEAP_SSH_USER` | cPanel username |
| Secret | `NAMECHEAP_SSH_KEY` | private SSH key (contents) |
| Secret | `CLOUDFLARE_ZONE_ID` | zone for the cache purge |
| Secret | `CLOUDFLARE_API_TOKEN` | token with cache-purge permission |
| Variable | `NAMECHEAP_SSH_PATH` | e.g. `/home/USER/public_html/andersonville/` |
| Variable | `EXTRACTION_MODEL` | optional; defaults to `claude-haiku-4-5-20251001` |

### Analytics

Google Analytics 4, measurement ID `G-2JVRVTGFNE`, via a `gtag.js` snippet in
every standalone page template. A custom `share` event fires on share-button
clicks. (Dashboard: analytics.google.com.)

---

## Notable design decisions

- **SQLite, one file, committed to git.** No DB server. The daily job commits
  the updated DB (and any new flyer images) back to `main`; the workflow rebases
  before pushing to avoid clobbering local pushes.
- **Single `events` table with a `kind` discriminator** (recurring vs. dated)
  rather than two tables — simpler, easier tag faceting.
- **Haiku 4.5 at `temperature=0.0`.** Plenty capable for extraction, ~10× cheaper
  than Sonnet; T=0 stabilizes structured fields.
- **Config over code.** Per-business behavior (hints, default tags, hours,
  coordinates) lives in YAML, never in prompts or source.
- **Manual-research preservation.** `locked_fields` lets the admin mark fields
  Claude must not overwrite; companion columns (`ticket_url`, `starts_on`,
  `ends_on`, `featured`, `alternate_sources`, …) support hand-curation that the
  pipeline never touches.
- **Chicago-time everything.** "Happening now" is always evaluated against
  `America/Chicago`, with explicit handling for events that cross midnight
  (neighborhood bars run to 2–3 AM). See `CLAUDE.md` for the rules.
- **AI/LLM discovery.** Every page has a markdown sibling (`.md`), plus
  `llms.txt`, JSON-LD, and a sitemap so assistants can read the site cleanly.

## Cost

Haiku 4.5, ~26 pages once a day with images: comfortably **under $5/month**.
Hosting (Namecheap) and Actions (free tier) add nothing meaningful.

## What's intentionally out of scope

- **Instagram / Facebook** — shelved (Meta App Review + per-business opt-in).
  Revisit only with Chamber buy-in.
- **User-submitted events** — spam moderation is its own project.
- **A hosted/web admin UI** — the local Flask admin + `sqlite3` CLI are enough.
- **Search, calendar views, accounts** — not needed for the current goal.

Resist scope creep. If a change would need a framework, a real database, or new
infrastructure, pause and confirm with Justin first.

## When things break

- **Site redesign** → extraction may go sideways. Events that vanish between
  runs flip to `status='stale'`, so you'll notice.
- **JS-rendered site** → empty page text / no images. Set `use_playwright: true`.
- **Claude API hiccup** → that business is logged and skipped; prior events
  remain (marked stale). Other businesses still process.
- **Namecheap down** → deploy fails but the DB update already committed; the
  next run re-deploys.
- **DB/disk image drift** → `python3 scripts/repair_missing_images.py`
  re-downloads missing files from each event's recorded source URL.
