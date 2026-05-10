# Drift log

Session-by-session record of checks where `CLAUDE.md` was verified against actual
code state, plus structural changes to the project that future sessions might
otherwise re-discover the hard way. Extracted from `CLAUDE.md` on 2026-05-05.

Append a new entry to the top of this file whenever a session changes how the
project actually works (schema migrations, workflow rules, deployment quirks,
shipped-feature pointers worth preserving).

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
