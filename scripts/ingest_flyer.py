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

import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Match thresholds — top-of-file constants for easy retuning.
BUSINESS_CONFIDENT_MATCH = 0.90
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
