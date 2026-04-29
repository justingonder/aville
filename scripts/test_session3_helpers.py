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
