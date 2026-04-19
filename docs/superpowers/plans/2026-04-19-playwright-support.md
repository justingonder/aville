# Playwright Support + Past-Event Stale Marking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `use_playwright: true` per-page flag that routes JS-rendered pages through a headless Chromium fetcher, and immediately mark any extracted dated event whose `start_datetime` is in the past as `status='stale'`.

**Architecture:** A new `fetch_html_playwright()` in `fetcher.py` mirrors the existing `fetch_html()` signature. `pipeline.py` and `test_extraction.py` each dispatch based on `page.get("use_playwright")`. Past-event stale marking runs in `pipeline.py` after every extraction — not just for Vincent. `db.py`'s `upsert_event` is fixed to accept `status` as a parameter rather than hardcoding `'active'`.

**Tech Stack:** `playwright>=1.40.0` (sync API, headless Chromium), existing httpx/SQLite/Claude stack unchanged.

---

## File Map

| File | What changes |
|---|---|
| `src/db.py` | Replace two hardcoded `'active'` literals in `upsert_event` with `:status` |
| `src/fetcher.py` | Add `fetch_html_playwright(url)` |
| `src/pipeline.py` | Import new fetcher; add dispatch block; add past-event stale marking |
| `scripts/test_extraction.py` | Mirror dispatch logic so `use_playwright` pages work in testing |
| `requirements.txt` | Add `playwright>=1.40.0` |
| `.github/workflows/scheduled.yml` | Add Playwright browser install step |
| `config/businesses.yaml` | Add `use_playwright: true` to Vincent page; rewrite hints |
| `README.md` | Add `playwright install chromium` to quickstart |

---

## Task 1: Parameterize `status` in `upsert_event`

**Files:**
- Modify: `src/db.py:190` (UPDATE query) and `src/db.py:221` (INSERT query)

`upsert_event` currently hardcodes `status = 'active'` in both branches. Setting `ev["status"] = "stale"` in `pipeline.py` before calling it would be silently ignored. Fix both SQL statements to use `:status`.

- [ ] **Step 1: Edit the UPDATE branch** — replace the hardcoded literal at line 190

Open `src/db.py`. In the `if existing:` branch, change:
```python
                status             = 'active',
```
to:
```python
                status             = :status,
```

- [ ] **Step 2: Edit the INSERT branch** — replace the hardcoded literal at line 221

In the `INSERT INTO events` statement, change:
```python
            :confidence, :raw_extraction, 'active',
```
to:
```python
            :confidence, :raw_extraction, :status,
```

- [ ] **Step 3: Verify the diff looks correct**

```bash
git diff src/db.py
```

Expected: exactly two lines changed — both replacing `'active'` with `:status`. No other changes.

- [ ] **Step 4: Commit**

```bash
git add src/db.py
git commit -m "Parameterize status in upsert_event (was hardcoded 'active')"
```

---

## Task 2: Add Playwright to dependencies and README

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`

- [ ] **Step 1: Add playwright to requirements.txt**

Add this line at the end of `requirements.txt`:
```
playwright>=1.40.0
```

- [ ] **Step 2: Install it**

```bash
pip3 install playwright
playwright install chromium
```

Expected: playwright installs cleanly; `playwright install chromium` downloads the Chromium binary (printed to stdout, ~150MB).

- [ ] **Step 3: Update README quickstart**

In `README.md`, find the install section (around line 83):
```markdown
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Change it to:
```markdown
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # needed for JS-rendered sites (e.g. Wix)
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt README.md
git commit -m "Add playwright dependency; update README install instructions"
```

---

## Task 3: Add `fetch_html_playwright` to `fetcher.py`

**Files:**
- Modify: `src/fetcher.py`

The function must return the same `(html, content_hash, status_code)` tuple as `fetch_html()`. It uses the synchronous Playwright API, keeps the codebase fully synchronous, and imports `sync_playwright` lazily (inside the function) so the module loads even on machines where Playwright binaries haven't been installed yet.

- [ ] **Step 1: Add the function**

Open `src/fetcher.py`. After the existing `fetch_html` function, add:

```python
def fetch_html_playwright(url: str, timeout: float = 30.0) -> tuple[str, str, int]:
    """Fetch fully JS-rendered HTML using a headless Chromium browser.

    Same return signature as fetch_html(). Use for pages where meaningful
    content (modals, dynamic sections) is injected by JavaScript after load.
    Waits for networkidle before capturing HTML so JS-rendered content is
    present in the DOM.
    """
    from playwright.sync_api import sync_playwright  # lazy import

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            pw_page = browser.new_page()
            pw_page.set_extra_http_headers({"User-Agent": USER_AGENT})
            pw_page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            html = pw_page.content()
        finally:
            browser.close()

    content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    return html, content_hash, 200
```

- [ ] **Step 2: Smoke-test the function directly**

```bash
python3 -c "
from src.fetcher import fetch_html_playwright
html, h, status = fetch_html_playwright('https://www.vincentchicago.com/')
print('status:', status)
print('hash:', h[:16])
print('html length:', len(html))
print('modal in html:', 'modal' in html.lower() or 'popup' in html.lower() or 'wix' in html.lower())
"
```

Expected output (values will vary, but shape is fixed):
```
status: 200
hash: <16 hex chars>
html length: <number well above 10000>
modal in html: True
```

If `html length` is suspiciously small (under 5000) or `modal in html` is False, the page didn't render — check network connectivity and that `playwright install chromium` completed.

- [ ] **Step 3: Commit**

```bash
git add src/fetcher.py
git commit -m "Add fetch_html_playwright for JS-rendered pages"
```

---

## Task 4: Fetcher dispatch + past-event stale marking in `pipeline.py`

**Files:**
- Modify: `src/pipeline.py`

Two changes in one file:
1. Import and dispatch to `fetch_html_playwright` when `page.get("use_playwright")` is set.
2. After `extract_events()` returns, loop events: set `ev.setdefault("status", "active")`, then override to `"stale"` if `start_datetime` is in the past.

- [ ] **Step 1: Update the import line**

Find the existing fetcher import in `pipeline.py`:
```python
from .fetcher import fetch_html
```
Change it to:
```python
from .fetcher import fetch_html, fetch_html_playwright
```

- [ ] **Step 2: Add datetime imports**

Find the existing stdlib imports at the top of `pipeline.py`. Add `datetime` and `timezone`:
```python
from datetime import datetime, timezone
```

- [ ] **Step 3: Replace the fetch call with a dispatch block**

Find this block (around line 48):
```python
                try:
                    html, content_hash, status = fetch_html(page["url"])
```
Change it to:
```python
                try:
                    if page.get("use_playwright"):
                        html, content_hash, status = fetch_html_playwright(page["url"])
                    else:
                        html, content_hash, status = fetch_html(page["url"])
```

- [ ] **Step 4: Add past-event stale marking**

Find the block that begins just after `extract_events()` returns (around line 82):
```python
                print(f"  extracted {len(events)} event(s)")
                default_tags = biz.get("default_tags") or []
                seen_keys: set[str] = set()
                for ev in events:
```

Insert the stale-marking block between `print(f"  extracted {len(events)} event(s)")` and `default_tags = ...`:

```python
                print(f"  extracted {len(events)} event(s)")
                now_dt = datetime.now(timezone.utc)
                for ev in events:
                    ev.setdefault("status", "active")
                    dt_str = ev.get("start_datetime")
                    if dt_str:
                        try:
                            ev_dt = datetime.fromisoformat(dt_str)
                            if ev_dt.tzinfo is None:
                                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                            if ev_dt < now_dt:
                                ev["status"] = "stale"
                        except ValueError:
                            pass
                default_tags = biz.get("default_tags") or []
```

- [ ] **Step 5: Update the log line to show stale prefix**

Find the log line that prints event status (around line 102):
```python
                    mark = "NEW " if action == "inserted" else "upd "
                    print(f"    {mark} [{ev.get('confidence', '?'):>4}] "
                          f"{ev.get('title', '(no title)')}")
```
Change it to:
```python
                    status_label = ev.get("status", "active")
                    if status_label == "stale":
                        mark = "stale"
                    elif action == "inserted":
                        mark = "NEW "
                    else:
                        mark = "upd "
                    print(f"    {mark} [{ev.get('confidence', '?'):>4}] "
                          f"{ev.get('title', '(no title)')}")
```

- [ ] **Step 6: Verify the diff**

```bash
git diff src/pipeline.py
```

Expected changes:
- Import line: `fetch_html` → `fetch_html, fetch_html_playwright`
- New `from datetime import datetime, timezone` import
- Dispatch block wrapping the fetch call
- Stale-marking loop inserted after the `print(f"  extracted...")` line
- Updated log mark logic

- [ ] **Step 7: Commit**

```bash
git add src/pipeline.py
git commit -m "Add Playwright dispatch and past-event stale marking to pipeline"
```

---

## Task 5: Update `test_extraction.py` to honor `use_playwright`

**Files:**
- Modify: `scripts/test_extraction.py`

The test script currently hardcodes `fetch_html` on line 42. Without this change, running `test_extraction.py` against Vincent would still use the static httpx fetcher and miss the modal.

- [ ] **Step 1: Update the import line**

Find line 24:
```python
from src.fetcher import fetch_html  # noqa: E402
```
Change it to:
```python
from src.fetcher import fetch_html, fetch_html_playwright  # noqa: E402
```

- [ ] **Step 2: Replace the hardcoded fetch call**

Find line 42:
```python
    html, _, _ = fetch_html(url)
```
Change it to:
```python
    if page.get("use_playwright"):
        html, _, _ = fetch_html_playwright(url)
    else:
        html, _, _ = fetch_html(url)
```

- [ ] **Step 3: Verify the diff**

```bash
git diff scripts/test_extraction.py
```

Expected: import line updated, single fetch call replaced with two-branch dispatch.

- [ ] **Step 4: Commit**

```bash
git add scripts/test_extraction.py
git commit -m "Honor use_playwright flag in test_extraction.py"
```

---

## Task 6: Add Playwright browser install to GitHub Actions

**Files:**
- Modify: `.github/workflows/scheduled.yml`

- [ ] **Step 1: Add the install step**

Open `.github/workflows/scheduled.yml`. Find the "Install dependencies" step:
```yaml
      - name: Install dependencies
        run: pip install -r requirements.txt
```

Add a new step immediately after it:
```yaml
      - name: Install Playwright browsers
        run: playwright install chromium --with-deps
```

`--with-deps` installs the system libraries Chromium needs on Ubuntu (libgconf, fonts, etc.). This is Linux-only and not needed locally on macOS.

- [ ] **Step 2: Verify the diff**

```bash
git diff .github/workflows/scheduled.yml
```

Expected: one new step block added between "Install dependencies" and "Run extraction".

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/scheduled.yml
git commit -m "Install Playwright Chromium in GitHub Actions"
```

---

## Task 7: Update Vincent config with `use_playwright` and rewritten hints

**Files:**
- Modify: `config/businesses.yaml`

The existing Vincent hint was written when only the httpx fetcher existed ("if no images are found, return the happy hour from page text alone"). Now that Playwright renders the page, the modal's three flyer images will be present. The hints must reflect this new reality.

- [ ] **Step 1: Update the Vincent page entry**

Find the Vincent entry in `config/businesses.yaml`. Replace the entire `pages:` block:

```yaml
    pages:
      - url: https://www.vincentchicago.com/
        kind: home
        hints: >
          Wix site fetched with a headless browser, so the JavaScript-rendered
          modal IS present in the HTML. The modal contains event flyer images —
          expect roughly 3 flyers at time of writing: Happy Hour, a seasonal
          dated special (e.g. Easter Brunch), and a food/drink recurring special
          (e.g. Half Off Mussels). Extract all of them. Happy Hour also appears
          as text in the footer ("Happy Hour Daily 4 - 6pm") — if the same event
          appears in both a flyer image and the footer text, MERGE the information
          from both sources into one event rather than picking one as authoritative;
          each source may contain details the other lacks. Venue hours for context:
          Sun–Thu 4pm–10pm, Fri–Sat 4pm–12am. This is a French bistro — expect
          food and drink specials rather than nightlife events.
        use_playwright: true
```

- [ ] **Step 2: Verify the diff**

```bash
git diff config/businesses.yaml
```

Expected: `use_playwright: true` added, hints block replaced.

- [ ] **Step 3: Commit**

```bash
git add config/businesses.yaml
git commit -m "Update Vincent config: use_playwright, rewrite hints for modal"
```

---

## Task 8: End-to-end test and final verification

Run `test_extraction.py` against Vincent and verify the pipeline handles all three modal flyers correctly, then do a spot-check that past-event stale marking works via the full pipeline.

- [ ] **Step 1: Run test extraction against Vincent**

```bash
python3 scripts/test_extraction.py vincent https://www.vincentchicago.com/ 2>&1
```

Expected in the `[2/3]` output: `kept N image(s)` where N ≥ 3 (the modal flyers). If `kept 0 image(s)`, Playwright didn't render the modal — check that `use_playwright: true` is in the config and the dispatch in `test_extraction.py` was updated.

Expected in the `[3/3]` JSON output — look for all three of:
- A Happy Hour event (`recurrence_pattern: "daily"`, `start_time: "16:00"`, `end_time: "18:00"`)
- An Easter Brunch event (dated, `start_datetime` with a past date — pipeline will mark stale, but test script shows raw extraction)
- A Half Off Mussels (or similar) event

If the Happy Hour appears twice (once from the flyer, once from the footer text), the merge instruction in the hint isn't working — tighten the hint.

- [ ] **Step 2: Verify past-event stale marking via the full pipeline**

Run the full pipeline (this writes to the DB):
```bash
python3 scripts/init_db.py && python3 scripts/run_extraction.py 2>&1 | grep -A2 "Vincent"
```

In the output, Easter Brunch should print with `stale` prefix:
```
    stale [0.9x] Easter Brunch
```

Then confirm in the DB:
```bash
sqlite3 data/app.db "SELECT title, status, start_datetime FROM events WHERE business_id = (SELECT id FROM businesses WHERE slug = 'vincent');"
```

Expected: Easter Brunch row has `status = stale`. Happy Hour and Half Off Mussels have `status = active`.

- [ ] **Step 3: Update CLAUDE.md business notes for Vincent**

In `CLAUDE.md`, find the Vincent section under "Business notes". Replace the current content (which documented the httpx limitation) with the new reality:

```markdown
### Vincent (`vincent`)

- **Platform:** Wix. All content is JavaScript-rendered.
- **Fetcher:** Uses `use_playwright: true` — headless Chromium via `playwright.sync_api`,
  waits for `networkidle` before capturing HTML. Playwright must be installed locally
  with `playwright install chromium` (done once after `pip install -r requirements.txt`).
- **Modal:** A popup fires on every page load (no session/cookie gate) containing ~3 event
  flyer images. As of 2026-04-19: Happy Hour (recurring daily), Easter Brunch (dated, past),
  Half Off Mussels (recurring). The modal is always in the DOM after `networkidle` — no
  dismissal needed.
- **Happy Hour duplication:** Happy Hour appears in both the modal flyer and the footer text.
  The hint instructs Claude to merge both sources into one event.
- **Past-event stale marking:** The Easter Brunch flyer had a past date when first scraped.
  The pipeline's past-event stale marking (added with this feature) immediately sets
  `status='stale'` for any extracted event whose `start_datetime` is in the past.
- **Hours for context:** Sun–Thu 4pm–10pm, Fri–Sat 4pm–12am.
```

- [ ] **Step 4: Commit everything**

```bash
git add CLAUDE.md
git commit -m "Update CLAUDE.md: Vincent now uses Playwright, document modal behavior"
```

- [ ] **Step 5: Push**

```bash
git push
```
