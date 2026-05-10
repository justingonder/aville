#!/usr/bin/env python3
"""Standalone test for events.locked_fields.

Confirms that:
  - upsert_event skips locked fields when re-upserting an existing event
  - unlocked fields still update normally
  - system-managed fields (image_*, source_*, etc.) always update
  - mark_missing_events_stale skips events with `status` locked

Runs against a fresh in-memory SQLite DB; no real-DB risk. Invoke directly:
    python3 scripts/test_locked_fields.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import (  # noqa: E402
    SCHEMA,
    LOCKABLE_FIELDS,
    init_db,
    upsert_business,
    upsert_event,
    mark_missing_events_stale,
)
import sqlite3  # noqa: E402


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Apply the same idempotent migrations init_db does
    try:
        conn.execute("ALTER TABLE events ADD COLUMN price_short TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE events ADD COLUMN locked_fields TEXT")
    except sqlite3.OperationalError:
        pass
    return conn


def seed_event(conn, business_id, **overrides) -> int:
    event = {
        "kind": "recurring",
        "title": "Test Event",
        "description": "original description",
        "recurrence_pattern": "weekly:monday",
        "start_time": "19:00",
        "end_time": "21:00",
        "start_datetime": None,
        "end_datetime": None,
        "price_info": None,
        "tags": ["weekly-recurring"],
        "performers": [],
        "image_source_url": None,
        "image_local_path": None,
        "external_link": None,
        "source_page_url": "https://example.com/events",
        "source_page_hash": "hash-v1",
        "confidence": 0.9,
        "status": "active",
        **overrides,
    }
    upsert_event(conn, business_id, event)
    row = conn.execute(
        "SELECT * FROM events WHERE business_id = ? AND title = ?",
        (business_id, event["title"]),
    ).fetchone()
    return row["id"]


def test_locked_field_survives_reextraction():
    """End_time + description test: keep `title`/`start_time`/`recurrence_pattern`
    constant so match_key matches and the UPDATE branch runs. Lock end_time and
    title; leave description unlocked."""
    conn = make_conn()
    bid = upsert_business(conn, {
        "slug": "test", "name": "Test", "category": "bar",
        "subcategory": None, "website": None, "address": None,
    })
    eid = seed_event(conn, bid)

    # Admin renames title and changes end_time, then locks both.
    conn.execute(
        "UPDATE events SET end_time = '22:00', title = 'Locked Title', locked_fields = ? WHERE id = ?",
        (json.dumps(["end_time", "title"]), eid),
    )

    # Re-upsert from "extraction" — match_key is built from the input event's
    # title ('Test Event'), which is what the source produced originally, so
    # this matches the row's stored match_key and exercises UPDATE.
    upsert_event(conn, bid, {
        "kind": "recurring",
        "title": "Test Event",  # source still says this
        "description": "UPDATED description",
        "recurrence_pattern": "weekly:monday",
        "start_time": "19:00",
        "end_time": "20:00",  # locked → should NOT clobber 22:00
        "start_datetime": None, "end_datetime": None, "price_info": None,
        "tags": ["weekly-recurring"], "performers": [],
        "image_source_url": "https://cdn.example.com/new.jpg",  # system field
        "image_local_path": None, "external_link": None,
        "source_page_url": "https://example.com/events",
        "source_page_hash": "hash-v2",  # system field
        "confidence": 0.95, "status": "active",
    })

    row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
    assert row["title"] == "Locked Title", f"title was clobbered: {row['title']!r}"
    assert row["end_time"] == "22:00", f"end_time was clobbered: {row['end_time']!r}"
    assert row["description"] == "UPDATED description", \
        f"description should have updated: {row['description']!r}"
    assert row["image_source_url"] == "https://cdn.example.com/new.jpg", \
        "system-managed image_source_url should always update"
    assert row["source_page_hash"] == "hash-v2", \
        "system-managed source_page_hash should always update"
    print("  ✓ locked title + end_time preserved; unlocked description updated; system fields updated")


def test_no_locks_behaves_normally():
    """No locks → user-facing fields update via UPDATE branch.
    Keep match_key-constituent fields (title, start_time, recurrence_pattern)
    stable; verify other fields update."""
    conn = make_conn()
    bid = upsert_business(conn, {
        "slug": "test", "name": "Test", "category": "bar",
        "subcategory": None, "website": None, "address": None,
    })
    eid = seed_event(conn, bid)

    upsert_event(conn, bid, {
        "kind": "recurring",
        "title": "Test Event",  # match_key-constituent: keep same
        "description": "new desc",
        "recurrence_pattern": "weekly:monday",
        "start_time": "19:00",  # match_key-constituent: keep same
        "end_time": "23:00",  # not in match_key — should update
        "start_datetime": None, "end_datetime": None, "price_info": "$5",
        "tags": ["weekly-recurring", "drag"], "performers": [],
        "image_source_url": None, "image_local_path": None, "external_link": None,
        "source_page_url": "https://example.com/events",
        "source_page_hash": "hash-v2",
        "confidence": 0.95, "status": "active",
    })

    row = conn.execute("SELECT * FROM events WHERE id = ?", (eid,)).fetchone()
    assert row["description"] == "new desc", f"description didn't update: {row['description']!r}"
    assert row["end_time"] == "23:00", f"end_time didn't update: {row['end_time']!r}"
    assert row["price_info"] == "$5", f"price_info didn't update: {row['price_info']!r}"
    assert json.loads(row["tags"]) == ["weekly-recurring", "drag"]
    print("  ✓ no locks → every user-facing field updates as before")


def test_status_lock_blocks_stale():
    conn = make_conn()
    bid = upsert_business(conn, {
        "slug": "test", "name": "Test", "category": "bar",
        "subcategory": None, "website": None, "address": None,
    })
    # Two events on the same source page
    e1 = seed_event(conn, bid, title="Event One")
    e2 = seed_event(conn, bid, title="Event Two")
    # Lock status on e2
    conn.execute(
        "UPDATE events SET locked_fields = ? WHERE id = ?",
        (json.dumps(["status"]), e2),
    )

    # Run stale-marking with NEITHER match_key seen
    stale_count = mark_missing_events_stale(
        conn, bid, "https://example.com/events", set()
    )

    row1 = conn.execute("SELECT status FROM events WHERE id = ?", (e1,)).fetchone()
    row2 = conn.execute("SELECT status FROM events WHERE id = ?", (e2,)).fetchone()
    assert row1["status"] == "stale", f"e1 should be stale, got {row1['status']!r}"
    assert row2["status"] == "active", f"e2 should remain active (status locked), got {row2['status']!r}"
    assert stale_count == 1, f"expected 1 stale, got {stale_count}"
    print("  ✓ status-locked event is not auto-staled; unlocked sibling is")


def test_locked_null_preserved():
    """A user locks a None field to say 'I know there is no end_time'."""
    conn = make_conn()
    bid = upsert_business(conn, {
        "slug": "test", "name": "Test", "category": "bar",
        "subcategory": None, "website": None, "address": None,
    })
    eid = seed_event(conn, bid, end_time=None)
    conn.execute(
        "UPDATE events SET locked_fields = ? WHERE id = ?",
        (json.dumps(["end_time"]), eid),
    )

    # Extraction now tries to fill in an end_time
    upsert_event(conn, bid, {
        "kind": "recurring",
        "title": "Test Event",
        "description": "x",
        "recurrence_pattern": "weekly:monday",
        "start_time": "19:00", "end_time": "23:00",  # would normally land
        "start_datetime": None, "end_datetime": None, "price_info": None,
        "tags": [], "performers": [],
        "image_source_url": None, "image_local_path": None, "external_link": None,
        "source_page_url": "https://example.com/events",
        "source_page_hash": "h",
        "confidence": 0.9, "status": "active",
    })

    row = conn.execute("SELECT end_time FROM events WHERE id = ?", (eid,)).fetchone()
    assert row["end_time"] is None, f"locked NULL should stay NULL, got {row['end_time']!r}"
    print("  ✓ locking a NULL field prevents extraction from filling it in")


def test_lockable_fields_constant_matches_columns():
    conn = make_conn()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
    missing = [f for f in LOCKABLE_FIELDS if f not in cols]
    assert not missing, f"LOCKABLE_FIELDS references nonexistent columns: {missing}"
    print(f"  ✓ all {len(LOCKABLE_FIELDS)} LOCKABLE_FIELDS map to real columns")


def main() -> None:
    tests = [
        test_lockable_fields_constant_matches_columns,
        test_no_locks_behaves_normally,
        test_locked_field_survives_reextraction,
        test_locked_null_preserved,
        test_status_lock_blocks_stale,
    ]
    print(f"Running {len(tests)} test(s):")
    for t in tests:
        print(f"- {t.__name__}")
        t()
    print(f"\nAll {len(tests)} test(s) passed.")


if __name__ == "__main__":
    main()
