"""Render active events into a static HTML page at public/index.html,
plus a per-event detail page at public/event/{id}/index.html for each event."""
from __future__ import annotations

import json
import urllib.request
import yaml
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .db import all_active_events, all_events_with_business, connect

CHICAGO = ZoneInfo("America/Chicago")
SITE_URL = "https://aville.net"
LAUNCH_DATE = date(2026, 4, 18)

_DAYS = {
    "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday",
    "thursday": "Thursday", "friday": "Friday", "saturday": "Saturday", "sunday": "Sunday",
}

_DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

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
    if not end or start == end:
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
            parts = days_part.split(",")
            # Named shortcuts
            if parts == ["monday", "tuesday", "wednesday", "thursday", "friday"]:
                return "Weekdays"
            if parts == ["saturday", "sunday"]:
                return "Weekends"
            # Consecutive run of 3+: collapse to range
            try:
                indices = [_DAY_ORDER.index(d) for d in parts]
                if (len(indices) >= 3
                        and indices == list(range(indices[0], indices[0] + len(indices)))):
                    return f"Every {_DAYS.get(parts[0], parts[0].title())}–{_DAYS.get(parts[-1], parts[-1].title())}"
            except ValueError:
                pass
            # 2 consecutive or non-consecutive: comma list, "and" before last
            day_names = [_DAYS.get(d, d.title()) for d in parts]
            if len(day_names) == 2:
                return f"Every {day_names[0]} and {day_names[1]}"
            return f"Every {', '.join(day_names[:-1])} and {day_names[-1]}"
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


def _daterange_str(dt_s: datetime, dt_e: datetime) -> str:
    """'Jun 25–28' or 'Apr 23–May 2' compact date range."""
    if dt_s.month == dt_e.month and dt_s.year == dt_e.year:
        return f"{dt_s.strftime('%B')} {dt_s.day}–{dt_e.day}"
    return f"{dt_s.strftime('%b')} {dt_s.day}–{dt_e.strftime('%b')} {dt_e.day}"


def _is_multiday(dt_s: datetime, dt_e: datetime) -> bool:
    """True if end date is genuinely more than one calendar day after start.
    Late-night midnight-crossing (e.g. 9pm–2am) returns False."""
    day_diff = (dt_e.date() - dt_s.date()).days
    s_time = dt_s.strftime('%H:%M')
    # All-day markers (00:00 start) spanning even 1 day count as multi-day
    return day_diff >= 2 or (day_diff >= 1 and s_time == "00:00")


def _humandaterange(start: str | None, end: str | None = None) -> str:
    """'2026-04-20T16:00:00-05:00', '2026-04-20T22:00:00-05:00' → 'Sunday, April 20 · 4–10pm'."""
    if not start:
        return ""
    try:
        dt_s = datetime.fromisoformat(start).astimezone(CHICAGO)
        s_time = dt_s.strftime('%H:%M')
        date_part = f"{dt_s.strftime('%A')}, {dt_s.strftime('%B')} {dt_s.day}"

        if end:
            dt_e = datetime.fromisoformat(end).astimezone(CHICAGO)
            if _is_multiday(dt_s, dt_e):
                return _daterange_str(dt_s, dt_e)
            time_part = _humanrange(s_time, dt_e.strftime('%H:%M'))
        else:
            time_part = _fmt_time(s_time)

        # Suppress 00:00 placeholder times
        if s_time == "00:00":
            return date_part
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


def _chicago_time_str(dt_str: str | None) -> str:
    """Extract HH:MM in Chicago time from an ISO datetime string, or '' if no time component."""
    if not dt_str or "T" not in dt_str:
        return ""
    try:
        return datetime.fromisoformat(dt_str).astimezone(CHICAGO).strftime("%H:%M")
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


def _shortdate(dt_str: str | None) -> str:
    """'2026-04-20T21:00:00' → 'Mon Apr 20'"""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str).astimezone(CHICAGO)
        return f"{dt.strftime('%a')} {dt.strftime('%b')} {dt.day}"
    except ValueError:
        return ""


def _card_date_str(start: str | None, end: str | None = None) -> str:
    """Compact date for card .f-day header. Multi-day → range, all-day → no time."""
    if not start:
        return ""
    try:
        dt_s = datetime.fromisoformat(start).astimezone(CHICAGO)
        s_time = dt_s.strftime('%H:%M')
        if end:
            dt_e = datetime.fromisoformat(end).astimezone(CHICAGO)
            if _is_multiday(dt_s, dt_e):
                return _daterange_str(dt_s, dt_e)
        short = f"{dt_s.strftime('%a')} {dt_s.strftime('%b')} {dt_s.day}"
        if s_time and s_time != "00:00":
            return f"{short} · {_fmt_time(s_time)}"
        return short
    except (ValueError, AttributeError):
        return ""


def _fmt_sunset(t: str) -> str:
    """'07:39 PM' → '7:39pm'"""
    try:
        time_part, ampm = t.strip().rsplit(" ", 1)
        h, m = time_part.split(":")
        return f"{int(h)}:{m}{ampm.lower()}"
    except Exception:
        return t


def _fetch_weather() -> dict:
    try:
        req = urllib.request.Request(
            "https://wttr.in/Chicago?format=j1",
            headers={"User-Agent": "aville.net/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        current = data["current_condition"][0]
        temp_f = current["temp_F"]
        desc = current["weatherDesc"][0]["value"].lower()
        sunset_raw = data["weather"][0]["astronomy"][0]["sunset"]
        return {"temp_f": temp_f, "desc": desc, "sunset": _fmt_sunset(sunset_raw)}
    except Exception as exc:
        print(f"  weather fetch skipped: {exc}")
        return {}


def _issue_number(build_date: date) -> int:
    return max(1, (build_date - LAUNCH_DATE).days + 1)


def _kicker(ev: dict, build_date: date) -> str:
    """Short eyebrow label for the detail page header."""
    raw_tags = ev.get("tags") or []
    tags = json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
    first_tag = tags[0] if tags else None
    if ev.get("kind") == "dated" and ev.get("start_datetime"):
        try:
            event_date = datetime.fromisoformat(ev["start_datetime"]).astimezone(CHICAGO).date()
            diff = (event_date - build_date).days
            if diff == 0:
                timing = "Today"
            elif diff == 1:
                timing = "Tomorrow"
            elif diff > 0:
                timing = f"{diff} days away"
            else:
                timing = "Past event"
        except Exception:
            timing = "Dated event"
        return " · ".join(p for p in [first_tag or "Event", timing] if p)
    pattern = ev.get("recurrence_pattern") or ""
    rec = _humanrecurrence(pattern)
    return " · ".join(p for p in [first_tag or "Weekly", rec] if p)


def _miniev_date(ev: dict) -> tuple[str, str]:
    """Returns (big, small) for the miniev date column."""
    if ev.get("kind") == "dated" and ev.get("start_datetime"):
        try:
            dt = datetime.fromisoformat(ev["start_datetime"]).astimezone(CHICAGO)
            return str(dt.day), dt.strftime("%b")
        except Exception:
            return "–", ""
    pattern = ev.get("recurrence_pattern") or ""
    if pattern.startswith("weekly:"):
        day = pattern[7:].split(",")[0][:3].title()
        return day, "wkly"
    if pattern == "daily":
        return "Daily", ""
    return "–", ""


def _venue_summary(events: list[dict]) -> list[tuple[str, str]]:
    """Returns list of (business_name, event_note) for sidebar."""
    by_biz: dict[str, list] = {}
    for ev in events:
        biz = ev.get("business_name") or ""
        if biz:
            by_biz.setdefault(biz, []).append(ev)
    result = []
    for biz, evs in sorted(by_biz.items()):
        count = len(evs)
        note = evs[0].get("title", "") if count == 1 else f"{count} events"
        result.append((biz, note))
    return result


ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
PUBLIC_DIR = ROOT / "public"
CONFIG_DIR = ROOT / "config"


def _load_marquee() -> dict:
    path = CONFIG_DIR / "marquee.yaml"
    try:
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "label": cfg.get("label") or "★ Featured ★",
            "headline": cfg.get("headline") or "",
            "body": cfg.get("body") or "",
            "link_text": cfg.get("link_text") or None,
            "link_url": cfg.get("link_url") or None,
        }
    except FileNotFoundError:
        return {"enabled": False}

DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _time_to_mins(t: str | None) -> int | None:
    """'HH:MM' → minutes since midnight, or None."""
    if not t or len(t) < 5:
        return None
    try:
        return int(t[:2]) * 60 + int(t[3:5])
    except ValueError:
        return None


def _superseded_recurring_ids(
    dated_events: list[dict],
    recurring_events: list[dict],
    window_mins: int = 60,
) -> set[int]:
    """Return IDs of recurring events superseded by a dated event at the same
    business with a start time within window_mins minutes.

    Example: a themed karaoke night (dated, Monday 9pm) supersedes the regular
    Karaoke Mondays (recurring, Monday 9pm) at the same venue.
    """
    superseded: set[int] = set()
    for dated in dated_events:
        biz_id = dated.get("business_id")
        d_mins = _time_to_mins(_chicago_time_str(dated.get("start_datetime") or ""))
        if not biz_id or d_mins is None:
            continue
        for rec in recurring_events:
            if rec.get("business_id") != biz_id:
                continue
            r_mins = _time_to_mins(rec.get("start_time"))
            if r_mins is None:
                continue
            if abs(d_mins - r_mins) <= window_mins:
                superseded.add(rec["id"])
    return superseded


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


_POSTER_VARIANTS = ["p-yellow", "p-red", "p-cream", "p-ink", "p-stripe"]


def _build_og_images(env, all_rows: list, public_dir: Path) -> None:
    """Generate 1200×630 OG images for every event that doesn't have one yet.

    Uses Playwright to screenshot an HTML template. Skips events whose
    og image already exists on disk (file-exists cache).
    """
    from playwright.sync_api import sync_playwright

    og_dir = public_dir / "images" / "og"
    og_dir.mkdir(parents=True, exist_ok=True)

    template = env.get_template("_og_image.html")

    to_generate = []
    for row in all_rows:
        ev = dict(row)
        og_path = og_dir / f"{ev['id']}.jpg"
        if not og_path.exists():
            ev["tags"] = json.loads(ev.get("tags") or "[]")
            to_generate.append((ev, og_path))

    if not to_generate:
        print("  OG images: all up to date, skipping")
        return

    print(f"  Generating {len(to_generate)} OG image(s)…")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1200, "height": 630})
        page = ctx.new_page()

        # Single temp file in public_dir so relative image paths resolve
        tmp_html = public_dir / "_og_tmp.html"
        try:
            for ev, og_path in to_generate:
                image_rel_path = None
                if ev.get("image_local_path"):
                    candidate = public_dir / ev["image_local_path"]
                    if candidate.exists():
                        image_rel_path = ev["image_local_path"]

                html = template.render(
                    image_rel_path=image_rel_path,
                    poster_variant=_POSTER_VARIANTS[ev["id"] % len(_POSTER_VARIANTS)],
                    poster_title=ev["title"],
                    poster_business=ev.get("business_name", ""),
                    poster_when=_when_text(ev),
                )

                tmp_html.write_text(html)
                page.goto(f"file://{tmp_html}")
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass  # fonts timed out; screenshot with fallback fonts
                page.screenshot(path=str(og_path), type="jpeg", quality=88)
        finally:
            tmp_html.unlink(missing_ok=True)

        browser.close()

    print(f"  OG images written to {og_dir.relative_to(public_dir.parent)}")


def _build_event_pages(
    template,
    all_rows: list,
    active_by_biz: dict[int, list[dict]],
    public_dir: Path,
    build_date: date,
    issue_number: int,
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
            event_when=_when_text(ev),
            kicker=_kicker(ev, build_date),
            site_url=SITE_URL,
            build_date=build_date,
            issue_number=issue_number,
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
    env.globals["chicago_time_str"] = _chicago_time_str
    env.globals["shortdate"] = _shortdate
    env.globals["card_date_str"] = _card_date_str
    env.globals["fmt_time"] = _fmt_time
    env.globals["when_text"] = _when_text
    env.globals["miniev_date"] = _miniev_date

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

    today_day_name = build_date.strftime("%A").lower()
    today_recurring = [
        ev for ev in recurring
        if _fires_on_days(ev.get("recurrence_pattern"), {today_day_name})
    ]

    # Remove recurring events superseded by a dated event at the same venue+time.
    # e.g. "Karaoke Mondays" (recurring, Mon 9pm) is hidden when "Panic! at the Karaoke"
    # (dated, Mon 9pm, same business) is on the board.
    today_superseded = _superseded_recurring_ids(today_events, today_recurring)
    if today_superseded:
        today_recurring = [ev for ev in today_recurring if ev["id"] not in today_superseded]

    weekend_superseded: set[int] = set()
    for d in weekend:
        day_name = d.strftime("%A").lower()
        day_dated = [ev for ev in weekend_events
                     if _chicago_date_str(ev.get("start_datetime")) == d.isoformat()]
        day_recurring = [ev for ev in weekend_recurring
                         if _fires_on_days(ev.get("recurrence_pattern"), {day_name})]
        weekend_superseded |= _superseded_recurring_ids(day_dated, day_recurring)
    if weekend_superseded:
        weekend_recurring = [ev for ev in weekend_recurring if ev["id"] not in weekend_superseded]

    weather = _fetch_weather()
    issue_number = _issue_number(build_date)
    venue_list = _venue_summary(events)
    marquee = _load_marquee()

    html = index_template.render(
        today_events=today_events,
        today_recurring=today_recurring,
        weekend_events=weekend_events,
        weekend_recurring=weekend_recurring,
        later_events=later_events,
        recurring_events=recurring,
        all_tags=sorted(all_tags),
        last_updated=last_updated,
        featured_events=featured_events,
        marquee=marquee,
        weather=weather,
        issue_number=issue_number,
        venue_list=venue_list,
        build_date=build_date,
    )

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(html)
    print(f"Wrote {PUBLIC_DIR / 'index.html'}")
    dated_total = len(today_events) + len(weekend_events) + len(later_events)
    print(f"  {dated_total} dated event(s) [{len(today_events)} today, {len(weekend_events)} this weekend, {len(later_events)} later]")
    print(f"  {len(recurring)} recurring event(s)")

    _build_event_pages(detail_template, all_rows, active_by_biz, PUBLIC_DIR, build_date, issue_number)
    _build_og_images(env, all_rows, PUBLIC_DIR)
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
