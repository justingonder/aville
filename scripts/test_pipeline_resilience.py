#!/usr/bin/env python3
"""Tests for pipeline resilience against malformed model output.

Reproduces the 2026-07-06 outage: Claude returned an event whose `kind` was
not 'recurring'/'dated'; the pipeline sent it straight to upsert_event, the DB
CHECK constraint raised sqlite3.IntegrityError, and — because the upsert loop
was unguarded — the exception aborted the entire daily run (every business
after Atmosphere never processed, build/deploy never ran).

Two fixes, both tested here:
  A. event_has_valid_kind() — skip invalid-kind events before upsert.
  B. try_upsert_event()     — guard per-event DB errors so one bad event can't
                              abort the whole run.

Run: python3 scripts/test_pipeline_resilience.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _event(**overrides) -> dict:
    ev = {
        "kind": "recurring",
        "title": "Test Event",
        "description": "d",
        "recurrence_pattern": "weekly:monday",
        "start_time": "19:00",
        "end_time": "21:00",
        "start_datetime": None,
        "end_datetime": None,
        "price_info": None,
        "tags": [],
        "performers": [],
        "image_source_url": None,
        "image_local_path": None,
        "external_link": None,
        "source_page_url": "https://example.com/events",
        "source_page_hash": "h",
        "confidence": 0.9,
        "status": "active",
    }
    ev.update(overrides)
    return ev


def _fresh_db_with_business(td):
    """Init a temp DB with one business (committed). Returns (db_path, business_id).
    Each test opens its own `with connect(db)` for the work under test."""
    from src.db import init_db, connect, upsert_business
    db = Path(td) / "t.db"
    init_db(db)
    with connect(db) as conn:
        business_id = upsert_business(conn, {
            "slug": "x", "name": "X", "category": "bar",
            "subcategory": "", "website": "https://x", "address": "",
        })
    return db, business_id


# --- Fix A: kind validation -------------------------------------------------

def test_event_has_valid_kind_accepts_allowed():
    from src.db import event_has_valid_kind
    assert event_has_valid_kind({"kind": "recurring"}) is True
    assert event_has_valid_kind({"kind": "dated"}) is True
    print("  valid kinds accepted: OK")


def test_event_has_valid_kind_rejects_bad_and_missing():
    from src.db import event_has_valid_kind
    assert event_has_valid_kind({"kind": "special"}) is False  # the 7/06 case
    assert event_has_valid_kind({"kind": ""}) is False
    assert event_has_valid_kind({"kind": None}) is False
    assert event_has_valid_kind({}) is False                   # missing entirely
    print("  invalid/missing kinds rejected: OK")


# --- Fix B: guarded upsert --------------------------------------------------

def test_try_upsert_event_swallows_bad_kind_integrity_error():
    """The exact 7/06 failure: a present-but-invalid kind reaches upsert and the
    CHECK constraint fires. try_upsert_event must return None, NOT raise."""
    from src.db import connect, upsert_event, try_upsert_event
    with tempfile.TemporaryDirectory() as td:
        db, bid = _fresh_db_with_business(td)
        with connect(db) as conn:
            # sanity: the raw upsert path really does raise on this input
            raised = False
            try:
                upsert_event(conn, bid, _event(kind="special"))
            except sqlite3.IntegrityError:
                raised = True
            assert raised, "precondition: raw upsert_event should raise on bad kind"

            # the guard swallows it
            result = try_upsert_event(conn, bid, _event(kind="special", title="Bad"))
            assert result is None, f"expected None on DB error, got {result!r}"
            n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            assert n == 0, "no row should be inserted for the bad event"
    print("  try_upsert_event swallows IntegrityError: OK")


def test_try_upsert_event_inserts_valid_event():
    from src.db import connect, try_upsert_event
    with tempfile.TemporaryDirectory() as td:
        db, bid = _fresh_db_with_business(td)
        with connect(db) as conn:
            action = try_upsert_event(conn, bid, _event(title="Good"))
            assert action == "inserted", f"expected 'inserted', got {action!r}"
            n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            assert n == 1, "valid event should be inserted"
    print("  try_upsert_event inserts valid event: OK")


def test_one_bad_event_does_not_block_a_good_one():
    """The blast-radius property: a bad event followed by a good one — the good
    one still lands. (Before the fix, the bad event aborted the whole loop.)"""
    from src.db import connect, try_upsert_event
    with tempfile.TemporaryDirectory() as td:
        db, bid = _fresh_db_with_business(td)
        with connect(db) as conn:
            assert try_upsert_event(conn, bid, _event(kind="special", title="Bad")) is None
            assert try_upsert_event(conn, bid, _event(title="Good")) == "inserted"
            titles = [r[0] for r in conn.execute("SELECT title FROM events")]
            assert titles == ["Good"], f"only the good event should persist, got {titles}"
    print("  bad event doesn't block subsequent good event: OK")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} pipeline-resilience tests passed.")
