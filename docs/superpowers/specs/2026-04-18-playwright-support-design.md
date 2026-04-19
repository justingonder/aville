# Playwright Support + Past-Event Stale Marking

**Date:** 2026-04-18
**Status:** Approved, ready for implementation

## Problem

Some businesses (starting with Vincent, a Wix site) render all meaningful content — including event modals — via JavaScript. The current `httpx`-based fetcher only sees the static HTML shell; modal flyer images and JS-injected content are invisible to it. Vincent is the first business that requires JS execution to extract anything useful.

A secondary problem surfaced during design: dated events whose `start_datetime` has already passed continue to sit in the DB with `status='active'`. The pipeline has no mechanism to immediately stale-mark events extracted from flyers that are already out of date.

## Scope

Four files change. Nothing else is touched.

| File | Change |
|---|---|
| `src/fetcher.py` | Add `fetch_html_playwright(url)` |
| `src/pipeline.py` | Dispatch to correct fetcher; stale-mark past dated events |
| `src/db.py` | Replace hardcoded `'active'` with `:status` in `upsert_event` |
| `requirements.txt` | Add `playwright>=1.40.0` |
| `.github/workflows/scheduled.yml` | Add browser install step |

`config/businesses.yaml` also gets `use_playwright: true` on Vincent's home page entry, and the Vincent hints are rewritten to reflect that images will now be present.

## Design

### `fetch_html_playwright(url)` — `src/fetcher.py`

Uses `playwright.sync_api` (synchronous, matching the rest of the codebase). Steps:

1. Launch headless Chromium via `sync_playwright().start()`
2. Navigate to `url`
3. Wait for `networkidle` — fires when all in-flight network requests have settled, reliably indicating JS-rendered content (including modals) is in the DOM
4. Call `page.content()` to get the fully-rendered HTML
5. Return `(html, sha256(html.encode()), 200)` — identical signature to `fetch_html()`

No modal interaction or dismissal needed. The Vincent modal is always present in the DOM on every page load (no session/cookie gate), so `networkidle` is sufficient to capture it.

The function is ~15 lines. Playwright launches a real browser process, so it is slower than httpx (~3–5s vs ~0.5s). Acceptable for one page per run.

### Fetcher dispatch — `src/pipeline.py`

Replace the single `fetch_html(page["url"])` call with a dispatch block:

```python
if page.get("use_playwright"):
    html, content_hash, status = fetch_html_playwright(page["url"])
else:
    html, content_hash, status = fetch_html(page["url"])
```

`fetch_html_playwright` is imported from `.fetcher` alongside the existing `fetch_html`.

### Past-event stale marking — `src/pipeline.py`

After `extract_events()` returns and before any upsert, check each event's `start_datetime` against the current UTC time. If the datetime is in the past, set `ev["status"] = "stale"`.

```python
now = datetime.now(timezone.utc)
for ev in events:
    dt_str = ev.get("start_datetime")
    if dt_str:
        try:
            dt = datetime.fromisoformat(dt_str)
            if dt < now:
                ev["status"] = "stale"
        except ValueError:
            pass  # malformed datetime — leave status alone
```

This runs for every business on every page, not just Vincent. The pipeline log prints `stale [confidence] Title` for any event immediately shelved, so past flyers are visible in the run output.

`db.py`'s `upsert_event` currently hardcodes `status = 'active'` on both INSERT and UPDATE, so it must be updated to use `:status` as a parameter (with `event.setdefault("status", "active")` in `pipeline.py` to ensure it's always present). No schema changes — the column and its CHECK constraint already support `'stale'`.

### `requirements.txt`

```
playwright>=1.40.0
```

### `.github/workflows/scheduled.yml`

Add one step between "Install dependencies" and "Run extraction":

```yaml
- name: Install Playwright browsers
  run: playwright install chromium --with-deps
```

`--with-deps` installs the system libraries Chromium needs on Ubuntu (libgconf, fonts, etc.). Required for the Actions runner; without it the browser fails to launch.

### Vincent hints update — `config/businesses.yaml`

The existing Vincent hint was written assuming no images would be found (httpx path). It must be rewritten to reflect the Playwright reality:

- Images **will** be found — the modal renders three flyers (Happy Hour, Easter Brunch, Half Off Mussels)
- Happy Hour appears in both a modal flyer image **and** the footer text ("Happy Hour Daily 4–6pm") — Claude should **merge** both sources into one event, not pick one as authoritative
- Easter Brunch has a past date — it will be extracted then immediately marked stale by the pipeline; no hint instruction needed
- Add `use_playwright: true` to the page entry

## Error Handling

`fetch_html_playwright` wraps the browser launch in a try/finally to ensure the browser process is always closed even if navigation or content capture fails. The caller (`pipeline.py`) already wraps `fetch_html` in a try/except that logs and continues — this catch covers the Playwright path too, no changes needed there.

## Local Dev Setup

First-time setup requires two additional commands after `pip install -r requirements.txt`:

```bash
playwright install chromium
```

(`--with-deps` is Linux-only and unnecessary on macOS.) We'll add a note to the README quickstart.

## What This Does Not Change

- `images.py` — image discovery runs identically on Playwright-rendered HTML
- `extractor.py` — Claude call is unchanged
- `db.py` — schema unchanged; only the two hardcoded `'active'` literals in `upsert_event` are replaced with `:status`
- `site_builder.py` — unchanged
- All scripts — unchanged
- The httpx path for all existing businesses — unchanged

## Future

- If more JS-rendered sites are added, `use_playwright: true` in their page config is all that's needed — no code changes.
- If Playwright pages become slow to run serially, consider async Playwright with `asyncio.gather` across JS pages only. Not needed now.
