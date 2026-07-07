"""Pipeline: for each business -> for each page -> fetch, extract, store."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import yaml

from .db import (
    all_active_events, build_match_key, compute_input_signature, connect,
    event_has_valid_kind, init_db, last_good_signature,
    mark_missing_events_stale, now_iso, try_upsert_event, upsert_business,
)
from .extractor import extract_events
from .fetcher import fetch_html, fetch_html_playwright, playwright_session
from .images import discover_and_download, page_text

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PUBLIC_DIR = ROOT / "public"
CHICAGO = ZoneInfo("America/Chicago")

_DAY_ABBREV = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def _close_time(hours_str: str) -> str:
    """Extract the closing time from an 'HH:MM-HH:MM' hours range string."""
    return hours_str.split("-", 1)[1]


def _close_sort_key(t: str) -> int:
    """Minutes since midnight, with times <8am treated as next-day (e.g. 02:00 → 1560)."""
    h, m = map(int, t.split(":"))
    mins = h * 60 + m
    return mins + 1440 if h < 8 else mins


def _recurrence_days(pattern: str | None) -> list[str]:
    """Return 3-letter day abbreviations for each day a recurrence pattern fires."""
    if not pattern:
        return []
    if pattern == "daily":
        return list(_DAY_ABBREV.values())
    if pattern.startswith("weekly:"):
        return [_DAY_ABBREV.get(d, d[:3]) for d in pattern[len("weekly:"):].split(",")]
    if pattern.startswith("monthly:"):
        # "monthly:1st-wednesday" → last segment is the day name
        day = pattern[len("monthly:"):].split("-")[-1]
        return [_DAY_ABBREV[day]] if day in _DAY_ABBREV else []
    return []


def _apply_hours_cap(ev: dict, biz_hours: dict | None) -> str | None:
    """Infer or cap event end times using venue closing hours.

    Returns a short log string if a change was made, else None.
    Closing times like "02:00" are treated as next-day (2am).
    """
    if not biz_hours:
        return None

    kind = ev.get("kind", "recurring")

    if kind == "recurring":
        days = _recurrence_days(ev.get("recurrence_pattern"))
        if not days:
            return None
        closing_times = [_close_time(biz_hours[d]) for d in days if biz_hours.get(d)]
        if not closing_times:
            return None
        earliest = min(closing_times, key=_close_sort_key)
        current = ev.get("end_time")
        if not current:
            ev["end_time"] = earliest
            return f"inferred end_time={earliest}"
        if _close_sort_key(current) > _close_sort_key(earliest):
            ev["end_time"] = earliest
            return f"capped end_time {current}→{earliest}"

    elif kind == "dated":
        dt_str = ev.get("start_datetime")
        if not dt_str:
            return None
        try:
            dt = datetime.fromisoformat(dt_str)
        except ValueError:
            return None
        day_abbrev = dt.strftime("%a").lower()
        hours_str = biz_hours.get(day_abbrev)
        if not hours_str:
            return None
        close_str = _close_time(hours_str)
        if not close_str:
            return None
        close_h, close_m = map(int, close_str.split(":"))
        tz = dt.tzinfo
        end_date = dt.date() + (timedelta(days=1) if close_h < 8 else timedelta())

        current_end = ev.get("end_datetime")
        if not current_end:
            end_dt = datetime(end_date.year, end_date.month, end_date.day,
                              close_h, close_m, tzinfo=tz)
            ev["end_datetime"] = end_dt.isoformat()
            return f"inferred end_datetime=…{close_str}"
        try:
            end_dt_parsed = datetime.fromisoformat(current_end)
            end_time_str = end_dt_parsed.strftime("%H:%M")
            if _close_sort_key(end_time_str) > _close_sort_key(close_str):
                capped = datetime(end_date.year, end_date.month, end_date.day,
                                  close_h, close_m, tzinfo=tz)
                ev["end_datetime"] = capped.isoformat()
                return f"capped end_datetime …{end_time_str}→{close_str}"
        except ValueError:
            pass

    return None


def load_businesses(include_pending: bool = False) -> list[dict]:
    with open(CONFIG_DIR / "businesses.yaml") as f:
        businesses = yaml.safe_load(f)["businesses"]
    if include_pending:
        pending_path = CONFIG_DIR / "businesses_pending.yaml"
        if pending_path.exists():
            with open(pending_path) as f:
                pending = yaml.safe_load(f).get("businesses") or []
            businesses = businesses + pending
    return businesses


def load_tag_vocab() -> list[str]:
    with open(CONFIG_DIR / "tags.yaml") as f:
        data = yaml.safe_load(f)
    vocab: list[str] = []
    for cat in data["categories"].values():
        vocab.extend(cat["tags"])
    return vocab


def run() -> None:
    init_db()
    businesses = load_businesses()
    tag_vocab = load_tag_vocab()

    extraction_attempts = 0
    extraction_failures = 0

    with connect() as conn:
        for biz in businesses:
            print(f"\n=== {biz['name']} ===")
            business_id = upsert_business(conn, biz)

            # A business may intentionally have no `pages:` (manual-only venues
            # like Lonesome Rose that carry hand-entered specials but have
            # nothing scrapeable — a 0-event scrape would stale those specials).
            # Skip the scrape loop in that case; the business row is already
            # upserted above so its page still builds.
            for page in biz.get("pages") or []:
                print(f"  fetching: {page['url']}")
                try:
                    if page.get("use_playwright"):
                        with playwright_session(page["url"]) as (html, content_hash, status, ctx):
                            print(f"  discovering images…")
                            images = discover_and_download(
                                html, biz["slug"], PUBLIC_DIR,
                                base_url=page["url"],
                                download_fn=lambda u: ctx.request.get(u).body(),
                            )
                    else:
                        html, content_hash, status = fetch_html(page["url"])
                        print(f"  discovering images…")
                        images = discover_and_download(html, biz["slug"], PUBLIC_DIR,
                                                       base_url=page["url"])
                except Exception as exc:  # noqa: BLE001
                    print(f"  FETCH FAILED: {exc}")
                    conn.execute(
                        """INSERT INTO fetch_log (page_url, fetched_at, status_code, notes)
                           VALUES (?, ?, ?, ?)""",
                        (page["url"], now_iso(), 0, str(exc)),
                    )
                    continue

                print(f"  {len(images)} image(s) kept after filtering")

                # Change detection: if what Claude would see (page text + kept
                # image URLs) is byte-identical to the last successful run, skip
                # the paid multimodal call and leave the existing events as-is.
                # FORCE_EXTRACT=1 bypasses the skip (prompt/model tweaks, backfills).
                page_txt = page_text(html)
                signature = compute_input_signature(
                    page_txt, [img.source_url for img in images]
                )
                force = os.environ.get("FORCE_EXTRACT") == "1"
                if not force and last_good_signature(conn, page["url"]) == signature:
                    print("  ↳ unchanged since last run — skipping extraction")
                    conn.execute(
                        """INSERT INTO fetch_log (page_url, fetched_at, status_code,
                           content_hash, input_signature, events_found, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (page["url"], now_iso(), status, content_hash, signature,
                         None, "skipped: inputs unchanged"),
                    )
                    continue

                print(f"  calling Claude for extraction…")
                extraction_attempts += 1
                try:
                    events = extract_events(
                        business=biz,
                        page=page,
                        page_text=page_txt,
                        images=images,
                        tag_vocab=tag_vocab,
                    )
                except Exception as exc:  # noqa: BLE001
                    extraction_failures += 1
                    print(f"  EXTRACTION FAILED: {exc}")
                    conn.execute(
                        """INSERT INTO fetch_log (page_url, fetched_at, status_code,
                           content_hash, events_found, notes)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (page["url"], now_iso(), status, content_hash, 0, f"extract: {exc}"),
                    )
                    continue

                print(f"  extracted {len(events)} event(s)")
                now_dt = datetime.now(timezone.utc)
                for ev in events:
                    ev.setdefault("status", "active")
                    dt_str = ev.get("start_datetime")
                    if dt_str:
                        try:
                            ev_dt = datetime.fromisoformat(dt_str)
                            if ev_dt.tzinfo is None:
                                ev_dt = ev_dt.replace(tzinfo=CHICAGO)
                            if ev_dt < now_dt:
                                ev["status"] = "stale"
                        except ValueError:
                            pass
                default_tags = biz.get("default_tags") or []
                seen_keys: set[str] = set()
                for ev in events:
                    # Guard against malformed model output: an off-vocabulary or
                    # missing `kind` would crash upsert (DB CHECK constraint) and,
                    # before this guard, abort the whole run (2026-07-06 outage).
                    # We'd rather drop one bad event than lose the day's run.
                    if not event_has_valid_kind(ev):
                        print(f"    SKIP (invalid kind={ev.get('kind')!r}): "
                              f"{ev.get('title', '(no title)')}")
                        continue
                    # Normalize + ensure required fields exist
                    ev.setdefault("description", None)
                    ev.setdefault("recurrence_pattern", None)
                    ev.setdefault("start_time", None)
                    ev.setdefault("end_time", None)
                    ev.setdefault("start_datetime", None)
                    ev.setdefault("end_datetime", None)
                    ev.setdefault("price_info", None)
                    ev.setdefault("performers", [])
                    ev["source_page_url"] = page["url"]
                    ev["source_page_hash"] = content_hash
                    ev.setdefault("raw_extraction", ev.copy())
                    # Merge business-level default tags with Claude's tags (dedup, stable order)
                    if default_tags:
                        tags = list(dict.fromkeys(list(ev.get("tags") or []) + default_tags))
                        ev["tags"] = tags
                    hours_note = _apply_hours_cap(ev, biz.get("hours"))
                    # Guarded upsert: a per-event DB error (constraint violation
                    # from any malformed field, not just kind) is logged and
                    # skipped rather than aborting the run — defense in depth.
                    action = try_upsert_event(conn, business_id, ev)
                    if action is None:
                        continue
                    seen_keys.add(build_match_key(ev))
                    status_label = ev.get("status", "active")
                    if status_label == "stale":
                        mark = "stale"
                    elif action == "inserted":
                        mark = "NEW "
                    else:
                        mark = "upd "
                    suffix = f" [{hours_note}]" if hours_note else ""
                    print(f"    {mark} [{ev.get('confidence', '?'):>4}] "
                          f"{ev.get('title', '(no title)')}{suffix}")

                stale = mark_missing_events_stale(
                    conn, business_id, page["url"], seen_keys,
                )
                if stale:
                    print(f"  marked {stale} missing event(s) as stale")

                conn.execute(
                    """INSERT INTO fetch_log (page_url, fetched_at, status_code,
                       content_hash, input_signature, events_found, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (page["url"], now_iso(), status, content_hash, signature,
                     len(events), None),
                )

        total = conn.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0]
        print(f"\nTotal active events in database: {total}")

    # Fail loud if every extraction attempt errored — billing exhaustion, bad
    # API key, or systemic network issues. Raised after the `with connect()`
    # block so fetch_log audit rows still commit. Tripped only on 100% failure
    # to avoid red builds from a single transient hiccup.
    if extraction_attempts > 0 and extraction_failures == extraction_attempts:
        raise RuntimeError(
            f"All {extraction_attempts} extraction attempt(s) failed. "
            "Likely causes: Anthropic credit balance exhausted, invalid "
            "ANTHROPIC_API_KEY, or network issue reaching Anthropic. "
            "See per-page EXTRACTION FAILED messages above."
        )
