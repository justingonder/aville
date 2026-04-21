#!/usr/bin/env python3
"""Manage the homepage marquee banner (config/marquee.yaml).

Usage:
  # Turn off
  python scripts/set_marquee.py --off

  # Point at a specific event (reads title/description/URL from DB)
  python scripts/set_marquee.py --event 42

  # Custom banner with any text
  python scripts/set_marquee.py \\
      --label "★ Restaurant Week ★" \\
      --headline "Andersonville Restaurant Week" \\
      --body "Twelve local spots, one week, special menus all around." \\
      --link-text "Browse events →" \\
      --link-url "/#dated-later"

  # Dev/maintenance notice (no link needed)
  python scripts/set_marquee.py \\
      --label "🚧 Notice" \\
      --headline "This site is under active development" \\
      --body "Some events may be missing or incomplete. Check back soon."

After running, rebuild the site:
  python scripts/build_site.py
  # or trigger GitHub Actions:
  gh workflow run "Site rebuild"
"""
import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "marquee.yaml"

sys.path.insert(0, str(ROOT))
from src.db import connect


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(cfg: dict) -> None:
    header = (
        "# Marquee banner — shown at the top of the homepage when enabled: true\n"
        "# Run scripts/set_marquee.py to manage this file, then rebuild the site.\n\n"
    )
    with open(CONFIG_PATH, "w") as f:
        f.write(header)
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the homepage marquee banner.")
    parser.add_argument("--off", action="store_true", help="Disable the marquee.")
    parser.add_argument("--event", type=int, metavar="ID", help="Feature an event by DB id.")
    parser.add_argument("--label", help='Eyebrow label, e.g. "★ Restaurant Week ★"')
    parser.add_argument("--headline", help="Main heading text.")
    parser.add_argument("--body", help="Optional subtext.")
    parser.add_argument("--link-text", dest="link_text", help='CTA button text, e.g. "See details →"')
    parser.add_argument("--link-url", dest="link_url", help="CTA button URL.")
    args = parser.parse_args()

    cfg = load_config()

    if args.off:
        cfg["enabled"] = False
        save_config(cfg)
        print("Marquee disabled.")
        print("Rebuild to apply: python scripts/build_site.py")
        return

    if args.event:
        with connect() as conn:
            row = conn.execute(
                """SELECT e.id, e.title, e.description, b.name AS business_name
                   FROM events e JOIN businesses b ON e.business_id = b.id
                   WHERE e.id = ?""",
                (args.event,),
            ).fetchone()
        if not row:
            print(f"Error: no event with id {args.event}")
            sys.exit(1)
        ev = dict(row)
        cfg["enabled"] = True
        cfg["label"] = args.label or "★ Featured event ★"
        cfg["headline"] = ev["title"]
        cfg["body"] = ev["description"] or ""
        cfg["link_text"] = args.link_text or "See details →"
        cfg["link_url"] = args.link_url or f"/event/{ev['id']}/"
        save_config(cfg)
        print(f"Marquee set to event {ev['id']}: {ev['title']}")
        print("Rebuild to apply: python scripts/build_site.py")
        return

    # Custom text mode — require at least a headline
    if not args.headline and not args.label:
        parser.print_help()
        sys.exit(1)

    cfg["enabled"] = True
    if args.label:
        cfg["label"] = args.label
    if args.headline:
        cfg["headline"] = args.headline
    if args.body is not None:
        cfg["body"] = args.body
    cfg["link_text"] = args.link_text or None
    cfg["link_url"] = args.link_url or None
    save_config(cfg)
    print(f"Marquee enabled: {cfg.get('headline', '')}")
    print("Rebuild to apply: python scripts/build_site.py")


if __name__ == "__main__":
    main()
