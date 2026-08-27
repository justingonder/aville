# Drift log

Session-by-session record of checks where `CLAUDE.md` was verified against actual
code state, plus structural changes to the project that future sessions might
otherwise re-discover the hard way. Extracted from `CLAUDE.md` on 2026-05-05.

Append a new entry to the top of this file whenever a session changes how the
project actually works (schema migrations, workflow rules, deployment quirks,
shipped-feature pointers worth preserving).

- **2026-08-22** — **Doc-fact correction + a CLAUDE.md-vs-reality drift caught.** No code
  was inspected or changed; this was a documentation reconciliation prompted by re-researching
  Instagram access options.
  - **The factual error.** "Instagram/Facebook integration … requires Meta App Review +
    per-business opt-in" (in *What is NOT in scope for v1*) was **wrong on the opt-in half**,
    and has been corrected in place. `business_discovery` lets you query any *public
    professional* account by username with no involvement from the target business; only the
    *direct account access* path (`instagram_basic` et al.) needs each business to
    OAuth-authorize the app. Two facts recorded that were nowhere in the docs before:
    (a) **Stories are unreachable for third-party accounts via any Meta API**, which caps
    what any compliant path can deliver — and a meaningful share of Andersonville flyers are
    Stories-only; (b) *Meta v. Bright Data* (N.D. Cal., Jan 2024) drew the line at
    **logged-out vs. logged-in**, not public vs. private, which is why the 2026-06-07
    experiment's third-party scrape JSON sits on the safer side of it.
  - **The drift (bigger than the correction).** CLAUDE.md still asserted "Websites only — no
    Instagram/Facebook for v1" more than two months *after* the 2026-06-07 IG ingestion
    experiment shipped to main and put 6 curated IG-sourced events on the live site. The
    2026-06-07 session is recorded in `handoffs.md` and its spec/plan, but **never made it
    into this drift log or into CLAUDE.md's scope section**. Both are now updated. Lesson for
    future sessions: a ship that changes *what the project is* needs a drift-log entry, not
    just a handoff entry — handoffs are read for recent context, CLAUDE.md and this file are
    read as standing truth.
  - **Goal restated** in CLAUDE.md's scope section per Justin (2026-08-22): this is a personal
    learning project — explicitly including learning multi-agent systems — Chamber outreach is
    deprioritized, and the binding quality bar is **trust** (never show wrong or outdated event
    info). Several deferred items were re-ranked against that bar; see the 2026-08-22 handoff.
  - **Verified against the live site, not just the docs:** the ~2026-07-13 one-time IG dated-event
    cleanup did run — neither `DAVELAPALOOZA` (6/26) nor `Club Kylie 16 Year Anniversary` (7/12)
    appears on aville.net. That candidate from the 2026-06-07 handoff is closed; the **durable**
    IG-aware expiry pass it called for is still unbuilt.
  - **Two further CLAUDE.md↔code discrepancies found while specced the verification agent
    (not yet fixed — queued into the verification-agent PR):** (a) the "Mobile LCP
    optimization (Shipped 2026-06-04)" entry claims the fix was "pre-rendering spotlight
    cards on the server." It was not — what shipped is build-time **LCP image candidate**
    selection plus a `<link rel="preload" as="image" imagesrcset>` in `<head>`
    (`site_builder.py` ~1872, `templates/index.html` 79–80). Spotlight promotion remains
    entirely client-side in the `isHappeningNow` IIFE. (b) The "Spotlight priority" section
    describes an `#spotlight` element controlled by `data-show-when-empty`; neither appears
    in `templates/index.html` any more. Both matter because they would send a future session
    editing the wrong layer.
  - **Note on the local checkout:** every tracked file in `C:\Dev\aville` carried a 2026-06-09
    mtime at the time of this session, i.e. the working copy was ~2.5 months behind the daily
    Actions commits of `data/app.db` + `public/images/`. `git pull` before trusting local DB
    state or committing doc edits.

- **2026-06-08** — CLAUDE.md reconciled against the shipped highlights + IG-channel state.
  - **Festival → highlights.** CLAUDE.md's "Where things live" entry described
    `config/festival.yaml` + `_festival_state()` as the festival driver and called the
    "Highlights" generalization "designed but not yet built." Neither file/function exists in
    code; the system **shipped 2026-06-04** as `config/highlights.yaml` + `_highlight_state()`
    / `_highlight_phase()` / `_resolve_highlight()` in `site_builder.py` (+ admin curation at
    `templates/admin/highlight_*.html`). `docs/midsommarfest-timing.md` already carried a note
    pointing here; CLAUDE.md did not. Corrected (`d6d5bde`).
  - **IG channel scope drift.** CLAUDE.md still said "Websites only — no Instagram/Facebook"
    and listed IG as fully out-of-scope, but the experimental scrape-JSON ingest shipped
    2026-06-07 (`source_type` column, `PUBLISHED_SOURCE_TYPES`, `scripts/ingest_instagram.py`).
    Updated scope line, "not in scope" line (now: full *Meta-API* integration deferred,
    lightweight channel shipped), schema-migration list (added the missing `source_type`
    migration), and the open-question. Added a `--quarantine` flag this session (`cf3bfad`):
    new IG events land `status='rejected'`, existing rows keep their status via match_key
    lookup; promote = set `active` + lock `status`.
  - **Two new gotchas documented.** (a) `public/index.html` renders **unstyled over
    `file://`** (root-absolute asset paths) — serve over HTTP to preview. (b) A *local* commit
    editing `data/app.db` rebased over the bot's fresh extraction hits a **binary conflict**;
    resolve by taking origin's DB + re-applying your `UPDATE`, not keeping either side
    wholesale. Both hit live this session.
  - **Stale semantics noted.** `status='stale'` still publishes (`all_active_events` is
    `status IN ('active','stale')`); past dated events are filtered from homepage buckets by
    `_is_past_today` regardless. ~212 stale past dated rows remain (deferred bulk cleanup).

- **2026-06-05** — Pipeline now tolerates **manual-only businesses** (no `pages:` key) +
  CI Node-runtime bump.
  - The 6am scheduled extraction crashed with `KeyError: 'pages'` at `src/pipeline.py:156`
    (`for page in biz["pages"]`). Cause: the 2026-06-04 **Lonesome Rose** add deliberately
    omitted `pages:` (manual-only venue — a 0-event scrape would stale its hand-entered
    specials), but the scrape loop assumed every business has the key. Fixed to
    `biz.get("pages") or []` (commit `5116b35`) — matches the idiom already used in
    `admin.py` (which `del`s the key when empty), `ingest_flyer.py`, and the
    backfill/metadata scripts. **Manual-only businesses (no `pages:`) are now an officially
    supported pattern**; never use bare `biz["pages"]` in new pipeline code. Crash aborted
    the run before DB commit-back/deploy, so nothing was lost; recovery re-run
    (`27028623982`) succeeded.
  - Bumped `actions/cache@v4 → @v5` in `.github/workflows/scheduled.yml` (commit `12d3f13`)
    to clear the Node.js 20 deprecation (v5 runs on Node 24; runner ≥ 2.327.1 required,
    GitHub-hosted ubuntu is well past). Only `actions/cache` usage in the repo.

- **2026-06-02** — Schema alignment pass, timezone-aware staleness check, and Git Sync UI feature.
  - Updated the `SCHEMA` constant in `src/db.py` to directly contain the newer columns (`locked_fields`, `alternate_sources`, `starts_on`, `ticket_url`), eliminating database schema drift. This resolved unit test failures in `test_locked_fields.py` and `test_recurrence_normalize.py` that instantiated in-memory test databases using the `SCHEMA` constant directly.
  - Updated consecutive-day range assertions in `test_session3_helpers.py` to match the implemented `"Tue–Wed"` range-collapsing logic in `site_builder.py`.
  - Fixed timezone logic in `src/pipeline.py` to default naive dated-event timestamps to `America/Chicago` (using `ZoneInfo`) instead of `timezone.utc`. This prevents events from being marked stale and hidden 5-6 hours too early.
  - Added a "Sync from Remote" feature in the admin dashboard (`scripts/admin.py` and `templates/admin/dashboard.html`) to pull and rebase (`git pull --rebase origin main`) when local changes are behind or diverged, automatically checking for working-tree cleanliness and aborting gracefully if conflicts occur.

- **2026-05-09 (late)** — Local admin UI shipped (`scripts/admin.py`). Two new pip deps:
  `flask>=3.0.0` (dev-only) and `ruamel.yaml>=0.18.0` (used only by the admin; the
  pipeline still uses `pyyaml` for read-only loads — the two coexist). Refactored
  `scripts/list_series_candidates.py` to expose `find_candidates(conn, ...)` for import;
  CLI behavior unchanged. **Real data drift surfaced** during round-trip testing: three
  `default_tags` (`craft-beer` on hopleaf, `cultural` on multiple, `food-specials` —
  note trailing 's'; `food-special` IS in vocab) and at least two event tags (`food-specials`
  on event 165, `cultural` on event 284) are not in `tags.yaml`. Admin renders them as
  already-selected options + warning so they round-trip cleanly, but they should get
  added to vocab or renamed in a future session. Full feature notes in `docs/shipped.md`.

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

- **2026-04-23** — Per-business landing pages shipped (PR #1). See `docs/shipped.md`.
  Workflow change made this session: switched from direct-to-main commits to feature
  branches (per user request). Saved as a feedback memory; applies to all future
  non-trivial work on this repo.

- **2026-04-27** — Flyer-ingestion pipeline brainstorm started (paused mid-design). New entry "Flyer-ingestion pipeline" added at the top of the Lower-priority section pointing at the DRAFT spec at `docs/superpowers/specs/2026-04-24-flyer-ingestion-pipeline-design.md`. New "Holiday-events representation" entry added to "Open questions / things to decide later". South Andersonville geographic clarification (Clark between Lawrence and Foster counts as Andersonville for aville.net) saved as a project memory. Branch `flyer-ingestion-design` carries these doc updates.

- **2026-04-29** — Design Handoff Session 3 — Phase 1 shipped (PR #4). See
  `docs/shipped.md`. Schema migration: `ADD COLUMN price_short TEXT`. Pre-existing bug
  surfaced this session: `git add -A` is unsafe in this repo because of recurring
  untracked files — caught and reverted before push.

- **2026-05-03** — Three ships: Tower SVG dark-surface refactor (PR #8), Refinement audit
  in four PR batches (PRs #12, #14, #15, #16), Static OSM maps per business (PR #17). See
  `docs/shipped.md`. Plus: re-enabled the `Site rebuild` and `Scheduled extraction +
  deploy` workflows after the 5-02 parking lockdown left them `disabled_manually` (via
  `gh workflow enable`); cron uncommented in `.github/workflows/scheduled.yml`. Excluded
  `design/` from git via `.gitignore` (PR #10) — Claude Design handoff bundles are local
  references, not build inputs.

- **2026-05-04** — Phase 2 (editorial copy + `price_short` backfills) shipped as PRs
  #19 + #20. See `docs/shipped.md`. Follow-up: `scripts/extract_business_metadata.py` is
  the outlier among the metadata scripts — no `load_dotenv` call, fails on a fresh shell
  without ambient `ANTHROPIC_API_KEY`. Backport when next touched.

- **2026-05-05** — CLAUDE.md size optimization. Extracted "Business notes" (107 lines) to
  `docs/businesses.md` and "Drift log" (53 lines) to this file. CLAUDE.md retains short
  pointers in their place. Local pre-trim copy at `CLAUDE.md.backup` (gitignored).
  Remaining trim opportunities flagged in the session: the "Lower priority / future
  pipeline improvements" section in CLAUDE.md still mixes shipped-feature write-ups with
  genuinely deferred items — collapsing the shipped entries to one-liners is the next
  biggest win. **Second pass same-day:** moved shipped-feature implementation detail out
  of the verbose 2026-04-23 / 04-29 / 05-03 / 05-04 drift-log entries into
  `docs/shipped.md` (added new sections for Tower SVG dark-surface refactor, the
  four-batch refinement audit, static OSM maps; augmented Phase 2 + Design Session 3
  entries with the missing detail). Drift-log entries now restricted to short
  shipped-pointers + structural project changes (workflow rules, schema migrations,
  cron/.gitignore updates, durable gotchas).
