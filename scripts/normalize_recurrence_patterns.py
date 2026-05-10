#!/usr/bin/env python3
"""One-time backfill: rewrite contiguous-day CSV recurrence_patterns into
range form for storage consistency.

`weekly:wednesday,thursday,friday,saturday,sunday` becomes
`weekly:wednesday-sunday`. Non-consecutive CSVs, single-day, already-range,
daily, and monthly:* patterns pass through unchanged.

Why this exists: extraction emits whichever shape Claude latched onto from
the source page wording, so logically-identical patterns get stored as
different strings. The display layer collapses both forms to the same
"Wed–Sun" label (PR #37), but `match_key` includes the raw pattern — if
extraction switches form between runs, the upsert misses and inserts a
duplicate. As of `src/db.py::normalize_recurrence_pattern` being wired
into `build_match_key` and `upsert_event`, the stored shape is now
canonicalized on write. This script backfills existing rows so the
storage is consistent immediately rather than waiting for re-extraction
to touch each row.

Collision handling:
  Normalizing existing rows can surface latent duplicates — rows that
  were created with different surface forms of the same pattern. By
  default the script reports collisions and exits without writing. Pass
  `--delete-stale-duplicates` to auto-resolve: keep the active row (or
  the most-recently-extracted row when all are non-active), DELETE the
  rest, then proceed with the normalization. Deletions are logged.

Usage:
  python3 scripts/normalize_recurrence_patterns.py --dry-run
  python3 scripts/normalize_recurrence_patterns.py
  python3 scripts/normalize_recurrence_patterns.py --delete-stale-duplicates

Idempotent once normalized: re-running is a no-op.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect, normalize_recurrence_pattern, build_match_key  # noqa: E402


_STATUS_RANK = {"active": 0, "stale": 1, "expired": 2, "rejected": 3}


def _survivor(rows: list[dict]) -> dict:
    """Pick the canonical row from a collision cluster.

    Preference order:
      1. Lowest _STATUS_RANK (active > stale > expired > rejected)
      2. Most recent last_extracted_at
      3. Lowest id (oldest)
    """
    def _key(r):
        return (
            _STATUS_RANK.get(r["status"], 99),
            -(int(r["last_extracted_at_epoch"]) if r["last_extracted_at_epoch"] else 0),
            r["id"],
        )
    return min(rows, key=_key)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change without writing")
    parser.add_argument("--delete-stale-duplicates", action="store_true",
                        help="auto-resolve collisions by deleting non-survivors")
    args = parser.parse_args()

    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT id, business_id, kind, title, recurrence_pattern,
                      start_time, match_key, status, last_extracted_at,
                      strftime('%s', last_extracted_at) AS last_extracted_at_epoch
               FROM events
               WHERE recurrence_pattern IS NOT NULL"""
        ).fetchall()]

        # Compute target pattern + match_key for every row (including those
        # that don't need pattern updates — they still tell us where the new
        # match_keys land for collision detection).
        for r in rows:
            r["new_pattern"] = normalize_recurrence_pattern(r["recurrence_pattern"])
            r["new_match_key"] = build_match_key({
                "kind": r["kind"],
                "title": r["title"],
                "recurrence_pattern": r["new_pattern"],
                "start_time": r["start_time"],
            })

        # Group by (business_id, new_match_key) to find collisions.
        clusters: dict[tuple[int, str], list[dict]] = {}
        for r in rows:
            key = (r["business_id"], r["new_match_key"])
            clusters.setdefault(key, []).append(r)

        collisions = [items for items in clusters.values() if len(items) > 1]
        # Rows that need a pattern UPDATE (target differs from current)
        pattern_changes = [r for r in rows if r["new_pattern"] != r["recurrence_pattern"]]
        # Rows that need a match_key UPDATE even though pattern is canonical
        # (e.g. monthly:last-friday whose old match_key was monthly:4th-friday)
        mk_drift = [r for r in rows
                    if r["new_pattern"] == r["recurrence_pattern"]
                    and r["new_match_key"] != r["match_key"]]

        # Plan summary
        print(f"\nFound {len(pattern_changes)} pattern(s) to normalize.")
        if mk_drift:
            print(f"Plus {len(mk_drift)} row(s) with match_key drift (pattern already canonical "
                  f"but stored match_key is stale).")
        print(f"{len(collisions)} collision cluster(s) — rows that would share a key after normalization.\n")

        if pattern_changes:
            groups: dict[tuple[str, str], list[dict]] = {}
            for c in pattern_changes:
                groups.setdefault((c["recurrence_pattern"], c["new_pattern"]), []).append(c)
            for (old, new), items in sorted(groups.items()):
                print(f"  {old}")
                print(f"    → {new}  ({len(items)} event{'s' if len(items) != 1 else ''})")
                for it in items[:5]:
                    print(f"      · event {it['id']}: {it['title']!r}")
                if len(items) > 5:
                    print(f"      · …and {len(items) - 5} more")
            print()

        if collisions:
            print("Collisions:\n")
            for cluster in collisions:
                surv = _survivor(cluster)
                print(f"  → cluster of {len(cluster)} on business_id={cluster[0]['business_id']}, "
                      f"target key {cluster[0]['new_match_key']!r}")
                for r in cluster:
                    marker = "KEEP" if r["id"] == surv["id"] else "DELETE"
                    print(f"      [{marker}] event {r['id']}: status={r['status']}, "
                          f"pattern={r['recurrence_pattern']!r}, last_extracted={r['last_extracted_at']}")
                print()

        # Decision tree
        if not pattern_changes and not mk_drift and not collisions:
            print("Nothing to do — already canonical.")
            return 0
        if collisions and not args.delete_stale_duplicates:
            print("Refusing to write because of collision(s). Re-run with "
                  "--delete-stale-duplicates to auto-resolve.")
            return 1
        if args.dry_run:
            print("[dry-run] no writes made. Re-run without --dry-run to apply.")
            return 0

        # Apply: collision deletions first, then pattern + match_key updates.
        deleted = 0
        for cluster in collisions:
            surv = _survivor(cluster)
            for r in cluster:
                if r["id"] == surv["id"]:
                    continue
                conn.execute("DELETE FROM events WHERE id = ?", (r["id"],))
                print(f"  deleted event {r['id']} ({r['title']!r}, status={r['status']})")
                deleted += 1

        updated = 0
        # Re-fetch surviving rows since cluster deletions changed the population
        rows = [dict(r) for r in conn.execute(
            """SELECT id, business_id, kind, title, recurrence_pattern,
                      start_time, match_key
               FROM events
               WHERE recurrence_pattern IS NOT NULL"""
        ).fetchall()]
        for r in rows:
            new_pat = normalize_recurrence_pattern(r["recurrence_pattern"])
            new_mk = build_match_key({
                "kind": r["kind"], "title": r["title"],
                "recurrence_pattern": new_pat, "start_time": r["start_time"],
            })
            if new_pat == r["recurrence_pattern"] and new_mk == r["match_key"]:
                continue  # already canonical
            conn.execute(
                "UPDATE events SET recurrence_pattern = ?, match_key = ? WHERE id = ?",
                (new_pat, new_mk, r["id"]),
            )
            updated += 1

        print(f"\nApplied {updated} update(s) and {deleted} deletion(s).")

        # Final uniqueness check
        dupes = conn.execute(
            """SELECT business_id, match_key, COUNT(*) AS n
               FROM events
               GROUP BY business_id, match_key
               HAVING n > 1"""
        ).fetchall()
        if dupes:
            print("\nWARNING: residual match_key collisions after normalization:")
            for d in dupes:
                print(f"  business_id={d['business_id']}, match_key={d['match_key']!r}, count={d['n']}")
            return 1

    print("\nUpsert-side normalization in src/db.py keeps this stable across "
          "future extraction runs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
