# Handoffs

Rolling log of Claude Code sessions. Newest at top. Each entry is scoped to
one working session; summarize rather than narrate. For durable project
context, see CLAUDE.md.

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
