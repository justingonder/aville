#!/usr/bin/env python3
"""Smoke tests for src/web_search.py. Run: python3 scripts/test_web_search.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.web_search import load_allowlist, domain_of


def test_ranker_prefers_tier_1():
    from src.web_search import rank_search_results, SearchResult
    candidates = [
        {"url": "https://blockclubchicago.org/event-foo", "title": "Foo"},
        {"url": "https://guesthousehotel.com/events", "title": "Foo at Guesthouse"},
    ]
    allowlist = ["blockclubchicago.org", "eventbrite.com"]
    result = rank_search_results(candidates, allowlist=allowlist, venue_domain="guesthousehotel.com")
    assert result is not None
    assert result.tier == 1
    assert result.url == "https://guesthousehotel.com/events"
    print(f"  ranker tier-1 preference: OK")


def test_ranker_falls_back_to_tier_2():
    from src.web_search import rank_search_results
    candidates = [
        {"url": "https://random-blog.example/foo", "title": "Foo"},
        {"url": "https://blockclubchicago.org/event-foo", "title": "Foo"},
    ]
    allowlist = ["blockclubchicago.org"]
    result = rank_search_results(candidates, allowlist=allowlist, venue_domain=None)
    assert result is not None
    assert result.tier == 2
    assert result.domain == "blockclubchicago.org"
    print(f"  ranker tier-2 fallback: OK")


def test_ranker_rejects_unknown_domains():
    from src.web_search import rank_search_results
    candidates = [
        {"url": "https://random-blog.example/foo", "title": "Foo"},
        {"url": "https://yelp.com/biz/foo", "title": "Foo"},
    ]
    allowlist = ["blockclubchicago.org"]
    result = rank_search_results(candidates, allowlist=allowlist, venue_domain=None)
    assert result is None
    print(f"  ranker rejects unknown: OK")


def test_ranker_handles_empty_input():
    from src.web_search import rank_search_results
    assert rank_search_results([], allowlist=["blockclubchicago.org"], venue_domain=None) is None
    print(f"  ranker empty input: OK")


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


def test_search_for_event_live():
    """Live test against Anthropic API + web_search tool. Requires ANTHROPIC_API_KEY."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"  search_for_event: SKIPPED (no ANTHROPIC_API_KEY)")
        return
    from src.web_search import search_for_event, load_allowlist
    seed = {
        "event_title": "Wander Home Holiday Market",
        "venue_name": "The Guesthouse Hotel Chicago",
        "date_hint": "May 2",
        "distinctive_strings": ["Mother's Day Edition", "local vendors"],
    }
    result = search_for_event(seed, allowlist=load_allowlist(), venue_domain=None)
    # We expect *some* result for a real event; if not, we want to see what came back.
    if result is None:
        print(f"  search_for_event: NO RESULT (seed may be too obscure or allowlist too tight)")
        print(f"     -> this isn't a hard failure; investigate manually")
        return
    assert result.url.startswith("http"), f"bad url: {result.url}"
    assert result.tier in (1, 2), f"bad tier: {result.tier}"
    print(f"  search_for_event: OK ({result.tier=}, {result.domain=})")
    print(f"     URL: {result.url}")


if __name__ == "__main__":
    test_allowlist_loads()
    test_domain_of()
    test_ranker_prefers_tier_1()
    test_ranker_falls_back_to_tier_2()
    test_ranker_rejects_unknown_domains()
    test_ranker_handles_empty_input()
    test_search_for_event_live()
    print("PASS")
