#!/usr/bin/env python3
"""Standalone test for src.db.normalize_recurrence_pattern + its integration
with build_match_key and upsert_event. Runs against an in-memory SQLite DB.

    python3 scripts/test_recurrence_normalize.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import (  # noqa: E402
    SCHEMA,
    build_match_key,
    normalize_recurrence_pattern,
    upsert_business,
    upsert_event,
)


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Apply the same idempotent migrations init_db does.
    for ddl in (
        "ALTER TABLE events ADD COLUMN price_short TEXT",
        "ALTER TABLE events ADD COLUMN locked_fields TEXT",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    return conn


def test_normalize_matrix():
    """Every CSV pattern in current DB + edge cases."""
    cases = [
        # (input, expected output)
        # Contiguous CSVs collapse to range form
        ("weekly:wednesday,thursday,friday,saturday,sunday", "weekly:wednesday-sunday"),
        ("weekly:thursday,friday,saturday,sunday", "weekly:thursday-sunday"),
        ("weekly:tuesday,wednesday,thursday,friday,saturday,sunday", "weekly:tuesday-sunday"),
        ("weekly:tuesday,wednesday,thursday,friday,saturday", "weekly:tuesday-saturday"),
        ("weekly:tuesday,wednesday,thursday,friday", "weekly:tuesday-friday"),
        ("weekly:tuesday,wednesday,thursday", "weekly:tuesday-thursday"),
        ("weekly:tuesday,wednesday", "weekly:tuesday-wednesday"),
        ("weekly:wednesday,thursday", "weekly:wednesday-thursday"),
        ("weekly:friday,saturday", "weekly:friday-saturday"),
        ("weekly:friday,saturday,sunday", "weekly:friday-sunday"),
        ("weekly:monday,tuesday,wednesday,thursday", "weekly:monday-thursday"),
        ("weekly:monday,tuesday,wednesday,thursday,friday", "weekly:monday-friday"),
        ("weekly:saturday,sunday", "weekly:saturday-sunday"),
        # Wrap (none in current DB but should still work)
        ("weekly:saturday,sunday,monday", "weekly:saturday-monday"),
        ("weekly:friday,saturday,sunday,monday", "weekly:friday-monday"),
        # Pass-through: already-range form
        ("weekly:tuesday-sunday", "weekly:tuesday-sunday"),
        ("weekly:monday-friday", "weekly:monday-friday"),
        # Pass-through: single day
        ("weekly:sunday", "weekly:sunday"),
        ("weekly:monday", "weekly:monday"),
        # Pass-through: non-consecutive
        ("weekly:monday,wednesday,friday", "weekly:monday,wednesday,friday"),
        ("weekly:tuesday,saturday", "weekly:tuesday,saturday"),
        # Pass-through: non-weekly
        ("daily", "daily"),
        ("monthly:1st-friday", "monthly:1st-friday"),
        ("monthly:last-saturday", "monthly:last-saturday"),
        # Pass-through: None / empty
        (None, None),
        ("", ""),
    ]
    failed = 0
    for inp, expected in cases:
        got = normalize_recurrence_pattern(inp)
        if got != expected:
            print(f"  ✗ {inp!r:<55} → {got!r:<35} (want {expected!r})")
            failed += 1
    if failed:
        raise AssertionError(f"{failed} case(s) failed")
    print(f"  ✓ {len(cases)} cases pass (contiguous, range, single, non-consecutive, non-weekly, None)")


def test_idempotent():
    """normalize(normalize(x)) == normalize(x) for every input."""
    samples = [
        "weekly:wednesday,thursday,friday,saturday,sunday",
        "weekly:tuesday-sunday",
        "weekly:monday,wednesday,friday",
        "weekly:saturday,sunday,monday",
        "daily",
        None,
    ]
    for s in samples:
        once = normalize_recurrence_pattern(s)
        twice = normalize_recurrence_pattern(once)
        assert once == twice, f"not idempotent for {s!r}: {once!r} → {twice!r}"
    print(f"  ✓ idempotent across {len(samples)} sample inputs")


def test_match_key_uses_normalized():
    """A CSV-form event and a range-form event with the same days produce the same match_key."""
    csv_event = {
        "kind": "recurring",
        "title": "Happy Hour",
        "recurrence_pattern": "weekly:wednesday,thursday,friday,saturday,sunday",
        "start_time": "16:00",
    }
    range_event = {**csv_event, "recurrence_pattern": "weekly:wednesday-sunday"}
    csv_key = build_match_key(csv_event)
    range_key = build_match_key(range_event)
    assert csv_key == range_key, f"keys differ:\n  csv:   {csv_key}\n  range: {range_key}"
    print(f"  ✓ build_match_key collapses semantically-equivalent patterns to same key")
    print(f"      {csv_key}")


def test_upsert_event_normalizes_storage():
    """upsert_event stores the normalized pattern regardless of which form was input."""
    conn = make_conn()
    bid = upsert_business(conn, {
        "slug": "test", "name": "Test", "category": "bar",
        "subcategory": None, "website": None, "address": None,
    })
    # First upsert: CSV form
    upsert_event(conn, bid, {
        "kind": "recurring",
        "title": "Friday Trivia",
        "description": "Weekly trivia",
        "recurrence_pattern": "weekly:wednesday,thursday,friday,saturday,sunday",
        "start_time": "19:00", "end_time": "21:00",
        "start_datetime": None, "end_datetime": None,
        "price_info": None, "tags": [], "performers": [],
        "image_source_url": None, "image_local_path": None, "external_link": None,
        "source_page_url": "https://example.com/events",
        "source_page_hash": "h1", "confidence": 0.9, "status": "active",
    })
    row = conn.execute("SELECT recurrence_pattern, match_key FROM events").fetchone()
    assert row["recurrence_pattern"] == "weekly:wednesday-sunday", \
        f"stored pattern not normalized: {row['recurrence_pattern']!r}"

    # Second upsert: same days but expressed as range. Should UPDATE the existing row.
    upsert_event(conn, bid, {
        "kind": "recurring",
        "title": "Friday Trivia",
        "description": "Updated description",
        "recurrence_pattern": "weekly:wednesday-sunday",
        "start_time": "19:00", "end_time": "22:00",  # different end time
        "start_datetime": None, "end_datetime": None,
        "price_info": None, "tags": [], "performers": [],
        "image_source_url": None, "image_local_path": None, "external_link": None,
        "source_page_url": "https://example.com/events",
        "source_page_hash": "h2", "confidence": 0.9, "status": "active",
    })
    n_rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert n_rows == 1, f"expected 1 event (UPDATE), got {n_rows} — duplicate insert from match_key drift"
    row = conn.execute("SELECT description, end_time FROM events").fetchone()
    assert row["description"] == "Updated description"
    assert row["end_time"] == "22:00"
    print(f"  ✓ upsert with CSV then range form produces ONE row, UPDATE path")
    print(f"  ✓ stored pattern stays canonical (weekly:wednesday-sunday)")


def main():
    tests = [
        test_normalize_matrix,
        test_idempotent,
        test_match_key_uses_normalized,
        test_upsert_event_normalizes_storage,
    ]
    print(f"Running {len(tests)} test(s):")
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print(f"\nAll {len(tests)} test(s) passed.")


if __name__ == "__main__":
    main()
