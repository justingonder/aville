#!/usr/bin/env python3
"""Print a data quality report for active events.

Flags events that likely need manual investigation:
  - No image (imageless events may need a flyer or poster)
  - No time (start_time / start_datetime time unknown)
  - No description
  - No price info
  - Low extraction confidence (< 0.7)
  - Recurring events with no end_time (open-ended)

Usage:
  python scripts/data_quality_report.py
  python scripts/data_quality_report.py --business "Hopleaf Bar"
  python scripts/data_quality_report.py --missing image
  python scripts/data_quality_report.py --missing image --missing time
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.db import connect

ISSUES = {
    "image":       "No image",
    "time":        "No time",
    "description": "No description",
    "price":       "No price info",
    "confidence":  "Low confidence",
    "end_time":    "No end time (recurring)",
}

COL_WIDTHS = (5, 36, 26, 24)


def fmt_row(id_, title, business, flags):
    return (
        f"{str(id_):<{COL_WIDTHS[0]}}  "
        f"{title[:COL_WIDTHS[1]]:<{COL_WIDTHS[1]}}  "
        f"{business[:COL_WIDTHS[2]]:<{COL_WIDTHS[2]}}  "
        f"{flags}"
    )


def has_time(ev: dict) -> bool:
    if ev["kind"] == "recurring":
        return bool(ev.get("start_time"))
    dt = ev.get("start_datetime") or ""
    if "T" not in dt:
        return False
    time_part = dt.split("T")[1][:5]
    return time_part != "00:00"


def main() -> None:
    parser = argparse.ArgumentParser(description="Data quality report for active events.")
    parser.add_argument("--business", help="Filter to one business name (partial match).")
    parser.add_argument(
        "--missing",
        action="append",
        choices=list(ISSUES.keys()),
        metavar="FIELD",
        help=f"Filter to events missing this field. Choices: {', '.join(ISSUES)}. Repeatable.",
    )
    args = parser.parse_args()

    with connect() as conn:
        rows = conn.execute(
            """SELECT e.id, e.title, e.kind, e.description, e.image_local_path,
                      e.start_time, e.end_time, e.start_datetime, e.price_info,
                      e.confidence, e.recurrence_pattern,
                      b.name AS business_name
               FROM events e JOIN businesses b ON e.business_id = b.id
               WHERE e.status = 'active'
               ORDER BY b.name, e.title"""
        ).fetchall()

    events = [dict(r) for r in rows]

    if args.business:
        needle = args.business.lower()
        events = [e for e in events if needle in (e["business_name"] or "").lower()]

    def issues(ev: dict) -> list[str]:
        found = []
        if not ev.get("image_local_path"):
            found.append("image")
        if not has_time(ev):
            found.append("time")
        if not (ev.get("description") or "").strip():
            found.append("description")
        if not (ev.get("price_info") or "").strip():
            found.append("price")
        conf = ev.get("confidence")
        if conf is not None and conf < 0.7:
            found.append("confidence")
        if ev["kind"] == "recurring" and ev.get("start_time") and not ev.get("end_time"):
            found.append("end_time")
        return found

    filter_missing = set(args.missing or [])

    flagged = []
    for ev in events:
        ev_issues = issues(ev)
        if filter_missing and not (filter_missing & set(ev_issues)):
            continue
        if ev_issues:
            flagged.append((ev, ev_issues))

    if not flagged:
        print("No issues found.")
        return

    header = fmt_row("ID", "Title", "Business", "Issues")
    divider = "-" * (sum(COL_WIDTHS) + 6)
    print(f"\n{header}")
    print(divider)
    for ev, ev_issues in flagged:
        flags = ", ".join(ISSUES[i] for i in ev_issues)
        print(fmt_row(ev["id"], ev["title"], ev["business_name"], flags))

    print(divider)
    total = len(flagged)
    print(f"\n{total} event{'s' if total != 1 else ''} flagged out of {len(events)} active.\n")

    # Issue-type summary
    counts: dict[str, int] = {}
    for _, ev_issues in flagged:
        for issue in ev_issues:
            counts[issue] = counts.get(issue, 0) + 1
    print("By issue type:")
    for key, label in ISSUES.items():
        if key in counts:
            print(f"  {label:<30} {counts[key]}")
    print()


if __name__ == "__main__":
    main()
