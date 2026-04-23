"""Render active events into a static HTML page at public/index.html,
plus a per-event detail page at public/event/{id}/index.html for each event."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
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


def _fmt_hours_range(rng: str | None) -> str:
    """'16:00-22:00' → '4pm–10pm'. Returns '' on parse failure."""
    if not rng or "-" not in rng:
        return ""
    try:
        opens, closes = rng.split("-", 1)
        return _humanrange(opens, closes)
    except Exception:
        return ""


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
STYLES_DIR = ROOT / "styles"
PUBLIC_DIR = ROOT / "public"
CONFIG_DIR = ROOT / "config"


def _publish_css(name: str) -> str:
    """Hash styles/{name}.css, copy to public/{name}.{hash8}.css, return href."""
    src = STYLES_DIR / f"{name}.css"
    css = src.read_bytes()
    h = hashlib.sha256(css).hexdigest()[:8]
    versioned = f"{name}.{h}.css"
    dst = PUBLIC_DIR / versioned
    if not dst.exists():
        # Remove stale versioned files for this name
        for old in PUBLIC_DIR.glob(f"{name}.????????.css"):
            old.unlink(missing_ok=True)
        dst.write_bytes(css)
    return f"/{versioned}"


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


def _is_ended_series(ev: dict, build_date: date) -> bool:
    """Return True if a recurring event has a manually-set ends_on date in the past.

    Used to hide watch-party-style events (e.g., TV-season viewing parties) after
    their series has wrapped. ends_on is the last date the event occurs, so the
    event still shows on that date itself and is hidden the next day.
    """
    ends_on = ev.get("ends_on")
    if not ends_on:
        return False
    try:
        return date.fromisoformat(ends_on) < build_date
    except ValueError:
        return False


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


_DIM_CACHE: dict[str, tuple[int, int]] = {}


def _img_dims(local_path: str | None) -> tuple[int, int] | None:
    """Return (width, height) for a local image, or None if unavailable.

    Used to emit explicit width/height attrs so the browser can reserve
    layout space before the image loads (fixes CLS).
    """
    if not local_path:
        return None
    if local_path in _DIM_CACHE:
        return _DIM_CACHE[local_path]
    full = PUBLIC_DIR / local_path
    if not full.exists():
        return None
    try:
        from PIL import Image  # lazy import; Pillow already required by images.py
        with Image.open(full) as im:
            dims = im.size  # (width, height)
        _DIM_CACHE[local_path] = dims
        return dims
    except Exception:
        return None


def _srcset(local_path: str | None) -> str:
    """Return srcset attribute value for a local WebP image path.

    Checks for 400w/800w variant files alongside the main 1200w image.
    Falls back gracefully if variants haven't been generated yet.
    """
    if not local_path or not local_path.endswith(".webp"):
        return ""
    p = Path(local_path)
    parts = []
    for w in [400, 800]:
        variant = PUBLIC_DIR / p.parent / f"{p.stem}-{w}w.webp"
        if variant.exists():
            parts.append(f"{p.parent}/{p.stem}-{w}w.webp {w}w")
    if not parts:
        return ""
    parts.append(f"{local_path} 1200w")
    return ", ".join(parts)


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
    """Generate 1200×630 OG images for the homepage and every event.

    Uses Playwright to screenshot HTML templates. Per-event images are cached
    on disk (skip if file exists). The homepage image is always regenerated so
    template changes land on the next build without manual file deletion.
    """
    from playwright.sync_api import sync_playwright

    og_dir = public_dir / "images" / "og"
    og_dir.mkdir(parents=True, exist_ok=True)

    event_template = env.get_template("_og_image.html")
    home_template = env.get_template("_og_image_home.html")
    home_og_path = public_dir / "images" / "og-home.jpg"

    to_generate = []
    for row in all_rows:
        ev = dict(row)
        og_path = og_dir / f"{ev['id']}.jpg"
        if not og_path.exists():
            ev["tags"] = json.loads(ev.get("tags") or "[]")
            ev["performers"] = json.loads(ev.get("performers") or "[]")
            to_generate.append((ev, og_path))

    if not to_generate:
        print(f"  OG images: per-event up to date; regenerating homepage ({home_og_path.name})")
    else:
        print(f"  Generating homepage OG + {len(to_generate)} per-event OG image(s)…")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1200, "height": 630})
        page = ctx.new_page()

        # Single temp file in public_dir so relative image paths resolve
        tmp_html = public_dir / "_og_tmp.html"
        try:
            # Homepage OG — always regenerate
            tmp_html.write_text(home_template.render())
            page.goto(f"file://{tmp_html}")
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.screenshot(path=str(home_og_path), type="jpeg", quality=90)

            # Per-event OGs — skip if file exists
            for ev, og_path in to_generate:
                image_rel_path = None
                if ev.get("image_local_path"):
                    candidate = public_dir / ev["image_local_path"]
                    if candidate.exists():
                        image_rel_path = ev["image_local_path"]

                html = event_template.render(
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


_PRICE_RE = re.compile(r"^\s*\$(\d+(?:\.\d{1,2})?)\s*$")
_FREE_PRICE_VALUES = {"free", "no cover"}


def _event_offer(price_info: str | None, event_url: str) -> dict | None:
    """Build a Schema.org Offer dict, or None if price isn't unambiguously parseable.

    Strict on purpose — Google's rich-results parser rejects free-form strings
    like '$5 cans, $4 shooters'. We'd rather emit no offer than a wrong one.
    """
    if not price_info:
        return None
    text = price_info.strip()
    lower = text.lower()
    price = None
    if lower in _FREE_PRICE_VALUES:
        price = "0"
    else:
        m = _PRICE_RE.match(text)
        if m:
            price = m.group(1)
    if price is None:
        return None
    return {
        "@type": "Offer",
        "price": price,
        "priceCurrency": "USD",
        "url": event_url,
        "availability": "https://schema.org/InStock",
    }


def _event_performers_schema(performers: list[dict]) -> list[dict]:
    """Map [{name, role}] performers to Schema.org Person entries."""
    return [
        {"@type": "Person", "name": p["name"]}
        for p in performers
        if p.get("name")
    ]


_SCHEMA_DAY_NAMES = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
    "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
}


def _opening_hours_schema(hours: dict | None) -> list[dict]:
    """Convert a YAML `hours:` block into Schema.org openingHoursSpecification[].

    Input: {"mon": "16:00-22:00", "tue": null, ...}
    Output: list of {"@type": "OpeningHoursSpecification", "dayOfWeek": "Monday",
                     "opens": "16:00", "closes": "22:00"}
    Skips days with null values (closed).
    """
    if not hours:
        return []
    specs = []
    for day_key, rng in hours.items():
        if not rng:
            continue
        try:
            opens, closes = rng.split("-", 1)
        except ValueError:
            continue
        day_name = _SCHEMA_DAY_NAMES.get(day_key)
        if not day_name:
            continue
        specs.append({
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": day_name,
            "opens": opens,
            "closes": closes,
        })
    return specs


def _business_schema(biz: dict, upcoming_events: list[dict]) -> dict:
    """Build the LocalBusiness JSON-LD dict for one business."""
    metadata = biz.get("metadata") or {}
    schema: dict = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "@id": f"{SITE_URL}/business/{biz['slug']}/",
        "name": biz["name"],
        "url": f"{SITE_URL}/business/{biz['slug']}/",
    }
    # sameAs: include the business's own external website first (if any),
    # then any social profile URLs from metadata.same_as.
    external_links = []
    if biz.get("website"):
        external_links.append(biz["website"])
    external_links.extend(metadata.get("same_as") or [])
    if external_links:
        schema["sameAs"] = external_links

    if biz.get("address"):
        schema["address"] = {
            "@type": "PostalAddress",
            "streetAddress": biz["address"].split(",")[0].strip(),
            "addressLocality": "Chicago",
            "addressRegion": "IL",
            "addressCountry": "US",
        }
    if biz.get("lat") and biz.get("lng"):
        schema["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": biz["lat"],
            "longitude": biz["lng"],
        }
    if metadata.get("telephone"):
        schema["telephone"] = metadata["telephone"]
    if metadata.get("price_range"):
        schema["priceRange"] = metadata["price_range"]
    if metadata.get("description"):
        schema["description"] = metadata["description"]
    hours_spec = _opening_hours_schema(biz.get("hours"))
    if hours_spec:
        schema["openingHoursSpecification"] = hours_spec

    # Representative image: most recent event flyer with an image
    for ev in upcoming_events:
        if ev.get("image_local_path"):
            schema["image"] = f"{SITE_URL}/{ev['image_local_path']}"
            break

    if upcoming_events:
        schema["event"] = [
            {
                "@type": "Event",
                "name": ev["title"],
                "url": f"{SITE_URL}/event/{ev['id']}/",
            }
            for ev in upcoming_events[:10]
        ]
    return schema


def _breadcrumb_schema(items: list[tuple[str, str]]) -> dict:
    """Build a BreadcrumbList JSON-LD dict from a list of (name, url) tuples."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": name,
                "item": url,
            }
            for i, (name, url) in enumerate(items)
        ],
    }


_WEEKDAY_NUM = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_MONTHLY_ORDINAL = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


def _parse_weekly_days(spec: str) -> set[int]:
    """'monday', 'monday,tuesday', or 'monday-friday' → {weekday ints (Mon=0)}."""
    if "," in spec:
        return {_WEEKDAY_NUM[d] for d in spec.split(",") if d in _WEEKDAY_NUM}
    if "-" in spec:
        a, b = spec.split("-", 1)
        if a in _WEEKDAY_NUM and b in _WEEKDAY_NUM:
            ai, bi = _WEEKDAY_NUM[a], _WEEKDAY_NUM[b]
            if ai <= bi:
                return set(range(ai, bi + 1))
            return set(range(ai, 7)) | set(range(0, bi + 1))
        return set()
    return {_WEEKDAY_NUM[spec]} if spec in _WEEKDAY_NUM else set()


def _is_nth_or_last_dow(d: date, ordinal: str) -> bool:
    """True if d is the Nth (or last) occurrence of its weekday in its month."""
    if ordinal == "last":
        return (d + timedelta(days=7)).month != d.month
    n = _MONTHLY_ORDINAL.get(ordinal)
    if n is None:
        return False
    return ((d.day - 1) // 7) + 1 == n


def _next_occurrence_date(pattern: str | None, build_date: date) -> date | None:
    """First date >= build_date matching the recurrence pattern, or None."""
    if not pattern:
        return None
    if pattern == "daily":
        return build_date
    if pattern.startswith("weekly:"):
        days = _parse_weekly_days(pattern[7:])
        if not days:
            return None
        for offset in range(7):
            d = build_date + timedelta(days=offset)
            if d.weekday() in days:
                return d
        return None
    if pattern.startswith("monthly:"):
        ordinal, _, day_str = pattern[8:].partition("-")
        target_dow = _WEEKDAY_NUM.get(day_str)
        if target_dow is None:
            return None
        for offset in range(40):
            d = build_date + timedelta(days=offset)
            if d.weekday() == target_dow and _is_nth_or_last_dow(d, ordinal):
                return d
        return None
    return None


def _event_schema_dates(ev: dict, build_date: date) -> tuple[str | None, str | None]:
    """Return (startDate, endDate) ISO strings for Schema.org Event, or (None, None)."""
    if ev.get("kind") == "dated":
        return ev.get("start_datetime"), ev.get("end_datetime")

    start_time = ev.get("start_time")
    if not start_time:
        return None, None
    next_date = _next_occurrence_date(ev.get("recurrence_pattern"), build_date)
    if not next_date:
        return None, None

    sh, sm = int(start_time[:2]), int(start_time[3:5])
    start_dt = datetime(next_date.year, next_date.month, next_date.day, sh, sm, tzinfo=CHICAGO)
    start_iso = start_dt.isoformat()

    end_time = ev.get("end_time")
    if not end_time:
        return start_iso, None
    eh, em = int(end_time[:2]), int(end_time[3:5])
    end_dt = datetime(next_date.year, next_date.month, next_date.day, eh, em, tzinfo=CHICAGO)
    if end_dt <= start_dt:  # midnight-crossing close
        end_dt += timedelta(days=1)
    return start_iso, end_dt.isoformat()


def _build_event_pages(
    template,
    md_template,
    all_rows: list,
    active_by_biz: dict[int, list[dict]],
    public_dir: Path,
    build_date: date,
    issue_number: int,
    event_css_href: str = "/event.css",
) -> None:
    count = 0
    for row in all_rows:
        ev = dict(row)
        ev["tags"] = json.loads(ev["tags"] or "[]")
        ev["performers"] = json.loads(ev.get("performers") or "[]")
        event_url = f"{SITE_URL}/event/{ev['id']}/"
        ev["schema_offer"] = _event_offer(
            ev.get("price_info"),
            ev.get("external_link") or event_url,
        )
        ev["schema_performers"] = _event_performers_schema(ev["performers"])
        ev["schema_start_date"], ev["schema_end_date"] = _event_schema_dates(ev, build_date)
        is_stale = ev["status"] != "active"
        event_when = _when_text(ev)

        related: list[dict] = []
        if is_stale:
            related = [
                e for e in active_by_biz.get(ev["business_id"], [])
                if e["id"] != ev["id"]
            ][:4]

        page_dir = public_dir / "event" / str(ev["id"])
        page_dir.mkdir(parents=True, exist_ok=True)
        breadcrumb_schema = _breadcrumb_schema([
            ("Home", f"{SITE_URL}/"),
            (ev.get("business_name", ""), f"{SITE_URL}/business/{ev.get('business_slug', '')}/"),
            (ev["title"], event_url),
        ])
        html = template.render(
            e=ev,
            is_stale=is_stale,
            related_events=related,
            event_when=event_when,
            kicker=_kicker(ev, build_date),
            site_url=SITE_URL,
            build_date=build_date,
            issue_number=issue_number,
            event_css_href=event_css_href,
            breadcrumb_schema=breadcrumb_schema,
        )
        (page_dir / "index.html").write_text(html)

        md = md_template.render(
            e=ev,
            is_stale=is_stale,
            event_when=event_when,
            site_url=SITE_URL,
        )
        (page_dir / "index.md").write_text(md)
        count += 1

    print(f"  {count} event page(s) written to public/event/ (html + md)")


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
    env.globals["srcset_for"] = _srcset
    env.globals["img_dims"] = _img_dims
    env.globals["fmt_hours_range"] = _fmt_hours_range

    index_css_href = _publish_css("index")
    event_css_href = _publish_css("event")

    index_template = env.get_template("index.html")
    detail_template = env.get_template("_event_detail.html")
    index_md_template = env.get_template("index.md")
    event_md_template = env.get_template("_event.md")
    business_html_template = env.get_template("_business_detail.html")
    business_md_template = env.get_template("_business.md")

    build_date = datetime.now(CHICAGO).date()
    weekend = _weekend_dates(build_date)

    with open(CONFIG_DIR / "businesses.yaml") as f:
        businesses = yaml.safe_load(f)["businesses"]

    with connect() as conn:
        rows = all_active_events(conn)
        all_rows = all_events_with_business(conn)
        last_updated = _last_updated(conn)

    events: list[dict] = []
    all_tags: set[str] = set()
    for row in rows:
        ev = dict(row)
        ev["tags"] = json.loads(ev["tags"] or "[]")
        ev["performers"] = json.loads(ev.get("performers") or "[]")
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
        [ev for ev in events
         if ev["kind"] == "recurring" and not _is_ended_series(ev, build_date)],
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
        index_css_href=index_css_href,
    )

    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(html)
    print(f"Wrote {PUBLIC_DIR / 'index.html'}")
    dated_total = len(today_events) + len(weekend_events) + len(later_events)
    print(f"  {dated_total} dated event(s) [{len(today_events)} today, {len(weekend_events)} this weekend, {len(later_events)} later]")
    print(f"  {len(recurring)} recurring event(s)")

    index_md = index_md_template.render(
        today_events=today_events,
        today_recurring=today_recurring,
        weekend_events=weekend_events,
        weekend_recurring=weekend_recurring,
        later_events=later_events,
        recurring_events=recurring,
        venue_list=venue_list,
        last_updated=last_updated,
        build_date=build_date,
        site_url=SITE_URL,
    )
    (PUBLIC_DIR / "index.md").write_text(index_md)
    print(f"  index.md written")

    _build_event_pages(detail_template, event_md_template, all_rows, active_by_biz, PUBLIC_DIR, build_date, issue_number, event_css_href)
    _build_business_pages(
        business_html_template,
        business_md_template,
        businesses,
        all_rows,
        PUBLIC_DIR,
        build_date,
        event_css_href,
        SITE_URL,
    )
    _build_og_images(env, all_rows, PUBLIC_DIR)
    _build_sitemap(all_rows, businesses, PUBLIC_DIR)
    _build_llms_txt(PUBLIC_DIR, businesses, last_updated, build_date)
    _assert_build(PUBLIC_DIR)


def _assert_build(public_dir: Path) -> None:
    """Post-build sanity checks. Fails fast with a clear error list if anything is broken."""
    from html.parser import HTMLParser

    errors: list[str] = []
    index_html = (public_dir / "index.html").read_text()

    # CSS <link> hrefs in index.html must exist on disk
    for href in re.findall(r'href="(/[^"]+\.css)"', index_html):
        if not (public_dir / href.lstrip("/")).exists():
            errors.append(f"Missing CSS: {href}")

    # Image src paths — only run when CHECK_IMAGES=1 (set by extraction workflow).
    # Site-rebuild CI and local dev skip this: images aren't present after a
    # build-only run (they live on the server, not in git).
    if os.environ.get("CHECK_IMAGES") == "1":
        class _SrcParser(HTMLParser):
            def __init__(self): super().__init__(); self.srcs: list[str] = []
            def handle_starttag(self, tag, attrs):
                if tag == "img":
                    for k, v in attrs:
                        if k == "src" and v and not v.startswith(("http", "data:")):
                            self.srcs.append(v.lstrip("/"))

        parser = _SrcParser()
        parser.feed(index_html)
        for src in parser.srcs:
            if not (public_dir / src).exists():
                errors.append(f"Missing image: {src}")

    if errors:
        print(f"\nBuild assertion errors ({len(errors)}):")
        for e in errors:
            print(f"  \u2717 {e}")
        sys.exit(1)

    print(f"  Build assertions: OK ({len(re.findall(r'<img ', index_html))} img tags checked)")


def _build_llms_txt(
    public_dir: Path,
    businesses: list[dict],
    last_updated: str,
    build_date: date,
) -> None:
    """Write /llms.txt — a compact orientation page for LLM agents.

    Follows the llmstxt.org convention: H1 title, blockquote summary, then
    H2 sections with linked bullets pointing to machine-readable resources.
    """
    lines: list[str] = [
        "# A'ville.net",
        "",
        "> Andersonville, Chicago events aggregator. Pulls events, happy hours, live music, drag shows, trivia, theater, and food/drink specials daily from neighborhood bar, restaurant, and venue websites. All times are local to America/Chicago.",
        "",
        f"Last updated: {last_updated or build_date.strftime('%A, %B %-d, %Y')}.",
        "",
        "## Primary resources",
        "",
        f"- [Event listing (markdown)]({SITE_URL}/index.md) — all current events grouped by tonight / this weekend / later / weekly regulars",
        f"- [Event listing (HTML)]({SITE_URL}/) — human-facing homepage, same content",
        f"- [Sitemap]({SITE_URL}/sitemap.xml) — every event has a canonical URL at `{SITE_URL}/event/{{id}}/` and every venue at `{SITE_URL}/business/{{slug}}/`",
        "",
        "## Per-event pages",
        "",
        f"Each event has both an HTML page at `{SITE_URL}/event/{{id}}/` and a markdown sibling at `{SITE_URL}/event/{{id}}/index.md` with the same content. Detail pages include the canonical URL, venue, address, when, performers, price, description, and a link to the source event page on the business's own website.",
        "",
        "## Per-venue pages",
        "",
        f"Each venue has a canonical entity page at `{SITE_URL}/business/{{slug}}/` (and a markdown sibling at `index.md`) with a `LocalBusiness` JSON-LD block, address, hours, and the list of current + recent events at that venue.",
        "",
        "## Structured data",
        "",
        f"- Every event page embeds Schema.org `Event` JSON-LD plus `BreadcrumbList` (Home → Business → Event).",
        f"- Every business page embeds Schema.org `LocalBusiness` JSON-LD plus `BreadcrumbList` (Home → Business).",
        f"- The homepage embeds `WebSite` + `ItemList` JSON-LD.",
        "",
        "## Venues currently covered",
        "",
    ]
    for biz in sorted(businesses, key=lambda b: b["name"].lower()):
        lines.append(f"- [{biz['name']}]({SITE_URL}/business/{biz['slug']}/)")
    lines.extend(
        [
            "",
            "## Usage",
            "",
            "Content on this site is explicitly opted in to AI training, search indexing, and real-time AI retrieval (see `/robots.txt` Content-Signal). Freely cite events and venues with their canonical URLs. The site is non-commercial and has no API auth.",
            "",
        ]
    )
    (public_dir / "llms.txt").write_text("\n".join(lines))
    print(f"  llms.txt written ({len(businesses)} venues listed, linked)")


def _build_business_pages(
    html_template,
    md_template,
    businesses: list[dict],
    all_rows: list,
    public_dir: Path,
    build_date: date,
    event_css_href: str,
    site_url: str,
) -> None:
    """Render /business/{slug}/index.html + index.md for each business."""
    events_by_slug: dict[str, list[dict]] = defaultdict(list)
    for row in all_rows:
        ev = dict(row)
        ev["tags"] = json.loads(ev.get("tags") or "[]")
        ev["performers"] = json.loads(ev.get("performers") or "[]")
        events_by_slug[ev["business_slug"]].append(ev)

    count = 0
    for biz in businesses:
        slug = biz["slug"]
        biz_events = events_by_slug.get(slug, [])

        active = [e for e in biz_events if e["status"] == "active"]
        stale = [e for e in biz_events if e["status"] == "stale"]
        upcoming_dated = sorted(
            [e for e in active if e["kind"] == "dated" and e.get("start_datetime")],
            key=lambda e: e["start_datetime"],
        )
        weekly_regulars = sorted(
            [e for e in active if e["kind"] == "recurring"
             and not _is_ended_series(e, build_date)],
            key=lambda e: _recurrence_sort_key(e.get("recurrence_pattern")),
        )
        recent_flyers = sorted(
            stale,
            key=lambda e: (e.get("last_seen_at") or ""),
            reverse=True,
        )

        business_schema = _business_schema(biz, upcoming_dated)
        breadcrumb_schema = _breadcrumb_schema([
            ("Home", f"{site_url}/"),
            (biz["name"], f"{site_url}/business/{slug}/"),
        ])

        page_dir = public_dir / "business" / slug
        page_dir.mkdir(parents=True, exist_ok=True)

        html = html_template.render(
            biz=biz,
            upcoming_dated=upcoming_dated,
            weekly_regulars=weekly_regulars,
            recent_flyers=recent_flyers,
            business_schema=business_schema,
            breadcrumb_schema=breadcrumb_schema,
            build_date=build_date,
            site_url=site_url,
            event_css_href=event_css_href,
        )
        (page_dir / "index.html").write_text(html)

        md = md_template.render(
            biz=biz,
            upcoming_dated=upcoming_dated,
            weekly_regulars=weekly_regulars,
            recent_flyers=recent_flyers,
            site_url=site_url,
        )
        (page_dir / "index.md").write_text(md)
        count += 1

    print(f"  {count} business page(s) written to public/business/ (html + md)")


def _build_sitemap(all_rows: list, businesses: list[dict], public_dir: Path) -> None:
    active_rows = [row for row in all_rows if row["status"] == "active"]

    def _lm(dt_str: str | None) -> str:
        if not dt_str:
            return ""
        try:
            return datetime.fromisoformat(dt_str).astimezone(CHICAGO).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return ""

    site_lm = max(
        (_lm(row["last_extracted_at"]) for row in active_rows if row["last_extracted_at"]),
        default="",
    )

    def _url(loc: str, lastmod: str) -> str:
        inner = f"<loc>{loc}</loc>"
        if lastmod:
            inner += f"<lastmod>{lastmod}</lastmod>"
        return f"  <url>{inner}</url>"

    urls = [_url(f"{SITE_URL}/", site_lm)]
    urls += [
        _url(f"{SITE_URL}/business/{biz['slug']}/", site_lm)
        for biz in businesses
    ]
    urls += [
        _url(f"{SITE_URL}/event/{row['id']}/", _lm(row["last_extracted_at"]))
        for row in active_rows
    ]
    active_ids = [row["id"] for row in active_rows]
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    (public_dir / "sitemap.xml").write_text(sitemap)
    # Content-Signal: opt in to AI training, search indexing, and real-time AI
    # retrieval. The site exists to surface neighborhood events — being found
    # by agents and LLMs is the goal. See contentsignals.org.
    (public_dir / "robots.txt").write_text(
        "User-agent: *\n"
        "Content-Signal: ai-train=yes, search=yes, ai-input=yes\n"
        "Allow: /\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    print(f"  sitemap.xml ({len(active_ids)} event URLs + {len(businesses)} business URLs) + robots.txt written")
