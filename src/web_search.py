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
