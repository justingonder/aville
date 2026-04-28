"""Web-search-based authoritative-source discovery for flyer ingestion.

Three responsibilities:
  1. Load the Tier-2 allowlist from config/web_search_allowlist.yaml.
  2. Rank a list of search results into Tier 1 (venue's own domain) vs.
     Tier 2 (curated allowlist) vs. rejected (everything else).
  3. Drive a Claude call with the server-side web_search tool to discover
     candidate URLs for an event seed, then rank them.

Positioned for reuse: the CLAUDE.md "Nav-link discovery for new special
pages" follow-up will reuse the same allowlist + ranker.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

ALLOWLIST_PATH = Path(__file__).resolve().parent.parent / "config" / "web_search_allowlist.yaml"


@dataclass
class SearchResult:
    url: str
    title: str
    domain: str
    tier: int  # 1 = venue's own domain; 2 = curated allowlist


def load_allowlist(path: Path = ALLOWLIST_PATH) -> list[str]:
    """Return the Tier-2 domain list from the YAML config."""
    doc = yaml.safe_load(path.read_text())
    domains = doc.get("tier_2") or []
    if not isinstance(domains, list) or not all(isinstance(d, str) for d in domains):
        raise ValueError(f"{path}: tier_2 must be a list of strings")
    return [d.lower().strip() for d in domains]


def domain_of(url: str) -> str:
    """Return the lowercase netloc of a URL, stripping any leading 'www.'."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def rank_search_results(
    candidates: list[dict],
    *,
    allowlist: list[str],
    venue_domain: str | None,
) -> SearchResult | None:
    """Rank web-search candidates and return the best one above the bar.

    candidates: list of {"url": str, "title": str} dicts in search-result order
                (best-first per the search engine).
    allowlist:  Tier-2 domain list (lowercase, stripped of 'www.').
    venue_domain: lowercase domain for the venue's own website (Tier 1), or None
                  when the venue is unknown (no Tier 1 boost).

    Returns: the highest-tier SearchResult (Tier 1 if any candidate matches the
    venue domain, else the first Tier-2 hit), or None if nothing matches.
    """
    tier_1: SearchResult | None = None
    tier_2: SearchResult | None = None

    for cand in candidates:
        url = cand.get("url") or ""
        if not url:
            continue
        domain = domain_of(url)
        title = cand.get("title") or ""

        if venue_domain and domain == venue_domain and tier_1 is None:
            tier_1 = SearchResult(url=url, title=title, domain=domain, tier=1)
        elif domain in allowlist and tier_2 is None:
            tier_2 = SearchResult(url=url, title=title, domain=domain, tier=2)

        if tier_1 is not None:
            break  # Tier 1 wins outright; no need to keep looking.

    return tier_1 or tier_2


import json
import os
import re

from anthropic import Anthropic


# How many web searches Claude is allowed to issue per call. 3 is enough for
# primary-query plus a couple of fallback queries with distinctive strings.
WEB_SEARCH_MAX_USES = 3


def search_for_event(
    seed: dict,
    *,
    allowlist: list[str],
    venue_domain: str | None,
    model: str | None = None,
) -> SearchResult | None:
    """Use Claude with the server-side web_search tool to find an authoritative
    URL for the event described in `seed`. Then rank against the allowlist.

    seed: dict with keys event_title, venue_name, optional date_hint,
          optional distinctive_strings (list of str).
    allowlist: Tier-2 domain list.
    venue_domain: Tier-1 anchor (the venue's own domain), or None.
    model: override for the model id; defaults to Haiku 4.5.

    Returns: best-ranked SearchResult, or None if nothing clears the bar.
    """
    client = Anthropic()
    model = model or os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")

    # Build a directive prompt. We ask Claude to use web_search up to N times
    # and to return a JSON list of {url, title} candidates. Final ranking is
    # done in Python so the allowlist is the source of truth.
    distinctive = seed.get("distinctive_strings") or []
    user_prompt = (
        "Find authoritative web pages describing this event so it can be "
        "added to an Andersonville (Chicago) event aggregator.\n\n"
        f"Event title: {seed.get('event_title') or '(unknown)'}\n"
        f"Venue: {seed.get('venue_name') or '(unknown)'}\n"
        f"Date hint: {seed.get('date_hint') or '(unknown)'}\n"
        f"Distinctive strings from the flyer: {', '.join(distinctive) if distinctive else '(none)'}\n\n"
        "Use the web_search tool to find candidate URLs. Try the primary query "
        "(event title + venue + 'Andersonville Chicago') first; if that yields "
        "nothing useful, try queries built from the distinctive strings.\n\n"
        "Return ONLY a JSON array of up to 10 candidates, ordered best-first:\n"
        '  [{"url": "https://...", "title": "..."}, ...]\n\n'
        "No commentary, no markdown fences. If you find nothing, return []."
    )

    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        temperature=0.0,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": WEB_SEARCH_MAX_USES,
        }],
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Concatenate text blocks from the final response.
    text_out = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    candidates = _extract_json_array(text_out)
    return rank_search_results(candidates, allowlist=allowlist, venue_domain=venue_domain)


def _extract_json_array(text: str) -> list[dict]:
    """Tolerant JSON-array extraction (mirrors src/extractor.py pattern)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    if start == -1:
        return []
    depth = 0
    in_str = False
    escape_next = False
    end = -1
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_str:
            escape_next = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        return []
    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
