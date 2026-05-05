# Per-business notes

Per-business context that isn't derivable from `config/businesses.yaml` or the site
structure alone. Extracted from `CLAUDE.md` on 2026-05-05 to keep the always-loaded
project brief lean. Read this before touching extraction logic for any of the
businesses below.

## Replay Andersonville (`replay-andersonville`)

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

## Atmosphere (`atmosphere`)

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

## Vincent (`vincent`)

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

## Hopleaf Bar (`hopleaf`)

- **Platform:** WordPress, Cloudflare-protected. Requires `use_playwright: true` for both page HTML and CDN image downloads (Cloudflare blocks plain httpx — returns 403 even on images). The `playwright_session()` context manager keeps the browser alive during image discovery so the `cf_clearance` cookie is used for CDN requests.
- **Events source:** Home page only (`hopleafbar.com/`). Events are blog posts with flyer images. Hopleaf has no recurring entertainment — everything is a dated one-off (Zwanze Day, Orval Day, TipoPils Day, tap takeovers, brewery anniversaries).
- **Section header drift:** This WordPress layout shifts headings by one post — each image's nearest `section_header` is from the *previous* blog post, not its own. Image filenames are reliable: `TipoPils` → TipoPils Day, `ZAWNZE` → Zwanze Day (Cantillon lambic, **not** Orval), `OrvalDay` → Orval Day. Hints instruct Claude to use filenames as primary identifiers.
- **Past events:** Claude includes past events in output despite the hint (acknowledges them as past in `notes` but still returns them). Pipeline's past-event stale marking catches them — they land as `status='stale'` immediately.
- **Upcoming Events page** (`hopleafbar.com/upcoming-events/`) — not yet scraped. Low priority since the home page covers upcoming events adequately.

## SoFo Tap (`sofo-tap`)

- **Platform:** Squarespace. Owned by same company as Meeting House Tavern.
- **Three pages scraped:**
  - `/specials` — server-side rendered, no Playwright. Happy hour text + a specials promo image (`SFT_WebSpecials` filename). Each day's special extracted as a separate recurring event.
  - `/events` — `use_playwright: true`. Squarespace calendar is JavaScript-rendered; static HTML returns empty event list. Known recurring events: GRRR (Fri), DILF, KOK, Bear Trap, Doggy Days (Sat afternoon), Sunday Funday (Sun afternoon), Bearaoke (Sun night), Nerd Bear Trivia (Wed).
  - `/events-2` — server-side rendered, no Playwright. Special IML 2026 (International Mr. Leather, Memorial Day weekend) page with 4 dated one-off events. Eventbrite-ticketed; no prices on page.
- **Cloudinary image URLs:** SoFo Tap serves flyer images from Cloudinary (`res.cloudinary.com`) via paths like `/saas/logos/image_xxx.webp`. The `saas/logos/` directory name previously matched the `logo` pattern in `SKIP_FILENAME_PATTERNS` and silently dropped all flyers. Fixed 2026-04-19: pattern now checked against filename only, not the full URL path. See Gotchas in `CLAUDE.md`.
- **Duplicate risks managed:**
  - `Daily Specials` catch-all (recurrence: daily) — hint explicitly says not to extract it.
  - Sunday Happy Hour ($3 shots + hot dogs) duplicated SUNDAY FUNDAY. Deleted from DB; hint updated: extract Sunday *drink* specials only, not the hot dog food component.
- **Day-of-week anchors in hints** — BEARAOKE is Sunday (not Saturday). Extraction model miscalculated once; explicit hint anchors added to prevent recurrence.

## Carol's Pub (`carols-pub`)

- **Extraction URL:** Use `https://www.carolspub.com/` (homepage), NOT `/music.html`.
  The music page shows the full historical archive from Feb 2025 onward, causing the
  pipeline to extract only stale past events. The homepage shows only the upcoming
  schedule. Fixed 2026-04-20.

## Chicago Magic Lounge (`chicago-magic-lounge`)

- **Platform:** Squarespace, server-side rendered. No Playwright needed.
- **Show structure:** Recurring shows by day of week — Mon (Close-Up Show), Tue (Showcase), Wed (Intimo, Luis Carreon solo), Thu–Sun (Signature Show), Daily at 5pm (Performance Bar, non-ticketed). Performers rotate weekly; the show titles/schedules are stable.
- **No times or prices on site:** Show times and ticket prices are handled by ThunderTix (external ticketing, returns 403 — can't scrape). Leave `start_time` and `price_info` null for show events. **After each extraction, set times manually via sqlite3** — check chicagomagiclounge.com for current show times and update with: `UPDATE events SET start_time='HH:MM' WHERE business_id=... AND title LIKE '...'`.
- **Ticketing:** ThunderTix at `chicagomagicloungellc.thundertix.com` — returns 403 to plain httpx. Not scraped.
- **Classes page:** `/classes` has dated Chicago Magic College workshop series. Extract with start/end dates, price, and instructor details.
- **Future show:** "52 Lovers" scheduled Wednesdays from July 1, 2026. Extract if visible as a future recurring event.
