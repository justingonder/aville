"""Pipeline: for each business -> for each page -> fetch, extract, store."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from .db import (
    all_active_events, build_match_key, connect, init_db,
    mark_missing_events_stale, now_iso, upsert_business, upsert_event,
)
from .extractor import extract_events
from .fetcher import fetch_html, fetch_html_playwright, playwright_session
from .images import discover_and_download, page_text

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PUBLIC_DIR = ROOT / "public"


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

    with connect() as conn:
        for biz in businesses:
            print(f"\n=== {biz['name']} ===")
            business_id = upsert_business(conn, biz)

            for page in biz["pages"]:
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

                print(f"  calling Claude for extraction…")
                try:
                    events = extract_events(
                        business=biz,
                        page=page,
                        page_text=page_text(html),
                        images=images,
                        tag_vocab=tag_vocab,
                    )
                except Exception as exc:  # noqa: BLE001
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
                                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                            if ev_dt < now_dt:
                                ev["status"] = "stale"
                        except ValueError:
                            pass
                default_tags = biz.get("default_tags") or []
                seen_keys: set[str] = set()
                for ev in events:
                    # Normalize + ensure required fields exist
                    ev.setdefault("description", None)
                    ev.setdefault("recurrence_pattern", None)
                    ev.setdefault("start_time", None)
                    ev.setdefault("end_time", None)
                    ev.setdefault("start_datetime", None)
                    ev.setdefault("end_datetime", None)
                    ev.setdefault("price_info", None)
                    ev["source_page_url"] = page["url"]
                    ev["source_page_hash"] = content_hash
                    ev.setdefault("raw_extraction", ev.copy())
                    # Merge business-level default tags with Claude's tags (dedup, stable order)
                    if default_tags:
                        tags = list(dict.fromkeys(list(ev.get("tags") or []) + default_tags))
                        ev["tags"] = tags
                    action = upsert_event(conn, business_id, ev)
                    seen_keys.add(build_match_key(ev))
                    status_label = ev.get("status", "active")
                    if status_label == "stale":
                        mark = "stale"
                    elif action == "inserted":
                        mark = "NEW "
                    else:
                        mark = "upd "
                    print(f"    {mark} [{ev.get('confidence', '?'):>4}] "
                          f"{ev.get('title', '(no title)')}")

                stale = mark_missing_events_stale(
                    conn, business_id, page["url"], seen_keys,
                )
                if stale:
                    print(f"  marked {stale} missing event(s) as stale")

                conn.execute(
                    """INSERT INTO fetch_log (page_url, fetched_at, status_code,
                       content_hash, events_found, notes)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (page["url"], now_iso(), status, content_hash, len(events), None),
                )

        total = conn.execute("SELECT COUNT(*) FROM events WHERE status='active'").fetchone()[0]
        print(f"\nTotal active events in database: {total}")
