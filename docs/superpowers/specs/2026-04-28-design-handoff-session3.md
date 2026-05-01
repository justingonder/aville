# Design Handoff Session 3 — Implementation Spec

**Status:** Final after Q&A on 2026-04-28. Ready to plan.
**Source design package:** `/Users/jgonder/Downloads/design_handoff_session3/`

## Three features

1. **Happy-hours sidebar card** ("Clock strip") — homepage sidebar component listing today's happy hours, sorted by start time, with a `.live` modifier for currently-active rows. Each row shows clock pill + business name + window meta + short-form price.
2. **Page breadcrumb + dateline** ("Stamped dateline") — a thin breadcrumb-plus-dateline strip above the masthead on every interior page (and a brand-only variant on the homepage). Replaces the existing minimal `.top-row` crumbs on business and event pages. Includes a 3-step responsive dateline and `data-short` parent-collapse contract.
3. **Business page editorial hero** ("Editorial") — replaces the current `.masthead-biz` hero on `/business/<slug>/` pages with a magazine-style treatment: kicker line, oversized italic h1, italic lede, action row with "Open until X" live pill, tag chips, and a 3-up image strip.

Acceptance criteria as written in the handoff README apply.

## Authoritative source files

- Handoff README: `/Users/jgonder/Downloads/design_handoff_session3/README.md`
- A1B (happy hours) CSS: `designs/session3-spec-frames.js`, `A1B_CSS` constant.
- B1B (breadcrumb) CSS: `designs/session3-spec-frames.js`, `CRUMB_CSS` constant.
- C1 (business hero) CSS: `designs/session3-frames-c.js`, `C1_CSS` and `c1Body` constants.

## Phasing

**Phase 1 — structural ship (this plan).** All three features live, with placeholder/derived content where editorial fields are missing.

**Phase 2 — editorial backfill (separate plan, deferred).** Claude Haiku script analogous to `extract_business_metadata.py` to draft `tagline`, `vibe_quote`, `about` (2 paragraphs) per business; user reviews/edits. `press[]`, `socials{}`, `branding_images[]` stay manual.

This spec covers Phase 1 only.

## Locked decisions (from 2026-04-28 brainstorm)

### D1. Happy-hours card data source

Server-render the card from `events` rows where `kind='recurring'` AND `'happy-hour' IN tags` AND today's day-of-week falls within the recurrence pattern (or pattern is `daily`). Sort by `start_time` ascending; tie-break alphabetical by business name.

Per row:
- **clock pill text** (e.g. "4–6") — derived from `start_time`/`end_time` via a new helper that drops `:00` when minutes are zero (`16:00-18:00` → `4–6`; `15:30-18:00` → `3:30–6`). En-dash separator (U+2013).
- **business name** — from `events.business_name`.
- **window meta** (e.g. "Daily", "M–F", "Tue–Fri") — derived from `recurrence_pattern` via a new helper.
- **price text** — short-form. NEW field on `events`: `price_short TEXT` (nullable). When null, fall back to first 14 chars of `price_info` (truncated with no ellipsis — short-form is a hard layout constraint). A Phase 2 backfill script can use Haiku to compress existing `price_info` to clean short forms; for Phase 1 we just plumb the column and the fallback.

### D2. Happy-hours / Happening Now interplay

Both surfaces share the same set of "live happy-hour" cards. Visibility is decided client-side by JS:

- Build the existing Happening Now spotlight from non-happy-hour live cards (cards whose `data-tags` does NOT include `happy-hour`).
- Build the happy-hours sidebar card from today's happy-hour-tagged events (server-rendered).
- IF the non-HH spotlight has at least one card → render Happening Now from those cards; show the HH sidebar card (with `.live` modifier on rows whose current time is within their window).
- IF the non-HH spotlight is empty BUT happy-hour-live cards exist → fall back to existing behavior: include happy-hour live cards in Happening Now AND hide the HH sidebar card (so the same data isn't shown twice).
- IF nothing is happening → both stay hidden.

The HH sidebar card is server-rendered. JS only toggles its `hidden` attribute on initial paint, after running the spotlight logic. The `.live` class on rows is also applied client-side based on Chicago-time-now.

### D3. Sidebar placement

When visible, the happy-hours card sits at the **top of the sidebar**, above the existing Filter card. When hidden, the sidebar collapses to its current order (Filter / Weather / Venues / Post-an-event).

### D4. Breadcrumb forms by page

| Page          | Trail                                          | Dateline (≥900px)                                       | Dateline (640–899px)         | Dateline (<640px) |
|---------------|------------------------------------------------|---------------------------------------------------------|------------------------------|-------------------|
| Home          | Single span "Aville.net" (no `.here` highlight, no padding) | `Issue No. NNNN · Wed, April 22, 2026 · Updated 5:30am` | `Issue No. NNNN · Wed Apr 22` | hidden            |
| Business      | `Aville.net → <BusinessName>` (active = biz)    | same                                                     | same                          | hidden            |
| Event         | `Aville.net → <BusinessName> → <EventTitle>`    | same                                                     | same                          | hidden            |

Implementation: render the compact form (`Issue No. NNNN · Wed Apr 22`) as the always-visible content; render the extra `· Wed, April 22, 2026 · Updated 5:30am` portion in a `<span class="dl-extra">` that's `display:none` below 900px. The compact form stays visible in the 640–899px band. Below 640px the entire `.dateline` is `display:none` (info isn't lost — the masthead's `.issue` block still carries it on mobile).

### D5. `data-short` parent-collapse

Below 720px, non-active parent crumbs collapse to a hand-curated short version via the `data-short` attribute. JS swaps `el.textContent = el.dataset.short` on initial paint and on resize past the breakpoint; restores full text on resize back above 720px. Only links in `.trail` are eligible — not `.here`, not separators.

For Phase 1, hand-author `data-short` values in `config/businesses.yaml` via a new optional `short_name` field. Default short-name renderer falls back to `name` itself when `short_name` is absent (so the attribute is always present, ensuring future opt-in is a one-line YAML change).

Currently long enough to need it: **Chicago Magic Lounge** → `Magic Lounge`. Worth backfilling at the same time (one entry).

### D6. Business hero data model

New fields on `config/businesses.yaml` per business:

| Field             | Type   | Required? | Phase | Source                                                                 |
|-------------------|--------|-----------|-------|------------------------------------------------------------------------|
| `tagline`         | string | optional  | 2     | New. ~120 char editorial lede. Claude Haiku drafts; user edits.        |
| `vibe_quote`      | string | optional  | 2     | New. The 28px italic pull quote. Claude drafts; user edits.            |
| `about`           | string | optional  | 2     | New. 2 paragraphs (separated by `\n\n`). Claude drafts; user edits.    |
| `press`           | list   | optional  | 2+    | New. List of `{quote, source, year}` objects. Manual.                  |
| `branding_images` | list   | optional  | 2+    | New. List of relative paths under `public/images/<slug>/branding/`. Manual curation. |
| `display_type`    | string | optional  | 1     | New. Override mapped `category`. Allowed: `Bar`/`Restaurant`/`Cafe`/`Shop`/`Venue`/`Service`. |
| `socials`         | object | optional  | 2+    | New. `{instagram, facebook}` handles. Manual.                          |
| `short_name`      | string | optional  | 1     | New. Breadcrumb `data-short` value. Falls back to `name`.              |

`type` (kicker text) is **derived from `category`** via a mapping table:

```
bar        → Bar
restaurant → Restaurant
cafe       → Cafe
theater    → Venue
museum     → Venue
```

`display_type` overrides the mapping. Validation: the resolved type must be in the allowed list (`Bar`/`Restaurant`/`Cafe`/`Shop`/`Venue`/`Service`); a build-time check raises on unmatched values.

### D7. Hero strip — pure spec, no flyer fallback

When fewer than 3 `branding_images` exist, fill remaining slots with the typographic placeholder per `C1_CSS`: `background: var(--riso-blue)`, italic 18px Fraunces pull quote, `<small>— hero photo placeholder</small>` annotation in mono. **Never falls back to event flyers.**

Phase 1 ships with 0 branding images per business, meaning every business page renders 3 placeholder cells. Visually intentional — pressures curation.

Pull-quote text inside the placeholder uses `vibe_quote` if present, else a single hardcoded default: `"More photos here soon."`. (Once Phase 2 lands `vibe_quote`, the default falls away naturally.)

### D8. "Open until X" pill

Computed at render time from `biz.hours[<today_lowercase>]` (existing format `"HH:MM-HH:MM"`). New helper `format_open_until(hours_str, now_chicago)`:

- Parses the day's range. Handles midnight-crossing closes (close < open means next-day close).
- If `now_chicago` falls within `[open, close)`: returns `"Open until <12-hour time, lowercase am/pm>"` (e.g. `"Open until 10pm"`, `"Open until 2am"`).
- If currently closed: returns `None` (template hides the pill — empty space reads cleaner than rendering `"Closed"`).

Computed on the server based on Chicago time at build, NOT live in JS. The pill goes stale within a day; that's fine — pages are rebuilt daily. Live JS recompute is deferred.

### D9. Existing `.top-row` breadcrumb removal

The current `.top-row` on business and event pages contains a tiny `crumbs` div: `<a href="/">A'ville.net</a> · <b>{name}</b>`. The new "Stamped Dateline" breadcrumb sits *above* the masthead and replaces this minimal crumbs span. The `.top-row` itself stays (it carries the Andersonville live status + weather + Post an event link), with the `.crumbs` div removed.

The new breadcrumb component is a standalone block between `.top-row` and `.mast` on every page.

### D10. CSS organization

Three CSS blocks land:
- `A1B_CSS` (happy-hours card) → `styles/index.css` (homepage-only).
- `CRUMB_CSS` (breadcrumb + dateline) → both `styles/index.css` AND `styles/event.css` (used on every page; deduplication can come later if it bothers us).
- `C1_CSS` (business hero) → `styles/event.css` (covers both event detail AND business detail pages currently — verify by grepping `event_css_href` usage).

The handoff CSS is meant to be lifted as-is (CSS variable names match). Lift verbatim with a normalizing pass: replace double-newlines, drop the `body{padding:18px}` test-frame stylings, convert `var(--slab),Impact` shorthand fallbacks to match existing convention.

## Out of scope for Phase 1

- All editorial copy backfill (`tagline` / `vibe_quote` / `about` / `press` / `socials`) → Phase 2.
- `branding_images` curation → manual, ongoing.
- The `/happy-hours/` index page mentioned by the "+N more" footer link in the spec. Phase 1 keeps the cork-colored `.hh-foot` band as a visual cap with text "All happy hours below ↓" linking to `#regulars` on the homepage (or hide entirely if cleaner). DECISION: render the band with the text "All happy hours on the board ↓" linking to homepage `#regulars` anchor. Easy to swap to a real index page later.
- Live "Open until X" recomputation in JS.
- Phase 2 backfill of `price_short` for existing happy-hour events. Phase 1 uses the `price_info[:14]` fallback; some rows will look ugly until Phase 2.

## Test surface

- **Visual:** rebuild site (`python3 scripts/build_site.py`); spot-check at desktop + mobile:
  - Homepage at 1280 / 720 / 375 viewports.
  - Business page (e.g. `/business/sofo-tap/`) at 1280 / 720 / 375.
  - Event page at 1280 / 720 / 375.
- **Functional happy-hours visibility:** three states — (a) mixed live (HN populated, sidebar visible), (b) only HH live (HN populated from HH, sidebar hidden), (c) nothing live (both hidden). Validate by manipulating system clock or with synthetic event fixture.
- **Functional dateline breakpoints:** load homepage at 1280 (full), 720 (compact), 375 (hidden).
- **Functional `data-short` collapse:** load event detail page where business is Chicago Magic Lounge; resize across 720px; verify text swap.
- **Functional `display_type` validation:** intentionally set `display_type: Garbage` on a business; rebuild; expect a clear error.
- **Build assertion:** `_assert_build()` must still pass after templates change.
- **Unit:** new helpers (`format_clock_pill`, `format_window_meta`, `select_today_happy_hours`, `format_open_until`, `derive_business_type`) under `scripts/test_*.py`.
