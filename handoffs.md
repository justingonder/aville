# Handoffs

Rolling log of Claude Code sessions. Newest at top. Each entry is scoped to
one working session; summarize rather than narrate. For durable project
context, see CLAUDE.md.

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
