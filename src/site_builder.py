"""Render active events into a static HTML page at public/index.html."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .db import all_active_events, connect

CHICAGO = ZoneInfo("America/Chicago")

_DAYS = {
    "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday",
    "thursday": "Thursday", "friday": "Friday", "saturday": "Saturday", "sunday": "Sunday",
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

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
PUBLIC_DIR = ROOT / "public"


DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


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


def build_site() -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["humanrecurrence"] = _humanrecurrence
    env.filters["humandate"] = _humandate
    env.globals["humanrange"] = _humanrange
    template = env.get_template("index.html")

    with connect() as conn:
        rows = all_active_events(conn)
        last_updated = _last_updated(conn)

    events = []
    all_tags: set[str] = set()
    for row in rows:
        ev = dict(row)
        ev["tags"] = json.loads(ev["tags"] or "[]")
        all_tags.update(ev["tags"])
        events.append(ev)

    dated = [e for e in events if e["kind"] == "dated"]
    recurring = sorted(
        [e for e in events if e["kind"] == "recurring"],
        key=lambda e: _recurrence_sort_key(e.get("recurrence_pattern")),
    )

    html = template.render(
        dated_events=dated,
        recurring_events=recurring,
        all_tags=sorted(all_tags),
        last_updated=last_updated,
    )

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(html)
    print(f"Wrote {PUBLIC_DIR / 'index.html'}")
    print(f"  {len(dated)} dated event(s), {len(recurring)} recurring event(s)")
