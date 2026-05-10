"""SQLite schema and helpers.

One table for businesses, one for events. The events table uses a 'kind'
discriminator ('recurring' vs 'dated') so both shapes live in one place —
simpler queries, easier tag faceting, at the cost of some nullable columns.
Revisit this split if recurring and dated events start diverging a lot.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

# Fields the admin UI can mark as "researched, don't overwrite during extraction."
# Listed in events.locked_fields (JSON array). upsert_event skips these on UPDATE.
# Single source of truth — scripts/admin.py imports this list.
LOCKABLE_FIELDS = [
    "title",
    "description",
    "recurrence_pattern",
    "start_time",
    "end_time",
    "start_datetime",
    "end_datetime",
    "price_info",
    "tags",
    "performers",
    "status",
]

# Canonical storage form for events.recurrence_pattern. Contiguous-day CSVs
# like `weekly:wednesday,thursday,friday,saturday,sunday` collapse to
# `weekly:wednesday-sunday`. Used by build_match_key and upsert_event so the
# stored shape is independent of what extraction emits (Claude may emit
# either form depending on the source page wording).
_DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def normalize_recurrence_pattern(pattern: str | None) -> str | None:
    """Return the canonical form of a recurrence pattern, or pass through.

    Collapses contiguous-day weekly CSVs to range form (handles wrap, e.g.
    saturday,sunday,monday → saturday-monday). Idempotent — already-canonical
    inputs pass through unchanged. Non-weekly patterns (daily, monthly:…),
    single-day, and non-consecutive CSVs all pass through.
    """
    if not pattern or not pattern.startswith("weekly:"):
        return pattern
    days_part = pattern[7:]
    if "," not in days_part:
        return pattern  # single day or already-range form
    days = [d.strip() for d in days_part.split(",") if d.strip()]
    if len(days) < 2:
        return pattern
    try:
        index_set = {_DAY_ORDER.index(d) for d in days}
    except ValueError:
        return pattern  # unrecognized day name
    if len(index_set) != len(days):
        return pattern  # duplicates
    n = len(index_set)
    for start in range(7):
        run = {(start + i) % 7 for i in range(n)}
        if run == index_set:
            end = (start + n - 1) % 7
            return f"weekly:{_DAY_ORDER[start]}-{_DAY_ORDER[end]}"
    return pattern  # non-consecutive


SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id           INTEGER PRIMARY KEY,
    slug         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    category     TEXT,
    subcategory  TEXT,
    website      TEXT,
    address      TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id                 INTEGER PRIMARY KEY,
    business_id        INTEGER NOT NULL,
    kind               TEXT    NOT NULL CHECK (kind IN ('recurring', 'dated')),
    title              TEXT    NOT NULL,
    description        TEXT,

    -- Recurring-only
    recurrence_pattern TEXT,    -- e.g., 'weekly:tuesday', 'monthly:2nd-thursday'
    start_time         TEXT,    -- 'HH:MM' 24-hour
    end_time           TEXT,

    -- Dated-only
    start_datetime     TEXT,    -- ISO8601
    end_datetime       TEXT,

    -- Common
    price_info         TEXT,
    price_short        TEXT,
    tags               TEXT,    -- JSON array of tag strings
    performers         TEXT,    -- JSON array of {"name": str, "role": str} objects
    image_source_url   TEXT,    -- original CDN URL
    image_local_path   TEXT,    -- path relative to public/, e.g. 'images/mht/abc.png'
    external_link      TEXT,    -- e.g., Facebook event link if the image was wrapped in <a>

    source_page_url    TEXT    NOT NULL,
    source_page_hash   TEXT,   -- hash of the page content used for change detection

    confidence         REAL,   -- 0..1, Claude's self-reported confidence
    raw_extraction     TEXT,   -- full JSON from Claude for debugging

    status             TEXT    NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'expired', 'stale', 'rejected')),
    featured           INTEGER NOT NULL DEFAULT 0,
    ends_on            TEXT,    -- ISO date; last occurrence of a recurring series.
                                -- Manually set (e.g., TV viewing party when season
                                -- ends). Recurring events where ends_on < build_date
                                -- are hidden from all display buckets. Pipeline
                                -- extraction never writes this column.

    first_seen_at      TEXT    NOT NULL,
    last_seen_at       TEXT    NOT NULL,
    last_extracted_at  TEXT    NOT NULL,

    -- Identity key for dedup (see upsert_event)
    match_key          TEXT    NOT NULL,

    FOREIGN KEY (business_id) REFERENCES businesses(id),
    UNIQUE (business_id, match_key)
);

CREATE INDEX IF NOT EXISTS idx_events_business ON events (business_id);
CREATE INDEX IF NOT EXISTS idx_events_status   ON events (status);
CREATE INDEX IF NOT EXISTS idx_events_kind     ON events (kind);

CREATE TABLE IF NOT EXISTS fetch_log (
    id              INTEGER PRIMARY KEY,
    page_url        TEXT    NOT NULL,
    fetched_at      TEXT    NOT NULL,
    status_code     INTEGER,
    content_hash    TEXT,
    events_found    INTEGER,
    notes           TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # Idempotent migrations for schema additions
        try:
            conn.execute("ALTER TABLE events ADD COLUMN price_short TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE events ADD COLUMN locked_fields TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists


def upsert_business(conn: sqlite3.Connection, b: dict) -> int:
    """Insert or update a business by slug. Returns its id."""
    now = now_iso()
    conn.execute(
        """
        INSERT INTO businesses (slug, name, category, subcategory, website, address,
                                created_at, updated_at)
        VALUES (:slug, :name, :category, :subcategory, :website, :address, :now, :now)
        ON CONFLICT(slug) DO UPDATE SET
            name        = excluded.name,
            category    = excluded.category,
            subcategory = excluded.subcategory,
            website     = excluded.website,
            address     = excluded.address,
            updated_at  = excluded.updated_at
        """,
        {**b, "now": now},
    )
    row = conn.execute("SELECT id FROM businesses WHERE slug = ?", (b["slug"],)).fetchone()
    return row["id"]


def build_match_key(event: dict) -> str:
    """Stable identity for an event so re-extraction updates instead of duplicating.

    For recurring: kind + title + normalize_recurrence_pattern(recurrence_pattern) + start_time
    For dated:     kind + title + start_datetime (date part)

    The recurrence_pattern is normalized so that semantically-identical patterns
    (e.g. `weekly:wed,thu,fri,sat,sun` and `weekly:wed-sun`) produce the same
    match_key — otherwise re-extraction would create duplicate events whenever
    Claude switches between the two surface forms.
    """
    parts = [event["kind"], (event.get("title") or "").strip().lower()]
    if event["kind"] == "recurring":
        normalized = normalize_recurrence_pattern(event.get("recurrence_pattern")) or ""
        parts += [normalized, event.get("start_time") or ""]
    else:
        sd = event.get("start_datetime") or ""
        parts += [sd[:10]]  # date portion only, so time tweaks don't break matching
    return "|".join(parts)


def upsert_event(conn: sqlite3.Connection, business_id: int, event: dict) -> str:
    """Insert or update an event by (business_id, match_key).

    Returns 'inserted' or 'updated'.

    Fields named in the row's `locked_fields` are skipped on UPDATE so manual
    research (via the admin UI) survives subsequent extraction runs. The
    image_*, source_*, confidence, raw_extraction, and last_*_at fields are
    always updated regardless — they're system-managed metadata, not
    user-facing values worth locking.

    Also normalizes the recurrence_pattern to canonical (range form when
    contiguous) on the way in, so storage shape is consistent regardless of
    what extraction emits.
    """
    now = now_iso()
    # Shallow-copy so we don't mutate the caller's dict.
    if event.get("recurrence_pattern"):
        event = {**event, "recurrence_pattern": normalize_recurrence_pattern(event["recurrence_pattern"])}
    match_key = build_match_key(event)

    existing = conn.execute(
        "SELECT id, locked_fields FROM events WHERE business_id = ? AND match_key = ?",
        (business_id, match_key),
    ).fetchone()

    tags_json = json.dumps(event.get("tags") or [])
    performers_json = json.dumps(event.get("performers") or [])
    raw_json = json.dumps(event.get("raw_extraction") or event, default=str)

    if existing:
        locked = set(json.loads(existing["locked_fields"] or "[]"))
        # User-lockable columns first, skipping the ones the user has marked.
        update_pairs = [f"{f} = :{f}" for f in LOCKABLE_FIELDS if f not in locked]
        # System-managed columns always update.
        update_pairs += [
            "image_source_url  = :image_source_url",
            "image_local_path  = :image_local_path",
            "external_link     = :external_link",
            "source_page_url   = :source_page_url",
            "source_page_hash  = :source_page_hash",
            "confidence        = :confidence",
            "raw_extraction    = :raw_extraction",
            "last_seen_at      = :now",
            "last_extracted_at = :now",
        ]
        sql = f"UPDATE events SET {', '.join(update_pairs)} WHERE id = :id"
        conn.execute(
            sql,
            {
                **event,
                "tags": tags_json,
                "performers": performers_json,
                "raw_extraction": raw_json,
                "now": now,
                "id": existing["id"],
            },
        )
        return "updated"

    conn.execute(
        """
        INSERT INTO events (
            business_id, kind, title, description,
            recurrence_pattern, start_time, end_time,
            start_datetime, end_datetime,
            price_info, tags, performers, image_source_url, image_local_path, external_link,
            source_page_url, source_page_hash,
            confidence, raw_extraction, status,
            first_seen_at, last_seen_at, last_extracted_at, match_key
        ) VALUES (
            :business_id, :kind, :title, :description,
            :recurrence_pattern, :start_time, :end_time,
            :start_datetime, :end_datetime,
            :price_info, :tags, :performers, :image_source_url, :image_local_path, :external_link,
            :source_page_url, :source_page_hash,
            :confidence, :raw_extraction, :status,
            :now, :now, :now, :match_key
        )
        """,
        {
            "business_id": business_id,
            **event,
            "tags": tags_json,
            "performers": performers_json,
            "raw_extraction": raw_json,
            "now": now,
            "match_key": match_key,
        },
    )
    return "inserted"


def mark_missing_events_stale(conn: sqlite3.Connection, business_id: int,
                              source_page_url: str, seen_match_keys: set[str]) -> int:
    """Events on this page that we didn't see this run get marked 'stale'.

    Skips events whose `status` is in their locked_fields — the admin has
    asserted the value (e.g. "I know this is canceled, don't auto-stale it").

    After a few consecutive stale runs, you might want to flip them to 'expired'.
    Left simple for v1.
    """
    rows = conn.execute(
        """SELECT id, match_key, locked_fields FROM events
           WHERE business_id = ? AND source_page_url = ? AND status = 'active'""",
        (business_id, source_page_url),
    ).fetchall()
    stale_count = 0
    for row in rows:
        if row["match_key"] in seen_match_keys:
            continue
        locked = set(json.loads(row["locked_fields"] or "[]"))
        if "status" in locked:
            continue
        conn.execute("UPDATE events SET status = 'stale' WHERE id = ?", (row["id"],))
        stale_count += 1
    return stale_count


def all_events_with_business(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All active + stale events with business info, for generating per-event static pages."""
    return conn.execute(
        """SELECT e.*, b.name AS business_name, b.slug AS business_slug,
                  b.category AS business_category, b.address AS business_address,
                  b.website AS business_website
           FROM events e
           JOIN businesses b ON e.business_id = b.id
           WHERE e.status IN ('active', 'stale')
           ORDER BY e.id"""
    ).fetchall()


def all_active_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.*, b.name AS business_name, b.slug AS business_slug,
                  b.category AS business_category, b.address AS business_address
           FROM events e
           JOIN businesses b ON e.business_id = b.id
           WHERE e.status = 'active'
           ORDER BY
             CASE e.kind WHEN 'dated' THEN 0 ELSE 1 END,
             e.start_datetime,
             b.name,
             e.title"""
    ).fetchall()
