"""Render active events into a static HTML page at public/index.html."""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .db import all_active_events, connect

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


def build_site() -> None:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("index.html")

    with connect() as conn:
        rows = all_active_events(conn)

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
    )

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(html)
    print(f"Wrote {PUBLIC_DIR / 'index.html'}")
    print(f"  {len(dated)} dated event(s), {len(recurring)} recurring event(s)")
