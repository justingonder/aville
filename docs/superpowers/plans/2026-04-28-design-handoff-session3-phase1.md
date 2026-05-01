# Design Handoff Session 3 — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the structural changes for the three Session-3 design features — happy-hours sidebar card, stamped-dateline breadcrumb, and editorial business-page hero — with placeholder content where editorial copy hasn't landed yet.

**Architecture:** Lift the handoff CSS verbatim into `styles/index.css` and `styles/event.css`. Add five small render-time helpers to `src/site_builder.py` (clock pill, window meta, today's happy hours selector, open-until pill, business type). Two new Jinja partials (`_breadcrumb.html`, `_happy_hours_card.html`) that the homepage, business detail, and event detail templates compose. Modify the existing Happening Now JS in `templates/index.html` and `templates/_business_detail.html` to filter happy-hour cards. Add `price_short` column to the `events` table (used at render time only — Phase 2 will backfill).

**Tech Stack:** Python 3 (procedural, stdlib-preferred), SQLite, Jinja2, vanilla JS, CSS custom properties. No build step beyond `python3 scripts/build_site.py`.

**Spec:** `docs/superpowers/specs/2026-04-28-design-handoff-session3.md`. The locked decisions D1–D10 in that file resolve every design ambiguity referenced below.

**Branch and PR strategy:** Per the project's "feature branches for non-trivial work" convention, this plan executes on a new branch (`design-handoff-session3-phase1`) cut from `main`. PR #3 (flyer-ingestion) is independent and stays open separately.

---

## File Structure

**Create:**
- `templates/_breadcrumb.html` — Jinja partial. Renders the `.crumbs` block including trail + dateline (compact + dl-extra spans). Takes `crumb_trail` (list of `{label, href, short}` with the last item being the active crumb) and `issue_number` + `build_date` + optional `last_updated` from the parent context.
- `templates/_happy_hours_card.html` — Jinja partial. Renders the sidebar `.hh-card`. Takes `happy_hours` (list of dicts from `select_today_happy_hours()`).
- `scripts/test_session3_helpers.py` — unit tests for the five new helpers in `site_builder.py`.

**Modify:**
- `src/db.py` — add `price_short TEXT` column to `events` schema and add an idempotent `ALTER TABLE` migration call.
- `src/site_builder.py` — add five helpers (`_format_clock_pill`, `_format_window_meta`, `_select_today_happy_hours`, `_format_open_until`, `_derive_business_type`); register `format_clock_pill`, `format_window_meta`, `format_open_until`, `derive_business_type` as Jinja globals; pass `happy_hours` and `crumb_trail` into `index_template.render()` and `_business_detail.html` and `_event_detail.html` render calls; add `display_type` validation guard inside `_build_business_pages`.
- `templates/index.html` — insert breadcrumb partial above masthead; insert happy-hours card partial at the top of the sidebar; modify the existing spotlight IIFE (lines ~430–500) to filter happy-hour cards from the "non-HH" pool, fall back to all cards when non-HH pool is empty, and toggle `#happy-hours-card` visibility accordingly; also add the `.live` class to HH rows whose current Chicago time is within their window; add the `data-short` resize handler.
- `templates/_business_detail.html` — replace the entire `<header class="masthead masthead-biz">…</header>` block with the editorial hero (kicker / h1 / lede / actions / chips / hero strip); insert breadcrumb partial above masthead; remove the inline `.crumbs` div from `.top-row`; modify the spotlight IIFE to mirror the homepage's HH-filter rule.
- `templates/_event_detail.html` — insert breadcrumb partial above masthead; remove the inline `.crumbs` div from `.top-row`.
- `styles/index.css` — append `A1B_CSS` block (happy-hours card) and `CRUMB_CSS` block (breadcrumb).
- `styles/event.css` — append `CRUMB_CSS` block AND `C1_CSS` block (business hero); add a small block scoping the C1 styles to `body.biz-page` (or similar) so they don't apply to event detail pages.
- `config/businesses.yaml` — add `short_name: "Magic Lounge"` to the `chicago-magic-lounge` entry (only existing business name long enough to need it).

---

## Task 1: Add `price_short` column to schema

**Files:**
- Modify: `src/db.py`

- [ ] **Step 1: Read existing schema & migration code**

Read `src/db.py` to find the `SCHEMA` constant and existing `ADD COLUMN` migration calls. Note the pattern used by the prior migrations (`featured`, `performers`, `ends_on`).

- [ ] **Step 2: Add column to SCHEMA constant**

In `src/db.py`, locate the `events` table definition inside `SCHEMA`. Add `price_short TEXT` immediately after the `price_info TEXT` column. Match indentation exactly.

- [ ] **Step 3: Add idempotent migration**

In the `init_db(conn)` function (or wherever existing `ADD COLUMN` migrations live), add:

```python
try:
    conn.execute("ALTER TABLE events ADD COLUMN price_short TEXT")
except sqlite3.OperationalError:
    pass  # column already exists
```

Place it next to the existing `featured`/`performers`/`ends_on` migration calls. Match the pattern used there.

- [ ] **Step 4: Run init script to verify migration**

Run: `python3 scripts/init_db.py`
Expected: no error. The DB already exists; the migration is idempotent and adds the column on the first run, then no-ops thereafter.

Verify with: `sqlite3 data/app.db "PRAGMA table_info(events)" | grep price_short`
Expected: a row showing `price_short` of type `TEXT`.

- [ ] **Step 5: Commit**

```bash
git add src/db.py
git commit -m "feat(schema): add price_short column for happy-hour card"
```

---

## Task 2: Helper — `_format_clock_pill(start_time, end_time)`

**Files:**
- Modify: `src/site_builder.py` (append helper near other `_fmt_*` helpers around line 60)
- Test: `scripts/test_session3_helpers.py`

- [ ] **Step 1: Write the failing tests**

Create `scripts/test_session3_helpers.py`:

```python
"""Unit tests for Session-3 design helpers."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.site_builder import (
    _format_clock_pill,
)


def test_clock_pill_basic_hours():
    assert _format_clock_pill("16:00", "18:00") == "4–6"

def test_clock_pill_keeps_minutes_when_nonzero():
    assert _format_clock_pill("15:30", "18:00") == "3:30–6"
    assert _format_clock_pill("16:00", "18:30") == "4–6:30"

def test_clock_pill_handles_noon_midnight():
    assert _format_clock_pill("12:00", "14:00") == "12–2"
    assert _format_clock_pill("00:00", "02:00") == "12–2"

def test_clock_pill_handles_missing_end():
    # No end time — show start only with em-dash trailing
    assert _format_clock_pill("16:00", None) == "4"

def test_clock_pill_handles_midnight_cross():
    # Just confirms we don't crash; the "4–2" form is correct (next-day close)
    assert _format_clock_pill("16:00", "02:00") == "4–2"

def test_clock_pill_returns_dash_on_garbage():
    assert _format_clock_pill(None, None) == "–"
    assert _format_clock_pill("", "") == "–"


if __name__ == "__main__":
    import sys
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                print(f"  FAIL  {name}: {e}")
                failures += 1
    print(f"\n{failures} failure(s)" if failures else "\nAll passed.")
    sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run the test, expect ImportError**

Run: `python3 scripts/test_session3_helpers.py`
Expected: ImportError because `_format_clock_pill` doesn't exist yet.

- [ ] **Step 3: Implement `_format_clock_pill`**

In `src/site_builder.py`, near the existing `_fmt_time` and `_fmt_hours_range` helpers (around line 60), add:

```python
def _format_clock_pill(start: str | None, end: str | None) -> str:
    """Compact clock-pill text for happy-hours card. '16:00','18:00' -> '4–6'.
    Drops :00 minutes; keeps minutes when non-zero. Uses en-dash."""
    def short(t: str | None) -> str | None:
        if not t or ":" not in t:
            return None
        try:
            h, m = (int(x) for x in t.split(":")[:2])
        except ValueError:
            return None
        h12 = h % 12 or 12
        return f"{h12}" if m == 0 else f"{h12}:{m:02d}"

    s = short(start)
    e = short(end)
    if s and e:
        return f"{s}–{e}"
    if s:
        return s
    return "–"
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 scripts/test_session3_helpers.py`
Expected: 6 PASS lines, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/site_builder.py scripts/test_session3_helpers.py
git commit -m "feat(site): add _format_clock_pill helper for happy-hours card"
```

---

## Task 3: Helper — `_format_window_meta(recurrence_pattern)`

**Files:**
- Modify: `src/site_builder.py`
- Modify: `scripts/test_session3_helpers.py`

- [ ] **Step 1: Append failing tests**

In `scripts/test_session3_helpers.py`, add an import line and new tests:

```python
from src.site_builder import (
    _format_clock_pill,
    _format_window_meta,
)


def test_window_meta_daily():
    assert _format_window_meta("daily") == "Daily"

def test_window_meta_weekdays():
    assert _format_window_meta("weekly:monday,tuesday,wednesday,thursday,friday") == "M–F"

def test_window_meta_weekday_range():
    assert _format_window_meta("weekly:tuesday-friday") == "Tue–Fri"

def test_window_meta_single_day():
    assert _format_window_meta("weekly:sunday") == "Sundays"

def test_window_meta_two_days():
    assert _format_window_meta("weekly:tuesday,wednesday") == "Tue, Wed"

def test_window_meta_weekend():
    assert _format_window_meta("weekly:saturday,sunday") == "Sat–Sun"

def test_window_meta_garbage():
    assert _format_window_meta(None) == ""
    assert _format_window_meta("") == ""
    assert _format_window_meta("monthly:last-friday") == ""
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `python3 scripts/test_session3_helpers.py`
Expected: ImportError on `_format_window_meta`.

- [ ] **Step 3: Implement `_format_window_meta`**

Append to `src/site_builder.py` next to `_format_clock_pill`:

```python
_DAY_FULL_TO_ABBR = {
    "monday": "Mon", "tuesday": "Tue", "wednesday": "Wed",
    "thursday": "Thu", "friday": "Fri", "saturday": "Sat", "sunday": "Sun",
}
_DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _format_window_meta(pattern: str | None) -> str:
    """Compact window meta for happy-hours card.
    'daily' -> 'Daily'; 'weekly:monday,tuesday,wednesday,thursday,friday' -> 'M–F';
    'weekly:saturday,sunday' -> 'Sat–Sun'; 'weekly:sunday' -> 'Sundays'.
    Monthly patterns and unrecognized inputs return ''."""
    if not pattern:
        return ""
    if pattern == "daily":
        return "Daily"
    if not pattern.startswith("weekly:"):
        return ""
    days_part = pattern[7:]
    if "-" in days_part and "," not in days_part:
        # range form 'tuesday-friday'
        try:
            start, end = days_part.split("-", 1)
            return f"{_DAY_FULL_TO_ABBR[start]}–{_DAY_FULL_TO_ABBR[end]}"
        except (KeyError, ValueError):
            return ""
    days = [d.strip() for d in days_part.split(",") if d.strip()]
    # Curated shortcuts
    if days == ["monday", "tuesday", "wednesday", "thursday", "friday"]:
        return "M–F"
    if days == ["saturday", "sunday"]:
        return "Sat–Sun"
    if len(days) == 1:
        # 'Sundays' / 'Mondays' / etc. — use the full day name + 's'
        full = days[0]
        if full in _DAY_ORDER:
            return full.capitalize() + "s"
        return ""
    # 2-3 day list, comma-separated abbreviated form
    try:
        return ", ".join(_DAY_FULL_TO_ABBR[d] for d in days)
    except KeyError:
        return ""
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 scripts/test_session3_helpers.py`
Expected: all tests PASS, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/site_builder.py scripts/test_session3_helpers.py
git commit -m "feat(site): add _format_window_meta helper"
```

---

## Task 4: Helper — `_select_today_happy_hours(events, build_date)`

**Files:**
- Modify: `src/site_builder.py`
- Modify: `scripts/test_session3_helpers.py`

- [ ] **Step 1: Append failing tests**

In `scripts/test_session3_helpers.py`, extend the import line and add tests:

```python
from src.site_builder import (
    _format_clock_pill,
    _format_window_meta,
    _select_today_happy_hours,
)
from datetime import date


def _ev(**kw):
    """Build a synthetic event row dict with sensible defaults."""
    base = {
        "id": 1, "kind": "recurring", "status": "active",
        "tags": ["happy-hour"], "business_name": "Test", "business_slug": "test",
        "recurrence_pattern": "daily", "start_time": "16:00", "end_time": "18:00",
        "price_info": "$5 drafts", "price_short": None,
    }
    base.update(kw)
    return base


def test_happy_hours_filters_non_hh():
    events = [
        _ev(id=1),
        _ev(id=2, tags=["live-music"]),  # not HH
    ]
    result = _select_today_happy_hours(events, date(2026, 4, 28))
    assert [e["id"] for e in result] == [1]


def test_happy_hours_filters_inactive():
    events = [_ev(id=1, status="stale")]
    assert _select_today_happy_hours(events, date(2026, 4, 28)) == []


def test_happy_hours_filters_dated_kind():
    events = [_ev(id=1, kind="dated")]
    assert _select_today_happy_hours(events, date(2026, 4, 28)) == []


def test_happy_hours_today_must_match_recurrence():
    # 2026-04-28 is a Tuesday
    tuesday_event = _ev(id=1, recurrence_pattern="weekly:tuesday")
    monday_event = _ev(id=2, recurrence_pattern="weekly:monday")
    daily_event = _ev(id=3)  # daily
    result = _select_today_happy_hours([tuesday_event, monday_event, daily_event], date(2026, 4, 28))
    assert sorted(e["id"] for e in result) == [1, 3]


def test_happy_hours_sorted_by_start_then_name():
    events = [
        _ev(id=1, start_time="17:00", business_name="Zebra"),
        _ev(id=2, start_time="15:00", business_name="Apple"),
        _ev(id=3, start_time="15:00", business_name="Banana"),
    ]
    result = _select_today_happy_hours(events, date(2026, 4, 28))
    assert [e["id"] for e in result] == [2, 3, 1]


def test_happy_hours_enriches_with_clock_window_price():
    events = [_ev(id=1, start_time="16:00", end_time="18:00",
                  recurrence_pattern="weekly:monday,tuesday,wednesday,thursday,friday",
                  price_info="$5 drafts", price_short=None)]
    result = _select_today_happy_hours(events, date(2026, 4, 28))
    assert result[0]["clock_pill"] == "4–6"
    assert result[0]["window_meta"] == "M–F"
    assert result[0]["display_price"] == "$5 drafts"


def test_happy_hours_uses_price_short_when_set():
    events = [_ev(id=1, price_info="$10 select cocktails", price_short="$10 cocktails")]
    result = _select_today_happy_hours(events, date(2026, 4, 28))
    assert result[0]["display_price"] == "$10 cocktails"


def test_happy_hours_truncates_long_price_info_when_no_short():
    events = [_ev(id=1, price_info="Half off all bottles of wine until 6pm", price_short=None)]
    result = _select_today_happy_hours(events, date(2026, 4, 28))
    assert result[0]["display_price"] == "Half off all b"  # 14 chars, no ellipsis
    assert len(result[0]["display_price"]) <= 14
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `python3 scripts/test_session3_helpers.py`
Expected: ImportError on `_select_today_happy_hours`.

- [ ] **Step 3: Implement helper**

Append to `src/site_builder.py`:

```python
def _select_today_happy_hours(events: list[dict], build_date: date) -> list[dict]:
    """Filter events for the homepage happy-hours sidebar card.

    Returns enriched dicts with clock_pill, window_meta, display_price added.
    Source rows must be active recurring events tagged 'happy-hour'.
    Today's day-of-week must match the recurrence pattern (or pattern is 'daily').
    Sorted by start_time ascending, then business_name alphabetical.
    """
    today_full = _DAY_ORDER[build_date.weekday()]  # Mon=0 → 'monday'

    def matches_today(pattern: str | None) -> bool:
        if not pattern:
            return False
        if pattern == "daily":
            return True
        if not pattern.startswith("weekly:"):
            return False
        days_part = pattern[7:]
        if "-" in days_part and "," not in days_part:
            try:
                start, end = days_part.split("-", 1)
                start_idx = _DAY_ORDER.index(start)
                end_idx = _DAY_ORDER.index(end)
                today_idx = _DAY_ORDER.index(today_full)
                if start_idx <= end_idx:
                    return start_idx <= today_idx <= end_idx
                # wrap-around (e.g. friday-monday)
                return today_idx >= start_idx or today_idx <= end_idx
            except (KeyError, ValueError):
                return False
        days = [d.strip() for d in days_part.split(",")]
        return today_full in days

    selected = []
    for ev in events:
        if ev.get("status") != "active":
            continue
        if ev.get("kind") != "recurring":
            continue
        tags = ev.get("tags") or []
        if "happy-hour" not in tags:
            continue
        if not matches_today(ev.get("recurrence_pattern")):
            continue
        enriched = dict(ev)
        enriched["clock_pill"] = _format_clock_pill(ev.get("start_time"), ev.get("end_time"))
        enriched["window_meta"] = _format_window_meta(ev.get("recurrence_pattern"))
        if ev.get("price_short"):
            enriched["display_price"] = ev["price_short"]
        elif ev.get("price_info"):
            enriched["display_price"] = ev["price_info"][:14]
        else:
            enriched["display_price"] = ""
        selected.append(enriched)

    selected.sort(key=lambda e: (e.get("start_time") or "99:99", (e.get("business_name") or "").lower()))
    return selected
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 scripts/test_session3_helpers.py`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/site_builder.py scripts/test_session3_helpers.py
git commit -m "feat(site): add _select_today_happy_hours selector"
```

---

## Task 5: Helper — `_format_open_until(hours_str, now_chicago)`

**Files:**
- Modify: `src/site_builder.py`
- Modify: `scripts/test_session3_helpers.py`

- [ ] **Step 1: Append failing tests**

In `scripts/test_session3_helpers.py`, extend imports and add tests:

```python
from src.site_builder import (
    _format_clock_pill,
    _format_window_meta,
    _select_today_happy_hours,
    _format_open_until,
)
from datetime import date, datetime


def test_open_until_during_open_hours():
    # Bar open 4pm to 2am next day; now is 8pm
    assert _format_open_until("16:00-02:00", datetime(2026, 4, 28, 20, 0)) == "Open until 2am"

def test_open_until_simple_close():
    # Restaurant open 11am to 10pm; now is 6pm
    assert _format_open_until("11:00-22:00", datetime(2026, 4, 28, 18, 0)) == "Open until 10pm"

def test_open_until_returns_none_before_open():
    assert _format_open_until("16:00-22:00", datetime(2026, 4, 28, 14, 0)) is None

def test_open_until_returns_none_after_close():
    assert _format_open_until("11:00-22:00", datetime(2026, 4, 28, 23, 0)) is None

def test_open_until_handles_post_midnight_window():
    # Bar open 4pm to 2am; now is 1am next day
    # The "current day" hours_str is the previous day's range — we test the post-midnight case at 1am
    # This is when the bar IS still open from yesterday's range.
    assert _format_open_until("16:00-02:00", datetime(2026, 4, 28, 1, 0)) == "Open until 2am"

def test_open_until_handles_noon():
    assert _format_open_until("11:00-22:00", datetime(2026, 4, 28, 12, 0)) == "Open until 10pm"

def test_open_until_returns_none_for_closed_day():
    assert _format_open_until(None, datetime(2026, 4, 28, 18, 0)) is None
    assert _format_open_until("", datetime(2026, 4, 28, 18, 0)) is None
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `python3 scripts/test_session3_helpers.py`
Expected: ImportError on `_format_open_until`.

- [ ] **Step 3: Implement helper**

Append to `src/site_builder.py`:

```python
def _format_open_until(hours_str: str | None, now: datetime) -> str | None:
    """Returns 'Open until 10pm' / 'Open until 2am' / None.

    hours_str is a 'HH:MM-HH:MM' range. Close < open means next-day close
    (e.g. '16:00-02:00' = 4pm to 2am next day).
    `now` is a naive datetime in Chicago local time.

    Returns None when currently closed (caller hides the pill).
    """
    if not hours_str or "-" not in hours_str:
        return None
    try:
        open_str, close_str = hours_str.split("-", 1)
        oh, om = (int(x) for x in open_str.split(":"))
        ch, cm = (int(x) for x in close_str.split(":"))
    except (ValueError, IndexError):
        return None

    open_min = oh * 60 + om
    close_min = ch * 60 + cm
    if close_min <= open_min:
        close_min += 24 * 60  # next-day close

    now_min = now.hour * 60 + now.minute
    # Test today's window
    if open_min <= now_min < close_min:
        is_open = True
    # Test post-midnight tail (yesterday's range crossing into today)
    elif close_min > 24 * 60 and now_min < (close_min - 24 * 60):
        is_open = True
    else:
        is_open = False

    if not is_open:
        return None

    # Format the close time as 12-hour lowercase am/pm
    h12 = ch % 12 or 12
    suffix = "am" if ch < 12 else "pm"
    if cm == 0:
        return f"Open until {h12}{suffix}"
    return f"Open until {h12}:{cm:02d}{suffix}"
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 scripts/test_session3_helpers.py`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/site_builder.py scripts/test_session3_helpers.py
git commit -m "feat(site): add _format_open_until helper"
```

---

## Task 6: Helper — `_derive_business_type(category, display_type)` + validation

**Files:**
- Modify: `src/site_builder.py`
- Modify: `scripts/test_session3_helpers.py`

- [ ] **Step 1: Append failing tests**

In `scripts/test_session3_helpers.py`, extend imports and add tests:

```python
from src.site_builder import (
    _format_clock_pill,
    _format_window_meta,
    _select_today_happy_hours,
    _format_open_until,
    _derive_business_type,
)


def test_business_type_maps_bar():
    assert _derive_business_type("bar", None) == "Bar"

def test_business_type_maps_restaurant():
    assert _derive_business_type("restaurant", None) == "Restaurant"

def test_business_type_maps_cafe():
    assert _derive_business_type("cafe", None) == "Cafe"

def test_business_type_maps_theater_to_venue():
    assert _derive_business_type("theater", None) == "Venue"

def test_business_type_maps_museum_to_venue():
    assert _derive_business_type("museum", None) == "Venue"

def test_business_type_display_type_overrides():
    assert _derive_business_type("bar", "Venue") == "Venue"

def test_business_type_unknown_category_passes_through_capitalized():
    # Falls back to capitalize, which then must validate
    import pytest  # using bare assertion fallback if pytest unavailable
    try:
        _derive_business_type("rocketship", None)
    except ValueError as e:
        assert "rocketship" in str(e).lower() or "allowed" in str(e).lower()
        return
    assert False, "expected ValueError for unknown category"

def test_business_type_invalid_display_type_raises():
    try:
        _derive_business_type("bar", "Garbage")
    except ValueError as e:
        assert "Garbage" in str(e) or "allowed" in str(e).lower()
        return
    assert False, "expected ValueError for invalid display_type"
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `python3 scripts/test_session3_helpers.py`
Expected: ImportError on `_derive_business_type`.

- [ ] **Step 3: Implement helper**

Append to `src/site_builder.py`:

```python
_BIZ_TYPE_MAP = {
    "bar": "Bar",
    "restaurant": "Restaurant",
    "cafe": "Cafe",
    "theater": "Venue",
    "museum": "Venue",
}
_ALLOWED_BIZ_TYPES = {"Bar", "Restaurant", "Cafe", "Shop", "Venue", "Service"}


def _derive_business_type(category: str | None, display_type: str | None) -> str:
    """Derives the business hero kicker type. display_type overrides category mapping.
    Raises ValueError when the resolved type is outside the allowed set."""
    if display_type:
        if display_type not in _ALLOWED_BIZ_TYPES:
            raise ValueError(
                f"Invalid display_type {display_type!r}. "
                f"Allowed: {sorted(_ALLOWED_BIZ_TYPES)}"
            )
        return display_type
    if not category:
        raise ValueError("Business has no category and no display_type override")
    mapped = _BIZ_TYPE_MAP.get(category.lower())
    if mapped:
        return mapped
    capitalized = category.capitalize()
    if capitalized not in _ALLOWED_BIZ_TYPES:
        raise ValueError(
            f"Cannot map category {category!r} to allowed type. "
            f"Allowed: {sorted(_ALLOWED_BIZ_TYPES)}. "
            f"Set 'display_type' on the business YAML to override."
        )
    return capitalized
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `python3 scripts/test_session3_helpers.py`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/site_builder.py scripts/test_session3_helpers.py
git commit -m "feat(site): add _derive_business_type helper with allowed-type validation"
```

---

## Task 7: Build the happy-hours sidebar partial + wire into homepage

**Files:**
- Create: `templates/_happy_hours_card.html`
- Modify: `templates/index.html` (add partial include at top of sidebar)
- Modify: `src/site_builder.py` (`_build_homepage` or wherever index template is rendered — pass `happy_hours` into context)
- Modify: `styles/index.css` (append A1B_CSS block)

- [ ] **Step 1: Create the partial**

Write `templates/_happy_hours_card.html`:

```jinja
{% if happy_hours %}
<div class="hh-card" id="happy-hours-card">
  <div class="hh-head">
    <h4>Happy hours today</h4>
    <span class="nowtag" id="hh-active-count">{{ happy_hours | length }} listed</span>
  </div>
  {% for hh in happy_hours %}
  <a href="/business/{{ hh.business_slug }}/" class="hh-row"
     data-event-id="{{ hh.id }}"
     {% if hh.start_time %}data-start-time="{{ hh.start_time }}"{% endif %}
     {% if hh.end_time %}data-end-time="{{ hh.end_time }}"{% endif %}
     {% set rdays = recurrence_days_js(hh.recurrence_pattern) %}{% if rdays %}data-recurrence-days="{{ rdays }}"{% endif %}>
    <div class="clock">{{ hh.clock_pill }}</div>
    <div>
      <div class="biz">{{ hh.business_name }}</div>
      <div class="meta">{{ hh.window_meta }}</div>
    </div>
    <div class="price">{{ hh.display_price }}</div>
  </a>
  {% endfor %}
  <div class="hh-foot"><a href="#regulars">All happy hours on the board ↓</a></div>
</div>
{% endif %}
```

- [ ] **Step 2: Wire `happy_hours` into the homepage build context**

In `src/site_builder.py`, locate `build_site()` (around line 920). The local variable `events` (built around line 964–971) is the list of all active events with `tags` already parsed as Python lists — exactly what `_select_today_happy_hours()` expects.

Insert this line right after `marquee = _load_marquee()` (around line 1039), immediately before the `index_template.render(` call (around line 1041):

```python
happy_hours = _select_today_happy_hours(events, build_date)
```

Then add `happy_hours=happy_hours,` to the `render(...)` kwargs (in the same block as `today_events=today_events`, etc.).

- [ ] **Step 3: Add the partial include to homepage sidebar**

In `templates/index.html`, find `<aside>` (around line 258). Insert this immediately after `<aside>` and before the existing `<!-- Filter / tag chips -->` comment:

```jinja
<!-- Happy hours today (sticky top of sidebar; JS may hide if HN takes over) -->
{% include '_happy_hours_card.html' %}

```

- [ ] **Step 4: Append A1B_CSS block to `styles/index.css`**

Append to the end of `styles/index.css`:

```css
/* ── Happy-hours sidebar card (Session 3 · A.1.B clock strip) ── */
.hh-card{max-width:280px;background:#fff;border:1px solid var(--rule);
  transform:rotate(-.4deg);box-shadow:2px 3px 0 rgba(0,0,0,.06);
  margin-bottom:18px}
.hh-head{padding:12px 14px 8px;border-bottom:2px solid var(--ink);
  display:flex;justify-content:space-between;align-items:baseline}
.hh-head h4{font-family:var(--slab),Impact;font-size:13px;letter-spacing:.06em;
  text-transform:uppercase;margin:0;color:var(--ink)}
.hh-card .nowtag{font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--riso-red);font-weight:700}
.hh-card .nowtag::before{content:"\2022";font-size:8px;margin-right:3px;vertical-align:middle}
.hh-row{display:grid;grid-template-columns:46px 1fr auto;gap:10px;
  padding:9px 14px;border-bottom:1px dashed var(--rule);align-items:center;
  cursor:pointer;transition:background .12s;text-decoration:none;color:inherit}
.hh-row:hover{background:rgba(232,184,74,.18)}
.hh-row:last-of-type{border-bottom:0}
.hh-row .clock{font-family:var(--mono);font-size:10px;letter-spacing:.04em;
  color:var(--ink);background:var(--cork);padding:4px 5px;text-align:center;
  line-height:1.1;border:1px solid var(--rule);font-weight:700}
.hh-row .biz{font-family:var(--sans);font-size:13px;font-weight:600;color:var(--ink);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hh-row .meta{font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.04em}
.hh-row .price{font-family:var(--mono);font-size:10px;color:var(--riso-red);
  font-weight:700;letter-spacing:.04em;text-align:right;white-space:nowrap}
.hh-row.live .clock{background:var(--riso-yellow);color:var(--ink);border-color:var(--ink)}
.hh-row.live .clock::before{content:"\2022";color:var(--riso-red);font-size:8px;
  display:inline-block;margin-right:3px;vertical-align:middle}
.hh-foot{padding:9px 14px;font-family:var(--mono);font-size:9.5px;
  color:var(--muted);letter-spacing:.06em;text-align:center;background:var(--cork)}
.hh-foot a{color:var(--riso-blue);font-weight:700;text-decoration:none}
```

(Note: the `\2022` is the bullet character `●`, encoded as a CSS escape so the file stays ASCII-safe.)

- [ ] **Step 5: Smoke build, verify card renders**

Run: `python3 scripts/build_site.py`
Expected: build completes without errors. `_assert_build()` passes.

Open `public/index.html` in a browser. Confirm a card titled "Happy hours today" appears at the top of the sidebar, with rows for each happy-hour event happening today. Visually compare against the A.1.B mock in `designs/session3-final.html` (search "A.1.B" or the iframe-A1b id). It should be visually identical except for content variation.

- [ ] **Step 6: Commit**

```bash
git add templates/_happy_hours_card.html templates/index.html src/site_builder.py styles/index.css
git commit -m "feat(site): add happy-hours sidebar card (Session 3 A.1.B)"
```

---

## Task 8: Modify spotlight JS to filter happy-hour cards

**Files:**
- Modify: `templates/index.html` (the IIFE around lines ~430–500)

- [ ] **Step 1: Read the existing IIFE**

Read `templates/index.html` lines 430–500 to confirm structure. The current IIFE finds `.f` cards, runs `isHappeningNow()` against each, takes the first 4–5 as the `spotlight`, and clones them into the `#happening-grid`. We're modifying the qualifier set.

- [ ] **Step 2: Replace the filter section**

Find the line(s) inside the IIFE that build the spotlight. Currently looks like:

```js
const liveCards = Array.from(document.querySelectorAll('.f')).filter(isHappeningNow);
const soonCards = Array.from(document.querySelectorAll('.f')).filter(isStartingSoon);
// ...
const spotlight = [...nowCards, ...soonCards.slice(0, 4)];
if (spotlight.length === 0) return;
```

Replace the spotlight assembly with HH-filter-aware logic. Find the existing block (read carefully — the actual variable names in `templates/index.html` may be `nowCards`/`soonCards`; verify by reading the IIFE before editing). Modify to:

```js
function isHappyHour(card) {
  const tags = (card.dataset.tags || '').split(',');
  return tags.includes('happy-hour');
}
const allCards = Array.from(document.querySelectorAll('.f'));
const nowCards = allCards.filter(isHappeningNow);
const soonCards = allCards.filter(c => isStartingSoon(c) && !isHappeningNow(c));
const nonHHNow  = nowCards.filter(c => !isHappyHour(c));
const nonHHSoon = soonCards.filter(c => !isHappyHour(c));

const hhCard = document.getElementById('happy-hours-card');

// Decide which spotlight to render.
let spotlight;
if (nonHHNow.length > 0 || nonHHSoon.length > 0) {
  // Mixed-state: HN gets only non-HH cards; HH sidebar visible.
  spotlight = [...nonHHNow, ...nonHHSoon.slice(0, 4)];
  if (hhCard) {
    // Apply .live class to HH rows whose current time is within their window.
    Array.from(hhCard.querySelectorAll('.hh-row')).forEach(row => {
      if (isHappeningNow(row)) row.classList.add('live');
    });
    // Sidebar stays visible (no-op on hidden).
  }
} else {
  // No non-HH live cards — fall back to ALL live cards (HH included) in HN, hide sidebar.
  spotlight = [...nowCards, ...soonCards.slice(0, 4)];
  if (hhCard) hhCard.hidden = true;
}

if (spotlight.length === 0) return;
```

(Note: `isHappeningNow` already checks `dataset.startTime` / `dataset.endTime` / `dataset.recurrenceDays` — the same attrs we put on each `.hh-row` in Task 7. So calling `isHappeningNow(row)` against an `.hh-row` element works.)

Keep the rest of the IIFE (DOM cloning, `idx === 0` eager-loading) unchanged.

- [ ] **Step 3: Smoke build & three-state visual test**

Run: `python3 scripts/build_site.py`
Open `public/index.html`. Open DevTools console; confirm no JS errors.

Now manually test the three states by setting the system clock (or use the DevTools "Sensors" panel / Date.now mock):
- **State A — mixed live:** set time to 6pm Friday → should be both HH rows live AND non-HH live (e.g., a happy-hour event PLUS a Trivia or DJ event). Verify HN section populated with non-HH cards only, and HH sidebar visible.
- **State B — only HH live:** set time to 4:30pm Tuesday → likely happy hours only. Verify HN populated FROM happy-hour cards, and HH sidebar hidden.
- **State C — nothing live:** set time to 3am Sunday morning → likely nothing. Verify HN section is hidden AND HH sidebar is hidden (or just absent if zero rows).

If a state can't be reproduced via clock alone (depends on actual events in DB), it's acceptable to verify by temporarily editing the IIFE to log decisions: `console.log({nonHHNow, nonHHSoon, nowCards, soonCards})`.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "feat(site): filter happy-hours from spotlight; toggle HH sidebar"
```

---

## Task 9: Build the breadcrumb partial + CSS lift

**Files:**
- Create: `templates/_breadcrumb.html`
- Modify: `styles/index.css` (append CRUMB_CSS)
- Modify: `styles/event.css` (append CRUMB_CSS)

- [ ] **Step 1: Create the partial**

Write `templates/_breadcrumb.html`:

```jinja
{# crumb_trail: list of dicts. Each {label, href, short, here}.
   The last item should have here=True (no href), the rest are links. #}
<div class="crumbs">
  <div class="trail">
    {% for c in crumb_trail %}
      {% if c.here %}
        <span class="here" title="{{ c.label }}">{{ c.label }}</span>
      {% else %}
        <a href="{{ c.href }}" data-short="{{ c.short or c.label }}">{{ c.label }}</a>
      {% endif %}
      {% if not loop.last %}<span class="sep">→</span>{% endif %}
    {% endfor %}
  </div>
  {% if issue_number %}
  <div class="dateline">
    Issue No. <b>{{ "%04d" | format(issue_number) }}</b><span class="dl-sep"> · {{ build_date.strftime('%a %b %-d') }}</span><span class="dl-extra">, {{ build_date.strftime('%Y') }}{% if last_updated %} · Updated <b>{{ last_updated }}</b>{% endif %}</span>
  </div>
  {% endif %}
</div>
```

(The dateline uses three nested spans: the always-visible Issue No., a 640+ visible compact-form `<span class="dl-sep">`, and a 900+ visible `<span class="dl-extra">` carrying year + Updated. Below 640px, the whole `.dateline` hides via CSS.)

- [ ] **Step 2: Append CRUMB_CSS to `styles/index.css`**

Append:

```css
/* ── Breadcrumb · Stamped Dateline (Session 3 · B.1.B) ── */
.crumbs{max-width:1380px;margin:0 auto;padding:14px 24px 8px;
  display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
.crumbs .trail{display:flex;gap:10px;align-items:baseline;
  font-family:var(--mono);font-size:11px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--muted);min-width:0;flex:1 1 auto}
.crumbs .trail a{color:var(--muted);text-decoration:none}
.crumbs .trail a:hover{color:var(--ink)}
.crumbs .trail .sep{color:var(--rule);flex-shrink:0}
.crumbs .trail .here{color:var(--ink);font-weight:700;
  background:linear-gradient(to bottom,transparent 65%,var(--riso-yellow) 65%,var(--riso-yellow) 92%,transparent 92%);
  padding:1px 4px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;
  max-width:42ch}
.crumbs .dateline{margin-left:auto;font-family:var(--mono);font-size:10.5px;
  color:var(--muted);letter-spacing:.06em;flex-shrink:0;white-space:nowrap}
.crumbs .dateline b{color:var(--ink);font-weight:700}
@media (max-width: 899px){
  .crumbs .dateline .dl-extra{display:none}
  .crumbs .trail .here{max-width:28ch}
}
@media (max-width: 639px){
  .crumbs .dateline{display:none}
  .crumbs .trail .here{max-width:18ch}
}
```

- [ ] **Step 3: Append the same block to `styles/event.css`**

Append the identical CSS to `styles/event.css` (event detail and business detail pages both load `event.css`; the breadcrumb sits on those pages too).

- [ ] **Step 4: Commit**

```bash
git add templates/_breadcrumb.html styles/index.css styles/event.css
git commit -m "feat(site): add breadcrumb partial + CRUMB_CSS (Session 3 B.1.B)"
```

---

## Task 10: Add `data-short` parent-collapse JS (shared inline IIFE)

**Files:**
- Modify: `templates/index.html` (add IIFE near the existing scripts)
- Modify: `templates/_business_detail.html`
- Modify: `templates/_event_detail.html`

- [ ] **Step 1: Define the IIFE**

The same script block goes in all three templates (homepage, business detail, event detail). Place it inside a `<script>` tag at the bottom of each `<body>`, just before the closing `</body>` (or anywhere after the `.crumbs` div renders).

```html
<script>
(function () {
  const BREAKPOINT = 720;
  const links = document.querySelectorAll('.crumbs .trail a[data-short]');
  function apply() {
    const compact = window.innerWidth < BREAKPOINT;
    links.forEach(a => {
      const full = a.dataset.full || a.textContent;
      if (!a.dataset.full) a.dataset.full = a.textContent;
      a.textContent = compact ? a.dataset.short : a.dataset.full;
    });
  }
  apply();
  window.addEventListener('resize', apply, { passive: true });
})();
</script>
```

- [ ] **Step 2: Insert into `templates/index.html`**

Add the script above near the bottom of `<body>` (after the existing IIFEs, before the closing `</body>` tag).

- [ ] **Step 3: Insert into `templates/_business_detail.html`**

Same — at the bottom of body before `</body>`.

- [ ] **Step 4: Insert into `templates/_event_detail.html`**

Same — at the bottom of body before `</body>`. Read the file first to find the exact closing tag location.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html templates/_business_detail.html templates/_event_detail.html
git commit -m "feat(site): add data-short parent-collapse JS for breadcrumb"
```

---

## Task 11: Wire breadcrumb into all three page templates + remove old crumbs

**Files:**
- Modify: `templates/index.html`
- Modify: `templates/_business_detail.html`
- Modify: `templates/_event_detail.html`
- Modify: `src/site_builder.py` (pass `crumb_trail` into each render call)
- Modify: `config/businesses.yaml` (add `short_name: "Magic Lounge"` to chicago-magic-lounge)

- [ ] **Step 1: Build crumb_trail data in `src/site_builder.py`**

Locate the homepage build code (where `index_template.render(...)` is called). Before the render call, build:

```python
crumb_trail = [
    {"label": "Aville.net", "href": None, "short": None, "here": True},
]
```

(Homepage form: single `.here` span, no other elements. Note the spec says "no `.here` highlight, no padding" for the home form. We'll handle this with a CSS variant — see Step 4 below.)

Pass `crumb_trail=crumb_trail` into the render kwargs.

- [ ] **Step 2: Build crumb_trail in `_build_business_pages`**

In the per-business render loop:

```python
crumb_trail = [
    {"label": "Aville.net", "href": "/", "short": None, "here": False},
    {"label": biz["name"], "href": None, "short": biz.get("short_name"), "here": True},
]
```

Pass into `html_template.render(...)` as `crumb_trail=crumb_trail`. Also pass `issue_number` (already available — pull from the homepage build site or recompute from `_issue_number(build_date)`), `build_date` (already passed), and `last_updated` (already available — pull from where the homepage renders pull it).

- [ ] **Step 3: Build crumb_trail in event-detail render**

Find `_build_event_pages` (or similar) in `src/site_builder.py`. For each event, build:

```python
crumb_trail = [
    {"label": "Aville.net", "href": "/", "short": None, "here": False},
    {"label": event["business_name"], "href": f"/business/{event['business_slug']}/",
     "short": _get_business_short_name(event["business_slug"], businesses), "here": False},
    {"label": event["title"], "href": None, "short": None, "here": True},
]
```

Where `_get_business_short_name` is a small lookup helper:

```python
def _get_business_short_name(slug: str, businesses: list[dict]) -> str | None:
    for b in businesses:
        if b["slug"] == slug:
            return b.get("short_name") or b["name"]
    return None
```

Add this helper at module scope. Pass `crumb_trail=crumb_trail`, `issue_number`, `last_updated` into the event-detail render kwargs.

- [ ] **Step 4: Insert breadcrumb partial into homepage**

In `templates/index.html`, find the `<div class="top">` block and the `<div class="mast">` block. Insert immediately between them:

```jinja
<!-- Stamped-dateline breadcrumb (Session 3 B.1.B) -->
{% include '_breadcrumb.html' %}

```

Then in the homepage's `crumb_trail` rendering, add a CSS class to the home variant. Modify `_breadcrumb.html` slightly: when `crumb_trail | length == 1`, the `.here` should not get the underline highlight per D4 ("no `.here` highlight, no padding"). Approach: pass an additional flag to the partial.

Actually, simpler: in the homepage `crumb_trail`, rename the marker so the partial can distinguish. Set `here=True` and add `home=True` to the entry. Update the partial:

```jinja
{% if c.here and c.home %}
  <span class="here home">{{ c.label }}</span>
{% elif c.here %}
  <span class="here" title="{{ c.label }}">{{ c.label }}</span>
{% else %}
  <a href="{{ c.href }}" data-short="{{ c.short or c.label }}">{{ c.label }}</a>
{% endif %}
```

And add to `styles/index.css`:

```css
.crumbs .trail .here.home{background:none;padding:0;color:var(--muted);font-weight:400;max-width:none}
```

Update the homepage `crumb_trail` builder in Step 1 to include `"home": True`.

- [ ] **Step 5: Insert breadcrumb partial into business detail template**

In `templates/_business_detail.html`, find the `<div class="top">` block. Insert immediately after its closing `</div>`:

```jinja
<!-- Stamped-dateline breadcrumb (Session 3 B.1.B) -->
{% include '_breadcrumb.html' %}

```

Then remove the existing `<div class="crumbs">…</div>` from inside `.top-row`. Read the existing block first (around line 46), confirm what to remove. Result: `.top-row` contains only `← Back to the board`, the (no-longer-present-but-was) crumbs, and the date. Remove the inline crumbs span; keep the rest.

- [ ] **Step 6: Insert breadcrumb partial into event detail template**

Read `templates/_event_detail.html` to find the `<div class="top">` block. Same pattern: insert breadcrumb after `.top` closes; remove inline `.crumbs` div from inside `.top-row`.

- [ ] **Step 7: Backfill `short_name` for Chicago Magic Lounge**

In `config/businesses.yaml`, find the entry with `slug: chicago-magic-lounge`. Add a top-level field (peer of `name`):

```yaml
    short_name: "Magic Lounge"
```

Match indentation of surrounding fields exactly. Place it right after `name:`.

- [ ] **Step 8: Smoke build & visual check**

Run: `python3 scripts/build_site.py`
Open homepage: confirm breadcrumb shows "Aville.net" (single span, muted, no underline) above the masthead. Confirm dateline shows full form on a wide window.

Open `public/business/sofo-tap/index.html`: confirm breadcrumb shows `AVILLE.NET → THE SOFO TAP` (active = SoFo Tap, with yellow underline). Confirm dateline.

Open `public/event/<some-id>/index.html` for a Chicago Magic Lounge event: confirm breadcrumb shows three levels. Resize to <720px. Confirm `Chicago Magic Lounge` collapses to `Magic Lounge` parent crumb.

- [ ] **Step 9: Commit**

```bash
git add templates/_breadcrumb.html templates/index.html templates/_business_detail.html templates/_event_detail.html src/site_builder.py styles/index.css config/businesses.yaml
git commit -m "feat(site): wire stamped-dateline breadcrumb on home, business, event pages"
```

---

## Task 12: Build the editorial business hero

**Files:**
- Modify: `templates/_business_detail.html` (replace `.masthead-biz` block)
- Modify: `styles/event.css` (append C1_CSS, scoped to business pages)
- Modify: `src/site_builder.py` (compute `display_type`, `open_until_pill`, `placeholder_slots` and pass into business render)

- [ ] **Step 1: Compute hero variables in `_build_business_pages`**

Inside the per-business loop in `_build_business_pages`, before the `html_template.render(...)` call, compute:

```python
from datetime import datetime as _datetime
import zoneinfo

biz_type = _derive_business_type(biz.get("category"), biz.get("display_type"))

today_full = _DAY_ORDER[build_date.weekday()]
hours_today = (biz.get("hours") or {}).get(today_full)
chicago = zoneinfo.ZoneInfo("America/Chicago")
now_chicago = _datetime.now(chicago).replace(tzinfo=None)
open_until_pill = _format_open_until(hours_today, now_chicago)

branding_images = biz.get("branding_images") or []
placeholder_slots = max(0, 3 - len(branding_images))
```

Pass into `html_template.render(...)` as kwargs:
```python
biz_type=biz_type,
open_until_pill=open_until_pill,
branding_images=branding_images,
placeholder_slots=placeholder_slots,
```

- [ ] **Step 2: Replace the masthead block in `_business_detail.html`**

Find the existing `<header class="masthead masthead-biz">…</header>` block (lines 53-64 in the current file). Replace the entire block with:

```jinja
<!-- Editorial hero (Session 3 C.1) -->
<section class="hero1">
  <p class="kicker">{{ biz_type }}{% if biz.address %} · {{ biz.address.split(',')[0] }}{% endif %} · Andersonville</p>
  <h1>{{ biz.name }}</h1>
  {% if biz.tagline %}
  <p class="lede">{{ biz.tagline }}</p>
  {% elif biz.vibe_quote %}
  <p class="lede">{{ biz.vibe_quote.split('. ')[0] }}{% if not biz.vibe_quote.split('. ')[0].endswith('.') %}.{% endif %}</p>
  {% endif %}
  <div class="biz-actions">
    {% if biz.metadata and biz.metadata.telephone %}<a class="primary" href="tel:{{ biz.metadata.telephone }}">Call</a>{% endif %}
    {% if biz.website %}<a href="{{ biz.website }}" rel="noopener" target="_blank">Website ↗</a>{% endif %}
    {% if biz.address %}<a href="https://www.google.com/maps/search/?api=1&amp;query={{ biz.address | urlencode }}" rel="noopener" target="_blank">Map ↗</a>{% endif %}
    {% if open_until_pill %}<span class="live">{{ open_until_pill }}</span>{% endif %}
  </div>
  {% if biz.default_tags %}
  <div class="chips">
    {% for t in biz.default_tags %}
    <span{% if loop.first %} class="hl"{% endif %}>{{ t }}</span>
    {% endfor %}
  </div>
  {% endif %}
</section>
<div class="hero1-strip">
  {% for img in branding_images %}
  <div><img src="{{ img }}" alt="{{ biz.name }}" loading="lazy" /></div>
  {% endfor %}
  {% for _ in range(placeholder_slots) %}
  <div class="placeholder">
    <span>{% if biz.vibe_quote %}{{ biz.vibe_quote }}{% else %}More photos here soon.{% endif %}</span>
    <small>— hero photo placeholder</small>
  </div>
  {% endfor %}
</div>
```

(Note: `biz.address.split(',')[0]` extracts just the street address — `"5358 N Clark St, Chicago, IL"` → `"5358 N Clark St"`. The kicker pattern is `{Type} · {Street} · Andersonville`.)

- [ ] **Step 3: Append C1_CSS to `styles/event.css`**

Append:

```css
/* ── Business page editorial hero (Session 3 · C.1) ── */
.masthead-biz{display:none}  /* old hero hidden — replaced by .hero1 */

.hero1{max-width:1280px;margin:0 auto;padding:28px 24px 18px;
  border-bottom:3px double var(--ink)}
.hero1 .kicker{font-family:var(--mono);font-size:11px;letter-spacing:.18em;
  text-transform:uppercase;color:var(--riso-blue);margin:0 0 12px;font-weight:700}
.hero1 h1{font-family:var(--serif);font-weight:900;font-size:88px;line-height:.92;
  letter-spacing:-0.035em;margin:0 0 14px;color:var(--ink);max-width:18ch;font-style:italic}
.hero1 .lede{font-family:var(--serif);font-size:18px;line-height:1.4;
  color:var(--ink-2);max-width:54ch;margin:0;font-style:italic}

.hero1 .biz-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
.hero1 .biz-actions a{font-family:var(--mono);font-size:11px;letter-spacing:.06em;
  text-transform:uppercase;background:#fff;border:1.5px solid var(--ink);
  padding:7px 11px;color:var(--ink);font-weight:700;text-decoration:none}
.hero1 .biz-actions a.primary{background:var(--ink);color:var(--cork)}
.hero1 .biz-actions .live{font-family:var(--mono);font-size:11px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink);background:var(--riso-yellow);
  border:1.5px solid var(--ink);padding:7px 11px;font-weight:700}
.hero1 .biz-actions .live::before{content:"\2022";color:var(--riso-red);font-size:8px;
  display:inline-block;margin-right:4px;vertical-align:middle}

.hero1 .chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:14px}
.hero1 .chips span{font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;
  text-transform:uppercase;background:var(--cork-2);color:var(--ink-2);
  padding:4px 8px;border:1px solid var(--rule);font-weight:600}
.hero1 .chips span.hl{background:var(--riso-blue);color:#fff;border-color:var(--ink)}

.hero1-strip{max-width:1280px;margin:0 auto;padding:20px 24px;
  display:grid;grid-template-columns:2fr 1fr 1fr;gap:14px}
.hero1-strip > div{aspect-ratio:4/3;overflow:hidden;background:var(--cork-2);position:relative}
.hero1-strip img{width:100%;height:100%;object-fit:cover}
.hero1-strip .placeholder{display:flex;flex-direction:column;justify-content:space-between;
  padding:14px;background:var(--riso-blue);color:var(--cork);
  font-family:var(--serif);font-style:italic;font-size:18px;line-height:1.3}
.hero1-strip .placeholder small{font-family:var(--mono);font-size:10px;letter-spacing:.1em;
  text-transform:uppercase;color:rgba(255,253,245,.7);font-style:normal}

@media (max-width: 720px){
  .hero1{padding:18px 16px 12px}
  .hero1 h1{font-size:48px}
  .hero1 .lede{font-size:15px}
  .hero1-strip{grid-template-columns:1fr;padding:14px 16px}
  .hero1-strip > div{aspect-ratio:16/9}
}
```

(Note: `.masthead-biz{display:none}` short-circuits the old hero in case any references remain. Once we're confident, a follow-up cleanup can remove `.masthead-biz` references entirely.)

- [ ] **Step 4: Smoke build at desktop and mobile**

Run: `python3 scripts/build_site.py`
Open `public/business/sofo-tap/index.html` in a browser at desktop width (1280px). Confirm:
- Kicker reads `BAR · 5358 N CLARK ST · ANDERSONVILLE` in blue uppercase mono.
- 88px serif italic h1 with the business name.
- Tagline absent (Phase 1) — that's correct for now.
- Action row with Call / Website / Map buttons; "Open until 2am" yellow pill if currently within hours.
- Tag chips below — first chip in blue (`hl`), rest in cork.
- Hero strip below: 3 placeholder cells with "More photos here soon." Fraunces italic and "— hero photo placeholder" mono small.

Resize to mobile (375px). Confirm:
- h1 shrinks to 48px.
- Hero strip becomes single-column, 16:9 aspect.

- [ ] **Step 5: Commit**

```bash
git add templates/_business_detail.html styles/event.css src/site_builder.py
git commit -m "feat(site): add editorial business hero (Session 3 C.1)"
```

---

## Task 13: Mirror HH-filter rule on business-page spotlight

**Files:**
- Modify: `templates/_business_detail.html` (the existing IIFE at lines 135–189)

- [ ] **Step 1: Read existing IIFE**

The business detail template has its own simpler version of the spotlight IIFE (around lines 135–189). It finds `.f` cards on the page (the cards rendered inside `.biz-whats-on`), filters by `isHappeningNow`, and clones the first into `#spotlight-slot`.

For consistency with the homepage rule: when there's a non-HH live card on the business page, prefer that one for the spotlight; only fall back to HH cards if nothing else is live.

- [ ] **Step 2: Modify the IIFE to add HH-filter**

Find the line:
```js
const liveCards = Array.from(document.querySelectorAll('.f')).filter(isHappeningNow);
if (!liveCards.length) return;
const first = liveCards[0].cloneNode(true);
```

Replace with:
```js
function isHappyHour(card) {
  const tags = (card.dataset.tags || '').split(',');
  return tags.includes('happy-hour');
}
const liveCards = Array.from(document.querySelectorAll('.f')).filter(isHappeningNow);
if (!liveCards.length) return;
const nonHHLive = liveCards.filter(c => !isHappyHour(c));
const pickFrom = nonHHLive.length > 0 ? nonHHLive : liveCards;
const first = pickFrom[0].cloneNode(true);
```

(Business pages don't have a sidebar HH card to toggle, so the rule is just "prefer non-HH for the spotlight.")

- [ ] **Step 3: Smoke build & visual check**

Run: `python3 scripts/build_site.py`
Open a business detail page (e.g. `/business/replay-andersonville/`). If the business currently has both a live happy hour AND a live non-HH event (e.g. trivia), confirm the spotlight shows the non-HH event. If only HH is live, spotlight shows that.

- [ ] **Step 4: Commit**

```bash
git add templates/_business_detail.html
git commit -m "feat(site): prefer non-HH live cards for business-page spotlight"
```

---

## Task 14: Final smoke build, visual deltas, build-assertion check

**Files:**
- (no edits unless smoke turns up issues)

- [ ] **Step 1: Run unit tests**

Run: `python3 scripts/test_session3_helpers.py`
Expected: all PASS.

- [ ] **Step 2: Full clean build with assertions**

Run: `CHECK_IMAGES=1 python3 scripts/build_site.py`
Expected: build completes, `_assert_build()` passes, no broken image refs.

- [ ] **Step 3: Visual smoke at three viewports**

Open `public/index.html`, `public/business/sofo-tap/index.html`, and a `public/event/<id>/index.html` page in a browser. Test at:
- 1280px (desktop)
- 720px (tablet)
- 375px (mobile)

Verify per the spec acceptance criteria:
- [ ] Happy-hours card renders with rows, hides when zero, hides when HN doesn't have non-HH live cards.
- [ ] Live row state shows on rows currently within window.
- [ ] Breadcrumb home/business/event forms correct.
- [ ] Dateline degrades correctly at 1280 / 720 / 375.
- [ ] Business page hero matches C1 mock at desktop and mobile.
- [ ] Image strip shows 3 placeholders for businesses without `branding_images`.
- [ ] "Open until X" pill computes correctly (or hides when closed).
- [ ] No new fonts, no new colors.

If any check fails, identify the file and fix in a separate follow-up commit on this branch.

- [ ] **Step 4: Open PR**

Push the branch, open a PR against `main`:

```bash
git push -u origin design-handoff-session3-phase1
gh pr create --title "feat: design handoff session 3 — phase 1 (structural)" --body "$(cat <<'EOF'
## Summary
- Adds happy-hours sidebar card (Session 3 A.1.B clock strip).
- Adds stamped-dateline breadcrumb on home/business/event pages (B.1.B).
- Replaces business-page hero with editorial layout (C.1).
- Adds 5 site-builder helpers + unit tests for clock/window/HH-select/open-until/biz-type.
- Adds `price_short` column for happy-hour short-form pricing (Phase 2 backfill).
- Adds `display_type` / `short_name` / `branding_images` / `tagline` / `vibe_quote` / `about` / `press` / `socials` to the businesses.yaml schema (Phase 1 only writes `display_type` + `short_name`; rest land in Phase 2).

## Spec
docs/superpowers/specs/2026-04-28-design-handoff-session3.md

## Plan
docs/superpowers/plans/2026-04-28-design-handoff-session3-phase1.md

## Phase 2 (deferred)
Editorial copy backfill via Claude Haiku script analogous to `extract_business_metadata.py`. Press / socials / branding images stay manual.

## Test plan
- [ ] `python3 scripts/test_session3_helpers.py` passes (≥ 25 assertions)
- [ ] `CHECK_IMAGES=1 python3 scripts/build_site.py` completes cleanly
- [ ] Visual smoke at 1280 / 720 / 375 on home, business, event pages
- [ ] Three HH/HN visibility states confirmed (mixed live, only-HH live, nothing live)
- [ ] `data-short` parent-collapse confirmed on Chicago Magic Lounge event page
EOF
)"
```

---

## Self-review checklist (already addressed inline; restated for execution)

- [ ] D1 (HH data source) — Tasks 4, 7
- [ ] D2 (HH/HN interplay) — Tasks 8, 13
- [ ] D3 (sidebar placement) — Task 7 step 3
- [ ] D4 (breadcrumb forms by page) — Tasks 9, 11
- [ ] D5 (`data-short` parent collapse) — Tasks 9, 10, 11
- [ ] D6 (business hero data model) — Tasks 6, 11, 12
- [ ] D7 (hero strip pure spec) — Task 12
- [ ] D8 ("Open until X" pill) — Tasks 5, 12
- [ ] D9 (old `.top-row` crumbs removal) — Task 11
- [ ] D10 (CSS organization) — Tasks 7, 9, 12
