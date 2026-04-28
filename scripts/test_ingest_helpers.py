#!/usr/bin/env python3
"""Smoke tests for the in-script helpers in scripts/ingest_flyer.py.

Run: python3 scripts/test_ingest_helpers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_resolve_business_confident_match():
    from scripts.ingest_flyer import resolve_business, BUSINESS_CONFIDENT_MATCH
    businesses = [
        {"slug": "guesthouse-hotel", "name": "The Guesthouse Hotel"},
        {"slug": "vincent",          "name": "Vincent"},
        {"slug": "hopleaf",          "name": "Hopleaf Bar"},
    ]
    # Realistic case: Claude's seed includes the city suffix; YAML name doesn't.
    result = resolve_business("The Guesthouse Hotel Chicago", businesses)
    assert isinstance(result, tuple), f"expected confident-match tuple, got {result!r}"
    slug, score = result
    assert slug == "guesthouse-hotel", f"wrong slug: {slug}"
    assert score >= BUSINESS_CONFIDENT_MATCH, \
        f"score {score} below confident threshold {BUSINESS_CONFIDENT_MATCH}"
    print(f"  resolve_business confident: OK ({slug}, score={score:.2f})")


def test_resolve_business_ambiguous():
    from scripts.ingest_flyer import resolve_business
    businesses = [
        {"slug": "guesthouse-hotel", "name": "The Guesthouse Hotel"},
        {"slug": "guesthouse-bar",   "name": "Guesthouse Bar"},
        {"slug": "vincent",          "name": "Vincent"},
    ]
    # "Guesthouse on Clark" is a realistic flyer hint that's close to two YAML
    # entries — both score in the ambiguous band, neither hits the confident
    # threshold. (Empirically: ~0.67 and ~0.79 against the two Guesthouse names.)
    result = resolve_business("Guesthouse on Clark", businesses)
    assert isinstance(result, list), f"expected ambiguous list, got {result!r}"
    assert len(result) >= 2, f"expected 2+ candidates, got {len(result)}"
    slugs = [c[0] for c in result]
    assert "guesthouse-hotel" in slugs and "guesthouse-bar" in slugs, f"missing candidates: {slugs}"
    print(f"  resolve_business ambiguous: OK ({slugs})")


def test_resolve_business_no_match():
    from scripts.ingest_flyer import resolve_business
    businesses = [
        {"slug": "vincent", "name": "Vincent"},
        {"slug": "hopleaf", "name": "Hopleaf Bar"},
    ]
    result = resolve_business("Some Totally Unrelated Cafe", businesses)
    assert result is None, f"expected None for no match, got {result!r}"
    print(f"  resolve_business no match: OK")


def test_dedup_match_dated_event():
    """Dated-event dedup: same business + ±2 days + title sim >= 0.7."""
    import sqlite3
    from scripts.ingest_flyer import find_dedup_match

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, business_id INTEGER, kind TEXT, title TEXT,
            recurrence_pattern TEXT, start_time TEXT, end_time TEXT,
            start_datetime TEXT, end_datetime TEXT, status TEXT
        );
        INSERT INTO events VALUES (1, 5, 'dated', 'Wander Home Holiday Market',
            NULL, NULL, NULL, '2026-05-02T12:00:00-05:00', NULL, 'active');
    """)

    seed = {
        "kind_guess": "dated",
        "event_title": "Wander Home Holiday Market",
        "date_hint_iso": "2026-05-03",  # 1 day off — within ±2-day window
    }
    match = find_dedup_match(conn, business_id=5, seed=seed)
    assert match is not None and match["id"] == 1, f"expected event 1, got {match}"
    print(f"  dedup dated within window: OK")

    # Outside the window
    seed["date_hint_iso"] = "2026-05-10"
    match = find_dedup_match(conn, business_id=5, seed=seed)
    assert match is None, f"expected None outside window, got {match}"
    print(f"  dedup dated outside window: OK")


def test_dedup_match_recurring_event():
    """Recurring-event dedup: same business + matching pattern + ±30 min start_time."""
    import sqlite3
    from scripts.ingest_flyer import find_dedup_match

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, business_id INTEGER, kind TEXT, title TEXT,
            recurrence_pattern TEXT, start_time TEXT, end_time TEXT,
            start_datetime TEXT, end_datetime TEXT, status TEXT
        );
        INSERT INTO events VALUES (1, 5, 'recurring', 'Drag Brunch',
            'weekly:saturday', '12:00', '14:00', NULL, NULL, 'active');
    """)

    seed = {
        "kind_guess": "recurring",
        "event_title": "Drag Brunch",
        "recurrence_pattern": "weekly:saturday",
        "start_time": "12:15",   # within ±30 min
    }
    match = find_dedup_match(conn, business_id=5, seed=seed)
    assert match is not None and match["id"] == 1, f"expected event 1, got {match}"
    print(f"  dedup recurring within window: OK")

    seed["start_time"] = "15:00"  # outside window
    match = find_dedup_match(conn, business_id=5, seed=seed)
    assert match is None, f"expected None for time-far recurring, got {match}"
    print(f"  dedup recurring outside window: OK")


def test_dedup_no_match_different_business():
    import sqlite3
    from scripts.ingest_flyer import find_dedup_match

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, business_id INTEGER, kind TEXT, title TEXT,
            recurrence_pattern TEXT, start_time TEXT, end_time TEXT,
            start_datetime TEXT, end_datetime TEXT, status TEXT
        );
        INSERT INTO events VALUES (1, 5, 'dated', 'Wander Home Holiday Market',
            NULL, NULL, NULL, '2026-05-02T12:00:00-05:00', NULL, 'active');
    """)

    seed = {"kind_guess": "dated", "event_title": "Wander Home Holiday Market",
            "date_hint_iso": "2026-05-02"}
    match = find_dedup_match(conn, business_id=99, seed=seed)
    assert match is None, "different business should not match"
    print(f"  dedup wrong business: OK")


def test_sidecar_log_creates_and_appends():
    import json
    import tempfile
    from scripts.ingest_flyer import SidecarLog

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / ".ingest_log.json"
        log = SidecarLog(log_path)
        log.append({"photo": "a.jpg", "outcome": "ingested", "event_id": 1})
        log.append({"photo": "b.jpg", "outcome": "skipped:no-web-trace"})
        # Re-load from disk
        data = json.loads(log_path.read_text())
        assert data["version"] == 1
        assert len(data["entries"]) == 2
        assert data["entries"][0]["photo"] == "a.jpg"
        assert data["entries"][1]["outcome"] == "skipped:no-web-trace"
        print(f"  sidecar log create+append: OK")


def test_sidecar_log_processed_photos_set():
    import tempfile
    from scripts.ingest_flyer import SidecarLog

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / ".ingest_log.json"
        log = SidecarLog(log_path)
        log.append({"photo": "a.jpg", "outcome": "ingested"})
        log.append({"photo": "b.jpg", "outcome": "skipped:no-web-trace"})
        # Reload as a fresh instance (simulates a re-run)
        log2 = SidecarLog(log_path)
        processed = log2.processed_photos()
        assert processed == {"a.jpg", "b.jpg"}, f"got {processed}"
        print(f"  sidecar log processed set: OK")


def test_sidecar_log_atomic_write():
    """Append-via-tmp-rename leaves no orphan .tmp files on success."""
    import tempfile
    from scripts.ingest_flyer import SidecarLog

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / ".ingest_log.json"
        log = SidecarLog(log_path)
        log.append({"photo": "a.jpg", "outcome": "ingested"})
        tmp_path = log_path.with_suffix(log_path.suffix + ".tmp")
        assert not tmp_path.exists(), "tmp file should not survive a successful write"
        print(f"  sidecar log atomic: OK")


def test_compute_enrichment_fills_gaps_only():
    from scripts.ingest_flyer import compute_enrichment

    existing = {
        "id": 1,
        "title": "Drag Brunch",
        "start_time": "12:00",
        "end_time": None,
        "price_info": None,
        "performers": "[]",   # JSON string in DB; helper handles parsing
        "description": "Some existing description.",
    }
    extracted = {
        "title": "Drag Brunch (Pride Edition)",   # would change but should NOT
        "start_time": "12:00",                    # same — no-op
        "end_time": "14:00",                      # fills gap
        "price_info": "$25 cover",                # fills gap
        "performers": [{"name": "Aunty Kim", "role": "host"}],   # fills empty list
        "description": "New description.",        # would change but should NOT
    }
    diff = compute_enrichment(existing, extracted)
    assert "title" not in diff, "title was non-null; must not enrich"
    assert "description" not in diff, "description was non-null; must not enrich"
    assert "start_time" not in diff, "start_time was already 12:00; no diff"
    assert diff.get("end_time") == "14:00"
    assert diff.get("price_info") == "$25 cover"
    # Performers: empty list / "[]" should be treated as gap-fillable.
    assert diff.get("performers") == [{"name": "Aunty Kim", "role": "host"}]
    print(f"  compute_enrichment fills only gaps: OK")


def test_compute_enrichment_no_gaps_returns_empty():
    from scripts.ingest_flyer import compute_enrichment
    existing = {"id": 1, "title": "X", "start_time": "12:00", "end_time": "14:00",
                "price_info": "$10", "performers": '[{"name":"A","role":"host"}]',
                "description": "Y"}
    extracted = {"title": "X", "start_time": "12:00", "end_time": "14:00",
                 "price_info": "$15", "performers": [], "description": "Z"}
    diff = compute_enrichment(existing, extracted)
    assert diff == {}, f"no gaps to fill, got {diff}"
    print(f"  compute_enrichment no gaps: OK")


def test_slug_from_name():
    from scripts.ingest_flyer import slug_from_name
    assert slug_from_name("The Guesthouse Hotel") == "guesthouse-hotel"
    assert slug_from_name("Mr. Beef & Pizza!") == "mr-beef-and-pizza"
    assert slug_from_name("  Hopleaf  Bar  ") == "hopleaf-bar"
    assert slug_from_name("Café 53") == "cafe-53"
    print(f"  slug_from_name: OK")


def test_format_business_yaml_block():
    from scripts.ingest_flyer import format_business_yaml_block
    block = format_business_yaml_block(
        slug="guesthouse-hotel",
        name="The Guesthouse Hotel",
        website="https://guesthousehotel.com",
        address="4872 N Clark St, Chicago, IL 60640",
    )
    # Required structural pieces (don't lock to exact whitespace; YAML parser will validate later).
    assert "  - slug: guesthouse-hotel" in block
    assert "name: The Guesthouse Hotel" in block
    assert "website: https://guesthousehotel.com" in block
    assert "4872 N Clark St" in block
    print(f"  format_business_yaml_block: OK")


def test_format_business_yaml_block_null_address():
    from scripts.ingest_flyer import format_business_yaml_block
    block = format_business_yaml_block(
        slug="x", name="X", website="https://x.com", address=None,
    )
    assert "address: null" in block, f"null address must serialize as 'null', got: {block}"
    print(f"  format_business_yaml_block null address: OK")


if __name__ == "__main__":
    test_resolve_business_confident_match()
    test_resolve_business_ambiguous()
    test_resolve_business_no_match()
    test_dedup_match_dated_event()
    test_dedup_match_recurring_event()
    test_dedup_no_match_different_business()
    test_sidecar_log_creates_and_appends()
    test_sidecar_log_processed_photos_set()
    test_sidecar_log_atomic_write()
    test_compute_enrichment_fills_gaps_only()
    test_compute_enrichment_no_gaps_returns_empty()
    test_slug_from_name()
    test_format_business_yaml_block()
    test_format_business_yaml_block_null_address()
    print("PASS")
