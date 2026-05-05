# Drift log

Session-by-session record of checks where `CLAUDE.md` was verified against actual
code state, plus structural changes to the project that future sessions might
otherwise re-discover the hard way. Extracted from `CLAUDE.md` on 2026-05-05.

Append a new entry to the top of this file whenever a session changes how the
project actually works (schema migrations, workflow rules, deployment quirks,
shipped-feature pointers worth preserving).

- **2026-04-18** — Verified two items:
  - `temperature=0.0` **was already set** in `extractor.py` (line 95). CLAUDE.md
    had incorrectly said it was not set. Fixed in CLAUDE.md.
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
  - Vincent section in `docs/businesses.md` reflects Playwright reality.
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

- **2026-05-04** — Phase 2 (editorial copy + price_short backfills) shipped as two independent PRs against `main`, both unmerged at session end. Full chronology in the day's `handoffs.md` entry. Project-state items:
  - **Two new backfill scripts** in `scripts/`. Both idempotent (skip when fields are populated; `--force` to refresh; positional slug/id arg targets one). Both use `load_dotenv(ROOT / ".env")` matching `run_extraction.py` — `extract_business_metadata.py` is the outlier and should be backported next time it's touched (no `load_dotenv`, fails on a fresh shell without ambient `ANTHROPIC_API_KEY`).
  - **`scripts/backfill_price_short.py`** (PR #19) — compresses `events.price_info` to ≤14-char `price_short` via Haiku, with fast-path passthrough when already short and creative compression for long lists. Hard-truncate at 14 chars as a safety net. Backfilled 13 of 22 active happy-hour rows.
  - **HH card layout fix** (PR #19) — original 3-col grid (`46px 1fr auto`) overflowed long biz names. New layout: 2-col grid with the price moved onto the meta-row line via flex `justify-content: space-between` (new `.hh-row .meta-row` rule in `styles/index.css`). Empty `price_short` renders `→` as a "click to learn more" sentinel via `_select_today_happy_hours` enrichment in `src/site_builder.py`; DB stores null.
  - **`scripts/backfill_editorial_copy.py`** (PR #20) — drafts `tagline`/`vibe_quote`/`about` for each business via Haiku. New `EDITORIAL_COPY_PROMPT` + `build_editorial_copy_prompt()` in `src/prompts.py` with explicit anti-fabrication + anti-marketing-voice rules + banned-word list. All 23 businesses backfilled (~$0.50 in Haiku calls). YAML written as flat top-level fields per business: single-quoted strings for `tagline`/`vibe_quote`, literal-block `|` for `about` (paragraph breaks survive). Comment-preserving raw-text editor matches `extract_business_metadata.py`'s pattern.
  - **`_business_detail.html` `.biz-description`** now consumes `biz.about` (split on `\n\n` for separate `<p>`s) with fallback to `biz.metadata.description`. The short metadata description stays as the source for `<meta name="description">` and `og:description` (SEO needs the short form).
  - **8 `vibe_quote`s flagged for hand-editing** in PR #20's description (Atmosphere, Bar Roma, Eli Tea Bar, Elixir, Nobody's Darling, Ranalli's, Sweet Hearts Bar, Uvae). Direct YAML edit is the workflow — `''` to escape apostrophes inside single-quoted strings; literal-block `|` indent rules apply for `about`. Validate with `python3 -c "import yaml; yaml.safe_load(open('config/businesses.yaml'))"`.

- **2026-05-05** — CLAUDE.md size optimization. Extracted "Business notes" (107 lines) to `docs/businesses.md` and "Drift log" (53 lines) to this file. CLAUDE.md retains short pointers in their place. Local pre-trim copy at `CLAUDE.md.backup` (gitignored). Remaining trim opportunities flagged in the session: the "Lower priority / future pipeline improvements" section still mixes shipped-feature write-ups with genuinely deferred items — collapsing the shipped entries to one-liners is the next biggest win.
