#!/usr/bin/env python3
"""Tests for extraction change-detection: skip the Claude call when the inputs
Claude would see (page text + kept image URLs) are unchanged since the last
successful run.

Run: python3 scripts/test_change_detection.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_signature_is_deterministic():
    from src.db import compute_input_signature
    sig1 = compute_input_signature("hello world", ["http://a/1.jpg", "http://a/2.jpg"])
    sig2 = compute_input_signature("hello world", ["http://a/1.jpg", "http://a/2.jpg"])
    assert sig1 == sig2, "same inputs must produce the same signature"
    print("  signature deterministic: OK")


def test_signature_order_independent_for_images():
    from src.db import compute_input_signature
    a = compute_input_signature("t", ["http://a/1.jpg", "http://a/2.jpg"])
    b = compute_input_signature("t", ["http://a/2.jpg", "http://a/1.jpg"])
    assert a == b, "image URL order must not change the signature"
    print("  signature order-independent: OK")


def test_signature_changes_with_page_text():
    from src.db import compute_input_signature
    a = compute_input_signature("Monday trivia 7pm", ["http://a/1.jpg"])
    b = compute_input_signature("Tuesday trivia 8pm", ["http://a/1.jpg"])
    assert a != b, "different page text must produce a different signature"
    print("  signature changes with page text: OK")


def test_signature_changes_with_images():
    from src.db import compute_input_signature
    a = compute_input_signature("t", ["http://a/1.jpg"])
    b = compute_input_signature("t", ["http://a/1.jpg", "http://a/2.jpg"])
    c = compute_input_signature("t", [])
    assert a != b, "adding an image must change the signature"
    assert a != c, "removing all images must change the signature"
    print("  signature changes with images: OK")


def test_last_good_signature_none_when_empty():
    from src.db import connect, init_db, last_good_signature
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        init_db(db)
        with connect(db) as conn:
            assert last_good_signature(conn, "http://x/events") is None
    print("  last_good_signature empty → None: OK")


def _log(conn, url, *, signature, events_found, notes=None):
    from src.db import now_iso
    conn.execute(
        """INSERT INTO fetch_log (page_url, fetched_at, status_code,
           content_hash, input_signature, events_found, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (url, now_iso(), 200, "htmlhash", signature, events_found, notes),
    )


def test_last_good_signature_returns_latest_non_null():
    from src.db import connect, init_db, last_good_signature
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        init_db(db)
        url = "http://x/events"
        with connect(db) as conn:
            _log(conn, url, signature="sig-old", events_found=3)
            _log(conn, url, signature="sig-new", events_found=3)
            assert last_good_signature(conn, url) == "sig-new"
    print("  last_good_signature returns latest: OK")


def test_last_good_signature_ignores_failed_runs():
    """A failed extraction stores NULL signature so the page keeps getting
    retried — the last *good* signature must skip over it."""
    from src.db import connect, init_db, last_good_signature
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        init_db(db)
        url = "http://x/events"
        with connect(db) as conn:
            _log(conn, url, signature="sig-good", events_found=2)
            # a later failure: no signature recorded
            _log(conn, url, signature=None, events_found=0, notes="extract: boom")
            assert last_good_signature(conn, url) == "sig-good", \
                "failed (NULL-signature) rows must not shadow the last good one"
    print("  last_good_signature ignores failures: OK")


def test_last_good_signature_scoped_per_url():
    from src.db import connect, init_db, last_good_signature
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        init_db(db)
        with connect(db) as conn:
            _log(conn, "http://x/a", signature="sig-a", events_found=1)
            _log(conn, "http://x/b", signature="sig-b", events_found=1)
            assert last_good_signature(conn, "http://x/a") == "sig-a"
            assert last_good_signature(conn, "http://x/b") == "sig-b"
    print("  last_good_signature scoped per URL: OK")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} change-detection tests passed.")
