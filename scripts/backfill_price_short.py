#!/usr/bin/env python3
"""Backfill the events.price_short column for happy-hour events.

Reads active recurring events tagged 'happy-hour' from data/app.db. For each
event with a populated price_info but no price_short, asks Claude Haiku to
compress the description into <=14 characters (creative compression
permitted — e.g. a long list of specials becomes "5 specials"). Writes the
result back to events.price_short.

Idempotent: skips rows that already have price_short set unless --force.
Fast-path: if price_info is already <=14 chars, copies it directly without
calling the API.

Usage:
    python3 scripts/backfill_price_short.py              # all eligible rows
    python3 scripts/backfill_price_short.py 165          # one event by id
    python3 scripts/backfill_price_short.py --force      # refresh all
    python3 scripts/backfill_price_short.py --dry-run    # preview only
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DB_PATH = ROOT / "data" / "app.db"
MODEL = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")
MAX_LEN = 14

PROMPT = f"""You are compressing a happy-hour price description so it fits a tight {MAX_LEN}-character display column on a small card.

Rules:
- Output ONE short string, no longer than {MAX_LEN} characters.
- Be creative when the source is a long list of specials. The goal is a short, evocative label, not a faithful summary. Examples:
    "$1 off slices, $2 off apps, $3 off pizzas, $2 off beer, $3 off cocktails/wine" -> "6 specials"
    "$8 wine, $9 oldies, $10 martinis" -> "$8 wine+" or "3 deals"
    "$2 oysters, $2 shrimp, $5 Cava glasses" -> "$2 oyster+"
    "1/2 off all draft beers" -> "1/2 off beer"
    "$3 house shots" -> "$3 shots"
    "$4 Signature Margaritas" -> "$4 margs"
    "$6-$24 (varies by item)" -> "$6+"
    "$15 bottles, $10 brunch cocktails" -> "$15 bottles"
- Use abbreviations: "wines"->"wine", "draft beers"->"draft", "old fashioneds"->"old fash", "signature"->"sig", "margaritas"->"margs", "cocktails"->"cktls".
- Prefer "$N+" or "N specials" or "N deals" over a hyper-specific summary that won't fit.
- No quotes, no trailing period, no explanation. Return ONLY the short string.

INPUT: {{price_info}}

Return the {MAX_LEN}-character-or-less short form now.
""".strip()


def compress_with_haiku(client: Anthropic, price_info: str) -> str:
    user_prompt = PROMPT.replace("{price_info}", price_info)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=64,
        temperature=0.0,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.strip('"').strip("'").rstrip(".").strip()
    return text[:MAX_LEN]


def fetch_eligible(conn: sqlite3.Connection, target_id: int | None) -> list[sqlite3.Row]:
    where = ["e.status = 'active'", "e.kind = 'recurring'", "e.tags LIKE '%happy-hour%'"]
    params: list = []
    if target_id is not None:
        where.append("e.id = ?")
        params.append(target_id)
    sql = f"""
        SELECT e.id, e.title, e.price_info, e.price_short, b.name AS business_name
        FROM events e
        JOIN businesses b ON b.id = e.business_id
        WHERE {' AND '.join(where)}
        ORDER BY e.id
    """
    return list(conn.execute(sql, params))


def main(argv: list[str]) -> int:
    force = "--force" in argv
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a not in ("--force", "--dry-run")]
    target_id = int(argv[0]) if argv else None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = fetch_eligible(conn, target_id)
    print(f"found {len(rows)} happy-hour rows")

    client = Anthropic()
    updates: list[tuple[int, str, str | None]] = []  # (id, new_price_short, source_desc)

    for row in rows:
        eid = row["id"]
        biz = row["business_name"]
        title = row["title"]
        price_info = (row["price_info"] or "").strip()
        existing = (row["price_short"] or "").strip()

        if existing and not force:
            print(f"  skip #{eid} {biz} — already has price_short={existing!r}")
            continue
        if not price_info:
            print(f"  skip #{eid} {biz} — empty price_info (sentinel handled at render)")
            continue

        if len(price_info) <= MAX_LEN:
            new_val = price_info
            source = "passthrough"
        else:
            new_val = compress_with_haiku(client, price_info)
            source = "haiku"

        print(f"  #{eid} {biz} ({title}): {price_info!r} -> {new_val!r}  [{source}, {len(new_val)} chars]")
        updates.append((eid, new_val, source))

    if dry_run:
        print(f"\ndry-run: {len(updates)} update(s) NOT written")
        return 0

    if not updates:
        print("\nnothing to update")
        return 0

    with conn:
        for eid, val, _ in updates:
            conn.execute("UPDATE events SET price_short = ? WHERE id = ?", (val, eid))
    print(f"\nwrote {len(updates)} update(s) to {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
