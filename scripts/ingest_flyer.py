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

import json
import os
import re
import sqlite3
import subprocess
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, TextIO
from urllib.parse import urlparse

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


def _now_iso_local() -> str:
    """Local-tz ISO timestamp, e.g. '2026-04-27T15:30:12-05:00'."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class SidecarLog:
    """Append-only JSON log for an ingest_flyer run.

    File layout:
      {
        "version": 1,
        "started_at": "<iso>",
        "entries": [<entry>, ...]
      }

    Each call to .append(entry) does an atomic read-mutate-write-rename so a
    Ctrl-C during write can't leave a partial file.
    """

    VERSION = 1

    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self._data = json.loads(path.read_text())
            if not isinstance(self._data.get("entries"), list):
                raise ValueError(f"{path}: malformed sidecar log")
        else:
            self._data = {
                "version": self.VERSION,
                "started_at": _now_iso_local(),
                "entries": [],
            }
            self._flush()

    def append(self, entry: dict) -> None:
        self._data["entries"].append(entry)
        self._flush()

    def processed_photos(self) -> set[str]:
        """Set of photo basenames already recorded in this log."""
        return {e["photo"] for e in self._data["entries"] if "photo" in e}

    def entries(self) -> list[dict]:
        return list(self._data["entries"])

    def _flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self.path)  # atomic rename on POSIX


ENRICHABLE_FIELDS = (
    "description",
    "start_time", "end_time",
    "start_datetime", "end_datetime",
    "price_info",
    "performers",
    "image_source_url", "image_local_path", "external_link",
    "recurrence_pattern",
)


def _is_empty(value) -> bool:
    """Treat None, empty string, empty list, and '[]' (DB JSON-empty) as empty."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in ("", "[]")
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def compute_enrichment(existing: dict, extracted: dict) -> dict:
    """Return only the fields where existing is empty AND extracted is non-empty.

    Never overwrite a non-empty existing value. Operates on the field set
    in ENRICHABLE_FIELDS.
    """
    diff: dict = {}
    for field in ENRICHABLE_FIELDS:
        if not _is_empty(existing.get(field)):
            continue
        new_val = extracted.get(field)
        if _is_empty(new_val):
            continue
        diff[field] = new_val
    return diff


# Path to config/businesses.yaml, relative to repo root.
BUSINESSES_YAML = Path(__file__).resolve().parent.parent / "config" / "businesses.yaml"


def slug_from_name(name: str) -> str:
    """Lowercase, ampersand->'and', strip non-alnum, hyphenate, trim leading 'the-'."""
    s = (name or "").strip().lower()
    s = s.replace("&", " and ")
    # Replace accented characters with their ASCII fallback (cafe, not café).
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # Anything not alnum becomes a space.
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = "-".join(s.split())
    if s.startswith("the-"):
        s = s[4:]
    return s


def format_business_yaml_block(
    *,
    slug: str,
    name: str,
    website: str,
    address: str | None,
) -> str:
    """Render a minimal businesses.yaml entry as text. Matches the existing
    file's indentation (2 spaces for list, 4 for fields, 6 for nested keys).

    The metadata + lat/lng + hours + pages blocks are intentionally omitted —
    they get filled in by the metadata extractor + geocoder + manual review.
    """
    addr_line = f"address: {address}" if address else "address: null"
    return (
        f"  - slug: {slug}\n"
        f"    name: {name}\n"
        f"    category: \n"
        f"    subcategory: \n"
        f"    website: {website}\n"
        f"    {addr_line}\n"
        f"    pages: []\n"
    )


def add_business_to_yaml(slug: str, name: str, website: str, address: str | None) -> None:
    """Append a new business entry to config/businesses.yaml.

    The file's structure is:
      businesses:
        - slug: ...
        ...
        - slug: ...
    We append after the last existing entry, preserving the comment header.
    """
    raw = BUSINESSES_YAML.read_text()
    block = format_business_yaml_block(slug=slug, name=name, website=website, address=address)
    # Ensure the file ends with a newline so our block doesn't run-on.
    if not raw.endswith("\n"):
        raw += "\n"
    BUSINESSES_YAML.write_text(raw + block)


def add_business_from_search(
    *,
    seed: dict,
    search_url: str,
    search_address: str | None,
    dry_run: bool = False,
) -> str:
    """Auto-add the venue to businesses.yaml + run metadata + geocoder.

    Returns the slug. Raises RuntimeError on subprocess failure (caller decides
    whether to mark the photo as failed:business-add-failed:<step>).

    When dry_run=True, prints what would happen and returns the would-be slug.
    """
    name = seed.get("venue_name") or "Unknown"
    slug = slug_from_name(name)

    # Derive website from the search URL: use the URL's origin if it points to
    # a venue page; otherwise leave it blank (metadata extractor needs *some*
    # website to crawl, so we default to the search URL itself).
    parsed = urlparse(search_url)
    website = f"{parsed.scheme}://{parsed.netloc}"

    if dry_run:
        print(f"    [DRY-RUN] would add business: slug={slug}, name={name},"
              f" website={website}, address={search_address!r}")
        return slug

    print(f"    adding business: {slug} ({name})")
    add_business_to_yaml(slug=slug, name=name, website=website, address=search_address)

    # Best-effort metadata + geocoding. If either fails, the entry stays in
    # the YAML and can be re-run later; the caller marks the photo failed.
    repo_root = Path(__file__).resolve().parent.parent
    print(f"    running extract_business_metadata.py {slug}…")
    r1 = subprocess.run(
        ["python3", "scripts/extract_business_metadata.py", slug],
        cwd=repo_root, capture_output=True, text=True,
    )
    if r1.returncode != 0:
        raise RuntimeError(f"extract_business_metadata failed: {r1.stderr or r1.stdout}")

    print(f"    running geocode_businesses.py {slug}…")
    r2 = subprocess.run(
        ["python3", "scripts/geocode_businesses.py", slug],
        cwd=repo_root, capture_output=True, text=True,
    )
    if r2.returncode != 0:
        raise RuntimeError(f"geocode_businesses failed: {r2.stderr or r2.stdout}")

    return slug


def print_walk_summary(entries: list[dict], *, dir_label: str, out: TextIO = sys.stdout) -> None:
    """Print a human-readable summary of a run from sidecar log entries."""
    counts = Counter(e.get("outcome", "unknown") for e in entries)
    total = sum(counts.values())

    out.write(f"\n─── Walk summary: {dir_label} ───\n")
    out.write(f"Photos processed: {total}\n")

    # Stable display order; only show categories that appeared.
    display_order = [
        "ingested", "enriched", "proceeded-as-new",
        "skipped:dedup-match", "skipped:no-web-trace", "skipped:user-quit",
    ]
    failed_categories = sorted(c for c in counts if c.startswith("failed:"))

    for cat in display_order + failed_categories:
        if cat not in counts:
            continue
        out.write(f"  {cat + ':':<26} {counts[cat]}")
        # Surface details for actionable categories.
        if cat == "skipped:no-web-trace":
            for e in entries:
                if e.get("outcome") == cat:
                    title = (e.get("seed") or {}).get("event_title") or e.get("photo")
                    out.write(f"\n     - {e.get('photo')} — \"{title}\"")
        elif cat.startswith("failed:"):
            for e in entries:
                if e.get("outcome") == cat:
                    out.write(f"\n     - {e.get('photo')} — {e.get('error') or '(no error captured)'}")
        out.write("\n")

    new_biz = [e for e in entries if e.get("business_added")]
    if new_biz:
        out.write(f"\nNew businesses added: {len(new_biz)}\n")
        for e in new_biz:
            out.write(f"  - {e.get('business_slug') or '(unknown slug)'}\n")
        out.write(f"  → review with: git diff config/businesses.yaml\n")

    out.write("\n")
