#!/usr/bin/env python3
"""Instagram post → event ingestion (experiment).

Treats each scraped Instagram post's caption as page text and its flyer image
as the single image, runs them through the existing multimodal extractor, and
writes events with source_type='instagram'. These rows are quarantined from the
live site (see PUBLISHED_SOURCE_TYPES in src/db.py) and deletable in one query:

    DELETE FROM events WHERE source_type='instagram';

Design: docs/superpowers/specs/2026-06-07-instagram-ingestion-design.md

Usage:
    python3 scripts/ingest_instagram.py <file.json>:<slug> [<file.json>:<slug> ...]
        [--dry-run] [--limit N] [--scraped-on YYYY-MM-DD]

Example:
    python3 scripts/ingest_instagram.py \\
        ~/Downloads/meetinghousetavernchi_instagram_posts.json:meeting-house-tavern \\
        ~/Downloads/atmospherebarchicago_instagram_posts.json:atmosphere
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def parse_relative_time(text: str | None, reference: date) -> date | None:
    """Convert Instagram's relative 'time' field to an absolute date.

    Handles 'N days ago', 'N day ago', 'a day ago', 'yesterday', 'today',
    'N weeks ago', 'a week ago', 'N hours/minutes ago' (→ reference day),
    'an hour ago'. Returns None for anything unrecognized (e.g. absolute dates
    we don't bother parsing — caller falls back to the reference date).
    """
    if not text:
        return None
    t = text.strip().lower()
    if t in ("today", "just now", "now"):
        return reference
    if t in ("yesterday",):
        return reference - timedelta(days=1)
    # hours / minutes ago → same calendar day as reference
    if re.search(r"\b(hour|hours|minute|minutes|min|mins|second|seconds)\b", t):
        return reference
    m = re.match(r"(?:a|an|\d+)\s+(day|days|week|weeks|month|months)\s+ago", t)
    if not m:
        return None
    num_token = t.split()[0]
    n = 1 if num_token in ("a", "an") else int(num_token)
    unit = m.group(1)
    if unit.startswith("day"):
        return reference - timedelta(days=n)
    if unit.startswith("week"):
        return reference - timedelta(weeks=n)
    if unit.startswith("month"):
        return reference - timedelta(days=30 * n)
    return None
