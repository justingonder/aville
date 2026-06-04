"""Tests for _poster_headline — the character-budget headline truncator used on
image-less event posters. Cases mirror the Bulletin v2 poster-headline-truncation
spec's expected-outcomes table. Run: python3 scripts/test_poster_headline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.site_builder import _poster_headline as ph

CASES = [
    # (title, max_chars, expected)
    # Spec outcomes table (budget 42): short titles pass through whole, no ellipsis.
    ("Belgian Beer Week Event", 42, "Belgian Beer Week Event"),
    ("Knitting Group", 42, "Knitting Group"),
    ("Sunday Funday - Free Hot Dogs", 42, "Sunday Funday - Free Hot Dogs"),
    ("Saturday, Gnocchi Gorgonzola", 42, "Saturday, Gnocchi Gorgonzola"),
    # The headline case: 36 chars ≤ 42 → shown whole, NOT "Complimentary Baby".
    ("Complimentary Baby Charcuterie Board", 42, "Complimentary Baby Charcuterie Board"),
    # Too many words → cut at word boundary with ellipsis.
    (
        "Memorial Day Weekend Patio Cookout and Live Music Festival",
        42,
        "Memorial Day Weekend Patio Cookout…",
    ),
    # Dangling connector trimmed before the ellipsis (never end on "…and…").
    ("Live Music and Dancing Tonight", 15, "Live Music…"),
    # Single giant word longer than the budget → hard-capped (only mid-word case).
    ("Supercalifragilisticexpialidocious", 10, "Supercali…"),
    # Whitespace normalized.
    ("  Spaced   Out   Title  ", 42, "Spaced Out Title"),
    # Empty / None guards.
    ("", 42, ""),
    (None, 42, ""),
    # Exactly at budget → no ellipsis.
    ("abcd efghi", 10, "abcd efghi"),
]


def main() -> int:
    failures = 0
    for title, budget, expected in CASES:
        got = ph(title, budget)
        ok = got == expected
        if not ok:
            failures += 1
            print(f"FAIL  ph({title!r}, {budget}) = {got!r}  expected {expected!r}")
        else:
            print(f"ok    ph({title!r}, {budget}) = {got!r}")
    print()
    if failures:
        print(f"{failures} failure(s)")
        return 1
    print(f"All {len(CASES)} cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
