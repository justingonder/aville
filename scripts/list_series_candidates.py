#!/usr/bin/env python3
"""List recurring events that look like they need a manual ends_on date.

TV viewing parties, sports watch parties, and other broadcast-tied recurring
events don't have a natural end date in the source data — the business page
just says "Fridays at 7pm" without mentioning that the current season ends in
N weeks. This script surfaces candidates so you can look up the real series
end date (quick web search) and set it:

    sqlite3 data/app.db "UPDATE events SET ends_on='YYYY-MM-DD' WHERE id=N;"

Once ends_on is in the past, the event is hidden from all display buckets.

Detection heuristics (broadcast-tied recurring events):
  - Tag: tv-viewing-party
  - Title contains: "viewing party", "watch party", "rpdr", "rupaul", "survivor"
    (or any substring passed via --keyword)

Trivia nights are explicitly excluded — even when themed around a TV show
(Friends trivia, Golden Girls trivia), they're evergreen and don't tie to a
broadcast calendar.

Usage:
  python3 scripts/list_series_candidates.py
  python3 scripts/list_series_candidates.py --keyword "bears"   # add one-off match
  python3 scripts/list_series_candidates.py --all               # show ones already set too
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.db import connect

DEFAULT_TITLE_KEYWORDS = [
    "viewing party",
    "watch party",
    "rpdr",
    "rupaul",
    "survivor",
]
SERIES_TAGS = {"tv-viewing-party"}
EXCLUDE_TAGS = {"trivia"}


def find_candidates(conn, extra_keywords=None, include_already_set=False):
    """Return [(event_row_dict, reason_str), ...] for recurring events that look
    like they need a manual ends_on date. Importable from other tools (admin UI).
    """
    title_keywords = [k.lower() for k in DEFAULT_TITLE_KEYWORDS + list(extra_keywords or [])]

    rows = conn.execute(
        """SELECT e.id, e.title, e.tags, e.recurrence_pattern, e.ends_on,
                  b.name AS business_name, b.slug AS business_slug
           FROM events e JOIN businesses b ON e.business_id = b.id
           WHERE e.status = 'active' AND e.kind = 'recurring'
           ORDER BY b.name, e.title"""
    ).fetchall()

    candidates = []
    for r in rows:
        ev = dict(r)
        tags = set(json.loads(ev["tags"] or "[]"))
        if tags & EXCLUDE_TAGS:
            continue
        title_lower = (ev["title"] or "").lower()

        tag_hit = bool(tags & SERIES_TAGS)
        title_hit = any(k in title_lower for k in title_keywords)
        if not (tag_hit or title_hit):
            continue

        if not include_already_set and ev["ends_on"]:
            continue

        reason = []
        if tag_hit:
            reason.append("tag:" + ",".join(sorted(tags & SERIES_TAGS)))
        if title_hit:
            matched = [k for k in title_keywords if k in title_lower]
            reason.append("title:" + ",".join(matched))

        candidates.append((ev, ", ".join(reason)))

    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Additional title-substring keyword to match. Repeatable.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include events that already have ends_on set (default: only nulls).",
    )
    args = parser.parse_args()

    with connect() as conn:
        candidates = find_candidates(conn, extra_keywords=args.keyword, include_already_set=args.all)

    if not candidates:
        print("No candidates found.")
        return

    print(f"\n{'ID':<5}  {'Title':<40}  {'Business':<26}  {'Pattern':<20}  {'ends_on':<12}  Reason")
    print("-" * 130)
    for ev, reason in candidates:
        ends = ev["ends_on"] or "-"
        pattern = ev["recurrence_pattern"] or "-"
        title = (ev["title"] or "")[:40]
        biz = (ev["business_name"] or "")[:26]
        print(f"{ev['id']:<5}  {title:<40}  {biz:<26}  {pattern:<20}  {ends:<12}  {reason}")
    print()
    print(f"{len(candidates)} candidate{'s' if len(candidates) != 1 else ''}.")
    print("\nTo set an end date:")
    print('  sqlite3 data/app.db "UPDATE events SET ends_on=\'YYYY-MM-DD\' WHERE id=N;"')
    print()


if __name__ == "__main__":
    main()
