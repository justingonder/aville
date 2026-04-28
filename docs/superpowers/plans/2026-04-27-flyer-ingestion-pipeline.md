# Flyer-Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone CLI (`scripts/ingest_flyer.py`) that ingests phone-camera photos of paper flyers into the existing `events` table by treating each photo as a SEED for a web search, then extracting from the discovered authoritative web source.

**Architecture:** A new orchestration script wires together five new helpers (seed extractor, allowlist loader, web-search ranker, web-search caller, business resolver) and reuses the existing extractor, fetcher, DB layer, business-metadata extractor, and geocoder. Each photo flows through a 7-step pipeline (Section A of the spec): seed → resolve business → DB dedup gate → web search → multimodal full extraction → auto-add business if new → upsert. A sidecar JSON log per run tracks outcomes and supports resume-after-interrupt.

**Tech Stack:** Python 3 stdlib (argparse, json, sqlite3, pathlib, difflib, subprocess), `anthropic` SDK (Haiku 4.5 multimodal calls + server-side `web_search_20250305` tool), existing `pyyaml`, `pillow` (already in requirements.txt). No new third-party dependencies.

**Testing convention:** This project has no pytest suite (per CLAUDE.md: "No frameworks. Procedural Python, stdlib-preferred."). Each pure-Python helper gets a dedicated smoke-test script at `scripts/test_<helper>.py` that uses plain `assert` statements and prints PASS/FAIL — matching the existing `scripts/test_extraction.py` pattern. Tests are run as `python3 scripts/test_<helper>.py` and exit non-zero on failure. Tests that need real Claude or web calls are documented as such; the implementer skips them on bare-bones runs and runs them at end-of-task verification.

---

## Spec reference

Full design lives at `docs/superpowers/specs/2026-04-24-flyer-ingestion-pipeline-design.md`. Decisions 1–10 there are **non-negotiable** — do not re-debate during implementation.

## File layout (locked by Decision 9)

**New files:**
- `scripts/ingest_flyer.py` — CLI orchestration
- `scripts/test_ingest_helpers.py` — bundled smoke tests for the in-script helpers
- `scripts/test_web_search.py` — smoke tests for `src/web_search.py`
- `scripts/test_seed_extraction.py` — smoke test for the seed extractor (real Claude call)
- `src/web_search.py` — allowlist loader + ranker + Claude-with-web-search caller
- `config/web_search_allowlist.yaml` — Tier 2 domain allowlist

**Modified files:**
- `src/prompts.py` — add `SEED_EXTRACTION_PROMPT` and `CROSS_VERIFY_NOTE`
- `src/extractor.py` — add `extract_flyer_seeds()`; modify `extract_events()` to optionally accept `cross_verify_image: bytes | None`

**Reused unchanged:**
- `src/db.py` — `connect()`, `upsert_event()`, `upsert_business()`, `build_match_key()`
- `src/fetcher.py` — `fetch_html()`, `fetch_html_playwright()`, `playwright_session()`
- `src/images.py` — `discover_and_download()`, `page_text()`, `PageImage`
- `src/pipeline.py` — `load_businesses()`, `load_tag_vocab()`, `PUBLIC_DIR`
- `scripts/extract_business_metadata.py` — invoked as subprocess
- `scripts/geocode_businesses.py` — invoked as subprocess

---

## Task 1: Authoritative-source allowlist YAML + loader

**Files:**
- Create: `config/web_search_allowlist.yaml`
- Create: `src/web_search.py`
- Create: `scripts/test_web_search.py`

- [ ] **Step 1: Create the allowlist YAML**

Create `config/web_search_allowlist.yaml` exactly as specified in the spec:

```yaml
# Authoritative-source allowlist for flyer-ingestion web search.
# Tier 1 is computed dynamically (the venue's own domain).
# Tier 2 is the curated list below — Chicago aggregators / neighborhood news /
# tourism boards we trust to publish accurate event information.
# Edit freely; the list is meant to evolve based on what actually returns
# useful results in practice.

tier_2:
  - eventbrite.com
  - do312.com
  - timeout.com           # Time Out Chicago lives under timeout.com/chicago
  - chicagoreader.com
  - andersonville.org     # Andersonville Chamber of Commerce
  - blockclubchicago.org
  - patch.com             # Andersonville Patch lives under patch.com/illinois/rogers-park-edgewater
  - choosechicago.com
```

- [ ] **Step 2: Create `src/web_search.py` with the loader (no Claude logic yet)**

Create `src/web_search.py`:

```python
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
```

- [ ] **Step 3: Create the smoke test**

Create `scripts/test_web_search.py`:

```python
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
```

- [ ] **Step 4: Run the smoke test, confirm PASS**

Run: `python3 scripts/test_web_search.py`
Expected output:
```
  load_allowlist: OK (9 domains)
  domain_of: OK
PASS
```

- [ ] **Step 5: Commit**

```bash
git add config/web_search_allowlist.yaml src/web_search.py scripts/test_web_search.py
git commit -m "feat(flyer-ingestion): add web-search allowlist YAML + loader"
```

---

## Task 2: Web-search result ranker

**Files:**
- Modify: `src/web_search.py`
- Modify: `scripts/test_web_search.py`

- [ ] **Step 1: Add the failing test first**

Append to `scripts/test_web_search.py` (before the `if __name__` block):

```python
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
```

Also add the new tests to the `if __name__` block:

```python
if __name__ == "__main__":
    test_allowlist_loads()
    test_domain_of()
    test_ranker_prefers_tier_1()
    test_ranker_falls_back_to_tier_2()
    test_ranker_rejects_unknown_domains()
    test_ranker_handles_empty_input()
    print("PASS")
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `python3 scripts/test_web_search.py`
Expected: ImportError on `rank_search_results` — function doesn't exist yet.

- [ ] **Step 3: Implement the ranker**

Append to `src/web_search.py`:

```python
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
```

- [ ] **Step 4: Run the smoke test, confirm PASS**

Run: `python3 scripts/test_web_search.py`
Expected: all 6 test functions print OK, final line `PASS`.

- [ ] **Step 5: Commit**

```bash
git add src/web_search.py scripts/test_web_search.py
git commit -m "feat(flyer-ingestion): add web-search result ranker (Tier 1/2)"
```

---

## Task 3: Web-search caller (Claude with web_search tool)

**Files:**
- Modify: `src/web_search.py`
- Modify: `scripts/test_web_search.py`

This task makes a real Claude API call. The smoke test runs only when `ANTHROPIC_API_KEY` is set in env; otherwise it skips with a clear message.

- [ ] **Step 1: Add the test for `search_for_event`**

Append to `scripts/test_web_search.py` (before the `if __name__` block):

```python
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
```

Add to `if __name__` block:

```python
    test_search_for_event_live()
```

- [ ] **Step 2: Run the test, confirm it fails (ImportError)**

Run: `python3 scripts/test_web_search.py`
Expected: ImportError on `search_for_event`.

- [ ] **Step 3: Implement `search_for_event`**

Append to `src/web_search.py`:

```python
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
```

- [ ] **Step 4: Run the smoke test**

Run: `python3 scripts/test_web_search.py`
Expected: previous tests still pass; `search_for_event` either prints `OK ({tier=...}, ...)` if Anthropic key is set, or `SKIPPED` if not. A `NO RESULT` outcome is acceptable for the v1 ship — investigate manually if it happens.

If `ANTHROPIC_API_KEY` is set and the live test errored (not just `NO RESULT`), capture the traceback for debugging before proceeding.

- [ ] **Step 5: Commit**

```bash
git add src/web_search.py scripts/test_web_search.py
git commit -m "feat(flyer-ingestion): add Claude-driven web search for authoritative URLs"
```

---

## Task 4: Seed-extraction prompt + `extract_flyer_seeds()`

**Files:**
- Modify: `src/prompts.py`
- Modify: `src/extractor.py`
- Create: `scripts/test_seed_extraction.py`

- [ ] **Step 1: Add the prompt**

Append to `src/prompts.py`:

```python
SEED_EXTRACTION_PROMPT = dedent("""
    You are looking at a phone-camera photo of a paper flyer or window sign
    in Andersonville, a Chicago neighborhood. The photo is NOT clean — it
    likely contains window reflections, surrounding storefront branding,
    nail-salon decals, decorative shadows, perspective skew, and other noise.

    The FLYER is the authoritative signal. Ignore everything else in the
    photo. Extract a small set of seeds we can use to web-search for an
    authoritative source for this event.

    Return ONE JSON object with exactly these fields:
      - event_title: string. The event name as it appears on the flyer.
        Null if you can't read it.
      - venue_name: string. The venue / business hosting the event, as it
        appears on the flyer (NOT the surrounding storefront, which may be
        a different business). Null if the flyer doesn't name a venue.
      - date_hint: string. The date as it appears on the flyer
        (e.g., "May 2", "Mother's Day", "Every Tuesday"). Null if absent.
      - time_hint: string. The time as it appears (e.g., "12pm-6pm").
        Null if absent.
      - kind_guess: "dated" or "recurring" or null. "Dated" for a one-off
        event with a specific date; "recurring" for "every Tuesday" /
        "monthly" / etc.
      - distinctive_strings: array of 1-4 short, distinctive strings from
        the flyer text that would make good fallback search queries
        (e.g., a tagline, sponsor name, sub-event name). Empty array if
        nothing stands out.
      - flyer_image_is_clean: boolean. True if the photo is dominated by
        the flyer (could plausibly be cropped and used as an image).
        False if the photo has substantial non-flyer content (storefront
        glass, decals, reflections, etc.). When in doubt, false.
      - seed_confidence: "high" | "medium" | "low". Your confidence that
        the seeds are correct enough to drive a useful web search.

    Return ONLY the JSON object. No preamble, no markdown fences, no
    commentary.
""").strip()


CROSS_VERIFY_NOTE = dedent("""
    Additionally, you have been given a phone-camera photo of a paper
    flyer for this event (labeled '--- CROSS-VERIFY FLYER ---' below).
    The flyer is a CORROBORATING SIGNAL only — the web source above is
    authoritative. Use the flyer to cross-check ambiguous fields (date,
    time, performers, price). When the web source and the flyer
    disagree, prefer the web source. Do NOT pick the flyer photo as
    `source_image_index`; it is not in the indexed images list.
""").strip()
```

- [ ] **Step 2: Add `extract_flyer_seeds()` to `src/extractor.py`**

Add at the bottom of `src/extractor.py` (after `extract_events`):

```python
def extract_flyer_seeds(
    image_bytes: bytes,
    *,
    media_type: str = "image/jpeg",
    model: str | None = None,
) -> dict:
    """Cheap multimodal Claude call: read seeds off a phone-camera flyer photo.

    Returns a dict with keys: event_title, venue_name, date_hint, time_hint,
    kind_guess, distinctive_strings, flyer_image_is_clean, seed_confidence.
    """
    import base64

    from .prompts import SEED_EXTRACTION_PROMPT

    client = Anthropic()
    model = model or os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")

    b64 = base64.b64encode(image_bytes).decode("ascii")

    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SEED_EXTRACTION_PROMPT,
        temperature=0.0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": "Return the JSON object now."},
            ],
        }],
    )
    text_out = "".join(b.text for b in resp.content if b.type == "text")
    return _extract_json_object(text_out)


def _extract_json_object(text: str) -> dict:
    """Tolerant JSON-object extraction. Mirrors _extract_json_array shape."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in Claude response: {text[:200]}")
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
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise ValueError(f"unbalanced braces in Claude response: {text[:200]}")
    return json.loads(text[start:end])
```

- [ ] **Step 3: Create the smoke-test script**

Create `scripts/test_seed_extraction.py`:

```python
#!/usr/bin/env python3
"""Smoke test for src/extractor.py::extract_flyer_seeds.

Runs against a real flyer photo. Requires ANTHROPIC_API_KEY.

Usage:
  python3 scripts/test_seed_extraction.py [path/to/photo.jpg]

Default photo: /Users/jgonder/Downloads/20260422_202538.jpg (Guesthouse flyer).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.extractor import extract_flyer_seeds  # noqa: E402

DEFAULT_PHOTO = Path("/Users/jgonder/Downloads/20260422_202538.jpg")


def main() -> int:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("SKIPPED: no ANTHROPIC_API_KEY in env")
        return 0

    photo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PHOTO
    if not photo_path.exists():
        print(f"FAIL: photo not found at {photo_path}")
        return 1

    media_type = "image/jpeg" if photo_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    seed = extract_flyer_seeds(photo_path.read_bytes(), media_type=media_type)
    print(json.dumps(seed, indent=2))

    # Structural assertions — content varies but shape is fixed.
    expected_keys = {
        "event_title", "venue_name", "date_hint", "time_hint",
        "kind_guess", "distinctive_strings", "flyer_image_is_clean", "seed_confidence",
    }
    missing = expected_keys - set(seed.keys())
    assert not missing, f"missing keys: {missing}"
    assert seed["seed_confidence"] in ("high", "medium", "low"), \
        f"bad seed_confidence: {seed['seed_confidence']}"
    assert isinstance(seed["distinctive_strings"], list), "distinctive_strings must be a list"
    assert isinstance(seed["flyer_image_is_clean"], bool), "flyer_image_is_clean must be bool"

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the smoke test against the Guesthouse photo**

Run: `python3 scripts/test_seed_extraction.py`
Expected: prints a JSON object with all 8 keys; final line `PASS`. The Guesthouse flyer should yield `event_title: "Wander Home Holiday Market"` (or similar) and `venue_name: "The Guesthouse Hotel"` (or similar) — the exact strings vary slightly run-to-run since Claude reads the image, but the shape is fixed.

If the photo isn't at the default path, pass it explicitly: `python3 scripts/test_seed_extraction.py /path/to/some-flyer.jpg`.

- [ ] **Step 5: Commit**

```bash
git add src/prompts.py src/extractor.py scripts/test_seed_extraction.py
git commit -m "feat(flyer-ingestion): add seed-extraction prompt + extract_flyer_seeds()"
```

---

## Task 5: Cross-verify image extension to `extract_events()`

**Files:**
- Modify: `src/extractor.py`
- Create: `scripts/test_extract_events_compat.py`

The change must be backward-compatible: existing pipeline callers don't pass `cross_verify_image`; their behavior must be identical. A regression test confirms this.

- [ ] **Step 1: Write the regression test**

Create `scripts/test_extract_events_compat.py`:

```python
#!/usr/bin/env python3
"""Regression test: extract_events with cross_verify_image=None must be
identical to the prior signature. Inspects the function signature only;
does not call Claude.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extractor import extract_events


def test_signature_keeps_existing_kwargs():
    sig = inspect.signature(extract_events)
    params = sig.parameters
    # Required kwargs from the prior signature must still exist.
    for name in ("business", "page", "page_text", "images", "tag_vocab"):
        assert name in params, f"missing kwarg: {name}"
        assert params[name].kind == inspect.Parameter.KEYWORD_ONLY, \
            f"{name} must be keyword-only"
    # The new kwarg must default to None so existing callers are unaffected.
    assert "cross_verify_image" in params, "missing cross_verify_image kwarg"
    cvi = params["cross_verify_image"]
    assert cvi.default is None, f"cross_verify_image default must be None, got {cvi.default}"
    assert cvi.kind == inspect.Parameter.KEYWORD_ONLY, "cross_verify_image must be keyword-only"
    print("  signature backward compat: OK")


if __name__ == "__main__":
    test_signature_keeps_existing_kwargs()
    print("PASS")
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `python3 scripts/test_extract_events_compat.py`
Expected: `AssertionError: missing cross_verify_image kwarg`.

- [ ] **Step 3: Add the new kwarg + cross-verify logic**

Modify `src/extractor.py`:

In the `extract_events` signature, add the new keyword-only argument:

```python
def extract_events(
    *,
    business: dict,
    page: dict,
    page_text: str,
    images: list[PageImage],
    tag_vocab: list[str],
    model: str | None = None,
    cross_verify_image: bytes | None = None,
    cross_verify_media_type: str = "image/jpeg",
) -> list[dict]:
```

In the function body, just before `resp = client.messages.create(...)` (around line 118), insert:

```python
    # Optional cross-verification image (Step 5 of the flyer-ingestion pipeline).
    # The flyer is a corroborating signal; the web source remains authoritative.
    if cross_verify_image is not None:
        import base64
        from .prompts import CROSS_VERIFY_NOTE
        content.append({"type": "text", "text": CROSS_VERIFY_NOTE})
        content.append({"type": "text", "text": "--- CROSS-VERIFY FLYER ---"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": cross_verify_media_type,
                "data": base64.b64encode(cross_verify_image).decode("ascii"),
            },
        })
```

- [ ] **Step 4: Run the regression test, confirm PASS**

Run: `python3 scripts/test_extract_events_compat.py`
Expected: `signature backward compat: OK` then `PASS`.

- [ ] **Step 5: Run the existing pipeline smoke test for extra safety**

Run: `python3 scripts/test_extraction.py vincent https://vincentchicago.com/`
Expected: same JSON output structure as before this task. (Look for the `events` list; it should contain 2-3 entries for Vincent: Happy Hour, Half Off Mussels, etc.)

If the call fails with a non-cross-verify-related error (network, etc.), retry; the goal is just to confirm we didn't break the prior code path.

- [ ] **Step 6: Commit**

```bash
git add src/extractor.py scripts/test_extract_events_compat.py
git commit -m "feat(flyer-ingestion): extend extract_events() with optional cross_verify_image"
```

---

## Task 6: In-script helpers — business resolver

**Files:**
- Create: `scripts/ingest_flyer.py` (skeleton)
- Create: `scripts/test_ingest_helpers.py`

This task creates the script file with just the resolver helper and its constants. Subsequent tasks will append more helpers to the same file.

- [ ] **Step 1: Write the failing test**

Create `scripts/test_ingest_helpers.py`:

```python
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
    result = resolve_business("The Guesthouse Hotel Chicago", businesses)
    assert isinstance(result, tuple), f"expected confident-match tuple, got {result!r}"
    slug, score = result
    assert slug == "guesthouse-hotel", f"wrong slug: {slug}"
    assert score >= 0.85, f"score {score} below confident threshold"
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
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: ImportError on `scripts.ingest_flyer` — script doesn't exist yet.

- [ ] **Step 3: Create the script skeleton + resolver**

Create `scripts/ingest_flyer.py`:

```python
#!/usr/bin/env python3
"""Flyer-ingestion CLI.

Treats phone-camera photos of paper flyers as SEEDS for a web search,
extracts events from the discovered authoritative web source, and writes
to the same events table the website-scraping pipeline uses.

See docs/superpowers/specs/2026-04-24-flyer-ingestion-pipeline-design.md
for the full design and decisions.

Usage:
    python3 scripts/ingest_flyer.py path/to/photo.jpg
    python3 scripts/ingest_flyer.py --dir walks/2026-04-27/
    python3 scripts/ingest_flyer.py path/to/photo.jpg --source-url https://...
    python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --seed-only
    python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --dry-run
    python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --force
"""
from __future__ import annotations

import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Match thresholds — top-of-file constants for easy retuning.
BUSINESS_CONFIDENT_MATCH = 0.85
BUSINESS_AMBIGUOUS_MIN = 0.60
TITLE_DEDUP_THRESHOLD = 0.70
DATED_EVENT_DAY_WINDOW = 2     # ±N days for dated-event dedup
RECURRING_TIME_WINDOW_MIN = 30  # ±N minutes for recurring-event dedup


def _name_similarity(a: str, b: str) -> float:
    """Case-insensitive sequence similarity in [0, 1]."""
    return SequenceMatcher(None, (a or "").lower().strip(), (b or "").lower().strip()).ratio()


def resolve_business(
    venue_name: str,
    businesses: Iterable[dict],
) -> tuple[str, float] | list[tuple[str, float]] | None:
    """Match the seed-extracted venue_name against businesses.yaml entries.

    Returns:
      (slug, score)         — confident match (best score >= BUSINESS_CONFIDENT_MATCH).
      [(slug, score), ...]  — ambiguous (best in [BUSINESS_AMBIGUOUS_MIN, BUSINESS_CONFIDENT_MATCH));
                              top 3 candidates above BUSINESS_AMBIGUOUS_MIN, best-first.
      None                  — no candidate above BUSINESS_AMBIGUOUS_MIN.
    """
    if not venue_name:
        return None

    scored = [
        (b["slug"], _name_similarity(venue_name, b.get("name") or ""))
        for b in businesses
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    if not scored:
        return None

    best_slug, best_score = scored[0]
    if best_score >= BUSINESS_CONFIDENT_MATCH:
        return (best_slug, best_score)
    if best_score >= BUSINESS_AMBIGUOUS_MIN:
        return [pair for pair in scored[:3] if pair[1] >= BUSINESS_AMBIGUOUS_MIN]
    return None
```

- [ ] **Step 4: Run the test, confirm PASS**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: 3 OK lines, then `PASS`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_flyer.py scripts/test_ingest_helpers.py
git commit -m "feat(flyer-ingestion): add ingest_flyer.py skeleton + resolve_business()"
```

---

## Task 7: DB-dedup helper (`find_dedup_match`)

**Files:**
- Modify: `scripts/ingest_flyer.py`
- Modify: `scripts/test_ingest_helpers.py`

- [ ] **Step 1: Add the failing tests**

Append to `scripts/test_ingest_helpers.py` (before `if __name__`):

```python
def test_dedup_match_dated_event():
    """Dated-event dedup: same business + ±2 days + title sim >= 0.7."""
    import sqlite3
    from scripts.ingest_flyer import find_dedup_match

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, business_id INTEGER, kind TEXT, title TEXT,
            recurrence_pattern TEXT, start_time TEXT, end_time TEXT,
            start_datetime TEXT, end_datetime TEXT, status TEXT
        );
        INSERT INTO events VALUES (1, 5, 'dated', 'Wander Home Holiday Market',
            NULL, NULL, NULL, '2026-05-02T12:00:00-05:00', NULL, 'active');
    """)

    seed = {
        "kind_guess": "dated",
        "event_title": "Wander Home Holiday Market",
        "date_hint_iso": "2026-05-03",  # 1 day off — within ±2-day window
    }
    match = find_dedup_match(conn, business_id=5, seed=seed)
    assert match is not None and match["id"] == 1, f"expected event 1, got {match}"
    print(f"  dedup dated within window: OK")

    # Outside the window
    seed["date_hint_iso"] = "2026-05-10"
    match = find_dedup_match(conn, business_id=5, seed=seed)
    assert match is None, f"expected None outside window, got {match}"
    print(f"  dedup dated outside window: OK")


def test_dedup_match_recurring_event():
    """Recurring-event dedup: same business + matching pattern + ±30 min start_time."""
    import sqlite3
    from scripts.ingest_flyer import find_dedup_match

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, business_id INTEGER, kind TEXT, title TEXT,
            recurrence_pattern TEXT, start_time TEXT, end_time TEXT,
            start_datetime TEXT, end_datetime TEXT, status TEXT
        );
        INSERT INTO events VALUES (1, 5, 'recurring', 'Drag Brunch',
            'weekly:saturday', '12:00', '14:00', NULL, NULL, 'active');
    """)

    seed = {
        "kind_guess": "recurring",
        "event_title": "Drag Brunch",
        "recurrence_pattern": "weekly:saturday",
        "start_time": "12:15",   # within ±30 min
    }
    match = find_dedup_match(conn, business_id=5, seed=seed)
    assert match is not None and match["id"] == 1, f"expected event 1, got {match}"
    print(f"  dedup recurring within window: OK")

    seed["start_time"] = "15:00"  # outside window
    match = find_dedup_match(conn, business_id=5, seed=seed)
    assert match is None, f"expected None for time-far recurring, got {match}"
    print(f"  dedup recurring outside window: OK")


def test_dedup_no_match_different_business():
    import sqlite3
    from scripts.ingest_flyer import find_dedup_match

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, business_id INTEGER, kind TEXT, title TEXT,
            recurrence_pattern TEXT, start_time TEXT, end_time TEXT,
            start_datetime TEXT, end_datetime TEXT, status TEXT
        );
        INSERT INTO events VALUES (1, 5, 'dated', 'Wander Home Holiday Market',
            NULL, NULL, NULL, '2026-05-02T12:00:00-05:00', NULL, 'active');
    """)

    seed = {"kind_guess": "dated", "event_title": "Wander Home Holiday Market",
            "date_hint_iso": "2026-05-02"}
    match = find_dedup_match(conn, business_id=99, seed=seed)
    assert match is None, "different business should not match"
    print(f"  dedup wrong business: OK")
```

Add to `if __name__` block:

```python
    test_dedup_match_dated_event()
    test_dedup_match_recurring_event()
    test_dedup_no_match_different_business()
```

- [ ] **Step 2: Run the test, confirm it fails**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: ImportError on `find_dedup_match`.

- [ ] **Step 3: Implement the helper**

Append to `scripts/ingest_flyer.py`:

```python
import sqlite3
from datetime import date, datetime, timedelta


def _parse_hhmm_to_minutes(hhmm: str | None) -> int | None:
    """'12:30' -> 750. None or unparseable -> None."""
    if not hhmm:
        return None
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _parse_iso_date(iso: str | None) -> date | None:
    """'2026-05-02' or '2026-05-02T...' -> date. None / unparseable -> None."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso[:10]).date()
    except ValueError:
        return None


def find_dedup_match(
    conn: sqlite3.Connection,
    *,
    business_id: int,
    seed: dict,
) -> sqlite3.Row | None:
    """Query active+stale events at this business; return the first match or None.

    Match rule (per spec Section A Step 3):
      - Dated:    same business + date within ±DATED_EVENT_DAY_WINDOW days
                  + fuzzy title similarity >= TITLE_DEDUP_THRESHOLD.
      - Recurring: same business + matching recurrence_pattern
                   + start_time within ±RECURRING_TIME_WINDOW_MIN minutes
                     (or both null) + title sim >= TITLE_DEDUP_THRESHOLD.
    """
    rows = conn.execute(
        """SELECT * FROM events
           WHERE business_id = ? AND status IN ('active', 'stale')""",
        (business_id,),
    ).fetchall()

    seed_title = seed.get("event_title") or ""
    seed_kind = seed.get("kind_guess")

    if seed_kind == "dated":
        seed_date = _parse_iso_date(seed.get("date_hint_iso"))
        for row in rows:
            if row["kind"] != "dated":
                continue
            if _name_similarity(seed_title, row["title"]) < TITLE_DEDUP_THRESHOLD:
                continue
            row_date = _parse_iso_date(row["start_datetime"])
            if seed_date is None or row_date is None:
                # Without dates we can't safely call this a dup — skip.
                continue
            if abs((row_date - seed_date).days) <= DATED_EVENT_DAY_WINDOW:
                return row
        return None

    if seed_kind == "recurring":
        seed_pattern = seed.get("recurrence_pattern") or ""
        seed_start = _parse_hhmm_to_minutes(seed.get("start_time"))
        for row in rows:
            if row["kind"] != "recurring":
                continue
            if _name_similarity(seed_title, row["title"]) < TITLE_DEDUP_THRESHOLD:
                continue
            if (row["recurrence_pattern"] or "") != seed_pattern:
                continue
            row_start = _parse_hhmm_to_minutes(row["start_time"])
            if seed_start is None and row_start is None:
                return row
            if seed_start is None or row_start is None:
                continue
            if abs(seed_start - row_start) <= RECURRING_TIME_WINDOW_MIN:
                return row
        return None

    # kind_guess unknown: don't risk a false-positive dup.
    return None
```

- [ ] **Step 4: Run the test, confirm PASS**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: all OK lines including the 4 new dedup tests, then `PASS`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_flyer.py scripts/test_ingest_helpers.py
git commit -m "feat(flyer-ingestion): add find_dedup_match() with date and time windows"
```

---

## Task 8: Sidecar log writer

**Files:**
- Modify: `scripts/ingest_flyer.py`
- Modify: `scripts/test_ingest_helpers.py`

- [ ] **Step 1: Add the failing tests**

Append to `scripts/test_ingest_helpers.py`:

```python
def test_sidecar_log_creates_and_appends():
    import json
    import tempfile
    from scripts.ingest_flyer import SidecarLog

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / ".ingest_log.json"
        log = SidecarLog(log_path)
        log.append({"photo": "a.jpg", "outcome": "ingested", "event_id": 1})
        log.append({"photo": "b.jpg", "outcome": "skipped:no-web-trace"})
        # Re-load from disk
        data = json.loads(log_path.read_text())
        assert data["version"] == 1
        assert len(data["entries"]) == 2
        assert data["entries"][0]["photo"] == "a.jpg"
        assert data["entries"][1]["outcome"] == "skipped:no-web-trace"
        print(f"  sidecar log create+append: OK")


def test_sidecar_log_processed_photos_set():
    import tempfile
    from scripts.ingest_flyer import SidecarLog

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / ".ingest_log.json"
        log = SidecarLog(log_path)
        log.append({"photo": "a.jpg", "outcome": "ingested"})
        log.append({"photo": "b.jpg", "outcome": "skipped:no-web-trace"})
        # Reload as a fresh instance (simulates a re-run)
        log2 = SidecarLog(log_path)
        processed = log2.processed_photos()
        assert processed == {"a.jpg", "b.jpg"}, f"got {processed}"
        print(f"  sidecar log processed set: OK")


def test_sidecar_log_atomic_write():
    """Append-via-tmp-rename leaves no orphan .tmp files on success."""
    import tempfile
    from scripts.ingest_flyer import SidecarLog

    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / ".ingest_log.json"
        log = SidecarLog(log_path)
        log.append({"photo": "a.jpg", "outcome": "ingested"})
        tmp_path = log_path.with_suffix(log_path.suffix + ".tmp")
        assert not tmp_path.exists(), "tmp file should not survive a successful write"
        print(f"  sidecar log atomic: OK")
```

Add to `if __name__`:

```python
    test_sidecar_log_creates_and_appends()
    test_sidecar_log_processed_photos_set()
    test_sidecar_log_atomic_write()
```

- [ ] **Step 2: Run, confirm ImportError**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: ImportError on `SidecarLog`.

- [ ] **Step 3: Implement `SidecarLog`**

Append to `scripts/ingest_flyer.py`:

```python
import json
import os
from datetime import timezone


def _now_iso_local() -> str:
    """Local-tz ISO timestamp, e.g. '2026-04-27T15:30:12-05:00'."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class SidecarLog:
    """Append-only JSON log for an ingest_flyer run.

    File layout:
      {
        "version": 1,
        "started_at": "<iso>",
        "entries": [<entry>, ...]
      }

    Each call to .append(entry) does an atomic read-mutate-write-rename so a
    Ctrl-C during write can't leave a partial file.
    """

    VERSION = 1

    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self._data = json.loads(path.read_text())
            if not isinstance(self._data.get("entries"), list):
                raise ValueError(f"{path}: malformed sidecar log")
        else:
            self._data = {
                "version": self.VERSION,
                "started_at": _now_iso_local(),
                "entries": [],
            }
            self._flush()

    def append(self, entry: dict) -> None:
        self._data["entries"].append(entry)
        self._flush()

    def processed_photos(self) -> set[str]:
        """Set of photo basenames already recorded in this log."""
        return {e["photo"] for e in self._data["entries"] if "photo" in e}

    def entries(self) -> list[dict]:
        return list(self._data["entries"])

    def _flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self.path)  # atomic rename on POSIX
```

- [ ] **Step 4: Run the test, confirm PASS**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: all prior tests + 3 new sidecar tests OK, then `PASS`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_flyer.py scripts/test_ingest_helpers.py
git commit -m "feat(flyer-ingestion): add SidecarLog with atomic append-via-rename"
```

---

## Task 9: Field-level enrich diff helper

**Files:**
- Modify: `scripts/ingest_flyer.py`
- Modify: `scripts/test_ingest_helpers.py`

- [ ] **Step 1: Add the failing tests**

Append to `scripts/test_ingest_helpers.py`:

```python
def test_compute_enrichment_fills_gaps_only():
    from scripts.ingest_flyer import compute_enrichment

    existing = {
        "id": 1,
        "title": "Drag Brunch",
        "start_time": "12:00",
        "end_time": None,
        "price_info": None,
        "performers": "[]",   # JSON string in DB; helper handles parsing
        "description": "Some existing description.",
    }
    extracted = {
        "title": "Drag Brunch (Pride Edition)",   # would change but should NOT
        "start_time": "12:00",                    # same — no-op
        "end_time": "14:00",                      # fills gap
        "price_info": "$25 cover",                # fills gap
        "performers": [{"name": "Aunty Kim", "role": "host"}],   # fills empty list
        "description": "New description.",        # would change but should NOT
    }
    diff = compute_enrichment(existing, extracted)
    assert "title" not in diff, "title was non-null; must not enrich"
    assert "description" not in diff, "description was non-null; must not enrich"
    assert "start_time" not in diff, "start_time was already 12:00; no diff"
    assert diff.get("end_time") == "14:00"
    assert diff.get("price_info") == "$25 cover"
    # Performers: empty list / "[]" should be treated as gap-fillable.
    assert diff.get("performers") == [{"name": "Aunty Kim", "role": "host"}]
    print(f"  compute_enrichment fills only gaps: OK")


def test_compute_enrichment_no_gaps_returns_empty():
    from scripts.ingest_flyer import compute_enrichment
    existing = {"id": 1, "title": "X", "start_time": "12:00", "end_time": "14:00",
                "price_info": "$10", "performers": '[{"name":"A","role":"host"}]',
                "description": "Y"}
    extracted = {"title": "X", "start_time": "12:00", "end_time": "14:00",
                 "price_info": "$15", "performers": [], "description": "Z"}
    diff = compute_enrichment(existing, extracted)
    assert diff == {}, f"no gaps to fill, got {diff}"
    print(f"  compute_enrichment no gaps: OK")
```

Add to `if __name__`:

```python
    test_compute_enrichment_fills_gaps_only()
    test_compute_enrichment_no_gaps_returns_empty()
```

- [ ] **Step 2: Run, confirm ImportError**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: ImportError on `compute_enrichment`.

- [ ] **Step 3: Implement the helper**

Append to `scripts/ingest_flyer.py`:

```python
ENRICHABLE_FIELDS = (
    "description",
    "start_time", "end_time",
    "start_datetime", "end_datetime",
    "price_info",
    "performers",
    "image_source_url", "image_local_path", "external_link",
    "recurrence_pattern",
)


def _is_empty(value) -> bool:
    """Treat None, empty string, empty list, and '[]' (DB JSON-empty) as empty."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in ("", "[]")
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def compute_enrichment(existing: dict, extracted: dict) -> dict:
    """Return only the fields where existing is empty AND extracted is non-empty.

    Never overwrite a non-empty existing value. Operates on the field set
    in ENRICHABLE_FIELDS.
    """
    diff: dict = {}
    for field in ENRICHABLE_FIELDS:
        if not _is_empty(existing.get(field)):
            continue
        new_val = extracted.get(field)
        if _is_empty(new_val):
            continue
        diff[field] = new_val
    return diff
```

- [ ] **Step 4: Run, confirm PASS**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: all prior + 2 new enrichment tests OK, then `PASS`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_flyer.py scripts/test_ingest_helpers.py
git commit -m "feat(flyer-ingestion): add compute_enrichment() (gap-fill diff only)"
```

---

## Task 10: Auto-add new business helper

**Files:**
- Modify: `scripts/ingest_flyer.py`
- Modify: `scripts/test_ingest_helpers.py`

This helper appends to `config/businesses.yaml` and runs the metadata + geocoder scripts as subprocesses. The unit test exercises the slug + YAML-formatting logic without actually mutating disk; an integration smoke happens in Task 13.

- [ ] **Step 1: Add the failing tests**

Append to `scripts/test_ingest_helpers.py`:

```python
def test_slug_from_name():
    from scripts.ingest_flyer import slug_from_name
    assert slug_from_name("The Guesthouse Hotel") == "guesthouse-hotel"
    assert slug_from_name("Mr. Beef & Pizza!") == "mr-beef-and-pizza"
    assert slug_from_name("  Hopleaf  Bar  ") == "hopleaf-bar"
    assert slug_from_name("Café 53") == "cafe-53"
    print(f"  slug_from_name: OK")


def test_format_business_yaml_block():
    from scripts.ingest_flyer import format_business_yaml_block
    block = format_business_yaml_block(
        slug="guesthouse-hotel",
        name="The Guesthouse Hotel",
        website="https://guesthousehotel.com",
        address="4872 N Clark St, Chicago, IL 60640",
    )
    # Required structural pieces (don't lock to exact whitespace; YAML parser will validate later).
    assert "  - slug: guesthouse-hotel" in block
    assert "name: The Guesthouse Hotel" in block
    assert "website: https://guesthousehotel.com" in block
    assert "4872 N Clark St" in block
    print(f"  format_business_yaml_block: OK")


def test_format_business_yaml_block_null_address():
    from scripts.ingest_flyer import format_business_yaml_block
    block = format_business_yaml_block(
        slug="x", name="X", website="https://x.com", address=None,
    )
    assert "address: null" in block, f"null address must serialize as 'null', got: {block}"
    print(f"  format_business_yaml_block null address: OK")
```

Add to `if __name__`:

```python
    test_slug_from_name()
    test_format_business_yaml_block()
    test_format_business_yaml_block_null_address()
```

- [ ] **Step 2: Run, confirm ImportError**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: ImportError on `slug_from_name`.

- [ ] **Step 3: Implement helpers**

Append to `scripts/ingest_flyer.py`:

```python
import re
import subprocess


# Path to config/businesses.yaml, relative to repo root.
BUSINESSES_YAML = Path(__file__).resolve().parent.parent / "config" / "businesses.yaml"


def slug_from_name(name: str) -> str:
    """Lowercase, ampersand->'and', strip non-alnum, hyphenate, trim leading 'the-'."""
    s = (name or "").strip().lower()
    s = s.replace("&", " and ")
    # Replace accented characters with their ASCII fallback (cafe, not café).
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # Anything not alnum becomes a space.
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = "-".join(s.split())
    if s.startswith("the-"):
        s = s[4:]
    return s


def format_business_yaml_block(
    *,
    slug: str,
    name: str,
    website: str,
    address: str | None,
) -> str:
    """Render a minimal businesses.yaml entry as text. Matches the existing
    file's indentation (2 spaces for list, 4 for fields, 6 for nested keys).

    The metadata + lat/lng + hours + pages blocks are intentionally omitted —
    they get filled in by the metadata extractor + geocoder + manual review.
    """
    addr_line = f"address: {address}" if address else "address: null"
    return (
        f"  - slug: {slug}\n"
        f"    name: {name}\n"
        f"    category: \n"
        f"    subcategory: \n"
        f"    website: {website}\n"
        f"    {addr_line}\n"
        f"    pages: []\n"
    )


def add_business_to_yaml(slug: str, name: str, website: str, address: str | None) -> None:
    """Append a new business entry to config/businesses.yaml.

    The file's structure is:
      businesses:
        - slug: ...
        ...
        - slug: ...
    We append after the last existing entry, preserving the comment header.
    """
    raw = BUSINESSES_YAML.read_text()
    block = format_business_yaml_block(slug=slug, name=name, website=website, address=address)
    # Ensure the file ends with a newline so our block doesn't run-on.
    if not raw.endswith("\n"):
        raw += "\n"
    BUSINESSES_YAML.write_text(raw + block)


def add_business_from_search(
    *,
    seed: dict,
    search_url: str,
    search_address: str | None,
    dry_run: bool = False,
) -> str:
    """Auto-add the venue to businesses.yaml + run metadata + geocoder.

    Returns the slug. Raises RuntimeError on subprocess failure (caller decides
    whether to mark the photo as failed:business-add-failed:<step>).

    When dry_run=True, prints what would happen and returns the would-be slug.
    """
    name = seed.get("venue_name") or "Unknown"
    slug = slug_from_name(name)

    # Derive website from the search URL: use the URL's origin if it points to
    # a venue page; otherwise leave it blank (metadata extractor needs *some*
    # website to crawl, so we default to the search URL itself).
    from urllib.parse import urlparse
    parsed = urlparse(search_url)
    website = f"{parsed.scheme}://{parsed.netloc}"

    if dry_run:
        print(f"    [DRY-RUN] would add business: slug={slug}, name={name},"
              f" website={website}, address={search_address!r}")
        return slug

    print(f"    adding business: {slug} ({name})")
    add_business_to_yaml(slug=slug, name=name, website=website, address=search_address)

    # Best-effort metadata + geocoding. If either fails, the entry stays in
    # the YAML and can be re-run later; the caller marks the photo failed.
    repo_root = Path(__file__).resolve().parent.parent
    print(f"    running extract_business_metadata.py {slug}…")
    r1 = subprocess.run(
        ["python3", "scripts/extract_business_metadata.py", slug],
        cwd=repo_root, capture_output=True, text=True,
    )
    if r1.returncode != 0:
        raise RuntimeError(f"extract_business_metadata failed: {r1.stderr or r1.stdout}")

    print(f"    running geocode_businesses.py {slug}…")
    r2 = subprocess.run(
        ["python3", "scripts/geocode_businesses.py", slug],
        cwd=repo_root, capture_output=True, text=True,
    )
    if r2.returncode != 0:
        raise RuntimeError(f"geocode_businesses failed: {r2.stderr or r2.stdout}")

    return slug
```

- [ ] **Step 4: Run, confirm PASS**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: all prior + 3 new tests OK.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_flyer.py scripts/test_ingest_helpers.py
git commit -m "feat(flyer-ingestion): add slug + YAML-block formatter + add_business_from_search"
```

---

## Task 11: Per-walk summary printer

**Files:**
- Modify: `scripts/ingest_flyer.py`
- Modify: `scripts/test_ingest_helpers.py`

- [ ] **Step 1: Add the failing test**

Append to `scripts/test_ingest_helpers.py`:

```python
def test_per_walk_summary_groups_outcomes():
    from io import StringIO
    from scripts.ingest_flyer import print_walk_summary

    entries = [
        {"photo": "a.jpg", "outcome": "ingested", "event_id": 245, "business_added": True,
         "business_slug": "guesthouse-hotel"},
        {"photo": "b.jpg", "outcome": "ingested", "event_id": 246},
        {"photo": "c.jpg", "outcome": "skipped:dedup-match"},
        {"photo": "d.jpg", "outcome": "skipped:no-web-trace",
         "seed": {"event_title": "Wander Home Holiday Market"}},
        {"photo": "e.jpg", "outcome": "failed:fetch_html-error",
         "error": "connection reset"},
    ]
    buf = StringIO()
    print_walk_summary(entries, dir_label="walks/2026-04-27/", out=buf)
    text = buf.getvalue()

    assert "Walk summary: walks/2026-04-27/" in text
    assert "Photos processed: 5" in text
    assert "ingested:" in text and "2" in text
    assert "skipped:dedup-match:" in text and "1" in text
    assert "skipped:no-web-trace:" in text and "Wander Home Holiday Market" in text, \
        "no-web-trace count must surface the seed title for manual follow-up"
    assert "failed:" in text and "connection reset" in text, \
        "failed count must surface the error for follow-up"
    assert "guesthouse-hotel" in text, "new businesses section must list slug"
    print(f"  print_walk_summary: OK")
```

Add to `if __name__`:

```python
    test_per_walk_summary_groups_outcomes()
```

- [ ] **Step 2: Run, confirm ImportError**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: ImportError on `print_walk_summary`.

- [ ] **Step 3: Implement the printer**

Append to `scripts/ingest_flyer.py`:

```python
from collections import Counter
from typing import TextIO


def print_walk_summary(entries: list[dict], *, dir_label: str, out: TextIO = sys.stdout) -> None:
    """Print a human-readable summary of a run from sidecar log entries."""
    counts = Counter(e.get("outcome", "unknown") for e in entries)
    total = sum(counts.values())

    out.write(f"\n─── Walk summary: {dir_label} ───\n")
    out.write(f"Photos processed: {total}\n")

    # Stable display order; only show categories that appeared.
    display_order = [
        "ingested", "enriched", "proceeded-as-new",
        "skipped:dedup-match", "skipped:no-web-trace", "skipped:user-quit",
    ]
    failed_categories = sorted(c for c in counts if c.startswith("failed:"))

    for cat in display_order + failed_categories:
        if cat not in counts:
            continue
        out.write(f"  {cat + ':':<26} {counts[cat]}")
        # Surface details for actionable categories.
        if cat == "skipped:no-web-trace":
            for e in entries:
                if e.get("outcome") == cat:
                    title = (e.get("seed") or {}).get("event_title") or e.get("photo")
                    out.write(f"\n     - {e.get('photo')} — \"{title}\"")
        elif cat.startswith("failed:"):
            for e in entries:
                if e.get("outcome") == cat:
                    out.write(f"\n     - {e.get('photo')} — {e.get('error') or '(no error captured)'}")
        out.write("\n")

    new_biz = [e for e in entries if e.get("business_added")]
    if new_biz:
        out.write(f"\nNew businesses added: {len(new_biz)}\n")
        for e in new_biz:
            out.write(f"  - {e.get('business_slug') or '(unknown slug)'}\n")
        out.write(f"  → review with: git diff config/businesses.yaml\n")

    out.write("\n")
```

- [ ] **Step 4: Run, confirm PASS**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: all prior + new summary test, then `PASS`.

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest_flyer.py scripts/test_ingest_helpers.py
git commit -m "feat(flyer-ingestion): add print_walk_summary() with actionable detail"
```

---

## Task 12: CLI orchestration — argparse + main loop

**Files:**
- Modify: `scripts/ingest_flyer.py`

This task wires everything together. The orchestration body is large — it's split across this one task because the pieces are tightly coupled and partial commits would leave the script non-runnable. Each sub-step compiles standalone after the prior helpers were added.

- [ ] **Step 1: Add argparse + entry-point skeleton**

Append to `scripts/ingest_flyer.py`:

```python
import argparse
from contextlib import contextmanager


PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".webp")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest phone-camera flyer photos into the events DB via web search.",
    )
    parser.add_argument("photo", nargs="?",
                        help="path to a single photo (mutually exclusive with --dir)")
    parser.add_argument("--dir", dest="directory",
                        help="directory of photos to process as a batch")
    parser.add_argument("--source-url",
                        help="manual authoritative URL (single-photo mode only); "
                             "bypasses Step 4 web search")
    parser.add_argument("--dry-run", action="store_true",
                        help="run the full pipeline but skip all writes (DB, YAML, sidecar log)")
    parser.add_argument("--seed-only", action="store_true",
                        help="run only Step 1 seed extraction; cheap preview")
    parser.add_argument("--force", action="store_true",
                        help="re-process photos already in the sidecar log")
    args = parser.parse_args(argv)

    # Mutual-exclusion / requirement validation.
    if not args.photo and not args.directory:
        parser.error("must provide either a photo path or --dir")
    if args.photo and args.directory:
        parser.error("--dir is mutually exclusive with a positional photo argument")
    if args.source_url and args.directory:
        parser.error("--source-url requires single-photo mode")
    if args.seed_only and args.dry_run:
        parser.error("--seed-only and --dry-run are mutually exclusive")
    return args


def collect_photos(args: argparse.Namespace) -> tuple[Path, list[Path]]:
    """Return (sidecar_dir, [photo_path, ...]) — one photo for single mode,
    a sorted list of photos for --dir mode."""
    if args.photo:
        photo = Path(args.photo).resolve()
        if not photo.exists():
            raise SystemExit(f"photo not found: {photo}")
        return photo.parent, [photo]
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        raise SystemExit(f"--dir not a directory: {directory}")
    photos = sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in PHOTO_EXTENSIONS
    )
    if not photos:
        raise SystemExit(f"no photos found in {directory}")
    return directory, photos


def media_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".heic":
        return "image/heic"
    return "application/octet-stream"
```

- [ ] **Step 2: Add the per-photo flow as a function**

Append:

```python
from datetime import date as _date


def _normalize_seed_dates(seed: dict) -> dict:
    """Best-effort: convert a `date_hint` like 'May 2' into ISO 'YYYY-MM-DD'.

    Used by find_dedup_match for dated events. Recurring events use
    recurrence_pattern + start_time directly.
    """
    out = dict(seed)
    hint = (seed.get("date_hint") or "").strip()
    if not hint:
        return out

    # Try a handful of common formats. We don't sweat exotic cases —
    # find_dedup_match treats unparseable dates as "skip the dated dedup".
    today = _date.today()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%m/%d"):
        try:
            d = datetime.strptime(hint, fmt).date()
            if fmt == "%m/%d":
                # Year-less: pick nearest future occurrence.
                d = d.replace(year=today.year)
                if d < today:
                    d = d.replace(year=today.year + 1)
            out["date_hint_iso"] = d.isoformat()
            return out
        except ValueError:
            continue

    for fmt in ("%B %d", "%b %d"):
        try:
            d = datetime.strptime(hint, fmt).date().replace(year=today.year)
            if d < today:
                d = d.replace(year=today.year + 1)
            out["date_hint_iso"] = d.isoformat()
            return out
        except ValueError:
            continue
    return out


def _prompt_choice(prompt: str, valid: str) -> str:
    """Read a single character from stdin (case-insensitive) and validate."""
    while True:
        raw = input(prompt).strip().lower()
        if raw and raw[0] in valid:
            return raw[0]
        print(f"  please pick one of: {', '.join(valid)}")


def _prompt_ambiguous_business(seed: dict, candidates: list[tuple[str, float]]) -> str | None:
    """Ask the user which candidate to pick; return slug, '__new__', or None
    (skip / quit signals up the stack via SystemExit / 'quit_batch')."""
    print(f"\n  Flyer says: {seed.get('venue_name')!r}")
    print(f"  Closest matches in businesses.yaml:")
    for i, (slug, score) in enumerate(candidates, 1):
        print(f"    [{i}] {slug:<26}  (score {score:.2f})")
    print(f"    [n] none of these — treat as new business")
    print(f"    [s] skip this photo")
    print(f"    [q] quit batch")
    valid = "".join(str(i) for i in range(1, len(candidates) + 1)) + "nsq"
    pick = _prompt_choice("  Pick: ", valid)
    if pick.isdigit():
        return candidates[int(pick) - 1][0]
    if pick == "n":
        return "__new__"
    if pick == "s":
        return None
    if pick == "q":
        raise KeyboardInterrupt("user quit at ambiguous business")
    return None


def _prompt_dedup_match(seed: dict, existing: dict) -> str:
    """Show field-by-field comparison and ask [s/e/p/q]. Returns the chosen letter."""
    print(f"\n  Existing event #{existing['id']}: {existing['title']!r}"
          f" ({existing['kind']}"
          f"{' ' + (existing['recurrence_pattern'] or '') if existing['kind']=='recurring' else ''})")
    print(f"  Field-by-field comparison:")
    for field in ("title", "start_time", "end_time", "price_info", "performers"):
        seed_val = seed.get(field) if field in seed else "(no seed)"
        existing_val = existing.get(field)
        marker = ""
        if seed_val == existing_val and seed_val:
            marker = "  ✓"
        elif _is_empty(existing_val) and not _is_empty(seed_val):
            marker = "  (seed fills)"
        elif _is_empty(seed_val) and not _is_empty(existing_val):
            marker = "  (existing fills)"
        print(f"    {field+':':<14} seed={seed_val!r:<24} existing={existing_val!r:<24}{marker}")
    print(f"\n  Action: [s]kip / [e]nrich / [p]roceed-as-new / [q]uit")
    return _prompt_choice("  Pick: ", "sepq")


def process_photo(
    photo_path: Path,
    *,
    args: argparse.Namespace,
    businesses: list[dict],
    tag_vocab: list[str],
    db_conn,
    sidecar: SidecarLog | None,
    allowlist: list[str],
) -> dict:
    """Run the 7-step pipeline on one photo. Returns the sidecar entry dict.

    Side effects honor args.dry_run (no DB / YAML / sidecar writes when True)
    and args.seed_only (Steps 1 only).
    """
    from src.extractor import extract_flyer_seeds, extract_events
    from src.web_search import search_for_event, domain_of

    print(f"\n[{photo_path.name}]")
    entry: dict = {
        "photo": photo_path.name,
        "started_at": _now_iso_local(),
    }

    # ── Step 1: seed extraction ─────────────────────────────────────────
    print(f"  [1/7] seed extraction…")
    image_bytes = photo_path.read_bytes()
    seed = extract_flyer_seeds(image_bytes, media_type=media_type_for(photo_path))
    entry["seed"] = seed
    print(f"        title={seed.get('event_title')!r}, venue={seed.get('venue_name')!r},"
          f" date={seed.get('date_hint')!r}, conf={seed.get('seed_confidence')!r}")

    if args.seed_only:
        entry["outcome"] = "seed-only-preview"
        entry["finished_at"] = _now_iso_local()
        return entry

    # ── Step 2: resolve business ────────────────────────────────────────
    print(f"  [2/7] resolve business…")
    resolution = resolve_business(seed.get("venue_name") or "", businesses)
    biz_slug: str | None
    biz_meta: dict | None
    business_added = False
    if isinstance(resolution, tuple):
        biz_slug, score = resolution
        print(f"        confident match: {biz_slug} (score {score:.2f})")
    elif isinstance(resolution, list):
        pick = _prompt_ambiguous_business(seed, resolution)
        if pick is None:
            entry["outcome"] = "skipped:user-quit"
            entry["finished_at"] = _now_iso_local()
            return entry
        biz_slug = None if pick == "__new__" else pick
    else:
        print(f"        no match — will treat as new business after web search")
        biz_slug = None

    biz_meta = next((b for b in businesses if b["slug"] == biz_slug), None) if biz_slug else None

    # ── Step 3: DB dedup gate (only if business is known) ───────────────
    if biz_slug:
        print(f"  [3/7] DB dedup check…")
        # Fetch business_id; lazy lookup since the YAML doesn't carry DB ids.
        biz_row = db_conn.execute(
            "SELECT id FROM businesses WHERE slug = ?", (biz_slug,)
        ).fetchone()
        if biz_row is not None:
            seed_for_dedup = _normalize_seed_dates(seed)
            existing = find_dedup_match(db_conn, business_id=biz_row["id"], seed=seed_for_dedup)
            if existing is not None:
                print(f"        match: event #{existing['id']} ({existing['title']!r})")
                action = _prompt_dedup_match(seed, dict(existing))
                if action == "s":
                    entry["outcome"] = "skipped:dedup-match"
                    entry["matched_event_id"] = existing["id"]
                    entry["finished_at"] = _now_iso_local()
                    return entry
                if action == "q":
                    raise KeyboardInterrupt("user quit at dedup match")
                if action == "e":
                    # Fall through to Steps 4-7, then enrich at upsert.
                    entry["enrich_target_event_id"] = existing["id"]
                # action == "p": fall through to Steps 4-7 as a new event.
        else:
            print(f"        business {biz_slug!r} not yet in DB — proceeding without dedup")

    # ── Step 4: web search ──────────────────────────────────────────────
    if args.source_url:
        print(f"  [4/7] manual --source-url override: {args.source_url}")
        from src.web_search import SearchResult
        search_result = SearchResult(
            url=args.source_url,
            title="(manual override)",
            domain=domain_of(args.source_url),
            tier=1,
        )
    else:
        print(f"  [4/7] web search…")
        venue_domain = None
        if biz_meta:
            website = biz_meta.get("website") or ""
            venue_domain = domain_of(website) if website else None
        search_result = search_for_event(seed, allowlist=allowlist, venue_domain=venue_domain)

        if search_result is None:
            print(f"        no result clears the allowlist — skipping")
            entry["outcome"] = "skipped:no-web-trace"
            entry["queries_tried"] = "(see seed.distinctive_strings)"
            entry["finished_at"] = _now_iso_local()
            return entry
        print(f"        found tier-{search_result.tier}: {search_result.url}")
    entry["source_url"] = search_result.url

    # ── Step 6: auto-add new business if needed ─────────────────────────
    # (Step 6 runs before Step 5 so we have a business_id to upsert against.)
    if biz_slug is None:
        print(f"  [6/7] auto-adding new business…")
        try:
            biz_slug = add_business_from_search(
                seed=seed,
                search_url=search_result.url,
                search_address=None,  # best-effort address extraction is a future enhancement
                dry_run=args.dry_run,
            )
            business_added = True
            entry["business_added"] = True
            entry["business_slug"] = biz_slug
        except RuntimeError as exc:
            print(f"        ERROR: {exc}")
            entry["outcome"] = f"failed:business-add-failed"
            entry["error"] = str(exc)
            entry["finished_at"] = _now_iso_local()
            return entry
        # Re-load businesses for downstream use.
        from src.pipeline import load_businesses
        businesses = load_businesses(include_pending=True)
        biz_meta = next((b for b in businesses if b["slug"] == biz_slug), None)

    entry["business_slug"] = biz_slug

    # ── Step 5: full extraction from authoritative URL ──────────────────
    print(f"  [5/7] full extraction from {search_result.url}…")
    try:
        events = _run_full_extraction(
            biz_meta=biz_meta,
            source_url=search_result.url,
            cross_verify_image=image_bytes,
            cross_verify_media_type=media_type_for(photo_path),
            tag_vocab=tag_vocab,
        )
    except Exception as exc:  # network / fetcher / Claude — surface and skip
        print(f"        ERROR: {exc}")
        entry["outcome"] = f"failed:extract-error"
        entry["error"] = str(exc)
        entry["finished_at"] = _now_iso_local()
        return entry

    if not events:
        print(f"        extraction returned 0 events; skipping")
        entry["outcome"] = "failed:no-events-extracted"
        entry["error"] = "extract_events returned []"
        entry["finished_at"] = _now_iso_local()
        return entry

    # Pick the event whose title is most similar to the seed title.
    chosen = max(events, key=lambda e: _name_similarity(e.get("title") or "",
                                                          seed.get("event_title") or ""))
    chosen.setdefault("source_page_url", search_result.url)
    chosen.setdefault("status", "active")

    # ── Step 7: upsert (or enrich) ──────────────────────────────────────
    print(f"  [7/7] {'enrich' if entry.get('enrich_target_event_id') else 'insert'}"
          f"{' [DRY-RUN]' if args.dry_run else ''}…")

    if args.dry_run:
        entry["outcome"] = "ingested" if not entry.get("enrich_target_event_id") else "enriched"
        entry["dry_run"] = True
        entry["finished_at"] = _now_iso_local()
        return entry

    # Bridge YAML -> DB: the daily pipeline upserts every YAML business at the
    # start of each run, but this CLI is single-photo and doesn't run that
    # phase, so we upsert the business now to guarantee it has a DB id.
    from src.db import upsert_business, upsert_event, build_match_key
    if biz_meta is None:
        # Should never happen — we set biz_meta either at confident-match in Step 2
        # or after auto-add reload in Step 6. Defensive guard.
        entry["outcome"] = "failed:business-meta-missing"
        entry["error"] = f"slug {biz_slug!r} resolved but biz_meta is None"
        entry["finished_at"] = _now_iso_local()
        return entry
    business_id = upsert_business(db_conn, {
        "slug":        biz_meta["slug"],
        "name":        biz_meta["name"],
        "category":    biz_meta.get("category"),
        "subcategory": biz_meta.get("subcategory"),
        "website":     biz_meta.get("website"),
        "address":     biz_meta.get("address"),
    })
    biz_row = {"id": business_id}

    enrich_id = entry.get("enrich_target_event_id")
    if enrich_id is not None:
        existing_row = dict(db_conn.execute(
            "SELECT * FROM events WHERE id = ?", (enrich_id,)
        ).fetchone())
        diff = compute_enrichment(existing_row, chosen)
        if diff:
            cols = ", ".join(f"{k} = :{k}" for k in diff)
            db_conn.execute(
                f"UPDATE events SET {cols}, last_seen_at = :now, last_extracted_at = :now"
                f" WHERE id = :id",
                {**diff, "now": _now_iso_local(), "id": enrich_id,
                 # JSON-serialize performers if it's a list
                 **({"performers": json.dumps(diff["performers"])} if "performers" in diff else {})},
            )
            print(f"        enriched event #{enrich_id} with {list(diff)}")
            entry["outcome"] = "enriched"
            entry["event_id"] = enrich_id
        else:
            print(f"        no enrichable gaps — skipping update")
            entry["outcome"] = "skipped:dedup-match"
            entry["matched_event_id"] = enrich_id
    else:
        result = upsert_event(db_conn, biz_row["id"], chosen)
        new_id_row = db_conn.execute(
            "SELECT id FROM events WHERE business_id = ? AND match_key = ?",
            (biz_row["id"], build_match_key(chosen)),
        ).fetchone()
        entry["event_id"] = new_id_row["id"] if new_id_row else None
        entry["outcome"] = "ingested" if entry.get("enrich_target_event_id") is None \
                           else ("proceeded-as-new" if result == "inserted" else "ingested")
        print(f"        {result} event #{entry.get('event_id')}")

    entry["finished_at"] = _now_iso_local()
    return entry


def _run_full_extraction(
    *,
    biz_meta: dict | None,
    source_url: str,
    cross_verify_image: bytes,
    cross_verify_media_type: str,
    tag_vocab: list[str],
):
    """Fetch + extract for an arbitrary URL. Tolerates a missing biz_meta
    (sets a minimal page record). Returns the events list."""
    from src.extractor import extract_events
    from src.fetcher import fetch_html, fetch_html_playwright
    from src.images import discover_and_download, page_text
    from src.pipeline import PUBLIC_DIR

    page_kind = "home"
    needs_playwright = False
    if biz_meta:
        page = next((p for p in (biz_meta.get("pages") or []) if p["url"] == source_url),
                    {"url": source_url, "kind": page_kind, "hints": ""})
        page_kind = page.get("kind") or "home"
        needs_playwright = bool(page.get("use_playwright"))
    else:
        page = {"url": source_url, "kind": page_kind, "hints": ""}

    if needs_playwright:
        html, _, _ = fetch_html_playwright(source_url)
    else:
        html, _, _ = fetch_html(source_url)

    business = biz_meta or {"slug": "(unknown)", "name": "(unknown)", "category": "", "subcategory": ""}
    images = discover_and_download(html, business["slug"], PUBLIC_DIR, base_url=source_url)
    return extract_events(
        business=business,
        page=page,
        page_text=page_text(html),
        images=images,
        tag_vocab=tag_vocab,
        cross_verify_image=cross_verify_image,
        cross_verify_media_type=cross_verify_media_type,
    )
```

- [ ] **Step 3: Add `main()` and the script entry point**

Append:

```python
def main(argv: list[str]) -> int:
    from dotenv import load_dotenv
    load_dotenv()

    args = parse_args(argv)
    sidecar_dir, photos = collect_photos(args)
    sidecar_path = sidecar_dir / ".ingest_log.json"
    sidecar = None if (args.seed_only or args.dry_run) else SidecarLog(sidecar_path)

    from src.db import connect
    from src.pipeline import load_businesses, load_tag_vocab
    from src.web_search import load_allowlist

    businesses = load_businesses(include_pending=True)
    tag_vocab = load_tag_vocab()
    allowlist = load_allowlist()

    skipped_already_processed = (
        set() if args.force or sidecar is None else sidecar.processed_photos()
    )

    entries: list[dict] = list(sidecar.entries()) if sidecar else []

    try:
        with connect() as db_conn:
            for photo_path in photos:
                if photo_path.name in skipped_already_processed:
                    print(f"\n[{photo_path.name}] already in sidecar log — skipping (use --force to redo)")
                    continue
                try:
                    entry = process_photo(
                        photo_path,
                        args=args,
                        businesses=businesses,
                        tag_vocab=tag_vocab,
                        db_conn=db_conn,
                        sidecar=sidecar,
                        allowlist=allowlist,
                    )
                except KeyboardInterrupt:
                    print("\n  user quit batch")
                    break
                except Exception as exc:
                    print(f"  ERROR processing {photo_path.name}: {exc}")
                    entry = {
                        "photo": photo_path.name,
                        "outcome": "failed:exception",
                        "error": repr(exc),
                        "finished_at": _now_iso_local(),
                    }
                if sidecar is not None:
                    sidecar.append(entry)
                entries.append(entry)
    finally:
        print_walk_summary(entries, dir_label=str(sidecar_dir))
        if sidecar is not None:
            print(f"Sidecar log: {sidecar.path}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Smoke-test the CLI parses args correctly**

Run: `python3 scripts/ingest_flyer.py --help`
Expected: argparse help text printing all flags.

Run: `python3 scripts/ingest_flyer.py 2>&1 | head -2`
Expected: error mentioning "must provide either a photo path or --dir".

Run: `python3 scripts/ingest_flyer.py foo.jpg --dir bar/ 2>&1 | head -2`
Expected: error mentioning mutual exclusion.

- [ ] **Step 5: Run all helper tests once more to confirm nothing regressed**

Run: `python3 scripts/test_ingest_helpers.py`
Expected: all OK lines, then `PASS`.

- [ ] **Step 6: Commit**

```bash
git add scripts/ingest_flyer.py
git commit -m "feat(flyer-ingestion): wire CLI orchestration with argparse + main loop"
```

---

## Task 13: End-to-end smoke test on the Guesthouse photo

**Files:**
- (no code changes — this task is verification)

The Guesthouse flyer photo at `/Users/jgonder/Downloads/20260422_202538.jpg` is the canonical real-world test case (per the spec).

- [ ] **Step 1: Verify `--seed-only` works**

Run:
```bash
python3 scripts/ingest_flyer.py /Users/jgonder/Downloads/20260422_202538.jpg --seed-only
```
Expected: prints the seed JSON inline, walk summary at the end shows 1 photo with outcome `seed-only-preview`. No DB or YAML changes.

If this fails: most likely a path/permission issue or a bug in `extract_flyer_seeds`. Debug from `scripts/test_seed_extraction.py` first (it isolates seed extraction).

- [ ] **Step 2: Run `--dry-run` end-to-end**

Run:
```bash
python3 scripts/ingest_flyer.py /Users/jgonder/Downloads/20260422_202538.jpg --dry-run
```
Expected output flow:
- `[1/7] seed extraction…` — Claude reads the photo
- `[2/7] resolve business…` — likely "no match" (Guesthouse not in YAML yet)
- `[4/7] web search…` — Claude finds an authoritative URL
- `[6/7] auto-adding new business…` — `[DRY-RUN] would add business: slug=guesthouse-hotel, ...`
- `[5/7] full extraction…` — fetches the URL, runs extract_events with cross-verify
- `[7/7] insert [DRY-RUN]…` — would insert event
- Walk summary shows 1 ingested, 1 new business added.

The dry-run must NOT modify `config/businesses.yaml` or `data/app.db`. Verify with `git status` after the run.

- [ ] **Step 3: If dry-run looks correct, run for real**

Run:
```bash
python3 scripts/ingest_flyer.py /Users/jgonder/Downloads/20260422_202538.jpg
```
Expected: same flow but with real writes. After the run:
- `git diff config/businesses.yaml` shows the new `guesthouse-hotel` entry
- `sqlite3 data/app.db "SELECT title, business_id FROM events ORDER BY id DESC LIMIT 1"` shows the new event
- A `.ingest_log.json` exists in `~/Downloads/`

- [ ] **Step 4: Re-run to verify resume + dedup work**

Run the same command a second time:
```bash
python3 scripts/ingest_flyer.py /Users/jgonder/Downloads/20260422_202538.jpg
```
Expected: prints `[20260422_202538.jpg] already in sidecar log — skipping (use --force to redo)`. No new events. No new YAML entries.

- [ ] **Step 5: Test `--force` re-processing**

Run with `--force`:
```bash
python3 scripts/ingest_flyer.py /Users/jgonder/Downloads/20260422_202538.jpg --force
```
Expected: re-processes the photo. At Step 3 the dedup gate fires (the event we just inserted matches the seed). The interactive prompt asks `[s/e/p/q]` — pick `s` to confirm the dedup-skip path works.

- [ ] **Step 6: Document any issues; commit if anything changed**

If smoke tests turned up any minor bugs that you fixed inline (typos, missing imports, etc.), commit them:

```bash
git add scripts/ingest_flyer.py src/ config/
git commit -m "fix(flyer-ingestion): smoke-test fixes (<one-line description>)"
```

If everything worked first try, no commit needed for this task.

---

## Self-review notes

### Spec coverage
- Decision 1 (flyer as seed): handled across Tasks 4 (seed extraction) + 5 (web search) + 12 (orchestration).
- Decision 2 (pause + check enrichment on dedup): Task 12 `_prompt_dedup_match` + Task 9 `compute_enrichment`.
- Decision 3 (auto-add new businesses inline): Task 10.
- Decision 4 (Claude identifies business, fuzzy match): Task 6 `resolve_business`.
- Decision 5 (phone photo signal-only, never displayed): Task 5 — cross-verify image is added to multimodal context but `extract_events` never assigns it as `image_local_path`. The chosen event's existing image fields come from the web source's discovered images via `discover_and_download`.
- Decision 6 (sidecar log resumability): Task 8 + Task 12 entry-point.
- Decision 7 (no-web-trace silent skip + log): Task 12 process_photo Step 4.
- Decision 8 (`--dry-run` + `--seed-only`): Task 12 argparse + early-returns.
- Decision 9 (hybrid file layout): Task 1 (`src/web_search.py`), Task 4 (`src/prompts.py`), Tasks 6–11 (everything inline in `scripts/ingest_flyer.py`).
- Decision 10 (allowlist v1): Task 1.

Section A 7 steps mapped to Task 12 process_photo, with Step 6 reordered before Step 5 (so we have a business_id ready for upsert).

Section B fully covered: invocation flags, sidecar log shape, interactive prompts, per-walk summary.

Section C fully covered: file layout, component specs, allowlist YAML shape, multimodal extension, testing approach, cost ceiling.

### Type / signature consistency check
- `resolve_business` returns `tuple | list | None` — same shape used in Task 12.
- `find_dedup_match` returns `sqlite3.Row | None` — Task 12 wraps the result in `dict()` before passing to `compute_enrichment`.
- `SearchResult` dataclass — used consistently across `src/web_search.py` and `scripts/ingest_flyer.py`.
- `compute_enrichment` returns `dict` of `field -> value` — Task 12 builds the UPDATE statement off it.
- `SidecarLog.append(entry: dict)` — entry shape matches the JSON shape in spec Section B.

### Known v1 gaps deliberately not in scope
- **Address extraction from search-result page** — Task 10's `add_business_from_search` always passes `search_address=None`. The spec's Section A Step 6 says "best-effort from search result page" — implementing the parser to read venue addresses out of Eventbrite/Block Club pages is genuinely worth doing but adds a non-trivial amount of HTML parsing. Deferred to a follow-up; the geocoder + manual review handle the gap.
- **Cost-of-web_search** — Task 3 documents the call shape but doesn't track or display per-photo cost. The summary's cost line in Section B is prose-level for v1; can be made real later by tracking `resp.usage` from each API call.
- **Resilience to partial subprocess failure in Task 10** — if `extract_business_metadata.py` succeeds but `geocode_businesses.py` fails, the business stays in YAML with metadata but no lat/lng. The `failed:business-add-failed` outcome surfaces this; user re-runs the geocoder manually. Acceptable for v1.

---

## Workflow note

Doc-only commits in this plan are on the `flyer-ingestion-design` branch (already in flight). Implementation commits per the tasks above also land on that branch. Once Task 13 passes, transition the branch from "design" to "implementation": rename or open a PR titled "Flyer ingestion pipeline" against `main`. Trigger the **Site rebuild** workflow only if any UI / template / CSS / `site_builder.py` changes accompany the work — this plan doesn't touch any of those, so no site rebuild is needed after merge.
