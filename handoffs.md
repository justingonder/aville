# Handoffs

Rolling log of Claude Code sessions. Newest at top. Each entry is scoped to
one working session; summarize rather than narrate. For durable project
context, see CLAUDE.md.

---

## 2026-05-01 evening (Site parked for aville.com bid)

### Summary
Justin is preparing to bid on the `aville.com` domain and didn't want the current `aville.com` owner browsing to `aville.net`, seeing the polished work, and demanding a higher price. Took the live site down and replaced it with a deliberately bland parking page so the domain looks dormant. Repo also flipped to private (done by Justin in the GitHub UI).

### What's deployed right now
- **`aville.net` serves a single bland page** — `park/index.html`: plain HTML, default browser fonts, just `aville.net` / `Under construction` / `noindex,nofollow`. No CSS, no analytics, no branding, no hint of the design work.
- **All `/event/...` and `/business/...` URLs return 404** — the parking workflow rsyncs `park/` (with `--delete`) so the server only contains `index.html`.
- **Daily 11:00 UTC extraction cron is ACTIVE.** The next scheduled run will rebuild from the committed DB and rsync the real `public/` over the parking page automatically. If you want to STAY parked beyond ~24h, either re-disable the cron in `scheduled.yml` or re-run the **Park site** workflow each morning.

### Where this is captured
- **PR #7** (`park-site-temporarily`) — merged. New files: `park/index.html`, `.github/workflows/park-site.yml`. Modified: `.github/workflows/scheduled.yml`.
- Park workflow ran successfully (rsync + Cloudflare purge).

### TO RESTORE THE SITE (when bid resolves, win or lose)

Easiest path: **do nothing.** The daily 11:00 UTC scheduled run automatically deploys the real site. By the next morning aville.net is back live with fresh data.

For an immediate restore: `gh workflow run "Site rebuild"` (or use the Actions tab). Builds from the committed DB and rsyncs `public/` with `--delete`, wiping the parking page. Watch with `gh run watch <id>`. Cloudflare cache is purged automatically. ~4 minutes end-to-end.

After restoring, verify in an incognito window:
- aville.net loads the real homepage
- a `/event/<id>/` and a `/business/<slug>/` page both load

**Optional cleanup** (only if you don't want this capability around anymore): delete `park/` and `.github/workflows/park-site.yml`. Worth keeping in place if there's any chance of future takedowns — re-running is just a workflow dispatch.

**To re-park the site** (e.g. if bidding extends): just run `gh workflow run "Park site (temporary takedown)"` again. The workflow is idempotent. Note: with the daily cron active, you'd need to re-park every morning or disable the cron.

### Loose ends
- Repo visibility: confirmed flipped to private. When restoring, no need to flip back unless you want it public again — site deploys work the same either way.
- The previous 4-30 `if: failure()` artifact-upload fix means a happy-path scheduled run produces no artifact, so resuming the cron won't reintroduce the storage-quota issue.
- Persistent untracked files in `git status` still unchanged (carries from prior 5-01 entry).

### Next session candidates
1. **Restore the site** (steps above) — top priority once the bid resolves.
2. **Plan + execute Phase 2** (editorial copy backfill via Haiku) — carries from earlier 5-01 entry.
3. **Process Clark St walk photos** through the flyer-ingestion pipeline.
4. **Per-business OG social-share images** — still queued.
5. **`.gitignore` audit** for the persistent untracked files.
6. **Mobile LCP structural decision (pre-Midsommarfest)** — biggest perf ceiling.

**Workflow note:** No further workflow runs needed during the parked window. Restoration requires uncommenting the cron + one **Site rebuild** dispatch (see above).

---

## 2026-05-01 (Design Phase 1 deployed + HH overflow hotfix + Node 20 routine scheduled)

### Summary
Continuation of the 4-30 session. Three ships, all live on aville.net.

1. **PR #4 merged → Design Session 3 Phase 1 live.** Required pre-resolving 2 expected merge conflicts before the GH "Merge" button would work: `data/app.db` (took main's — design branch never touched it) and `handoffs.md` (combined entries newest-first). Then `gh pr merge --merge` → `gh workflow run "Site rebuild"`. Run 25202904137 succeeded in ~4 min.

2. **PR #6 merged → HH sidebar card overflow hotfix.** User screenshot showed populated `price_info[:14]` strings busting horizontally past the card's 280px max-width. Root cause: CSS grid `grid-template-columns: 46px 1fr auto` + `.price { white-space:nowrap }` — the `auto` track expanded freely with single-line content, no width constraint. The spec's "hard layout constraint, no ellipsis" rule was only enforced in Python truncation, not CSS. Fix: hide the price column entirely (Phase 1 fallback was always going to be ugly per the spec; in practice it broke the layout); grid drops to `46px 1fr`. Coordinated change: re-target HH row link from `/business/{slug}/` → `/event/{id}/` so the no-price curiosity gap drives clicks toward the event detail page where full price info lives. `display_price` enrichment in `_select_today_happy_hours` kept so Phase 2 can re-enable display with one template-line change. Site rebuild run 25203439612 deployed in ~4 min — the upload-artifact step showed as skipped (`-`), confirming the 4-30 `if: failure()` fix works as intended on the happy path.

3. **Routine scheduled for Node 20 → Node 24 action bump.** GitHub Actions runner annotation flagged `actions/checkout@v4` and `actions/setup-python@v5` as Node 20-based; forced switch to Node 24 happens 2026-06-02. Created one-time routine `trig_01FQTj1HcXnrs4fAodKjiJDc` (Sonnet 4.6, default cloud env) firing on 2026-05-15 14:00 UTC (9am Chicago) to investigate latest stable versions, update both workflow files, and open a PR (no auto-merge — leaves for review). https://claude.ai/code/routines/trig_01FQTj1HcXnrs4fAodKjiJDc

### Where this is captured
- **Phase 1 ship (PR #4):** merged at `13f6f12`. Spec/plan unchanged from 4-29.
- **HH overflow fix (PR #6):** merged at `0d1a3d5`. 2 files changed (`templates/_happy_hours_card.html`, `styles/index.css`).
- **Node 20 routine:** managed via claude.ai routines; link above.

### Loose ends
- **Persistent untracked files** (`.claude/settings.local.json`, `.superpowers/`, `design/design_handoff_*`, `docs/dbeaver-queries.sql`, `public/event/`, `public/robots.txt`, `public/sitemap.xml`) flagged in 4-29 + 4-30 handoffs and still flapping. Worth a focused `.gitignore` audit.
- **Dead `.hh-row .price` CSS rule** (`styles/index.css` lines 476–477) is no longer rendered. Left in place — Phase 2 will reuse it when the price column comes back.

### Next session candidates
1. **Plan + execute Phase 2** (editorial copy backfill via Haiku) — elevated priority since the HH card needs `price_short` to restore the price column. Phase 2 also covers `tagline`/`vibe_quote`/`about` for 23 venues. When `price_short` ships, restore the column by re-adding `<div class="price">{{ hh.display_price }}</div>` to the template and reverting CSS grid to `46px 1fr auto`.
2. **Process Clark St walk photos** through the flyer-ingestion pipeline (PR #3 is on main; pipeline ready).
3. **Per-business OG social-share images** — still queued.
4. **`.gitignore` audit** for the persistent untracked files.
5. **Mobile LCP structural decision (pre-Midsommarfest)** — biggest perf ceiling.

**Workflow note:** Two Site rebuilds already triggered + succeeded this session (post-PR-#4, post-PR-#6). No further deploys needed; site is current. Tomorrow's 11:00 UTC scheduled extraction will be the first happy-path run exercising the new `if: failure()` upload step.

---

## 2026-04-30 (GitHub Actions artifact-quota wall — diagnosed + permanently fixed)

### Summary
Two consecutive scheduled runs (4-29, 4-30) failed mid-pipeline with `Failed to CreateArtifact: Artifact storage quota has been hit`. Site went stale on aville.net for 2 days.

Root cause: every successful run was uploading the entire `public/` directory (~70 MB after flyer images joined the build output on 2026-04-21) as a debug artifact with 14-day retention. Steady-state accumulation × manual-trigger overflow = 44 unexpired artifacts totaling 1.39 GB, over the GitHub free-tier storage cap. The upload step sat between Build and Deploy, so its failure blocked the rsync-deploy + DB-commit + Cloudflare-purge steps that actually matter.

Considered (and rejected) moving the archive to Namecheap: storage was viable but the daily snapshot itself doesn't earn its keep — happy-path output is fully reproducible from the committed DB + images, and the live site is the source of truth. Different storage doesn't fix "is this archive useful?".

Fix: `if: failure()` on the upload step in both `scheduled.yml` and `site-rebuild.yml`. Snapshot now only captures the case where it has unique value (a broken build) at zero quota cost in steady state. Existing 44 artifacts cleared via the GitHub API to immediately restore headroom.

### Where this is captured
- **PR #5** (`fix/actions-artifact-quota`) — merged into `main` at commit `3c39ff9`. 4-line diff.
- Workflow files: `.github/workflows/scheduled.yml`, `.github/workflows/site-rebuild.yml`.

### Loose ends
- One ~70 MB artifact uploaded by the 2026-05-01 02:51 UTC validation run before the fix landed on main (the manual trigger ran on pre-merge HEAD). Negligible — it'll expire in 14 days and the next happy-path run won't add another.
- Persistent untracked files (`.claude/settings.local.json`, `.superpowers/`, `design/design_handoff_*`, `docs/dbeaver-queries.sql`, `public/event/`, `public/robots.txt`, `public/sitemap.xml`) still flapping in `git status`. Prior handoff (4-29, on the `design-handoff-session3-phase1` branch) flagged a `.gitignore` audit — still queued.

### Next session candidates
1. **Browser review of PR #4 + merge** when satisfied → trigger **Site rebuild** (carries from 4-29).
2. **Process Clark St walk photos** through the flyer-ingestion pipeline (PR #3 merged into main during this gap — pipeline is now live).
3. **Plan and execute Phase 2** (editorial copy backfill via Haiku).
4. **Per-business OG social-share images** — still queued.
5. **Mobile LCP structural decision (pre-Midsommarfest)** — biggest perf ceiling.
6. **`.gitignore` audit** for the persistent untracked files.

**Workflow note:** This session's changes are already on `main` and the next scheduled run will pick up the failure-only upload behavior automatically. No additional workflow trigger required.

---

## 2026-04-29 (Design handoff session 3 — Phase 1 shipped)

### Summary
Long focused session executing the Session 3 design handoff (designer's package at `/Users/jgonder/Downloads/design_handoff_session3/`). Three discrete features shipped together as Phase 1 of a planned two-phase ship:

1. **Happy-hours sidebar card (A.1.B "clock strip")** — homepage sidebar listing today's happy hours. Three-state interplay with Happening Now spotlight: mixed-live (sidebar visible, spotlight non-HH only), HH-only-live (sidebar hidden, all-cards in spotlight), nothing-live (both hidden).
2. **Stamped-dateline breadcrumb (B.1.B)** — replaces inline `.top-row` crumbs on biz/event pages; new partial above the masthead on home / business / event / business-directory. 3-step responsive dateline (≥900 / 640–899 / <640px). `data-short` parent collapse via JS at <720px.
3. **Editorial business hero (C.1)** — replaces `<header class="masthead-biz">` on `/business/<slug>/`. 88px Fraunces italic h1, mono-blue kicker, italic lede, action row with "Open until X" yellow live pill, tag chips with first-chip highlight, 3-up image strip with typographic placeholder cells (Phase 1 ships with 0 `branding_images` curated; placeholders are deliberately call-out-the-gap design).

Approach: full superpowers brainstorm → spec → 14-task plan → subagent-driven execution. Implementer per task → spec compliance review → code quality review → fix → mark complete. Lighter-touch reviews on mechanical TDD helper tasks (Tasks 2–6); full reviews on integration tasks (7, 8, 11, 12).

Final cumulative review caught **3 real bugs** that per-task reviews missed:
1. **Critical:** "Open until X" pill always returned None — `_DAY_ORDER[weekday()]` produced "monday" but `businesses.yaml` uses 3-letter keys ("mon"). Fixed with `[:3]` slice.
2. **Important:** `.hero1 .kicker` inherited a 20px riso-red bar from base `.kicker::before` rule used by event-detail pages. Suppressed via `display:none`.
3. **Important:** Happy-hours card footer `#regulars` link went nowhere — no element had that id. Added to `<div class="regulars">`.

PR #4 opened against `main`: https://github.com/justingonder/aville/pull/4. 16 commits on branch `design-handoff-session3-phase1`.

### Where this is captured
- **Spec (final):** `docs/superpowers/specs/2026-04-28-design-handoff-session3.md` — 3 features + 10 locked decisions D1–D10.
- **Plan:** `docs/superpowers/plans/2026-04-28-design-handoff-session3-phase1.md` — 14 tasks with verbatim code.
- **Source design package:** `/Users/jgonder/Downloads/design_handoff_session3/` (the A.1.B / B.1.B / C.1 picked variants).
- **Implementation:**
  - `src/site_builder.py` — 5 new helpers (`_format_clock_pill`, `_format_window_meta`, `_select_today_happy_hours`, `_format_open_until`, `_derive_business_type`) + `crumb_trail` builds in 4 render paths (homepage, biz, event, biz-index).
  - `src/db.py` — `price_short TEXT` column + idempotent ALTER TABLE migration.
  - `templates/_breadcrumb.html`, `templates/_happy_hours_card.html` — new partials.
  - `templates/index.html` — breadcrumb + HH card wired into sidebar; spotlight JS HH-filter rule; `id="regulars"` added; `data-short` IIFE.
  - `templates/_business_detail.html` — old `.masthead-biz` replaced by `.hero1` editorial hero; old inline crumbs removed; HH-filter on spotlight; `data-short` IIFE.
  - `templates/_event_detail.html`, `templates/_business_index.html` — breadcrumb wired in, old inline crumbs removed; `data-short` IIFE.
  - `styles/index.css` + `styles/event.css` — A1B_CSS, CRUMB_CSS, C1_CSS lifted from design handoff.
  - `config/businesses.yaml` — `short_name: "Magic Lounge"` for chicago-magic-lounge.
- **Unit tests:** `scripts/test_session3_helpers.py` — 36 assertions across the 5 new helpers, all green.

### New optional YAML fields on businesses
Phase 1 consumes `display_type` (override capitalized `category`) and `short_name` (breadcrumb `data-short`). Phase 2 will consume `tagline`, `vibe_quote`, `about`, `press`, `branding_images`, `socials`. All optional; no immediate edits required to the 23 existing entries.

### Phase 2 (deferred — separate plan)
- Editorial copy backfill: Claude Haiku script analogous to `extract_business_metadata.py` that drafts `tagline`, `vibe_quote`, `about` for each of 23 venues; user reviews/edits.
- Manual: `press[]`, `socials{}`, `branding_images[]`.
- `price_short` column backfill for happy-hours card price column (Phase 1 falls back to `price_info[:14]`).
- Live JS recompute of "Open until X" pill (today server-rendered, goes stale within a day).

### Known low-priority follow-ups
- Two near-duplicate `_DAY_ORDER` / `DAY_ORDER` constants in `src/site_builder.py` (lines 30 and 580). Maintenance hazard but no current bug.
- `.top .crumbs` rules in `event.css` (lines 49–50, 293–294) are now dead CSS since the inline `.top-row .crumbs` was removed.
- Happening Now count text shows total `nowCards.length` including HH cards even though they go to the sidebar — slightly misleading wording when state is mixed-live.
- `price_short` column isn't in `upsert_event` INSERT/UPDATE (intentional Phase 2 deferral).

### Loose ends
- Untracked files persist across sessions (`.claude/settings.local.json`, `.superpowers/`, `design/design_handoff_*`, `docs/dbeaver-queries.sql`, `public/event/`, `public/robots.txt`, `public/sitemap.xml`). Worth a `.gitignore` audit at some point — `git add -A` is unsafe in this repo.
- PR #3 (flyer-ingestion-design) still open against `main`; independent of PR #4.
- The user planned to do visual review of PR #4 in-browser the next day at the right time-of-day windows (4–6pm peak HH; 8–10pm mixed-live) to see all three states.

### Next session candidates
1. **Browser review of PR #4 + merge** when satisfied → trigger **Site rebuild** (NOT scheduled extraction — code-only changes).
2. **Plan and execute Phase 2** (editorial copy backfill).
3. **Process Clark St walk photos** through the flyer-ingestion pipeline once PR #3 merges.
4. **Per-business OG social-share images** — still queued.
5. **Mobile LCP structural decision (pre-Midsommarfest)** — biggest perf ceiling.

**Workflow note:** Phase 1 = template / CSS / `site_builder.py` changes only — no extraction touched. After PR #4 merges, **Site rebuild** is the right deploy trigger.

---

## 2026-04-27 (flyer-ingestion pipeline brainstorm — paused mid-design)

### Summary
Short session that started as item #7 from the previous handoff (Clark St walk to add new businesses), then pivoted into a much more useful design conversation. User had photographed a flyer for "Wander Home Holiday Market" at The Guesthouse Hotel (4872 N. Clark, in the South Andersonville stretch — between Lawrence and Foster). Research showed the hotel hosts the market but doesn't advertise public events on its own website. Considered three paths: hard-reject the flyer; manually `sqlite3 INSERT` the event; build a "manual flyer ingestion" lane.

User then made the key reframe: web-search the flyer's distinctive strings to find a third-party authoritative source (event aggregators, neighborhood blogs, etc.), and treat the flyer as a SEED rather than a source. This unlocks a clean architecture — `source_page_url` is real, cross-verification filters flyer noise (window decals / shadows), and "no web trace = skip" is a clean quality gate. User also added: build a dedup check EARLY in the pipeline so already-scraped events don't burn tokens.

Brainstorm proceeded through scoping questions (one at a time):
- Dedup match action: pause + check for enrichment opportunities (option b + enrich).
- New-business handling: auto-add inline since the project is in build-up phase.
- Batch ergonomics: directory mode, Claude identifies business per photo, ask only when uncertain (no pre-renaming required).

Section A of the design (per-photo 7-step pipeline) was presented in chat. Sections B (CLI UX) and C (technical components / testing) were not drafted before pausing.

### Where this is captured
- **Design draft (resume point):** `docs/superpowers/specs/2026-04-24-flyer-ingestion-pipeline-design.md`. Status DRAFT. Section A is in the doc; B and C have to-do stubs. Decisions made are listed in a "don't re-litigate" section so the next session can resume cleanly.
- **Branch:** `flyer-ingestion-design` (renamed from the original `business-discovery-2026-04-24`, since we never got to actual discovery). One commit on the branch carrying these docs.
- **The Guesthouse flyer photo:** sitting at `/Users/jgonder/Downloads/20260422_202538.jpg`. User has more walk photos pending — all blocked on the pipeline shipping.

### Memories saved
- `project_south_andersonville_geography.md` — Clark between Lawrence and Foster counts as Andersonville for aville.net; precedent is Carol's Pub at 4659 N Clark already in the YAML.

### Followup added to CLAUDE.md
- **Holiday-events representation** — user observation prompted by the Mother's Day flyer: how should events tied to holidays be surfaced? Not a blocker for the flyer-ingestion work; revisit once we have a few more holiday-tied data points.

### Next session candidates
1. **Resume the flyer-ingestion brainstorm** — re-invoke `superpowers:brainstorming`, point at the spec draft, get Section A approval, then draft Sections B + C, then transition to writing-plans. Probably 30–45 min of focused conversation to finish the design.
2. **After spec is final: implement the pipeline.** Standalone CLI (`scripts/ingest_flyer.py`), reuses the existing extractor + fetcher + metadata-extractor + geocoder. Estimated 1–2 sessions.
3. **THEN process the Clark St walk photos** through the new pipeline. Real validation.
4. **Per-business OG social-share images** — small win, still queued from previous session.
5. **Shared spotlight-JS module** — homepage + business page IIFE deduplication.
6. **Homepage "See all venues →" link** pointing at `/business/`.
7. **All-day specials missing startDate** — 14/101 recurring events flagged by Rich Results.
8. **Mobile LCP structural decision (pre-Midsommarfest)** — biggest perf ceiling.

**Workflow note:** Doc-only changes on a feature branch. No site changes; no Site rebuild needed. The branch is open and can be picked up directly next session.

---

## 2026-04-23 (AI/LLM agent-readiness + per-business landing pages)

### Summary
Long session, two major threads plus workflow process changes. Both threads shipped end-to-end on their own feature branches; the per-business work is in an open PR (#1) awaiting user review + merge.

**Thread 1 — AI/LLM agent-readiness Tier 1** (committed to `main` as `7fb08c4`, deployed via Site rebuild run 24813561031). Shipped as a coordinated bundle:
- `/llms.txt` orientation page following the llmstxt.org convention, regenerated each build.
- `robots.txt` gains `Content-Signal: ai-train=yes, search=yes, ai-input=yes` — the site explicitly opts in to AI training, search indexing, and real-time retrieval.
- `.htaccess` emits RFC 8288 Link headers on every `*.html` response: `rel="sitemap"`, `rel="describedby"` → `/llms.txt`, `rel="alternate"; type="text/markdown"` → relative `<index.md>` URI-ref that resolves per-request (so `/index.md` for the homepage, `/event/NN/index.md` for event pages). Also sets `Content-Type: text/markdown; charset=utf-8` for all `*.md` files.
- Build-time markdown siblings: `/index.md` and `/event/{id}/index.md` rendered from new `templates/index.md` and `templates/_event.md` alongside their HTML pages. In-DOM `<link rel="alternate" type="text/markdown">` tags in both root templates for agents that parse DOM instead of headers.

Initial brainstorm triaged Cloudflare's `isitagentready.com` checklist down from 9 items to the 4 that applied to a pure-content static site (API catalog, OAuth, MCP server card, agent-skills index, WebMCP all don't apply — we have no API or interactive tools). Tier 2 deferred items documented in CLAUDE.md: ICS feeds, JSON Feed/RSS, Markdown-via-Worker, read-only MCP server, machine-readable markdown sitemap.

**Thread 2 — per-business landing pages** (feature branch `per-business-pages`, PR #1 — 20 commits, ~2k inserts). Full brainstorm → spec → plan → implementation cycle. Ships:
- 23 canonical entity pages at `/business/{slug}/` with full `LocalBusiness` JSON-LD (name, address, `geo`, telephone, `priceRange`, `openingHoursSpecification`, `sameAs`, representative flyer image, up to 10 upcoming events).
- `BreadcrumbList` JSON-LD on both business pages AND event detail pages, with a visible 3-level breadcrumb on event pages (`Home › Business › Event`) — unlocks Google's SERP breadcrumb rendering.
- Internal-link rewrite: every business-name mention on event cards + event detail (top-bar crumb, "More at …" back-link, facts-strip Venue cell, sidebar Venue card) now points at `/business/{slug}/` instead of the external site. Homepage venue sidebar also linked. Huge for internal PageRank flow.
- Markdown sibling per business page at `/business/{slug}/index.md`.
- `/business/` directory landing page (HTML + MD) listing all 23 venues alphabetically, with `ItemList` + `BreadcrumbList` JSON-LD. Added after the user pointed out hitting `/business/` otherwise showed a server directory listing.
- Historical flyer gallery with 4-visible + `<details>` disclosure on each business page. JS "Happening right now at this venue" spotlight mirroring the homepage.
- One-time data-collection scripts:
  - `scripts/extract_business_metadata.py` — Claude Haiku extractor (~$0.05 one-time) pulling `{description, telephone, price_range, same_as}` from each homepage. Surgical text-level YAML editor preserves the file's 16-line comment header and field ordering (deliberate deviation from the plan's `yaml.safe_dump` — the implementer caught this).
  - `scripts/geocode_businesses.py` — Nominatim geocoder (free) populating top-level `lat`/`lng`. Same text-level editor; TOS-compliant User-Agent + 1.1s rate limit. 23/23 geocoded on first run.
- `sitemap.xml` now includes 24 business URLs (23 detail + 1 directory). `llms.txt` venue list is linked to business pages and mentions the directory as a primary resource.

Pre-existing spec document: `docs/superpowers/specs/2026-04-23-per-business-landing-pages-design.md`. Implementation plan: `docs/superpowers/plans/2026-04-23-per-business-landing-pages.md` (14 tasks).

**Thread 3 — workflow process changes:**
- **Switched from direct-to-main commits to feature branches.** User's call: direct-to-main was fine while getting the project off the ground, but now feature work goes on a branch with a PR. Preference saved to memory.
- Used the `superpowers:subagent-driven-development` skill to execute the per-business plan with a pragmatic scaling heuristic (Option B): full implementer + spec reviewer + code quality reviewer on substantial tasks (Task 2 extractor, Task 4 geocoder, Task 6 HTML template); single implementer or inline controller work on smaller tasks (templates, CSS, one-line changes). ~10 subagent dispatches instead of the ~42 a strict reading would have required. Reviews actually caught real bugs (Task 4 defensive fix for partial lat/lng state; Task 6 `&amp;` escape, missing `<footer>`, spotlight card dedup). Worth the overhead for the substantial tasks, would have been pure cost on the trivial ones.

### User discovery patches during review
Between the user's first browser walkthrough and final PR state, two issues surfaced that were not in the original plan:
- Several business-name mentions on event pages were still unlinked (or pointed at homepage#recurring). Fixed in commit `bf37997` — now every event page has 5 internal links to its venue (top-bar crumb, back-link, facts strip, sidebar name, sidebar "More at..." anchor).
- Hitting `/business/` (no slug) showed a server directory listing. Fixed in commit `a57c3de` with a proper directory landing page + markdown sibling.

### Next session candidates
1. **Merge PR #1, trigger Site rebuild, run Google Rich Results Test** on a live business page + event page to confirm `LocalBusiness` and `BreadcrumbList` validate without errors.
2. **Per-business OG social-share images** — currently every business page uses `og-home.jpg`. `_business_schema()` already picks the most recent event flyer as `image`; the same source could feed a per-business `og:image`.
3. **Shared spotlight JS module** — homepage and business page each carry a near-identical `isHappeningNow` IIFE. Extract to `public/spotlight.js` if a third page ever needs it.
4. **Homepage "See all venues →" link** pointing at `/business/` — venue sidebar shows 20+ venues but no direct path to the new index.
5. **All-day specials missing startDate** — 14/101 recurring events have null `start_time`; extend `_apply_hours_cap()` to default `start_time` from business opening hours.
6. **Mobile LCP structural decision (pre-Midsommarfest)** — pick one of the three paths in CLAUDE.md's `Mobile LCP structural ceiling` entry. Still the biggest performance ceiling.
7. **Clark St walk** — user has window-sign photos to process; highest-value undiscovered businesses.

### Workflow note
Thread 1 deployed during the session (Site rebuild run 24813561031 — ran on `main` before we switched to feature branches). Thread 2 lives on branch `per-business-pages`, PR #1, NOT yet deployed. After the user reviews the PR locally and merges, they should trigger `Site rebuild` to deploy. The build has no DB/extraction changes, so no API-credit cost.

---

## 2026-04-22 (SEO + Core Web Vitals + Cloudflare HTML caching)

### Summary
Long session. Three major threads: expanded Schema.org JSON-LD, ran a Core Web Vitals pass guided by PageSpeed Insights, and shipped Cloudflare HTML edge caching. Mobile Performance ended at 81 (variance noise around a real ~83 baseline) but subjectively the site loads dramatically faster — HTML latency 1,178ms → 159ms, image bundle 57 MB → 33 MB.

**Schema.org Event expansion** (early-session) — `_event_offer()`, `_event_performers_schema()`, and `_event_schema_dates()` added to `src/site_builder.py`. Recurring events now emit `startDate` via `_next_occurrence_date()` (walks the recurrence pattern forward from build date; handles weekly day-list/range, monthly Nth/last weekday, daily). Strict numeric-only price parsing for `offers` (`^\s*\$(\d+(?:\.\d{1,2})?)\s*$`, FREE_PRICE_VALUES = {"free", "no cover"}). `organizer.url` added from `businesses.website`. Validated on event 18 (recurring) + event 23 (dated). Coverage: 87/101 active recurring with `startDate`, 70/261 events with `performer`, 39/261 with `offers`.

**Core Web Vitals (Tier 1 fixes)** — Image dimension helper `_img_dims()` (Pillow lazy-import + cache) writes explicit `width`/`height` on cards (kills CLS). Hero image on detail pages: `loading="eager"` + `fetchpriority="high"` + dims. First 3 static cards on homepage: eager + high-priority on card 0 (via `img_priority` namespace counter). Google Fonts: `rel="preload" as="style" + onload="this.rel='stylesheet'"` + noscript fallback. **Result on desktop: 80 → 98 Performance, 93 → 100 Accessibility.**

**Mobile LCP root cause hunt** — Initial fixes barely moved Mobile (78 → 76 then back to 78). Debugged with `curl + grep`: discovered the LCP element was the spotlight clone built by JS at `templates/index.html:476`, which hardcoded `loading="lazy"` and copied only `src` (the 1200w fallback) — dropping `srcset`, `sizes`, `width`, `height`. **Fixed:** rewrote the spotlight loop to use `cloneNode(true)` and mark the first cloned image `eager` + `fetchpriority="high"`. Also tightened `_event_card.html` `sizes` from `(max-width: 640px) calc(100vw - 32px), 380px` → `(max-width: 720px) calc(50vw - 19px), 400px` to match the real 720px breakpoint and 50vw-mobile card width.

**Accessibility cleanup** — `.side.ad .ad-tag` color `--muted` → `--ink-2` (was 4.1:1, now ~12:1). `footer .bar` color `rgba(232,222,196,.5)` → `.85` (was 2.5:1, now ~7:1). `.reg-list h5` → `.reg-list h4` (heading hierarchy — h2 → h5 jump fixed; both base and `:hover` rules updated). All 100 on accessibility now.

**Cloudflare HTML edge caching (Tier 1)** — `.htaccess` HTML rule changed from `no-cache, must-revalidate` → `public, max-age=300, s-maxage=3600` (5min browser, 1h edge). User configured a Cloudflare Cache Rule (Caching → Cache Rules) matching URI ends with `/` OR `.html`, set to "Eligible for cache" + Edge TTL "Use cache-control header if present, bypass if not" + Browser TTL "Respect origin TTL". Verified: `cf-cache-status: MISS` first request, `HIT` second. **HTML latency dropped 1,178ms → 159ms** in PageSpeed.

**WebP quality tuning (Tier 2)** — `WEBP_QUALITY = 75` (was 82) + `WEBP_METHOD = 6` in `src/images.py`. New `scripts/reencode_webps.py` walks `public/images/<business>/*.webp` and re-saves at the new settings (skips og/, skips files that would grow). One-time bulk run shrunk 57 MB → 33 MB (42.7% savings, 24 MB shaved). Visual difference imperceptible for flyer images. Image savings opportunity in PageSpeed dropped 178 → 107 KiB.

**User-global HEREDOC auto-approve hook** (off-topic but related) — User was getting frequent "Newline followed by # inside a quoted argument" Bash safety prompts on every git-commit/PR-body HEREDOC. Created `~/.claude/hooks/auto_approve_heredoc.py` (PreToolUse, matches `Bash`, detects `\n[ \t]*#` in `tool_input.command`, outputs `hookSpecificOutput.permissionDecision: "allow"`). Wired in `~/.claude/settings.json`. Memory entry saved at `reference_heredoc_auto_approve_hook.md` so future sessions know it exists.

**Documented but deferred** — `Mobile LCP structural ceiling — pre-Midsommarfest critical` added to CLAUDE.md as a high-priority entry. Real cause of the LCP plateau (~3.8-4.0s on Slow 4G): the LCP element is built by JS at the end of the 251 KB body, so it can't start fetching until the entire HTML parses. Three ranked fix paths captured: lazy-render below-fold cards (best, expensive), build-time spotlight prerender (medium, UX cost), inline LCP image as base64 (clever, fragile). Decision triggered by user noting Midsommarfest cell-tower congestion will make Slow 4G real for thousands of attendees simultaneously.

### Final scores
- **Mobile:** Perf 81 (was 78 baseline), A11y 100, Best Practices 100, SEO 100. LCP 4.0s, FCP 3.2s, CLS 0.002, TBT 0ms, Speed Index 3.2s.
- **Desktop:** Perf 98 (was 80), all others 100. (Earlier in session, before re-test.)
- **CrUX field data:** still "No Data" — needs 28 days of real traffic to populate.

### Next session candidates
1. **Mobile LCP structural decision (pre-Midsommarfest)** — pick one of the three paths in CLAUDE.md's `Mobile LCP structural ceiling` entry. Lazy-render below-fold cards is the right answer if cell congestion at the festival is going to stress the page; needs careful refactor of card-querying JS (`isHappeningNow`, search/filter, share-leaderboard).
2. **LocalBusiness schema + per-business landing pages + breadcrumbs** — bundled medium-priority entry in CLAUDE.md. Revisit week of 2026-04-29 when Claude Design credits reset. Biggest single SEO win for "bars in Andersonville" / venue-name queries.
3. **All-day specials missing startDate** — 14/101 recurring events have null `start_time` and emit no `startDate` (Rich Results flags this). Plumbing exists in `_apply_hours_cap()` to read business `hours:`; extend to default `start_time` from open time for all-day specials.
4. **Clark St walk** — user has window-sign photos to process; highest-value undiscovered businesses.
5. **Stale event expiry** — `status='stale'` events linger forever; add 14-day → expired rule.

**Workflow note:** Site rebuild was triggered ~5 times across the session for incremental fixes (CWV, a11y, spotlight LCP fix, .htaccess change, WebP re-encode). No extraction runs — all changes were templates/CSS/site_builder/images. Final deploy at 24810654690 succeeded.

---

## 2026-04-22 (Business discovery + image-commit workflow)

### Summary
Two distinct threads: finished a batch of 4 business-discovery cycles, then fixed a CI failure by committing business flyer images to git.

**Business discovery — 4 businesses added:** Calo Ristorante (WordPress+Elementor SSR, 7 daily specials), Big Jones (Toast CMS + Cloudflare challenge → Playwright, HH only), Fiya (Wix + Playwright, PDFs baked into hints since pipeline can't fetch PDFs), Pizza Lobo (Squarespace SSR, `$1 Wings` Tue/Wed only — always-on combos excluded). Each followed the full per-business discovery cycle; `docs/business-discovery/progress.json` updated.

**CI build failure — 4 missing atmosphere .webp files:** `_assert_build()` was failing because `data/app.db` had `image_local_path` set for events whose files weren't on disk and were gitignored. Initial fix nullified the DB path when the file was missing — rejected by user ("isn't that potentially an indicator that the event has been cancelled?"). Reverted, and instead:
- `.gitignore` — removed `public/images/*`; now only `public/images/og/` and `og-home.jpg` (build artifacts) are ignored. Business flyers are tracked.
- Backfilled repo with 412 existing flyer files (~61MB).
- `scheduled.yml` — `git add public/images` alongside `data/app.db` so new flyers get committed each run.
- `site-rebuild.yml` — dropped the `--include='images/' --exclude='images/*'` filter; plain `rsync --delete` is safe now that the repo owns the images.
- `scripts/repair_missing_images.py` — re-downloads missing files from DB-recorded `image_source_url`, verifying the SHA256 hash matches the expected filename. Used to repair the 4 originally-failing atmosphere images + 26 others that happened to be missing on disk.
- 16 events couldn't be repaired (source CDN images rotated — mostly MHT + 3 atmosphere + 1 Replay B-Day). Their `image_local_path` was nulled so they render with the poster fallback. See "Known stale image state" below.

**Verified:** manual `Scheduled extraction + deploy` run passed in 10m17s. Deploy + Cloudflare purge ran cleanly.

### Known stale image state
16 event IDs whose CDN source rotated between the original extraction and 2026-04-22 — `image_local_path` is now NULL, they render poster fallback. Not broken, just imageless. IDs: 1, 3, 5, 6, 8, 9, 10, 11, 12, 13, 15, 27, 30, 48, 49, 97. The DB still has `image_source_url` for most — if the source pages re-publish compatible images at the same URL, a future extraction will pick them up fresh.

### Next session candidates
1. **Clark St walk** — user has photos from window signs; highest-value undiscovered businesses
2. **Homepage OG image** — `index.html` still uses `twitter:card: summary` (no image); needs a static 1200×630 for `summary_large_image`
3. **Why did atmosphere's `/upcoming-events` fail to download new flyers this run?** — the 4 originally-failing images had to be repaired from source rather than produced by the extraction run. Worth checking if there's an ongoing fetcher issue with that page.
4. **Schema.org validation** — run Google Rich Results Test on event detail pages
5. **Stale event expiry** — `status='stale'` events linger forever; add 14-day → expired rule

**Workflow note:** Scheduled extraction + deploy was triggered and succeeded. No follow-up run needed.

---

## 2026-04-21 (SessionEnd hook schema fix)

### Summary
Restored `.claude/settings.json` to a valid hook schema. The committed state used the deprecated flat format (`{"type": "prompt", "instruction": "..."}`), which Claude Code no longer accepts — this produced a startup error and silently disabled the entire settings file, so the `SessionEnd` hook set up on 2026-04-20 was never actually firing. A prior uncommitted edit had fixed the schema (`matcher` + nested `hooks` array, renamed `instruction` → `prompt`) but also changed the event from `SessionEnd` to `Stop`, which fires after every assistant response instead of once at session close — producing a nag loop. Reverted event to `SessionEnd` while keeping the new schema.

### Known behavior notes
- Settings load at session start, so for any session that started before this fix, the old `Stop` hook keeps firing through session close. Fix takes effect on the next session.
- Prompt-type hooks on `SessionEnd` are unverified end-to-end — the prior `SessionEnd` hook never ran because the schema error disabled the file. Confirm behavior after the next SessionEnd fires.
- Empirical note from this session: prompt-type hooks do fire on `Stop` (non-tool event), contradicting some older skill docs that claim prompt hooks are tool-event-only.

### Next session candidates
Same priorities as the earlier 2026-04-21 entry (Clark St walk, homepage OG image, Schema.org validation, data quality pass, stale event expiry) — not restated.

**Workflow note:** Settings + docs only → no workflow trigger needed.

---

## 2026-04-21 (Performers, hours capping, wordmark, Claude Design feedback)

### Summary
Long session. Two pipeline features, one design update, one CI fix, and a full sweep of 7 Claude Design feedback items.

**Business hours capping** — New `hours:` block in `config/businesses.yaml` (per day, `"HH:MM-HH:MM"` format, 10 businesses populated). `_apply_hours_cap()` in `pipeline.py` infers null `end_time` from closing time and caps events that run past close. Midnight-crossing closes handled by `_close_sort_key()`: times < 8am get +1440 mins so 02:00 (1560) > 22:00 (1320) in comparisons.

**Performers extraction** — New `performers TEXT` column in `events` table (JSON array: `[{"name": "...", "role": "..."}]`). Role vocabulary: `host`, `dj`, `headliner`, `featured`, `performer`, `drag`. Added to `src/prompts.py` (extraction prompt), `src/db.py` (schema + upsert), `src/site_builder.py` (JSON parse), `templates/_event_card.html` (inline list, `·`-separated), `templates/_event_detail.html` (structured `.performers` block with role labels). Existing events have empty performers until next extraction run.

**Wordmark update** — Implemented Claude Design handoff (`design/design_handoff_wordmark_logo/`). Dropped the apostrophe: `A'ville` → `Aville`. `.dot` color changed from red to yellow in `index.html`. Prose/meta tags keep "A'ville.net". `_og_image.html` also updated. New favicon system: `scripts/build_icons.py` (Playwright-based) generates `favicon.svg`, `favicon.ico` (16/32/48), `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`. `public/site.webmanifest` added. Favicon `<link>` tags added to both page templates.

**CI fix** — `site-rebuild.yml` was missing `playwright install chromium --with-deps`. Build was failing at `_build_og_images()`. Fixed.

**Claude Design feedback (7 items, all shipped):**
- **#21 Image pipeline** — `_generate_srcset_variants()` in `images.py` writes 400w/800w WebP variants alongside main 1200w file. `_srcset()` Jinja global checks for variant files and returns srcset string. `srcset`/`sizes`/`decoding="async"` added to card and detail img tags. Variants generated on extraction; degrades gracefully on site-rebuild.
- **#22 Extract inline CSS** — `styles/index.css` and `styles/event.css` extracted from templates. `_publish_css()` in `site_builder.py` hashes content → `public/{name}.{hash8}.css`. Templates use `<link href="{{ *_css_href }}">`. `public/*.css` added to `.gitignore`.
- **#23 Tower SVG partial** — `templates/_tower.html` Jinja macro with `cork` (dark strokes `#1a1812`/`#2a2620`) and `og` (light strokes `#e8dec4`/`#4a4338`) variants. All three template inline SVGs replaced with `{{ tower() }}` / `{{ tower('og') }}`.
- **#24 Cache headers** — `public/.htaccess` with `<IfModule mod_headers.c>` guards: 1yr immutable for `*.{hash8}.css` and content-addressed `[a-f0-9]{16}(-NNNw)?.webp`; 7d for icons/OG images; no-cache for HTML.
- **#25 Sitemap lastmod** — `<lastmod>` added to each `<url>` in `sitemap.xml` from `last_extracted_at`; homepage gets max of all active events.
- **#26 Ribbon scroll indicators** — CSS fade gradients on `.ribbon::before/::after` (mobile only), toggled by JS `can-scroll-left` / `can-scroll-right` classes. Scroll + resize listeners.
- **#27 Build assertions** — `_assert_build()` at end of `build_site()`: CSS link existence always checked; image src paths checked only when `CHECK_IMAGES=1` (set in `scheduled.yml` build step). Exits non-zero with error list on failure.

**Workflow triggered:** Site rebuild (templates/CSS/site_builder changes). Extraction run needed to populate `performers` for existing events.

### Next session candidates
1. **Clark St walk** — user has photos from window signs; highest-value undiscovered businesses
2. **Homepage OG image** — `index.html` still uses `twitter:card: summary` (no image); needs a static 1200×630 for `summary_large_image`
3. **Schema.org validation** — run Google Rich Results Test on event detail pages
4. **Data quality pass** — 123/139 active events missing fields; targeted cleanup
5. **Stale event expiry** — `status='stale'` events linger forever; add 14-day → expired rule

---

## 2026-04-20 (OG images, Carol's Pub images, extraction fixes)

### Summary
Four tasks completed in sequence.

**Superseding logic (carried over)** — Already landed in previous session. Verified working.

**Carol's Pub images** — Root cause: `images.py` only resolved `//`-prefixed URLs, not plain relative paths. Fix: added `urljoin(base_url, src)` fallback for any `img src` that isn't already absolute. This was a general fix; Carol's Pub and any other business using relative image URLs now work. Also added `venue-\d` to `SKIP_FILENAME_PATTERNS` to filter venue photos. 9/10 active Carol's Pub artist photos appeared on next extraction run.

**Extraction pipeline bugs** — Direct `sqlite3` patches to `data/app.db`:
- Chicago Magic Lounge show times: Close-Up (id=111) 19:30, Showcase (id=112) 19:30, Intimo (id=113) 19:00, Signature (id=114) 19:30, 52 Lovers (id=116) 19:30
- SPINOFF (id=109): `end_datetime` corrected to `2026-05-02T00:00:00-05:00`
- Zwanze Day (id=60): `start_datetime` corrected to `2026-04-25T12:00:00-05:00`

**Per-event OG social sharing images** — Build-time Playwright generation of 1200×630 JPEGs in `public/images/og/{id}.jpg`. Events with a flyer/photo show the image above a branded A'ville.net banner (118px tall, `#1a1812` background, water-tower SVG wordmark, yellow tape accent). Events without an image get a poster fallback: 5 deterministic color variants (`p-yellow`, `p-red`, `p-cream`, `p-ink`, `p-stripe`) selected by `event_id % 5`. Generated 233 images on first build. `_event_detail.html` updated: always uses `summary_large_image`, `og:image` points to `/images/og/{id}.jpg`.
- Template: `templates/_og_image.html`
- Generator: `_build_og_images()` in `src/site_builder.py` (file-exists cache to skip already-generated images)
- Design sketch: `design/og-image-sketch.html`
- Key bug fixed: Playwright `set_content(base_url=...)` not supported in installed version → use temp file `public/_og_tmp.html` + `page.goto(file://)` so relative image paths resolve

**Workflow triggered:** Site rebuild. Commit: 825f366. Run: https://github.com/justingonder/aville/actions/runs/24703640495

### Next session candidates
1. **Clark St walk** — user has photos from window signs; highest-value undiscovered businesses
2. **Homepage OG image** — `templates/index.html` still uses `summary` card with no image; create a 1200×630 branded static image for the homepage
3. **Schema.org validation** — run Google Rich Results Test on event detail pages after OG image deploy
4. **Data quality pass** — 123/139 active events flagged missing fields; do a targeted cleanup pass
5. **Stale event expiry** — events with `status='stale'` linger forever; add a rule (e.g., 14 days stale → expired)

---

## 2026-04-20 (Superseding logic, marquee config, data quality tools)

### Summary
Full session building on the Bulletin v2 polish pass. Several new features landed.

**Superseding logic** — When a dated event exists at the same business with a start time within 60 minutes of a recurring event on the same day, the recurring event is suppressed from `today_recurring` and `weekend_recurring`. Implementation in `site_builder.py`: `_time_to_mins()` + `_superseded_recurring_ids()` compute which recurring IDs to drop at build time. Tested: "Karaoke Mondays" (event 18) correctly disappears from the Monday page when "Panic! at the Karaoke" (event 16, same business, same time) is present.

**Config-driven marquee** — `config/marquee.yaml` controls the homepage banner independently of the DB's `featured` column. Fields: `enabled`, `label`, `headline`, `body`, `link_url`, `link_text`. Currently `enabled: true` with an "under active development" message. `scripts/set_marquee.py` is the CLI tool to update it (flags: `--off`, `--event <id>`, `--label/--headline/--body/--link-text/--link-url`).

**Data quality report** — `scripts/data_quality_report.py` flags active events missing image, time, description, price, or confidence. `--business <slug>` and `--missing <field>` filters. On first run: 123/139 active events flagged.

**Other fixes this session:**
- Happening-now deduplication: `seenIds` Set prevents same event appearing in both `#recurring-today` and `#recurring-weekend`; all DOM instances suppressed together via `nowIds`
- "Other Monday events" section: `#recurring-today` gets its own independent section-rule so JS `previousElementSibling` hide works correctly when the section empties
- Multi-day event display in cards: `_card_date_str()` shows date ranges for true multi-day; suppresses `00:00` times
- `python3` reminder added to CLAUDE.md (macOS doesn't alias `python`)
- Extraction prompt updated: use `T00:00:00` not `T23:59:00` for unknown end times
- DB patched: events 106, 107, 118 had `T23:59:00` end datetimes corrected to `T00:00:00`

**Workflow triggered:** Site rebuild. Run: https://github.com/justingonder/aville/actions/runs/24702190950

### Next session candidates
1. **Social sharing image** — create 1200×630 `public/images/andersonville-happenings-social.jpg` for `summary_large_image` Twitter card on homepage
2. **Chicago Magic Lounge** — show times still null; set via `sqlite3` after checking current schedule at chicagomagiclounge.com
3. **In-person Clark St walk** — user has photos from window signs; highest-value undiscovered businesses
4. **Schema.org validation** — run Google Rich Results Test on event detail pages
5. **Extraction pipeline bugs** — fix bad end_datetime on multi-day events (SPINOFF, Zwanze Day, etc.)

---

## 2026-04-20 (Polish pass — rendering bugs)

### Summary
End-to-end polish pass fixing all visible rendering bugs found in the Bulletin v2 site. Single commit covers all fixes.

**Fixed (Issues 1–7):**
1. **Recurrence humanizer** — consecutive weekday runs now collapse: `Mon–Fri` → "Weekdays", `Sat–Sun` → "Weekends", `Thu–Sun` → "Every Thursday–Sunday". 2-day stays as "X and Y".
2. **Zero-duration / midnight times** — `start==end` renders single time (no dash). `00:00` start treated as all-day (no time shown). Multi-day spans render as date range ("Apr 23–May 2", "June 25–28") instead of a nonsense time. `_is_multiday()` helper: date diff ≥ 2, or date diff ≥ 1 with 00:00 start.
3. **Truncated recurrence** — removed `truncate(14)` from card `.f-day` span.
4. **Alt text truncation** — removed `truncate(80)` from `<img alt=...>`.
5. **No-image treatment** — investigated; all 9 Uvae no-image events correctly render `.poster` in Bulletin v2 template. Issue was a legacy concern, not a current bug.
6. **Venue sidebar** — removed `[:8]` cap from `_venue_summary()`. All 18 venues now shown.
7. **Tonight recurring events** — added `today_recurring` list (computed via `_fires_on_days`) and a `#recurring-today` bucket to the Tonight section. Monday events tested: 7 recurring events appear.

**Not fixed (pipeline-level bugs — out of scope for this session):**
- `SPINOFF` has `data-end-time="19:00"` matching start (zero-duration in the data). Card now suppresses the duplicate time display, but the underlying DB value is wrong — extraction stored a bad end time. Fix in a dedicated extraction session.
- `Zwanze Day 2026`, `Black Bear Island`, `Festival of Unfinished Work 2026` — start datetimes are `00:00` placeholders stored by extraction. Display is now correct (no fake time shown), but root cause is in the extraction pipeline.

**Surprising findings during walk-through:**
- `Wednesday Broadway Boulevard` legitimately runs 8pm–12am (midnight close), NOT a placeholder. The "00:00 end time" suppression was intentionally scoped to *start* times only.
- Monthly patterns (`monthly:last-sunday`) don't fire in `today_recurring` / `weekend_recurring`. This is correct behavior — we can't determine "last Sunday of month" without a calendar check, which is out of scope.

**Workflow triggered:** Site rebuild. Run: https://github.com/justingonder/aville/actions/runs/24699622170

### Next session candidates
1. **Social sharing image** — create 1200×630 `public/images/andersonville-happenings-social.jpg`
2. **Chicago Magic Lounge** — show times still null; set via sqlite3 after checking current schedule
3. **In-person Clark St walk** — user has photos from window signs; highest-value undiscovered businesses
4. **Schema.org validation** — run Google Rich Results Test on event detail pages
5. **Extraction pipeline bugs** — fix bad end_datetime on multi-day events (SPINOFF, Zwanze Day, etc.)

---

## 2026-04-20 (Bulletin v2 event detail page redesign)

### Summary
Implemented the Bulletin v2 event detail page (`_event_detail.html`) following the same Swedish corkboard aesthetic as the home page. Fixed a tags list/string type error that caused the build to fail on `_kicker()`.

**Changes:**
- `templates/_event_detail.html` — full rewrite: condensed masthead (small tower + issue number), top bar breadcrumbs, hero flyer (real image or poster template with tape strips), 4-column facts strip, body text with drop-cap, tag chips, action buttons, sticky aside with venue card (CSS star-pin map) + related events (`.miniev` format) + ad card
- `src/site_builder.py` — added `_kicker(ev, build_date)`, `_miniev_date(ev)`, registered `when_text` and `miniev_date` as Jinja2 globals; fixed tags type handling (list vs JSON string); `_build_event_pages` now accepts `build_date` + `issue_number`; renamed render variable to `event_when` to avoid shadowing the callable global

**Key decisions:**
- Related events shown in aside only when event is stale (keeps aside useful)
- `when_text` stays as a Jinja2 global callable for related events; `event_when` is the pre-computed string for the main event

**Workflow triggered:** Site rebuild. Run: https://github.com/justingonder/aville/actions/runs/24699094314

### Next session candidates
1. **Social sharing image** — create 1200×630 `public/images/andersonville-happenings-social.jpg` for `summary_large_image` Twitter card on homepage
2. **Event card polish** — happening-now indicator on live cards, tag display tweaks
3. **Chicago Magic Lounge** — show times still null; set manually via sqlite3 after checking current schedule on chicagomagiclounge.com
4. **In-person Clark St walk** — user has photos from window signs; highest-value undiscovered businesses
5. **Schema.org validation** — run Google Rich Results Test on event detail pages

---

## 2026-04-20 (Bulletin v2 home page redesign)

### Summary
Implemented the full Bulletin v2 home page redesign from the Claude Design handoff at `design/design_handoff_bulletin_v2/`. The site now has a Swedish corkboard aesthetic with cork background, riso-print color palette, and the Andersonville water tower as the masthead.

**Changes:**
- `templates/index.html` — full rewrite: water tower SVG masthead, top bar, nav ribbon, flyer card grid, "Happening right now" section (JS), regulars list, sidebar (filter chips + live weather + venues + post-event card), classifieds placeholder, dark footer
- `templates/_event_card.html` — rewritten as `.f` flyer card: tape/pin decorations, portrait image container, poster templates for imageless events, grid span classes, rotation variants
- `src/site_builder.py` — added `_fetch_weather()` (wttr.in), `_issue_number()` (days since launch), `_venue_summary()`, `_shortdate()`, `fmt_time` — all passed to template

**Key decisions:**
- Classifieds: placeholder "Coming soon" copy as requested
- Weather: live via `wttr.in/Chicago?format=j1` at build time; silently skipped if API down
- "Post an event" link: `https://forms.gle/ZkPqZ6dFjUH7F2GD9`
- Issue number: days since 2026-04-18 (launch date)
- Mobile: `@media (max-width: 720px)` — rotations flatten, grid → 2-col, sidebar stacks below

**Workflow triggered:** Site rebuild (template-only change). Run: https://github.com/justingonder/aville/actions/runs/24698409350

### Next session candidates
1. **Event detail page redesign** — `templates/_event_detail.html` needs the same treatment: condensed masthead, hero flyer, facts strip, sticky sidebar (the `bulletin-v2-detail.html` reference file is in the design handoff)
2. **Event card update** — current card works but consider further polish: happening-now indicator on cards that are live, tag display tweaks
3. **Classifieds** — replace placeholder with real community notices mechanism when ready
4. **Social sharing image** — still TODO: create 1200×630 branded `public/images/andersonville-happenings-social.jpg` for `summary_large_image` Twitter card
5. **Chicago Magic Lounge** — show times still null; set manually via sqlite3

---

## 2026-04-20 (continued discovery, Carol's Pub fix, SEO improvements)

### Summary
**Discovery:** Web research is now saturated — documented 7 more rejections (Wil's Martini Lounge, Penelope's Vegan Taqueria, Tanoshii Sushi, Big Chicks, Oda Mediterranean, Artisan's Locale, Lady Gregory's). Demijohn still not open. Checked retail stores for scrapeable sales — most use Instagram/email; Early to Bed (workshops) uses Atom platform which blocks scraping.

**Carol's Pub fix:** The `/music.html` URL was wrong — it shows the full event archive back to Feb 2025, so the pipeline extracted only old stale events. Changed to `carolspub.com/` (homepage), which shows only upcoming events. Test extraction on the homepage correctly yielded 12 dated shows (Apr 24–May 2, 2026) + 4 recurring events (Trivia Wed, Karaoke, Cougar Bingo, Y'all's Brunch).

**SEO improvements (template-only):** Added Twitter card meta tags to index.html. Improved subtitle text to include "Andersonville, Chicago." Added local address/zip to footer. Added `areaServed` with PostalAddress to the WebSite Schema.org JSON-LD. These reinforce geographic focus for search engines and AI surfaces.

**Workflows triggered:** "Scheduled extraction + deploy" at session start (run 24655014344, picks up Uvae specials + 3 new businesses). "Scheduled extraction + deploy" again after Carol's Pub fix (run 24655666182). "Site rebuild" after SEO template changes (run 24655783923).

### Commits
- `e5b4a89` — docs: 7 rejections from Apr 2026 discovery
- `9fd48e0` — fix: Carol's Pub URL to homepage
- `9bea2ab` — feat: Twitter cards on homepage
- `82ab623` — feat: local SEO signals (subtitle, footer, areaServed)

### Next session candidates
1. **In-person Clark St walk** — user's photos of window signs/specials boards would surface businesses invisible to web research (highest value)
2. **Retail stores** — user wants to capture sales at Andersonville retailers. Early to Bed (5138 N Clark) is the best candidate (hosts workshops) but blocked by Atom. Check if they have a standalone events page.
3. **Social sharing image** — create a branded social.jpg (1200×630) for og:image on the homepage; currently falls back to summary card
4. **Schema.org validation** — run Google Rich Results Test on event detail pages
5. **Chicago Magic Lounge** — show times still null; set manually via sqlite3
6. **Demijohn** — check again in a few months (still not open Apr 2026)

### Workflow note
"Site rebuild" triggered (run 24655783923) — deploys Carol's Pub fix + SEO template changes. Next extraction run scheduled for 11:00 UTC tomorrow (daily) which will pick up the Carol's Pub homepage URL and produce active events.

---

## 2026-04-20 (continued discovery + Schema.org SEO implementation)

### Summary
Continued autonomous discovery scan on Clark St corridor (Lawrence to Bryn Mawr, east of Ashland, west of Broadway per user's geographic clarification). Found and promoted 3 more businesses: **Swedish American Museum** (Drupal SSR, 6 monthly events), **Ranalli's of Andersonville** (Wix, happy hour + Monday pizza special), **Kopi Cafe** (Squarespace SSR, monthly accordion + Songwriter's Showcase). Documented 14 additional rejections (closed businesses, out-of-geography venues, no-events-page restaurants). Implemented **Schema.org JSON-LD** on both `index.html` (`WebSite` + `ItemList`) and `_event_detail.html` (`Event` schema with name, startDate, location, organizer, image) — the primary mechanism for AI search surfaces to understand events on the site. Triggered extraction run for all 17 businesses. Also caught that Carol's Pub DB events were all stale (from Feb 2026) — new extraction should refresh them.

### Commits
- `30dee30` — complete Swedish American Museum discovery cycle
- `388c20e` — stage Ranalli's of Andersonville
- `5d414fb` — stage Kopi Cafe
- `0ef6a67` — rejection batch (14 new rejections, fix Kopi Cafe)
- `d6fa22e` — promote all 3 to pipeline, clear staging file
- `[pending]` — Schema.org JSON-LD + CLAUDE.md updates

### Next session candidates
1. **Andersonsvillle Galleria** (5247 N Clark) — indoor art marketplace, check for events calendar
2. **Simon's Tavern** — free live music almost every Sunday; no events page but worth checking if they've added one
3. **Event Horizon Gallery** (5517 N Clark) — concerts + VR events, Instagram-driven but worth rechecking for website
4. **Demijohn** (5259 N Clark) — check if finally opened (was in zoning review May 2025)
5. **Schema.org validation** — run Google Rich Results Test on a few event detail pages to verify the JSON-LD parses correctly
6. **Chicago Magic Lounge** — set show times manually via sqlite3 (times still null)
7. Monitor whether the new Carol's Pub events show up correctly after extraction run completes

### Workflow note
Triggered "Scheduled extraction + deploy" (run https://github.com/justingonder/aville/actions/runs/24654624013). Should pick up all 3 new businesses + refresh Carol's Pub events. Then "Site rebuild" needed after Schema.org commit to deploy template changes.

---

## 2026-04-20 (autonomous business discovery — 4 new businesses staged)

### Summary
Ran autonomous discovery loop across all of Andersonville's bars and entertainment venues. Researched ~25 businesses, accepted 4 into `businesses_pending.yaml`, rejected 21 with documented reasons. Ran test extractions for all 4 accepted businesses — all pass. Fixed Playwright user-agent bug (bot UA triggered anti-bot protection on Nobody's Darling). Updated `load_businesses()` to optionally include pending entries for testing.

### Commits
- `b92791b` — feat: autonomous business discovery — stage 4 candidates for pipeline
- `b731d01` — feat: test extractions pass for all 4 pending businesses; fix Playwright UA
- `fe5e116` — docs: update progress.json with full discovery results

### Businesses staged (in `config/businesses_pending.yaml`)
1. **Nobody's Darling** (1744 W Balmoral) — LGBTQ+ cocktail bar, text calendar widget, 20 events/happy hours. Playwright + Chrome UA required.
2. **Elixir Andersonville** (1509 W Balmoral) — cocktail lounge, 6 day-specific drink specials + 4 recurring events from hints.
3. **Uvae Kitchen & Wine Bar** (5553 N Clark) — wine bar, 5 wine tasting events extracted cleanly from SpotApps page.
4. **Carol's Pub** (4659 N Clark) — legendary honky-tonk, 80+ live music events as structured text, plus trivia/karaoke/drag brunch.

### Decisions made
- **Staged vs. pipeline**: New businesses go to `businesses_pending.yaml` (not picked up until manually promoted to `businesses.yaml`). This lets us test configs without risking the production DB.
- **Playwright Chrome UA**: `playwright_session()` now uses `PLAYWRIGHT_USER_AGENT` (real Chrome UA string) instead of the bot UA. Some sites (notably Nobody's Darling custom CMS) block headless bot identifiers even from Playwright. Bot UA preserved for httpx `fetch_html` calls.
- **load_businesses(include_pending=True)**: `src/pipeline.py` updated so `test_extraction.py` can test pending entries. The pipeline itself never passes `include_pending=True`.
- **Geography**: Expanded to "feels like Andersonville" per Justin's instruction — Carol's Pub (4659 N Clark, technically Uptown) included because locals consider it Andersonville.

### Known remaining candidates to check in future sessions
- **Demijohn** (5259 N Clark) — Heisler Hospitality bar, zoning approval as of May 2025. Check if open.
- **In Fine Spirits** (5418 N Clark) — wine shop with tastings, but City Hive platform events don't render. May need special handling.

### In flight / incomplete
- The 4 staged businesses need to be promoted to `businesses.yaml` and run through a full extraction to populate the DB. Do this manually via `sqlite3` review or run scheduled extraction after promoting.

### Next session candidates
1. **Promote staged businesses** to `businesses.yaml` and trigger full extraction + deploy (run "Scheduled extraction + deploy" workflow)
2. **Schema.org JSON-LD** on index.html and _event_detail.html (documented in CLAUDE.md lower-priority section)
3. **Chicago Magic Lounge show times** — set manually via sqlite3 after verifying on their website
4. **Visual design pass** — frontend-design skill session (per earlier session notes)
5. **Check Demijohn** — verify if open and has a website

### Workflow note
No template/CSS changes this session. Discovery work only — no workflow trigger needed beyond the already-triggered "Site rebuild" for CLAUDE.md/docs changes.

---

## 2026-04-20 (late-night spotlight bugs, workflow race fix)

### Summary
Fixed three separate `isHappeningNow` bugs that caused false positives at 1:30am. Fixed race condition in scheduled extraction workflow causing DB push failures when local commits land during a run.

### Commits
- `a437ba7` — fix: rebase before push in DB commit step to avoid race with local pushes
- `fc1468a` (rebased) — fix: three spotlight 'happening now' bugs causing false positives at 1:30am

### Decisions made
- **Midnight-crossing events (the core bug):** A recurring event with `end_time < start_time` (e.g., Mon 5pm–2am) has its post-midnight tail on the NEXT calendar day. The old code matched on today's day only, so at 1:30am Monday it incorrectly fired for a Monday event's "before 2am" window. Fix: for wraparound events, check `eventDays.includes(chicago.dayOfWeek) && nowMins >= startMins` (still going) OR `eventDays.includes(prevDay) && nowMins < endMins` (in the post-midnight tail). `prevDay = (chicago.dayOfWeek - 1 + 7) % 7`.
- **No-start-time events:** `if (!startTime) return true` was treating any event with an unknown time as always-live on its recurrence day. Changed to `return false` — we'd rather show nothing than a false positive.
- **Dated events missing `data-start-time`:** Time was stored in `start_datetime` (ISO string) but the card template only emitted `data-event-date`. Added `chicago_time_str()` helper in `site_builder.py` that extracts HH:MM in Chicago time from an ISO datetime string; card template now also emits `data-start-time` and `data-end-time` for dated events.
- **Workflow race condition:** `git push` in the "Commit updated database" step failed when local commits landed during the ~10-minute extraction run. Added `git pull --rebase origin main` before the push.

### Known behavior note
Chicago Magic Lounge show times are still null — spotlight won't surface those events until times are set manually via sqlite3.

### In flight / incomplete
- Not applicable.

### Next session candidates
1. Manually set Chicago Magic Lounge show times in DB.
2. Schema.org JSON-LD structured data.
3. Node.js 20 deprecation in Actions — bump action versions before June 2026.
4. Visual polish: missing design tokens (`#5a3d00`, `#f0dc5a`, `#c8dff0`) still as bare hex.

**Workflow note:** Templates + workflow changed → **Site rebuild** triggered (run 24652128528). No extraction needed.

---

## 2026-04-20 (SEO, Chicago Magic Lounge, weekend recurring events)

### Summary
Completed SEO quick wins (meta descriptions, canonical, sitemap.xml, robots.txt). Added SessionEnd hook to auto-update handoffs on session close. Added Chicago Magic Lounge to extraction config (show times unavailable — ThunderTix blocks scraping, manual sqlite3 entry required post-extraction). Updated "This Weekend" bucket to include recurring events with a "regulars" divider below one-offs.

### Commits
- `6519f75` — feat: SEO quick wins — meta descriptions, canonical, sitemap, robots.txt
- `c4a6692` — feat: add SessionEnd hook + update session continuity instructions
- `145ffbb` — feat: add Chicago Magic Lounge
- `3df344a` — docs: note manual time entry required for Chicago Magic Lounge
- `bd1aba4` — feat: include recurring events in 'This Weekend' bucket

### Decisions made
- **SEO quick wins** — `<meta name="description">` and `<link rel="canonical">` added to both `index.html` and `_event_detail.html`. `sitemap.xml` generated by `site_builder.py` (`_build_sitemap()`) listing homepage + all active event URLs. `robots.txt` points to sitemap. Schema.org JSON-LD deferred (documented as next-session item in CLAUDE.md).
- **SessionEnd hook** — `.claude/settings.json` created with a `SessionEnd` prompt hook; fires when session closes and prompts Claude to write handoffs.md if not already done. Note: does NOT fire on mid-session compaction (PreCompact hook exists but can't inject prompts). CLAUDE.md updated to say "update at natural stopping points, not just session end."
- **Chicago Magic Lounge** — Squarespace, server-side rendered, no Playwright. Two pages: `/purchase-tickets` (5 recurring show types: Mon/Tue/Wed/Thu–Sun/Daily) and `/classes` (dated magic college workshops). Show times and ticket prices only on ThunderTix (returns 403) — `start_time` and `price_info` left null. Manual sqlite3 update required after each extraction. Address: 5050 N Clark St.
- **"This Weekend" recurring events** — `_fires_on_days()` helper in `site_builder.py` checks a recurrence pattern against the actual day names in the `weekend` set (adapts correctly when today is Sat/Sun and weekend = next weekend). Template shows one-offs first, then a subtle centered "regulars" rule-with-label divider, then weekend recurring events. Currently ~22 recurring events appear on a Fri–Sun weekend.

### Known behavior note
- Chicago Magic Lounge show times are null in DB after extraction — need manual update. Check chicagomagiclounge.com for current times and run: `UPDATE events SET start_time='HH:MM' WHERE business_id=X AND title LIKE '...'` for each show type.

### In flight / incomplete
- Scheduled extraction run 24646311454 triggered for Chicago Magic Lounge — check results.
- Site rebuild run 24646560152 triggered for "This Weekend" feature — check results.

### Next session candidates
1. Manually set Chicago Magic Lounge show times in DB (ThunderTix blocks scraping).
2. Schema.org JSON-LD structured data — `<script type="application/ld+json">` on both `index.html` (WebSite + ItemList) and `_event_detail.html` (Event schema). See CLAUDE.md for field mapping notes.
3. Node.js 20 deprecation in Actions — bump action versions before June 2026.
4. Visual polish: missing design tokens (`#5a3d00`, `#f0dc5a`, `#c8dff0`) still as bare hex in both templates.

**Workflow note:** Config + templates changed → **Scheduled extraction + deploy** triggered (run 24646311454). Site rebuild also triggered (run 24646560152).

---

## 2026-04-19/20 (SoFo Tap, spotlight, image fixes, analytics)

### Summary
Added SoFo Tap (22 events across 3 pages including IML 2026 special events). Fixed two silent image-dropping bugs. Extended spotlight to surface "starting soon" events (within 60 min). Added Plausible analytics with custom Share event tracking. Fixed Replay Andersonville missing images by enabling Playwright.

### Commits
- `c9bb151` — feat: add SoFo Tap to extraction config
- `b619559` — fix: remove duplicate SoFo Tap specials, add hints to prevent re-extraction
- `4bb33a0` — feat: show events starting within 60 min in spotlight
- `34b8459` — fix: two image/placeholder fixes (Cloudinary + spotlight no-image placeholder)
- `32be015` — fix: add use_playwright to Replay events page to capture JS-rendered images
- `e1bacbd` — feat: add Plausible analytics to index and event detail pages
- `2cdc8ee` — feat: track share button clicks in Plausible
- `40bfee1` — fix: restore async on Plausible script tag (was incorrectly changed to defer)

### Decisions made
- **SoFo Tap images via Cloudinary** — `SKIP_FILENAME_PATTERNS` was matching "logo" inside `/saas/logos/` in the Cloudinary URL path, silently dropping all event flyers. Fixed by checking pattern against filename only (last path segment before `?`), not the full URL. Went from 1 image to 8 images on test run.
- **BEARAOKE is Sunday** — extraction initially produced `weekly:saturday` because the model miscalculated what day April 19 fell on. Explicit day-of-week anchor hints added to SoFo events page config to prevent recurrence. CLAUDE.md now documents a lower-priority post-extraction day-of-week validation idea.
- **Duplicate SoFo specials** — "Daily Specials" ($5 shots/$4 tall boys, unverified) and Sunday Happy Hour ($3 shots + hot dogs) both deleted from DB. Hints updated: no "Daily Specials" catch-all, no Sunday food component (it's already SUNDAY FUNDAY). Prefer specific over general.
- **Spotlight "starting soon"** — events starting within 60 min show in spotlight alongside happening-now events. Label switches between "HAPPENING NOW" and "STARTING SOON · X min"; per-card badge differentiates the two states. All time logic evaluates against Chicago time via `Intl` API.
- **Spotlight no-image placeholder** — dynamically built spotlight cards now render the same `event-placeholder` div as the static card template, including `event--no-image` class and `data-category` attribute.
- **Replay Andersonville images** — events page uses Elementor; static HTML has only logo `<img>` tags. Event card images are JavaScript-rendered. Added `use_playwright: true` to config; Playwright renders 7–8 event images including Karaoke (#6) and Trivia (#7).
- **Plausible analytics** — script in `<head>` of both public templates with `async` and `data-domain="aville.net"`. Verification passed after two fixes: (1) `async` was incorrectly changed to `defer` during implementation — Plausible v2 custom scripts require `async`; (2) domain was registered as `aville.com` in Plausible settings, updated to `aville.net`.
- **Share tracking** — `plausible('Share', { props: { event_slug, business } })` fires on every share button click before the native share sheet or clipboard copy. Counts intent. `event_slug` is the DB id (matches `/event/{id}/` URL). Business read from parent `article[data-business]` on index; from `data-business` attribute added to button on detail page.

### Known behavior note
Node.js 20 deprecation in GitHub Actions — `actions/checkout`, `setup-python`, `upload-artifact` will stop working June 2026. Not urgent but worth a session soon.

### In flight / incomplete
- Not applicable.

### Next session candidates
1. Add more businesses — content is thin for the Planner view (date buckets need density). Target 4–7 new venues.
2. Node.js 20 deprecation in Actions — bump action versions before June 2026.
3. Visual polish pass — missing design tokens (`#5a3d00`, `#f0dc5a`, `#c8dff0`) still as bare hex in both index and detail templates.

**Workflow note:** Both pipeline config (businesses.yaml, images.py) and templates changed → **Scheduled extraction + deploy** triggered (run 24644781076). Site rebuild also triggered twice for template-only changes (runs 24644865134, 24644909883).

---

## 2026-04-19 (visual redesign)

### Summary
Applied full Andersonville visual theme across all three templates. Design system: Swedish blue (`#006AA7`) + flag yellow (`#FECC02`) Nordic cross motif (yellow left stripe on `html`, yellow bottom border on blue header band), Albert Sans variable font (weights 300–800), yellow throughout (filter pills, h2 dividers, bucket headings, price badges, footer), blue-tint placeholders and tag pills. All neighborhood-specific values isolated in `:root` CSS custom properties for future theme swaps.

Also fixed a layout regression caught in code review: the `main {}` max-width/padding rule was accidentally dropped from the CSS replacement block.

### Commits
- `83de310` — feat: apply Andersonville visual theme to index.html
- `9f49013` — fix: restore main element max-width and padding rule
- `fc09c8e` — fix: add container-type to event placeholder for cqi font sizing
- `0b287b3` — feat: apply Andersonville visual theme to event detail page
- (rebased on top of d90f2da from scheduled extraction that ran between sessions)

### Decisions made
- Yellow accessibility rule: `#FECC02` used only as background/border — never as text color (fails WCAG on white). Text ON yellow uses `--yellow-dark: #3a2800`.
- Nordic cross without a literal flag: CSS borders form the right half of the cross — `html { border-left }` + `.site-header-band { border-bottom }`.
- `_event_detail.html` has its own fully independent stylesheet (not shared with `index.html`) — required a complete separate rewrite.
- `container-type: inline-size` on `.event-placeholder` in CSS (detail page) vs. inline style (card template) — both enable `5cqi` container query units for responsive placeholder title sizing.

### Known behavior note
Two minor design token gaps noted in review but deferred: `#5a3d00` (stale notice / spotlight label amber text) and `#f0dc5a` / `#c8dff0` (mid-tone border values) appear as bare hex in both `index.html` and `_event_detail.html` — not in `:root`. Non-functional, deferred to future polish pass.

### In flight / incomplete
- Not applicable.

### Next session candidates
1. Add 4–7 more businesses (top priority — date buckets and spotlight become much more valuable with more content).
2. Visual polish: add missing design tokens (`#5a3d00`, `#f0dc5a`, `#c8dff0`) to `:root`; consider `.share-btn` `font: inherit` cleanup in `_event_detail.html`.
3. Node.js 20 deprecation in Actions — bump `actions/checkout`, `setup-python`, `upload-artifact` to Node 24-compatible versions before June 2026.

**Workflow note:** Templates only changed → **Site rebuild** triggered and succeeded (run 24643510709).

---

## 2026-04-19 (session continues)

### Summary
Added Hopleaf Bar (hopleafbar.com) to the extraction pipeline. Required Playwright + `playwright_session()` context manager to handle Cloudflare protection on both page HTML and CDN image downloads. Fixed a long-standing `_extract_json_array` bug where a greedy regex concatenated multiple JSON arrays into invalid JSON.

### Commits
- `f161567` — feat: add Hopleaf, Playwright image downloads, fix JSON parser

### Decisions made
- `playwright_session()` context manager keeps browser alive during image discovery/download — Cloudflare `cf_clearance` cookie carried via `ctx.request.get(url).body()`. Required because CDN images return 403 to plain httpx even after the page loads.
- `discover_and_download()` now accepts `download_fn` override (defaults to `fetch_bytes`). Pipeline and test script pass a Playwright-backed lambda for `use_playwright` pages.
- `_extract_json_array`: replaced `re.search(r"\[.*\]", text, re.DOTALL)` with bracket-depth character-by-character traversal. Finds first complete `[...]` and stops, ignoring trailing content.
- Hopleaf hints instruct Claude to use image filenames as primary event identifiers (section headers are shifted by one post on this WordPress layout).

### Known behavior note
Claude still includes past events in output (TipoPils: Mar 26, Orval: Mar 21) despite explicit hint not to. Claude acknowledges them as past in `notes` but includes them anyway. Pipeline's past-event stale marking handles it — they land as `status='stale'` immediately.

### In flight / incomplete
- Not applicable.

### Next session candidates
- Add 4–7 more businesses across different site technologies (top priority — date buckets and spotlight become much more valuable with more content).
- Node.js 20 deprecation in Actions — bump `actions/checkout`, `setup-python`, `upload-artifact` to Node 24-compatible versions before June 2026.

**Workflow note:** Pipeline code and businesses.yaml changed → run **Scheduled extraction + deploy**. Remember to `git push` first.

---

## 2026-04-19 (overnight)

### Summary
Added `data-event-id` to cards for debugging, fixed end times on dated events, then built the full "Planner + Already Out" feature set: per-event static pages with OG tags, spotlight section (featured → happening now), date-bucketed upcoming events, and share buttons on every card.

### Commits
- `131df68` — Add data-event-id to event cards for debugging
- `52551da` — Show end time on dated events using humandaterange
- `2998508` — Add per-event pages, spotlight section, date buckets, and share buttons
- `46953d9` — Hide happening-now events from dated buckets; collapse empty buckets

### Decisions made
- `data-event-id` on each `<article>` — lets Justin inspect any card and report the ID for DB lookups.
- End times on dated events: `_humandaterange(start, end)` global (parallel to `humanrange`) — `end_datetime` was already in DB, template just wasn't using it.
- Per-event static pages at `/event/{id}/index.html` — Option B over SPA routing. OG tags work for iMessage/Slack link previews. `<base href="/">` fixes relative paths. Stale events get smart tombstone: "This event has passed" + related active events from same business.
- Date bucketing is **build-time Python** (not client-side JS as originally proposed) — cleaner for a static site, no flash of unsorted content. Buckets: Today / This Weekend (nearest Fri–Sun) / Coming Up.
- Spotlight priority: manually `featured` events (DB flag, never overwritten by pipeline) → happening now (Chicago time via `Intl` API) → hidden. `data-show-when-empty="false"` attribute is the toggle hook for future empty-state behavior.
- `spotlight-hidden` CSS class (separate from tag-filter `.hidden`) — prevents tag filter's "All" button from un-suppressing spotlight events.
- `featured` column (`INTEGER DEFAULT 0`) added to events schema; ALTER TABLE migration run on live DB; pipeline never touches it.
- User Stories section added to CLAUDE.md.

### Known behavior note
Date buckets look unchanged with the current dataset: "Today" has 1 event (id=45) which gets suppressed into spotlight when happening; "This Weekend" has 0 events; only "Coming Up" (6 events) is visible. Will become meaningful once more businesses are added.

### In flight / incomplete
- Not applicable.

### Next session candidates
- Add 4–7 more businesses across different site technologies (top priority — date buckets and spotlight become much more valuable with more content).
- Node.js 20 deprecation in Actions — bump `actions/checkout`, `setup-python`, `upload-artifact` to Node 24-compatible versions before June 2026.

**Workflow note:** Templates, site_builder.py, and DB schema changed → Site rebuild triggered and succeeded (run 24640685156, 46953d9 follow-up run 24640759979).

---

## 2026-04-19 (very late night)

### Summary
Humanized all time and date formatting site-wide, fixed the last-Friday recurrence pattern end-to-end, added a "Last updated" header line, and documented audience conventions in CLAUDE.md.

### Commits
- `1218f6b` — Add Audience and conventions section to CLAUDE.md
- `08bcba6` — Add 'Last updated' line to header using most recent extraction timestamp
- `81387a1` — Humanize time, recurrence, and date formatting in event cards
- `abf329a` — Add monthly:last-{day} recurrence pattern; fix The 80s event in DB

### Decisions made
- Formatting logic lives entirely in `site_builder.py` as Python functions registered as Jinja2 filters/globals — DB stays ISO/24h throughout.
- `humanrange` is a global function (not a filter) because it needs two arguments: `{{ humanrange(e.start_time, e.end_time) }}`.
- "Last updated" uses `MAX(last_extracted_at)` in Chicago time via `zoneinfo.ZoneInfo("America/Chicago")` — correct for DST automatically.
- `monthly:last-{day}` was a known gap: added to the extraction prompt, fixed The 80s in DB directly (was `monthly:4th-friday`), updated CLAUDE.md Atmosphere notes and removed open-question bullet.

### Before / after (one event)
| | Before | After |
|---|---|---|
| MHT Karaoke Cabaret | `weekly:thursday` · `21:00–01:00` | `Every Thursday · 9pm–1am` |
| Atmosphere The 80s | `monthly:4th-friday` · `21:00` | `Last Friday of the month · 9pm` |
| Replay Panic! at the Karaoke | `2026-04-20 21:00` | `Monday, April 20 · 9pm` |

### In flight / incomplete
- Not applicable.

### Next session candidates
- Add 4–7 more businesses across different site technologies (top priority for v1 growth).
- Node.js 20 deprecation in Actions — bump action versions before June 2026.

**Workflow note:** Templates and `site_builder.py` changed → Site rebuild triggered and succeeded (run 24639418103).

---

## 2026-04-19 (late night, design round 2)

### Summary
Fixed broken alt text (no-link image path missed), reduced card image area to 4:5, and added zine-style placeholder for no-image events.

### Commits
- `ab9df46` — Zine-style placeholder for no-image events: business name, rule, large title
- `95dffcf` — Reduce image container to 4:5 aspect ratio for better mobile card height
- `7f82ac0` — Fix alt text: no-link img path was missed in earlier edit

### Decisions made
- Alt text bug root cause: the earlier `replace_all` edit only matched the `<img>` inside the `<a>` tag (10-space indent); the standalone `<img>` (8-space indent) was a different string and wasn't replaced. Replay events have `external_link` set so they hit the updated path; all other businesses don't, explaining why only Replay showed rich alt text.
- Placeholder uses `clamp(1.1rem, 5cqi, 1.75rem)` with `-webkit-line-clamp: 3` — handles both short titles ("House Party") and long ones ("Madonnarama: Confessions II First Listen Live") without overflow.
- Left border on `.event--no-image` retained alongside placeholder — placeholder carries the visual weight in the image area; border provides the category accent signal at the card edge.

### In flight / incomplete
- `5cqi` (container query inline size) has broad but not universal browser support. Falls back gracefully to `1.1rem` on older browsers — acceptable for this audience.

### Next session candidates
- Add 4–7 more businesses across different site technologies (top priority for v1 growth).
- Node.js 20 deprecation in Actions — bump `actions/checkout`, `setup-python`, `upload-artifact` to Node 24 compatible versions before June 2026.

**Workflow note:** Templates and CSS only → Site rebuild triggered and succeeded (run 24638579678, 17s).

---

## 2026-04-19 (late night, addendum)

### Summary
Fixed site-rebuild workflow bug (rsync `--delete` was wiping server images); confirmed `gh` CLI available and authenticated.

### Commits
- `f5ae7b8` — Update CLAUDE.md: gh CLI now installed and authenticated
- `f3fc35b` — Fix site-rebuild: exclude images/ from rsync to preserve server-side images

### Decisions made
- Site-rebuild rsync now uses `--exclude='images/'` — images live on the server only (not in the repo), so site-rebuild should never touch that directory. The scheduled workflow is unaffected (it re-downloads images before deploying).

### In flight / incomplete
- Not applicable.

### Next session candidates
- Add 4–7 more businesses across different site technologies (top priority for v1 growth).
- Node.js 20 deprecation warning appeared in Actions output — actions/checkout@v4, setup-python@v5, upload-artifact@v4 will need Node 24 variants by June 2026. Low urgency for now.

**Workflow note:** Site rebuild triggered and succeeded (run 24638220457, 16s). Images restored on aville.net.

---

## 2026-04-19 (late night)

### Summary
Added a lightweight site-rebuild workflow, documented workflow dispatch decision rules in CLAUDE.md, and updated handoffs.md instructions to include workflow status in each entry.

### Commits
- `04ecabc` — Add workflow note requirement to handoffs.md session instructions
- `1b2719a` — Document workflow dispatch decision rule; note gh CLI not installed
- `bb993db` — Add site-rebuild workflow: manual redeploy without re-extraction

### Decisions made
- Site-rebuild workflow is `workflow_dispatch` only — no schedule, 5-minute timeout. No DB commit step (nothing to commit — DB is unchanged).
- `gh` CLI is not installed locally; manual triggers require the GitHub Actions tab. Documented in CLAUDE.md so future sessions don't waste time trying to use it.

### In flight / incomplete
- Site-rebuild workflow is new and untested end-to-end. The logic mirrors the deploy step from `scheduled.yml` exactly, but it hasn't run on a real Actions runner yet.

### Next session candidates
- Trigger the "Site rebuild" workflow manually from GitHub Actions tab to verify it works end-to-end (this session's changes touched templates and site_builder — a site rebuild is warranted).
- Add 4–7 more businesses across different site technologies.

**Workflow note:** Templates and CSS changed this session → trigger **Site rebuild**. Not triggered yet (`gh` not available; use the Actions tab).

---

## 2026-04-19 (night)

### Summary
Event card design fixes: letterbox portrait images instead of cropping, and proper typographic treatment for no-image events.

### Commits
- `f5c0de7` — No-image events: category-tinted left border, larger title, no broken image area
- `ac16041` — Letterbox event images: 3:4 portrait container, object-fit contain, dark warm background

### Decisions made
- **3:4 over 2:3** for the image container — 2:3 is more cinematic but makes mobile cards too tall; 3:4 shows portrait flyers fully (0.61–0.67 ratio fills ~85–90% of the container) while keeping scroll distance reasonable on phones.
- **`#1e1612`** for the letterbox background — dark warm brown stays in the existing cream/brick-red/bronze palette register rather than using a cold black.
- **Left border via CSS custom property** (`--no-image-accent`) so category-specific color is a single override per category, with `var(--border)` as the default fallback for unknown categories.

### Before / after observations
- **Before:** Atmosphere and Bar Roma portrait flyers (0.61–0.65 ratio) were cropped to roughly the top 40% in the 16:10 container — dates and key info at the bottom of flyers were invisible.
- **After:** All flyers render fully. Landscape images (MHT, Replay — 1.78:1) have dark horizontal bars top and bottom; reads as intentional framing.
- **No-image events:** Were visually broken (card with no image area, content starting at the top). Now have a 4px left accent border (brick-red for bars, warm umber for restaurants) and a slightly larger title, making them look like a deliberate text-first card variant.
- 10 no-image events in the current DB, all Replay Andersonville drink specials (`data-category="bar"`).

### In flight / incomplete
- Not applicable this session.

### Next session candidates
- Verify on aville.net that letterbox and no-image cards look correct on mobile (next Actions deploy).
- Add 4–7 more businesses across different site technologies.
- Confirm the first post-optimization Actions run succeeded (images now re-encoded as webp).

---

## 2026-04-19 (late evening)

### Summary
Image optimization (resize + webp re-encode) and richer alt text on event image cards.

### Commits
- `3a67d27` — Richer alt text on event images: title, business name, truncated description
- `9f99f34` — Optimize scraped images: resize to max 1200px, re-encode as webp at 82% quality

### Decisions made
- `digest` for filenames is still hashed from original `raw` bytes (not optimized), so filenames are stable and tied to source content, not optimization parameters.
- All images now stored as `.webp` regardless of source format — existing `.jpg`/`.png` cached files are orphaned but harmless; wipe `public/images/` to clean up.
- Alt text uses Jinja2's `truncate(100, false, '…')` on `description`; guarded by `{% if e.description %}` so events with no description get `"Title at Business"` only.

### Before/after file sizes (three representative images)
| Image | Original | Optimized | Reduction |
|---|---|---|---|
| Atmosphere Inferno flyer (1650×2550 jpg) | 329 KB | 115 KB | 65% |
| Vincent food photo (1280×720 png) | 1.8 MB | 49 KB | 97% |
| Vincent event flyer (323×484 png, no resize) | 105 KB | 27 KB | 75% |

### In flight / incomplete
- Existing cached images in `public/images/` are now orphaned (old `.jpg`/`.png` filenames). They won't be served (DB points to new `.webp` paths) but take up disk space. A one-time `rm -rf public/images/` + pipeline re-run cleans this up.
- First Actions run after this change will re-download and re-encode all images (one-time cost).

### Next session candidates
- Verify the first post-optimization Actions run succeeds and image sizes on aville.net are visibly smaller.
- Add 4–7 more businesses across different site technologies.
- Consider a one-time `rm -rf public/images/` in the Actions workflow to purge orphaned originals (low priority).

---

## 2026-04-19 (evening)

### Summary
CLAUDE.md restoration and cleanup: added top-level project framing, removed SSH diagnostics, documented last-Friday recurrence limitation, and established handoffs.md format with priority ordering.

### Commits
- `092d852` — Document known limitation with last-Friday recurrence pattern
- `e5689e4` — Document priority ordering for handoffs next-session items
- `fd6c14f` — Remove verbose SSH diagnostics from deploy step
- `9686e5b` — Restore top-level sections lost from CLAUDE.md
- `0c4ecf5` — Establish handoffs.md for session continuity

### Decisions made
- CLAUDE.md top-level sections (title, project purpose, current scope) were never in git history — ported summary from README.md rather than restoring from a prior version.
- Drift log updated to record that SSH diagnostics were removed (rather than deleting the log entry entirely).

### In flight / incomplete
- Not applicable this session.

### Next session candidates
- Image optimization: resize scraped images to max 1200px wide, convert to webp at ~80% quality in `src/images.py` after the download step (site loads noticeably slowly; three image-heavy businesses now deployed).
- Verify the first post-cleanup Actions run succeeds end-to-end (diagnostic removal is a small but real workflow change).
- Add 4–7 more businesses across different site technologies (next natural growth step for v1).

---

## 2026-04-19 (afternoon)

### Summary
Added Playwright support for JS-rendered sites, added three businesses (Replay Andersonville, Atmosphere, Vincent), and implemented pipeline-wide past-event stale marking.

### Commits
- `bc2d096` — chore: update event DB after full pipeline run with Playwright support
- `0b56bec` — Task 8: end-to-end verification, fix networkidle flakiness, update CLAUDE.md
- `a6ad160` — Update Vincent config: use_playwright, rewrite hints for modal
- `5dcc32b` — Install Playwright Chromium in GitHub Actions
- `86c85c8` — Honor use_playwright flag in test_extraction.py
- `b4e1002` — Add Playwright dispatch and past-event stale marking to pipeline
- `835222c` — Add fetch_html_playwright for JS-rendered pages
- `c93b2f3` — Add playwright dependency; update README install instructions
- `a6e85d9` — Parameterize status in upsert_event (was hardcoded 'active')
- `9e61e92` — Add Vincent; document Wix/Playwright limitation in CLAUDE.md
- `9ab28f0` — Add Atmosphere; fix protocol-relative URLs and JSON fence stripping

### Decisions made
- `use_playwright: true` is a per-page flag in `businesses.yaml` — routes that page through headless Chromium instead of httpx. No code changes needed to add future JS-rendered sites.
- `wait_until="load"` + 5s `wait_for_timeout` instead of `networkidle` for Playwright — Wix emits continuous background XHR/WebSocket traffic that prevents `networkidle` from ever firing.
- Past-event stale marking runs pipeline-wide (not just Vincent): any extracted event with `start_datetime` in the past is immediately set to `status='stale'` before upsert.
- Atmosphere dedup strategy: home page = recurring events only, upcoming events page = dated one-offs only. Enforced via hints.

### In flight / incomplete
- GitHub Actions hasn't run yet with Playwright support — first real test of `playwright install chromium --with-deps` on Ubuntu will be the next scheduled run (daily at 11:00 UTC).
- SSH deploy diagnostics are still in `.github/workflows/scheduled.yml` (echo statements printing SSH_KEY length/boundary chars). Remove once deployment is confirmed working end-to-end.

### Next session candidates
- Confirm the GitHub Actions run succeeded with Playwright (check Actions tab after 11:00 UTC).
- Remove SSH diagnostic echo lines from the deploy step once deployment is confirmed.
- Image optimization: resize scraped images to max 1200px / webp 80% in `src/images.py` (site loads slowly on first visit — noted in CLAUDE.md open questions).

---
