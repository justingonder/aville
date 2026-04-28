#!/usr/bin/env python3
"""Flyer-ingestion CLI.

Treats phone-camera photos of paper flyers as SEEDS for a web search,
extracts events from the discovered authoritative web source, and writes
to the same events table the website-scraping pipeline uses.

See docs/superpowers/specs/2026-04-24-flyer-ingestion-pipeline-design.md
for the full design and decisions.

Usage:
    python3 scripts/ingest_flyer.py path/to/photo.jpg
    python3 scripts/ingest_flyer.py --dir walks/2026-04-27/
    python3 scripts/ingest_flyer.py path/to/photo.jpg --source-url https://...
    python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --seed-only
    python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --dry-run
    python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --force
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Match thresholds — top-of-file constants for easy retuning.
BUSINESS_CONFIDENT_MATCH = 0.80
BUSINESS_AMBIGUOUS_MIN = 0.60
TITLE_DEDUP_THRESHOLD = 0.70
DATED_EVENT_DAY_WINDOW = 2     # ±N days for dated-event dedup
RECURRING_TIME_WINDOW_MIN = 30  # ±N minutes for recurring-event dedup


def _name_similarity(a: str, b: str) -> float:
    """Case-insensitive sequence similarity in [0, 1]."""
    return SequenceMatcher(None, (a or "").lower().strip(), (b or "").lower().strip()).ratio()


def resolve_business(
    venue_name: str,
    businesses: Iterable[dict],
) -> tuple[str, float] | list[tuple[str, float]] | None:
    """Match the seed-extracted venue_name against businesses.yaml entries.

    Returns:
      (slug, score)         — confident match (best score >= BUSINESS_CONFIDENT_MATCH).
      [(slug, score), ...]  — ambiguous (best in [BUSINESS_AMBIGUOUS_MIN, BUSINESS_CONFIDENT_MATCH));
                              top 3 candidates above BUSINESS_AMBIGUOUS_MIN, best-first.
      None                  — no candidate above BUSINESS_AMBIGUOUS_MIN.
    """
    if not venue_name:
        return None

    scored = [
        (b["slug"], _name_similarity(venue_name, b.get("name") or ""))
        for b in businesses
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    if not scored:
        return None

    best_slug, best_score = scored[0]
    if best_score >= BUSINESS_CONFIDENT_MATCH:
        return (best_slug, best_score)
    if best_score >= BUSINESS_AMBIGUOUS_MIN:
        return [pair for pair in scored[:3] if pair[1] >= BUSINESS_AMBIGUOUS_MIN]
    return None


def _parse_hhmm_to_minutes(hhmm: str | None) -> int | None:
    """'12:30' -> 750. None or unparseable -> None."""
    if not hhmm:
        return None
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _parse_iso_date(iso: str | None) -> date | None:
    """'2026-05-02' or '2026-05-02T...' -> date. None / unparseable -> None."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso[:10]).date()
    except ValueError:
        return None


def find_dedup_match(
    conn: sqlite3.Connection,
    *,
    business_id: int,
    seed: dict,
) -> sqlite3.Row | None:
    """Query active+stale events at this business; return the first match or None.

    Match rule (per spec Section A Step 3):
      - Dated:    same business + date within ±DATED_EVENT_DAY_WINDOW days
                  + fuzzy title similarity >= TITLE_DEDUP_THRESHOLD.
      - Recurring: same business + matching recurrence_pattern
                   + start_time within ±RECURRING_TIME_WINDOW_MIN minutes
                     (or both null) + title sim >= TITLE_DEDUP_THRESHOLD.
    """
    rows = conn.execute(
        """SELECT * FROM events
           WHERE business_id = ? AND status IN ('active', 'stale')""",
        (business_id,),
    ).fetchall()

    seed_title = seed.get("event_title") or ""
    seed_kind = seed.get("kind_guess")

    if seed_kind == "dated":
        seed_date = _parse_iso_date(seed.get("date_hint_iso"))
        for row in rows:
            if row["kind"] != "dated":
                continue
            if _name_similarity(seed_title, row["title"]) < TITLE_DEDUP_THRESHOLD:
                continue
            row_date = _parse_iso_date(row["start_datetime"])
            if seed_date is None or row_date is None:
                # Without dates we can't safely call this a dup — skip.
                continue
            if abs((row_date - seed_date).days) <= DATED_EVENT_DAY_WINDOW:
                return row
        return None

    if seed_kind == "recurring":
        seed_pattern = seed.get("recurrence_pattern") or ""
        seed_start = _parse_hhmm_to_minutes(seed.get("start_time"))
        for row in rows:
            if row["kind"] != "recurring":
                continue
            if _name_similarity(seed_title, row["title"]) < TITLE_DEDUP_THRESHOLD:
                continue
            if (row["recurrence_pattern"] or "") != seed_pattern:
                continue
            row_start = _parse_hhmm_to_minutes(row["start_time"])
            if seed_start is None and row_start is None:
                return row
            if seed_start is None or row_start is None:
                continue
            if abs(seed_start - row_start) <= RECURRING_TIME_WINDOW_MIN:
                return row
        return None

    # kind_guess unknown: don't risk a false-positive dup.
    return None
