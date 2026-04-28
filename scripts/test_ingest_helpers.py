#!/usr/bin/env python3
"""Smoke tests for the in-script helpers in scripts/ingest_flyer.py.

Run: python3 scripts/test_ingest_helpers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_resolve_business_confident_match():
    from scripts.ingest_flyer import resolve_business
    businesses = [
        {"slug": "guesthouse-hotel", "name": "The Guesthouse Hotel"},
        {"slug": "vincent",          "name": "Vincent"},
        {"slug": "hopleaf",          "name": "Hopleaf Bar"},
    ]
    result = resolve_business("The Guesthouse Hotel", businesses)
    assert isinstance(result, tuple), f"expected confident-match tuple, got {result!r}"
    slug, score = result
    assert slug == "guesthouse-hotel", f"wrong slug: {slug}"
    assert score >= 0.90, f"score {score} below confident threshold"
    print(f"  resolve_business confident: OK ({slug}, score={score:.2f})")


def test_resolve_business_ambiguous():
    from scripts.ingest_flyer import resolve_business
    businesses = [
        {"slug": "guesthouse-hotel", "name": "The Guesthouse Hotel"},
        {"slug": "guesthouse-bar",   "name": "Guesthouse Bar"},
        {"slug": "vincent",          "name": "Vincent"},
    ]
    result = resolve_business("Guesthouse", businesses)
    assert isinstance(result, list), f"expected ambiguous list, got {result!r}"
    assert len(result) >= 2, f"expected 2+ candidates, got {len(result)}"
    slugs = [c[0] for c in result]
    assert "guesthouse-hotel" in slugs and "guesthouse-bar" in slugs, f"missing candidates: {slugs}"
    print(f"  resolve_business ambiguous: OK ({slugs})")


def test_resolve_business_no_match():
    from scripts.ingest_flyer import resolve_business
    businesses = [
        {"slug": "vincent", "name": "Vincent"},
        {"slug": "hopleaf", "name": "Hopleaf Bar"},
    ]
    result = resolve_business("Some Totally Unrelated Cafe", businesses)
    assert result is None, f"expected None for no match, got {result!r}"
    print(f"  resolve_business no match: OK")


if __name__ == "__main__":
    test_resolve_business_confident_match()
    test_resolve_business_ambiguous()
    test_resolve_business_no_match()
    print("PASS")
