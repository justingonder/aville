#!/usr/bin/env python3
"""Smoke tests for src/web_search.py. Run: python3 scripts/test_web_search.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.web_search import load_allowlist, domain_of


def test_allowlist_loads():
    domains = load_allowlist()
    assert isinstance(domains, list)
    assert "eventbrite.com" in domains
    assert "blockclubchicago.org" in domains
    assert "patch.com" in domains
    assert "andersonville.org" in domains
    assert all(d == d.lower() for d in domains), "domains must be lowercase"
    print(f"  load_allowlist: OK ({len(domains)} domains)")


def test_domain_of():
    assert domain_of("https://www.blockclubchicago.org/2026/04/01/foo") == "blockclubchicago.org"
    assert domain_of("https://eventbrite.com/e/123") == "eventbrite.com"
    assert domain_of("http://EXAMPLE.COM/x") == "example.com"
    assert domain_of("https://timeout.com/chicago/things-to-do") == "timeout.com"
    print(f"  domain_of: OK")


if __name__ == "__main__":
    test_allowlist_loads()
    test_domain_of()
    print("PASS")
