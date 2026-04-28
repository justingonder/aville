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

import argparse
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


PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".webp")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest phone-camera flyer photos into the events DB via web search.",
    )
    parser.add_argument("photo", nargs="?",
                        help="path to a single photo (mutually exclusive with --dir)")
    parser.add_argument("--dir", dest="directory",
                        help="directory of photos to process as a batch")
    parser.add_argument("--source-url",
                        help="manual authoritative URL (single-photo mode only); "
                             "bypasses Step 4 web search")
    parser.add_argument("--dry-run", action="store_true",
                        help="run the full pipeline but skip all writes (DB, YAML, sidecar log)")
    parser.add_argument("--seed-only", action="store_true",
                        help="run only Step 1 seed extraction; cheap preview")
    parser.add_argument("--force", action="store_true",
                        help="re-process photos already in the sidecar log")
    args = parser.parse_args(argv)

    # Mutual-exclusion / requirement validation.
    if not args.photo and not args.directory:
        parser.error("must provide either a photo path or --dir")
    if args.photo and args.directory:
        parser.error("--dir is mutually exclusive with a positional photo argument")
    if args.source_url and args.directory:
        parser.error("--source-url requires single-photo mode")
    if args.seed_only and args.dry_run:
        parser.error("--seed-only and --dry-run are mutually exclusive")
    return args


def collect_photos(args: argparse.Namespace) -> tuple[Path, list[Path]]:
    """Return (sidecar_dir, [photo_path, ...]) — one photo for single mode,
    a sorted list of photos for --dir mode."""
    if args.photo:
        photo = Path(args.photo).resolve()
        if not photo.exists():
            raise SystemExit(f"photo not found: {photo}")
        return photo.parent, [photo]
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        raise SystemExit(f"--dir not a directory: {directory}")
    photos = sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in PHOTO_EXTENSIONS
    )
    if not photos:
        raise SystemExit(f"no photos found in {directory}")
    return directory, photos


def media_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".heic":
        return "image/heic"
    return "application/octet-stream"


def _normalize_seed_dates(seed: dict) -> dict:
    """Best-effort: convert a `date_hint` like 'May 2' into ISO 'YYYY-MM-DD'.

    Used by find_dedup_match for dated events. Recurring events use
    recurrence_pattern + start_time directly.
    """
    out = dict(seed)
    hint = (seed.get("date_hint") or "").strip()
    if not hint:
        return out

    # Try a handful of common formats. We don't sweat exotic cases —
    # find_dedup_match treats unparseable dates as "skip the dated dedup".
    today = date.today()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%m/%d"):
        try:
            d = datetime.strptime(hint, fmt).date()
            if fmt == "%m/%d":
                # Year-less: pick nearest future occurrence.
                d = d.replace(year=today.year)
                if d < today:
                    d = d.replace(year=today.year + 1)
            out["date_hint_iso"] = d.isoformat()
            return out
        except ValueError:
            continue

    for fmt in ("%B %d", "%b %d"):
        try:
            d = datetime.strptime(hint, fmt).date().replace(year=today.year)
            if d < today:
                d = d.replace(year=today.year + 1)
            out["date_hint_iso"] = d.isoformat()
            return out
        except ValueError:
            continue
    return out


def _prompt_choice(prompt: str, valid: str) -> str:
    """Read a single character from stdin (case-insensitive) and validate."""
    while True:
        raw = input(prompt).strip().lower()
        if raw and raw[0] in valid:
            return raw[0]
        print(f"  please pick one of: {', '.join(valid)}")


def _prompt_ambiguous_business(seed: dict, candidates: list[tuple[str, float]]) -> str | None:
    """Ask the user which candidate to pick; return slug, '__new__', or None
    (skip / quit signals up the stack via SystemExit / 'quit_batch')."""
    print(f"\n  Flyer says: {seed.get('venue_name')!r}")
    print(f"  Closest matches in businesses.yaml:")
    for i, (slug, score) in enumerate(candidates, 1):
        print(f"    [{i}] {slug:<26}  (score {score:.2f})")
    print(f"    [n] none of these — treat as new business")
    print(f"    [s] skip this photo")
    print(f"    [q] quit batch")
    valid = "".join(str(i) for i in range(1, len(candidates) + 1)) + "nsq"
    pick = _prompt_choice("  Pick: ", valid)
    if pick.isdigit():
        return candidates[int(pick) - 1][0]
    if pick == "n":
        return "__new__"
    if pick == "s":
        return None
    if pick == "q":
        raise KeyboardInterrupt("user quit at ambiguous business")
    return None


def _prompt_dedup_match(seed: dict, existing: dict) -> str:
    """Show field-by-field comparison and ask [s/e/p/q]. Returns the chosen letter."""
    print(f"\n  Existing event #{existing['id']}: {existing['title']!r}"
          f" ({existing['kind']}"
          f"{' ' + (existing['recurrence_pattern'] or '') if existing['kind']=='recurring' else ''})")
    print(f"  Field-by-field comparison:")
    for field in ("title", "start_time", "end_time", "price_info", "performers"):
        seed_val = seed.get(field) if field in seed else "(no seed)"
        existing_val = existing.get(field)
        marker = ""
        if seed_val == existing_val and seed_val:
            marker = "  ✓"
        elif _is_empty(existing_val) and not _is_empty(seed_val):
            marker = "  (seed fills)"
        elif _is_empty(seed_val) and not _is_empty(existing_val):
            marker = "  (existing fills)"
        print(f"    {field+':':<14} seed={seed_val!r:<24} existing={existing_val!r:<24}{marker}")
    print(f"\n  Action: [s]kip / [e]nrich / [p]roceed-as-new / [q]uit")
    return _prompt_choice("  Pick: ", "sepq")


def process_photo(
    photo_path: Path,
    *,
    args: argparse.Namespace,
    businesses: list[dict],
    tag_vocab: list[str],
    db_conn,
    sidecar: SidecarLog | None,
    allowlist: list[str],
) -> dict:
    """Run the 7-step pipeline on one photo. Returns the sidecar entry dict.

    Side effects honor args.dry_run (no DB / YAML / sidecar writes when True)
    and args.seed_only (Steps 1 only).
    """
    from src.extractor import extract_flyer_seeds, extract_events
    from src.web_search import search_for_event, domain_of

    print(f"\n[{photo_path.name}]")
    entry: dict = {
        "photo": photo_path.name,
        "started_at": _now_iso_local(),
    }

    # ── Step 1: seed extraction ─────────────────────────────────────────
    print(f"  [1/7] seed extraction…")
    image_bytes = photo_path.read_bytes()
    seed = extract_flyer_seeds(image_bytes, media_type=media_type_for(photo_path))
    entry["seed"] = seed
    print(f"        title={seed.get('event_title')!r}, venue={seed.get('venue_name')!r},"
          f" date={seed.get('date_hint')!r}, conf={seed.get('seed_confidence')!r}")

    if args.seed_only:
        entry["outcome"] = "seed-only-preview"
        entry["finished_at"] = _now_iso_local()
        return entry

    # ── Step 2: resolve business ────────────────────────────────────────
    print(f"  [2/7] resolve business…")
    resolution = resolve_business(seed.get("venue_name") or "", businesses)
    biz_slug: str | None
    biz_meta: dict | None
    if isinstance(resolution, tuple):
        biz_slug, score = resolution
        print(f"        confident match: {biz_slug} (score {score:.2f})")
    elif isinstance(resolution, list):
        pick = _prompt_ambiguous_business(seed, resolution)
        if pick is None:
            entry["outcome"] = "skipped:user-quit"
            entry["finished_at"] = _now_iso_local()
            return entry
        biz_slug = None if pick == "__new__" else pick
    else:
        print(f"        no match — will treat as new business after web search")
        biz_slug = None

    biz_meta = next((b for b in businesses if b["slug"] == biz_slug), None) if biz_slug else None

    # ── Step 3: DB dedup gate (only if business is known) ───────────────
    if biz_slug:
        print(f"  [3/7] DB dedup check…")
        # Fetch business_id; lazy lookup since the YAML doesn't carry DB ids.
        biz_row = db_conn.execute(
            "SELECT id FROM businesses WHERE slug = ?", (biz_slug,)
        ).fetchone()
        if biz_row is not None:
            seed_for_dedup = _normalize_seed_dates(seed)
            existing = find_dedup_match(db_conn, business_id=biz_row["id"], seed=seed_for_dedup)
            if existing is not None:
                print(f"        match: event #{existing['id']} ({existing['title']!r})")
                action = _prompt_dedup_match(seed, dict(existing))
                if action == "s":
                    entry["outcome"] = "skipped:dedup-match"
                    entry["matched_event_id"] = existing["id"]
                    entry["finished_at"] = _now_iso_local()
                    return entry
                if action == "q":
                    raise KeyboardInterrupt("user quit at dedup match")
                if action == "e":
                    # Fall through to Steps 4-7, then enrich at upsert.
                    entry["enrich_target_event_id"] = existing["id"]
                if action == "p":
                    # Fall through to Steps 4-7 as a new event. Tagged so the
                    # outcome label distinguishes it from a no-dedup ingest.
                    entry["proceeded_as_new"] = True
        else:
            print(f"        business {biz_slug!r} not yet in DB — proceeding without dedup")

    # ── Step 4: web search ──────────────────────────────────────────────
    if args.source_url:
        print(f"  [4/7] manual --source-url override: {args.source_url}")
        from src.web_search import SearchResult
        search_result = SearchResult(
            url=args.source_url,
            title="(manual override)",
            domain=domain_of(args.source_url),
            tier=1,
        )
    else:
        print(f"  [4/7] web search…")
        venue_domain = None
        if biz_meta:
            website = biz_meta.get("website") or ""
            venue_domain = domain_of(website) if website else None
        search_result = search_for_event(seed, allowlist=allowlist, venue_domain=venue_domain)

        if search_result is None:
            print(f"        no result clears the allowlist — skipping")
            entry["outcome"] = "skipped:no-web-trace"
            entry["queries_tried"] = "(see seed.distinctive_strings)"
            entry["finished_at"] = _now_iso_local()
            return entry
        print(f"        found tier-{search_result.tier}: {search_result.url}")
    entry["source_url"] = search_result.url

    # ── Step 6: auto-add new business if needed ─────────────────────────
    # (Step 6 runs before Step 5 so we have a business_id to upsert against.)
    if biz_slug is None:
        print(f"  [6/7] auto-adding new business…")
        try:
            biz_slug = add_business_from_search(
                seed=seed,
                search_url=search_result.url,
                search_address=None,  # best-effort address extraction is a future enhancement
                dry_run=args.dry_run,
            )
            entry["business_added"] = True
            entry["business_slug"] = biz_slug
        except RuntimeError as exc:
            print(f"        ERROR: {exc}")
            entry["outcome"] = f"failed:business-add-failed"
            entry["error"] = str(exc)
            entry["finished_at"] = _now_iso_local()
            return entry
        # Re-load businesses for downstream use.
        from src.pipeline import load_businesses
        businesses = load_businesses(include_pending=True)
        biz_meta = next((b for b in businesses if b["slug"] == biz_slug), None)

    entry["business_slug"] = biz_slug

    # ── Step 5: full extraction from authoritative URL ──────────────────
    # Dry-run short-circuits before _run_full_extraction because that helper
    # calls discover_and_download(), which writes images to public/images/<slug>/
    # — a real filesystem side effect that would violate the dry-run promise.
    # We accept that dry-run loses the validation of Step 5 + 7, in exchange
    # for not polluting the working tree.
    if args.dry_run:
        print(f"  [5/7] [DRY-RUN] would extract events from {search_result.url}")
        print(f"  [7/7] [DRY-RUN] would {'enrich' if entry.get('enrich_target_event_id') else 'insert'}")
        if entry.get("enrich_target_event_id"):
            entry["outcome"] = "enriched"
        elif entry.get("proceeded_as_new"):
            entry["outcome"] = "proceeded-as-new"
        else:
            entry["outcome"] = "ingested"
        entry["dry_run"] = True
        entry["finished_at"] = _now_iso_local()
        return entry

    print(f"  [5/7] full extraction from {search_result.url}…")
    try:
        events = _run_full_extraction(
            biz_meta=biz_meta,
            source_url=search_result.url,
            cross_verify_image=image_bytes,
            cross_verify_media_type=media_type_for(photo_path),
            tag_vocab=tag_vocab,
        )
    except Exception as exc:  # network / fetcher / Claude — surface and skip
        print(f"        ERROR: {exc}")
        entry["outcome"] = f"failed:extract-error"
        entry["error"] = str(exc)
        entry["finished_at"] = _now_iso_local()
        return entry

    if not events:
        print(f"        extraction returned 0 events; skipping")
        entry["outcome"] = "failed:no-events-extracted"
        entry["error"] = "extract_events returned []"
        entry["finished_at"] = _now_iso_local()
        return entry

    # Pick the event whose title is most similar to the seed title.
    chosen = max(events, key=lambda e: _name_similarity(e.get("title") or "",
                                                          seed.get("event_title") or ""))
    chosen.setdefault("source_page_url", search_result.url)
    chosen.setdefault("status", "active")

    # ── Step 7: upsert (or enrich) ──────────────────────────────────────
    print(f"  [7/7] {'enrich' if entry.get('enrich_target_event_id') else 'insert'}…")

    # Bridge YAML -> DB: the daily pipeline upserts every YAML business at the
    # start of each run, but this CLI is single-photo and doesn't run that
    # phase, so we upsert the business now to guarantee it has a DB id.
    from src.db import upsert_business, upsert_event, build_match_key
    if biz_meta is None:
        # Should never happen — we set biz_meta either at confident-match in Step 2
        # or after auto-add reload in Step 6. Defensive guard.
        entry["outcome"] = "failed:business-meta-missing"
        entry["error"] = f"slug {biz_slug!r} resolved but biz_meta is None"
        entry["finished_at"] = _now_iso_local()
        return entry
    business_id = upsert_business(db_conn, {
        "slug":        biz_meta["slug"],
        "name":        biz_meta["name"],
        "category":    biz_meta.get("category"),
        "subcategory": biz_meta.get("subcategory"),
        "website":     biz_meta.get("website"),
        "address":     biz_meta.get("address"),
    })
    biz_row = {"id": business_id}

    enrich_id = entry.get("enrich_target_event_id")
    if enrich_id is not None:
        existing_row = dict(db_conn.execute(
            "SELECT * FROM events WHERE id = ?", (enrich_id,)
        ).fetchone())
        diff = compute_enrichment(existing_row, chosen)
        if diff:
            cols = ", ".join(f"{k} = :{k}" for k in diff)
            db_conn.execute(
                f"UPDATE events SET {cols}, last_seen_at = :now, last_extracted_at = :now"
                f" WHERE id = :id",
                {**diff, "now": _now_iso_local(), "id": enrich_id,
                 # JSON-serialize performers if it's a list
                 **({"performers": json.dumps(diff["performers"])} if "performers" in diff else {})},
            )
            print(f"        enriched event #{enrich_id} with {list(diff)}")
            entry["outcome"] = "enriched"
            entry["event_id"] = enrich_id
        else:
            print(f"        no enrichable gaps — skipping update")
            entry["outcome"] = "skipped:dedup-match"
            entry["matched_event_id"] = enrich_id
    else:
        result = upsert_event(db_conn, biz_row["id"], chosen)
        new_id_row = db_conn.execute(
            "SELECT id FROM events WHERE business_id = ? AND match_key = ?",
            (biz_row["id"], build_match_key(chosen)),
        ).fetchone()
        entry["event_id"] = new_id_row["id"] if new_id_row else None
        entry["outcome"] = "proceeded-as-new" if entry.get("proceeded_as_new") else "ingested"
        print(f"        {result} event #{entry.get('event_id')}")

    entry["finished_at"] = _now_iso_local()
    return entry


def _run_full_extraction(
    *,
    biz_meta: dict | None,
    source_url: str,
    cross_verify_image: bytes,
    cross_verify_media_type: str,
    tag_vocab: list[str],
):
    """Fetch + extract for an arbitrary URL. Tolerates a missing biz_meta
    (sets a minimal page record). Returns the events list."""
    from src.extractor import extract_events
    from src.fetcher import fetch_html, fetch_html_playwright
    from src.images import discover_and_download, page_text
    from src.pipeline import PUBLIC_DIR

    page_kind = "home"
    needs_playwright = False
    if biz_meta:
        page = next((p for p in (biz_meta.get("pages") or []) if p["url"] == source_url),
                    {"url": source_url, "kind": page_kind, "hints": ""})
        page_kind = page.get("kind") or "home"
        needs_playwright = bool(page.get("use_playwright"))
    else:
        page = {"url": source_url, "kind": page_kind, "hints": ""}

    if needs_playwright:
        html, _, _ = fetch_html_playwright(source_url)
    else:
        html, _, _ = fetch_html(source_url)

    business = biz_meta or {"slug": "(unknown)", "name": "(unknown)", "category": "", "subcategory": ""}
    images = discover_and_download(html, business["slug"], PUBLIC_DIR, base_url=source_url)
    return extract_events(
        business=business,
        page=page,
        page_text=page_text(html),
        images=images,
        tag_vocab=tag_vocab,
        cross_verify_image=cross_verify_image,
        cross_verify_media_type=cross_verify_media_type,
    )


def main(argv: list[str]) -> int:
    from dotenv import load_dotenv
    load_dotenv()

    args = parse_args(argv)
    sidecar_dir, photos = collect_photos(args)
    sidecar_path = sidecar_dir / ".ingest_log.json"
    sidecar = None if (args.seed_only or args.dry_run) else SidecarLog(sidecar_path)

    from src.db import connect
    from src.pipeline import load_businesses, load_tag_vocab
    from src.web_search import load_allowlist

    businesses = load_businesses(include_pending=True)
    tag_vocab = load_tag_vocab()
    allowlist = load_allowlist()

    skipped_already_processed = (
        set() if args.force or sidecar is None else sidecar.processed_photos()
    )

    entries: list[dict] = list(sidecar.entries()) if sidecar else []

    try:
        with connect() as db_conn:
            for photo_path in photos:
                if photo_path.name in skipped_already_processed:
                    print(f"\n[{photo_path.name}] already in sidecar log — skipping (use --force to redo)")
                    continue
                try:
                    entry = process_photo(
                        photo_path,
                        args=args,
                        businesses=businesses,
                        tag_vocab=tag_vocab,
                        db_conn=db_conn,
                        sidecar=sidecar,
                        allowlist=allowlist,
                    )
                except KeyboardInterrupt:
                    print("\n  user quit batch")
                    break
                except Exception as exc:
                    print(f"  ERROR processing {photo_path.name}: {exc}")
                    entry = {
                        "photo": photo_path.name,
                        "outcome": "failed:exception",
                        "error": repr(exc),
                        "finished_at": _now_iso_local(),
                    }
                if sidecar is not None:
                    sidecar.append(entry)
                entries.append(entry)
    finally:
        print_walk_summary(entries, dir_label=str(sidecar_dir))
        if sidecar is not None:
            print(f"Sidecar log: {sidecar.path}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
