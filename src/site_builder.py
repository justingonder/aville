"""Render active events into a static HTML page at public/index.html,
plus a per-event detail page at public/event/{id}/index.html for each event."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .db import all_active_events, all_events_with_business, connect

CHICAGO = ZoneInfo("America/Chicago")
SITE_URL = "https://aville.net"

_DAYS = {
    "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday",
    "thursday": "Thursday", "friday": "Friday", "saturday": "Saturday", "sunday": "Sunday",
}

_DAY_NAMES_JS = {
    "sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3,
    "thursday": 4, "friday": 5, "saturday": 6,
}


def _fmt_time(t: str | None) -> str:
    """'HH:MM' → '7pm' / '7:30pm'. Drops :00 at the top of the hour."""
    if not t:
        return ""
    h, m = int(t[:2]), int(t[3:5])
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{suffix}" if m else f"{h12}{suffix}"


def _humanrange(start: str | None, end: str | None = None) -> str:
    """Format a time range, omitting repeated am/pm when both times share a suffix."""
    if not start:
        return ""
    s = _fmt_time(start)
    if not end:
        return s
    e = _fmt_time(end)
    if s[-2:] == e[-2:]:   # same suffix → strip from start
        return f"{s[:-2]}–{e}"
    return f"{s}–{e}"


def _humanrecurrence(pattern: str | None) -> str:
    """'weekly:tuesday' → 'Every Tuesday', 'monthly:last-friday' → 'Last Friday of the month'."""
    if not pattern:
        return ""
    if pattern == "daily":
        return "Every day"
    if pattern.startswith("weekly:"):
        days_part = pattern[7:]
        if "," in days_part:
            parts = [_DAYS.get(d, d.title()) for d in days_part.split(",")]
            return "Every " + " and ".join(parts)
        if "-" in days_part:
            a, b = days_part.split("-", 1)
            return f"Every {_DAYS.get(a, a.title())} through {_DAYS.get(b, b.title())}"
        return f"Every {_DAYS.get(days_part, days_part.title())}"
    if pattern.startswith("monthly:"):
        ordinal, _, day = pattern[8:].partition("-")
        day_name = _DAYS.get(day, day.title())
        if ordinal == "last":
            return f"Last {day_name} of the month"
        return f"{ordinal} {day_name} of the month"
    return pattern


def _humandate(dt_str: str | None) -> str:
    """'2026-04-20T21:00:00-05:00' → 'Monday, April 20 · 9pm'."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str)
        return f"{dt.strftime('%A')}, {dt.strftime('%B')} {dt.day} · {_fmt_time(dt.strftime('%H:%M'))}"
    except ValueError:
        return dt_str[:16].replace("T", " ")


def _humandaterange(start: str | None, end: str | None = None) -> str:
    """'2026-04-20T16:00:00-05:00', '2026-04-20T22:00:00-05:00' → 'Sunday, April 20 · 4–10pm'."""
    if not start:
        return ""
    try:
        dt_s = datetime.fromisoformat(start)
        date_part = f"{dt_s.strftime('%A')}, {dt_s.strftime('%B')} {dt_s.day}"
        s_time = dt_s.strftime('%H:%M')
        if end:
            dt_e = datetime.fromisoformat(end)
            time_part = _humanrange(s_time, dt_e.strftime('%H:%M'))
        else:
            time_part = _fmt_time(s_time)
        return f"{date_part} · {time_part}"
    except ValueError:
        return start[:16].replace("T", " ")


def _recurrence_days_js(pattern: str | None) -> str:
    """Returns comma-separated JS day indices (0=Sun) for client-side happening-now checks."""
    if not pattern:
        return ""
    if pattern == "daily":
        return "0,1,2,3,4,5,6"
    if pattern.startswith("weekly:"):
        part = pattern[7:]
        if "," in part:
            return ",".join(
                str(_DAY_NAMES_JS[d]) for d in part.split(",") if d in _DAY_NAMES_JS
            )
        if "-" in part:
            a, b = part.split("-", 1)
            if a in _DAY_NAMES_JS and b in _DAY_NAMES_JS:
                return ",".join(
                    str(i) for i in range(_DAY_NAMES_JS[a], _DAY_NAMES_JS[b] + 1)
                )
        return str(_DAY_NAMES_JS.get(part, ""))
    return ""  # monthly patterns not handled in client-side JS


def _chicago_date_str(dt_str: str | None) -> str:
    """Extract YYYY-MM-DD in Chicago time from an ISO datetime string."""
    if not dt_str:
        return ""
    try:
        return datetime.fromisoformat(dt_str).astimezone(CHICAGO).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _when_text(ev: dict) -> str:
    """Human-readable 'when' line for OG descriptions and detail pages."""
    if ev.get("kind") == "dated" and ev.get("start_datetime"):
        return _humandaterange(ev.get("start_datetime"), ev.get("end_datetime"))
    if ev.get("kind") == "recurring":
        rec = _humanrecurrence(ev.get("recurrence_pattern"))
        tr = _humanrange(ev.get("start_time"), ev.get("end_time"))
        return f"{rec} · {tr}" if tr else rec
    return ""


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
PUBLIC_DIR = ROOT / "public"

DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _fires_on_days(pattern: str | None, target_days: set[str]) -> bool:
    """Return True if a recurrence pattern fires on any day in target_days."""
    if not pattern:
        return False
    if pattern == "daily":
        return bool(target_days)
    if pattern.startswith("weekly:"):
        part = pattern[7:]
        if "," in part:
            return bool(set(part.split(",")) & target_days)
        if "-" in part:
            a, b = part.split("-", 1)
            if a in DAY_ORDER and b in DAY_ORDER:
                ia, ib = DAY_ORDER.index(a), DAY_ORDER.index(b)
                return bool(set(DAY_ORDER[ia : ib + 1]) & target_days)
        return part in target_days
    return False


def _recurrence_sort_key(pattern: str | None) -> tuple:
    """Sort recurring events by day-of-week when possible."""
    if not pattern:
        return (99, "")
    if pattern.startswith("weekly:"):
        day = pattern.removeprefix("weekly:").split("-")[0].split(",")[0]
        try:
            return (0, DAY_ORDER.index(day))
        except ValueError:
            return (1, day)
    if pattern.startswith("monthly:"):
        return (2, pattern)
    return (3, pattern)


def _last_updated(conn) -> str:
    row = conn.execute(
        "SELECT MAX(last_extracted_at) FROM events WHERE status='active'"
    ).fetchone()
    if not row or not row[0]:
        return ""
    dt = datetime.fromisoformat(row[0]).astimezone(CHICAGO)
    return f"{dt.strftime('%A')}, {dt.strftime('%B')} {dt.day} · {_fmt_time(dt.strftime('%H:%M'))}"


def _weekend_dates(build_date: date) -> set[date]:
    """Return the set of Fri/Sat/Sun dates for 'This Weekend', excluding today."""
    weekday = build_date.weekday()  # 0=Mon, 6=Sun
    days_to_fri = (4 - weekday) % 7
    fri = build_date + timedelta(days=days_to_fri)
    candidates = {fri, fri + timedelta(1), fri + timedelta(2)}
    candidates.discard(build_date)
    return candidates


def _build_event_pages(
    template,
    all_rows: list,
    active_by_biz: dict[int, list[dict]],
    public_dir: Path,
) -> None:
    count = 0
    for row in all_rows:
        ev = dict(row)
        ev["tags"] = json.loads(ev["tags"] or "[]")
        is_stale = ev["status"] != "active"

        related: list[dict] = []
        if is_stale:
            related = [
                e for e in active_by_biz.get(ev["business_id"], [])
                if e["id"] != ev["id"]
            ][:4]

        page_dir = public_dir / "event" / str(ev["id"])
        page_dir.mkdir(parents=True, exist_ok=True)
        html = template.render(
            e=ev,
            is_stale=is_stale,
            related_events=related,
            when_text=_when_text(ev),
            site_url=SITE_URL,
        )
        (page_dir / "index.html").write_text(html)
        count += 1

    print(f"  {count} event page(s) written to public/event/")


def build_site() -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["humanrecurrence"] = _humanrecurrence
    env.filters["humandate"] = _humandate
    env.globals["humanrange"] = _humanrange
    env.globals["humandaterange"] = _humandaterange
    env.globals["recurrence_days_js"] = _recurrence_days_js
    env.globals["chicago_date_str"] = _chicago_date_str

    index_template = env.get_template("index.html")
    detail_template = env.get_template("_event_detail.html")

    build_date = datetime.now(CHICAGO).date()
    weekend = _weekend_dates(build_date)

    with connect() as conn:
        rows = all_active_events(conn)
        all_rows = all_events_with_business(conn)
        last_updated = _last_updated(conn)

    events: list[dict] = []
    all_tags: set[str] = set()
    for row in rows:
        ev = dict(row)
        ev["tags"] = json.loads(ev["tags"] or "[]")
        all_tags.update(ev["tags"])
        events.append(ev)

    # Build lookup for tombstone related-events
    active_by_biz: dict[int, list[dict]] = defaultdict(list)
    for ev in events:
        active_by_biz[ev["business_id"]].append(ev)

    # Date-bucket dated events
    today_events: list[dict] = []
    weekend_events: list[dict] = []
    later_events: list[dict] = []
    for ev in events:
        if ev["kind"] != "dated":
            continue
        ds = _chicago_date_str(ev.get("start_datetime"))
        try:
            ed = date.fromisoformat(ds) if ds else None
        except ValueError:
            ed = None
        if ed == build_date:
            today_events.append(ev)
        elif ed in weekend:
            weekend_events.append(ev)
        else:
            later_events.append(ev)

    featured_events = [ev for ev in events if ev.get("featured")]

    weekend_day_names = {d.strftime("%A").lower() for d in weekend}

    recurring = sorted(
        [ev for ev in events if ev["kind"] == "recurring"],
        key=lambda ev: _recurrence_sort_key(ev.get("recurrence_pattern")),
    )

    weekend_recurring = [
        ev for ev in recurring
        if _fires_on_days(ev.get("recurrence_pattern"), weekend_day_names)
    ]

    html = index_template.render(
        today_events=today_events,
        weekend_events=weekend_events,
        weekend_recurring=weekend_recurring,
        later_events=later_events,
        recurring_events=recurring,
        all_tags=sorted(all_tags),
        last_updated=last_updated,
        featured_events=featured_events,
    )

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(html)
    print(f"Wrote {PUBLIC_DIR / 'index.html'}")
    dated_total = len(today_events) + len(weekend_events) + len(later_events)
    print(f"  {dated_total} dated event(s) [{len(today_events)} today, {len(weekend_events)} this weekend, {len(later_events)} later]")
    print(f"  {len(recurring)} recurring event(s)")

    _build_event_pages(detail_template, all_rows, active_by_biz, PUBLIC_DIR)
    _build_sitemap(all_rows, PUBLIC_DIR)


def _build_sitemap(all_rows: list, public_dir: Path) -> None:
    active_ids = [row["id"] for row in all_rows if row["status"] == "active"]
    urls = [f"  <url><loc>{SITE_URL}/</loc></url>"] + [
        f"  <url><loc>{SITE_URL}/event/{eid}/</loc></url>" for eid in active_ids
    ]
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    (public_dir / "sitemap.xml").write_text(sitemap)
    (public_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    )
    print(f"  sitemap.xml ({len(active_ids)} event URLs) + robots.txt written")
