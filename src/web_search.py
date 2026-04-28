"""Web-search-based authoritative-source discovery for flyer ingestion.

Two responsibilities:
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
