#!/usr/bin/env python3
"""Geocode businesses in config/businesses.yaml using Nominatim.

For each business that has an `address` but no `lat`/`lng` at the top level,
calls Nominatim and writes `lat:` and `lng:` directly into the YAML text
(comment-preserving, surgical edit — no yaml.safe_dump reformatting).

Usage:
    python3 scripts/geocode_businesses.py                # all missing
    python3 scripts/geocode_businesses.py vincent        # one by slug
    python3 scripts/geocode_businesses.py --force        # refresh all
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / "config" / "businesses.yaml"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "aville.net/1.0 (justingonder@gmail.com)"
TIMEOUT = 8
RATE_LIMIT_SLEEP = 1.1  # seconds between requests (Nominatim TOS: max 1 req/s)


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

def _normalize_address(address: str) -> str:
    """Strip secondary unit designators that confuse Nominatim (e.g. '2nd Floor', 'Suite 200').

    Nominatim geocodes street addresses; unit/floor suffixes often return no results.
    """
    # Remove common secondary designators: "Floor N", "Nth Floor", "Suite N", "#N"
    address = re.sub(r",?\s*\d+(st|nd|rd|th)\s+[Ff]loor\b", "", address)
    address = re.sub(r",?\s*[Ff]loor\s+\d+\b", "", address)
    address = re.sub(r",?\s*[Ss]uite\s+\S+", "", address)
    address = re.sub(r",?\s*#\s*\S+", "", address)
    return address.strip().strip(",").strip()


def geocode(address: str) -> tuple[float, float] | None:
    """Call Nominatim and return (lat, lng) or None on failure."""
    normalized = _normalize_address(address)
    if normalized != address:
        print(f"  (normalized address: {normalized!r})")
    params = urllib.parse.urlencode({
        "q": normalized,
        "format": "json",
        "limit": "1",
        "countrycodes": "us",
    })
    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        print(f"  WARNING: network error: {exc}")
        return None

    if not data:
        print(f"  WARNING: no results for address: {normalized!r}")
        return None

    try:
        lat = float(data[0]["lat"])
        lng = float(data[0]["lon"])
        return lat, lng
    except (KeyError, ValueError, IndexError) as exc:
        print(f"  WARNING: parse error ({exc}) for address: {normalized!r}")
        return None


# ---------------------------------------------------------------------------
# Text-level YAML editor
# ---------------------------------------------------------------------------

def _insert_latlng_in_yaml(raw: str, slug: str, lat: float, lng: float) -> str:
    """Insert (or replace) lat/lng lines for the given slug in raw YAML text.

    Places `lat:` and `lng:` immediately after the `address:` line for
    natural field ordering. If they already exist, replaces them in place.

    Does NOT reformat any other part of the file.
    """
    lines = raw.splitlines(keepends=True)

    # Find the line index where this slug's entry starts.
    slug_line_idx = None
    for i, line in enumerate(lines):
        if re.match(rf"^  - slug:\s*{re.escape(slug)}\s*$", line):
            slug_line_idx = i
            break
    if slug_line_idx is None:
        raise ValueError(f"slug '{slug}' not found in YAML")

    # Find the bounds of this entry (up to the next slug or EOF).
    next_entry_idx = len(lines)
    for i in range(slug_line_idx + 1, len(lines)):
        if re.match(r"^  - slug:\s*\S", lines[i]):
            next_entry_idx = i
            break

    entry_lines = lines[slug_line_idx:next_entry_idx]

    lat_line = f"    lat: {lat}\n"
    lng_line = f"    lng: {lng}\n"

    # Check if lat/lng already exist within this entry; if so, replace them.
    lat_idx_in_entry = None
    lng_idx_in_entry = None
    address_idx_in_entry = None

    for j, line in enumerate(entry_lines):
        if re.match(r"^    address:\s*", line):
            address_idx_in_entry = j
        if re.match(r"^    lat:\s*", line):
            lat_idx_in_entry = j
        if re.match(r"^    lng:\s*", line):
            lng_idx_in_entry = j

    if lat_idx_in_entry is not None and lng_idx_in_entry is not None:
        # Replace both existing lines in place.
        entry_lines[lat_idx_in_entry] = lat_line
        entry_lines[lng_idx_in_entry] = lng_line
    elif lat_idx_in_entry is not None:
        # lat exists but not lng — insert lng right after lat.
        entry_lines[lat_idx_in_entry] = lat_line
        entry_lines.insert(lat_idx_in_entry + 1, lng_line)
    elif lng_idx_in_entry is not None:
        # lng exists but not lat — insert lat right before lng.
        entry_lines[lng_idx_in_entry] = lng_line
        entry_lines.insert(lng_idx_in_entry, lat_line)
    elif address_idx_in_entry is not None:
        # Insert lat + lng right after address:.
        insert_at = address_idx_in_entry + 1
        entry_lines.insert(insert_at, lng_line)
        entry_lines.insert(insert_at, lat_line)
    else:
        # No address line found — append to end of entry as fallback.
        entry_lines.append(lat_line)
        entry_lines.append(lng_line)

    lines[slug_line_idx:next_entry_idx] = entry_lines
    return "".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    target_slug = argv[0] if argv else None

    raw_yaml = YAML_PATH.read_text()
    doc = yaml.safe_load(raw_yaml)
    businesses = doc["businesses"]

    updated: list[tuple[str, float, float]] = []  # (slug, lat, lng)

    for biz in businesses:
        slug = biz["slug"]
        if target_slug and slug != target_slug:
            continue

        address = biz.get("address") or ""
        if not address:
            print(f"skip {slug} (no address)")
            continue

        has_lat = biz.get("lat") is not None
        has_lng = biz.get("lng") is not None
        if has_lat and has_lng and not force:
            print(f"skip {slug} (already geocoded; --force to refresh)")
            continue

        print(f"-> {slug}: geocoding {address!r} …")
        result = geocode(address)
        time.sleep(RATE_LIMIT_SLEEP)

        if result is None:
            print(f"  FAILED: skipping {slug}")
            continue

        lat, lng = result
        print(f"  geocoded: lat={lat}, lng={lng}")
        updated.append((slug, lat, lng))

    if not updated:
        print("\nnothing to write.")
        return 0

    # Apply all updates to raw YAML text (comment-preserving, surgical).
    for slug, lat, lng in updated:
        raw_yaml = _insert_latlng_in_yaml(raw_yaml, slug, lat, lng)

    YAML_PATH.write_text(raw_yaml)
    print(f"\nwrote {YAML_PATH} ({len(updated)} business(es) geocoded)")

    # Sanity-check: the updated file must still parse.
    yaml.safe_load(YAML_PATH.read_text())
    print("YAML parse check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
