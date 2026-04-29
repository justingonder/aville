"""Unit tests for Session-3 design helpers."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.site_builder import (
    _format_clock_pill,
    _format_window_meta,
    _select_today_happy_hours,
    _format_open_until,
)
from datetime import date, datetime


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
