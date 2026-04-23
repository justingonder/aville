# Per-business landing pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `/business/{slug}/` entity pages for all 23 Andersonville businesses, with `LocalBusiness` JSON-LD, breadcrumb wiring on event pages, internal-link rewrite from events to business pages, historical flyer gallery, markdown siblings, and a one-time metadata-extraction + build-time-geocoding pipeline to populate the new fields.

**Architecture:** Extend the existing static-site build. A new Claude-based extraction script pulls `description`, `telephone`, `price_range`, `sameAs[]` from each business's homepage into `config/businesses.yaml`. A build-time geocoder resolves `address` → `lat`/`lng` via Nominatim and caches results back into the YAML. `src/site_builder.py` gains a new `_build_business_pages()` pass that renders HTML + markdown per business using existing event data joined from `all_events_with_business()`. Event page templates are edited to link business names at internal pages and render a visible + JSON-LD breadcrumb trail.

**Tech Stack:** Python 3, Jinja2, Anthropic SDK (Claude Haiku 4.5), `urllib.request` (stdlib) for Nominatim, PyYAML, SQLite (read-only here), existing fetcher module for page HTML.

**Spec:** `docs/superpowers/specs/2026-04-23-per-business-landing-pages-design.md`

---

## File map

**New files:**
- `scripts/extract_business_metadata.py` — one-shot Claude extraction script
- `templates/_business_detail.html` — per-business HTML template
- `templates/_business.md` — per-business markdown template

**Modified files:**
- `src/prompts.py` — new `BUSINESS_METADATA_PROMPT` + builder
- `src/site_builder.py` — `_geocode()`, `_opening_hours_schema()`, `_business_schema()`, `_breadcrumb_schema()`, `_build_business_pages()`, sitemap + llms.txt updates, wiring in `build_site()`
- `config/businesses.yaml` — new `metadata:` block per business (written by the extraction script), `lat`/`lng` (written by the geocoder)
- `templates/_event_card.html` — business-name link target
- `templates/_event_detail.html` — business-name link + visible breadcrumb strip + `BreadcrumbList` JSON-LD
- `.gitignore` — possibly extend for `public/business/` artifacts if needed

**No DB schema changes.** Businesses stay config-driven.

---

## Task 1: Add business-metadata extraction prompt

**Files:**
- Modify: `src/prompts.py` (append at end)

- [ ] **Step 1: Append the prompt + builder**

Add to the end of `src/prompts.py`:

```python
BUSINESS_METADATA_PROMPT = dedent("""
    You are extracting canonical entity metadata about a single small
    business in Andersonville, Chicago, from its homepage HTML.

    Return ONE JSON object with exactly these fields:
      - description: string. 2 or 3 neutral, factual sentences describing
        what the venue is and what it's known for. No marketing fluff,
        no superlatives, no second-person ("you'll love..."). Prefer
        concrete specifics over vague adjectives. Max ~350 characters.
      - telephone: string in E.164 format if possible
        (e.g. "+1-773-334-7402"), otherwise as written on the page,
        or null if no phone number is visible.
      - price_range: one of "$", "$$", "$$$", "$$$$", or null.
        Infer from menu prices if visible, or from the venue type.
        Use null when genuinely unclear.
      - same_as: array of absolute URLs to the venue's own profiles on
        Instagram, Facebook, X/Twitter, Threads, TikTok, YouTube,
        LinkedIn. Include only profiles that obviously belong to THIS
        venue. Empty array if none visible.

    Return ONLY the JSON object. No preamble, no code fences, no commentary.
""").strip()


def build_business_metadata_prompt(
    *,
    business_name: str,
    business_category: str,
    website: str,
    page_text: str,
) -> str:
    return dedent(f"""
        BUSINESS: {business_name} ({business_category})
        WEBSITE: {website}

        ---
        HOMEPAGE TEXT (truncated):
        {page_text}

        ---
        Return the JSON object now.
    """).strip()
```

- [ ] **Step 2: Sanity-check by importing**

Run: `python3 -c "from src.prompts import BUSINESS_METADATA_PROMPT, build_business_metadata_prompt; print(BUSINESS_METADATA_PROMPT[:80])"`
Expected: First 80 chars of the prompt print cleanly. No ImportError.

- [ ] **Step 3: Commit**

```bash
git add src/prompts.py
git commit -m "feat: add business-metadata extraction prompt"
```

---

## Task 2: Write the extraction script

**Files:**
- Create: `scripts/extract_business_metadata.py`

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
"""Extract entity metadata (description, phone, price_range, same_as)
for each business in config/businesses.yaml using Claude.

Writes results into a top-level `metadata:` block inside each business
entry. Idempotent: skips businesses that already have a metadata block
unless --force is passed.

Usage:
    python3 scripts/extract_business_metadata.py               # all missing
    python3 scripts/extract_business_metadata.py vincent       # one by slug
    python3 scripts/extract_business_metadata.py --force       # refresh all
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.fetcher import fetch_html, fetch_html_playwright
from src.prompts import BUSINESS_METADATA_PROMPT, build_business_metadata_prompt

YAML_PATH = ROOT / "config" / "businesses.yaml"
MODEL = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")
MAX_PAGE_CHARS = 20000  # truncate long pages before sending to Claude


def _extract_json_object(text: str) -> dict:
    """Parse a JSON object out of Claude's response, tolerating code fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start != -1:
        depth = 0
        in_str = False
        escape_next = False
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
                    text = text[start:i + 1]
                    break
    return json.loads(text)


def _page_text(html: str) -> str:
    """Strip script/style and collapse whitespace. Good enough for metadata extraction."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_PAGE_CHARS]


def extract_one(business: dict, client: Anthropic) -> dict:
    """Fetch the business homepage and call Claude. Returns the metadata dict."""
    website = business.get("website") or ""
    if not website:
        raise ValueError(f"{business['slug']}: no website URL")

    # Respect per-business Playwright hint (look at pages list for `use_playwright`).
    needs_playwright = any(
        p.get("use_playwright") for p in (business.get("pages") or [])
    )
    print(f"  fetching {website} ({'playwright' if needs_playwright else 'httpx'})…")
    html = fetch_html_playwright(website) if needs_playwright else fetch_html(website)

    user_prompt = build_business_metadata_prompt(
        business_name=business["name"],
        business_category=business.get("category") or "",
        website=website,
        page_text=_page_text(html),
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=BUSINESS_METADATA_PROMPT,
        temperature=0.0,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return _extract_json_object(text)


def main(argv: list[str]) -> int:
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    target_slug = argv[0] if argv else None

    with open(YAML_PATH) as f:
        doc = yaml.safe_load(f)
    businesses = doc["businesses"]

    client = Anthropic()  # uses ANTHROPIC_API_KEY

    for biz in businesses:
        slug = biz["slug"]
        if target_slug and slug != target_slug:
            continue
        if "metadata" in biz and not force:
            print(f"skip {slug} (already has metadata; --force to refresh)")
            continue
        print(f"→ {slug}: {biz['name']}")
        try:
            md = extract_one(biz, client)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue
        biz["metadata"] = md
        print(f"  got: {json.dumps(md, indent=2)[:200]}")

    # Write back preserving order and style as much as PyYAML allows.
    with open(YAML_PATH, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=1000)
    print(f"\nwrote {YAML_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 2: Make it executable + syntax-check**

```bash
chmod +x scripts/extract_business_metadata.py
python3 -c "import ast; ast.parse(open('scripts/extract_business_metadata.py').read())"
```

Expected: no output (clean parse).

- [ ] **Step 3: Dry-run against ONE business (sanity check)**

Requires `ANTHROPIC_API_KEY` in environment. Pick a simple-HTML business for the trial.

```bash
python3 scripts/extract_business_metadata.py vincent
```

Expected:
```
→ vincent: Vincent
  fetching https://www.vincentchicago.com/ (playwright)…
  got: {
    "description": "...",
    "telephone": "...",
    "price_range": "$$$",
    "same_as": [...]
  }

wrote /Users/jgonder/Development/aville/config/businesses.yaml
```

Inspect: `grep -A 6 "^  - slug: vincent" config/businesses.yaml | head -20` — should now show a `metadata:` block under `vincent`.

- [ ] **Step 4: Commit the script + Vincent's metadata**

```bash
git add scripts/extract_business_metadata.py config/businesses.yaml
git commit -m "feat: Claude-based business-metadata extractor + vincent metadata"
```

---

## Task 3: Run extraction against remaining 22 businesses

**User-gated: costs Claude API credits (~23 Haiku calls, ≈$0.05 total). Only run when you're ready to spend.**

- [ ] **Step 1: Run extraction for all missing businesses**

```bash
python3 scripts/extract_business_metadata.py
```

Expected: ~22 successful extractions printed. Any business whose homepage is down or Cloudflare-gated will print `ERROR:` and be skipped — that's fine; re-run targeted later.

- [ ] **Step 2: Spot-check 3 businesses**

```bash
grep -A 7 "metadata:" config/businesses.yaml | head -40
```

Visually confirm the prose doesn't hallucinate details (check against one or two websites). If any description reads wrong, re-run that one business with `--force`.

- [ ] **Step 3: Commit**

```bash
git add config/businesses.yaml
git commit -m "chore: one-time Claude-extracted metadata for all 23 businesses"
```

---

## Task 4: Build-time Nominatim geocoder

**Files:**
- Modify: `src/site_builder.py`
- Modify: `config/businesses.yaml` (lat/lng written back on first build)

- [ ] **Step 1: Add the geocoder function**

Append to `src/site_builder.py` near `_fetch_weather()` (both are network helpers with graceful-degrade behavior):

```python
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_UA = "aville.net/1.0 (justingonder@gmail.com)"  # required by Nominatim TOS


def _geocode(address: str) -> tuple[float, float] | None:
    """Resolve an address to (lat, lng) via Nominatim. Returns None on failure.

    One-time use per address. Caller is responsible for writing the result
    back to businesses.yaml so subsequent builds skip this network call.
    """
    import time
    from urllib.parse import urlencode

    params = {
        "q": address,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    req = urllib.request.Request(
        f"{_NOMINATIM_URL}?{urlencode(params)}",
        headers={"User-Agent": _NOMINATIM_UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        if not data:
            return None
        first = data[0]
        # 1 req/sec per Nominatim TOS — enforced here so callers don't have to
        time.sleep(1.1)
        return float(first["lat"]), float(first["lon"])
    except Exception as exc:
        print(f"  geocode failed for {address!r}: {exc}")
        return None


def _ensure_geocoded(businesses_yaml_path: Path) -> dict:
    """Load businesses.yaml. For any business missing lat/lng, geocode and
    write back to disk. Returns the full YAML doc."""
    with open(businesses_yaml_path) as f:
        doc = yaml.safe_load(f)

    dirty = False
    for biz in doc["businesses"]:
        if biz.get("lat") and biz.get("lng"):
            continue
        if not biz.get("address"):
            continue
        print(f"  geocoding {biz['slug']}: {biz['address']}")
        coords = _geocode(biz["address"])
        if coords:
            biz["lat"], biz["lng"] = coords
            dirty = True

    if dirty:
        with open(businesses_yaml_path, "w") as f:
            yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=1000)
        print(f"  wrote geocoded lat/lng to {businesses_yaml_path.name}")

    return doc
```

- [ ] **Step 2: Syntax-check**

Run: `python3 -c "from src.site_builder import _geocode, _ensure_geocoded"`
Expected: no output.

- [ ] **Step 3: One-shot test against a single address**

```bash
python3 -c "from src.site_builder import _geocode; print(_geocode('1475 W. Balmoral Ave., Chicago, IL 60640'))"
```

Expected: `(41.9799..., -87.6731...)` (approx — Vincent is real and on the map).

- [ ] **Step 4: Commit**

```bash
git add src/site_builder.py
git commit -m "feat: Nominatim geocoder for business addresses with YAML write-back"
```

---

## Task 5: Schema builder helpers

**Files:**
- Modify: `src/site_builder.py`

- [ ] **Step 1: Add `_opening_hours_schema()`**

Find the existing `_DAY_ORDER` constant at the top of `src/site_builder.py`. Append these helpers just below the existing `_WEEKDAY_NUM` constants block (near the `_next_occurrence_date` area — these are all pure-function helpers):

```python
_SCHEMA_DAY_NAMES = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
    "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
}


def _opening_hours_schema(hours: dict | None) -> list[dict]:
    """Convert a YAML `hours:` block into Schema.org openingHoursSpecification[].

    Input: {"mon": "16:00-22:00", "tue": null, ...}
    Output: list of {"@type": "OpeningHoursSpecification", "dayOfWeek": "Monday",
                     "opens": "16:00", "closes": "22:00"}
    Skips days with null values (closed).
    """
    if not hours:
        return []
    specs = []
    for day_key, rng in hours.items():
        if not rng:
            continue
        try:
            opens, closes = rng.split("-", 1)
        except ValueError:
            continue
        day_name = _SCHEMA_DAY_NAMES.get(day_key)
        if not day_name:
            continue
        specs.append({
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": day_name,
            "opens": opens,
            "closes": closes,
        })
    return specs
```

- [ ] **Step 2: Add `_business_schema()`**

Append:

```python
def _business_schema(biz: dict, upcoming_events: list[dict]) -> dict:
    """Build the LocalBusiness JSON-LD dict for one business."""
    metadata = biz.get("metadata") or {}
    schema: dict = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "@id": f"{SITE_URL}/business/{biz['slug']}/",
        "name": biz["name"],
        "url": f"{SITE_URL}/business/{biz['slug']}/",
    }
    if biz.get("website"):
        schema["sameAs"] = [biz["website"]] + list(metadata.get("same_as") or [])
    elif metadata.get("same_as"):
        schema["sameAs"] = list(metadata["same_as"])

    if biz.get("address"):
        schema["address"] = {
            "@type": "PostalAddress",
            "streetAddress": biz["address"].split(",")[0].strip(),
            "addressLocality": "Chicago",
            "addressRegion": "IL",
            "addressCountry": "US",
        }
    if biz.get("lat") and biz.get("lng"):
        schema["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": biz["lat"],
            "longitude": biz["lng"],
        }
    if metadata.get("telephone"):
        schema["telephone"] = metadata["telephone"]
    if metadata.get("price_range"):
        schema["priceRange"] = metadata["price_range"]
    if metadata.get("description"):
        schema["description"] = metadata["description"]
    hours_spec = _opening_hours_schema(biz.get("hours"))
    if hours_spec:
        schema["openingHoursSpecification"] = hours_spec

    # Representative image: most recent event flyer with an image
    for ev in upcoming_events:
        if ev.get("image_local_path"):
            schema["image"] = f"{SITE_URL}/{ev['image_local_path']}"
            break

    if upcoming_events:
        schema["event"] = [
            {
                "@type": "Event",
                "name": ev["title"],
                "url": f"{SITE_URL}/event/{ev['id']}/",
            }
            for ev in upcoming_events[:10]
        ]
    return schema
```

- [ ] **Step 3: Add `_breadcrumb_schema()`**

Append:

```python
def _breadcrumb_schema(items: list[tuple[str, str]]) -> dict:
    """Build a BreadcrumbList JSON-LD dict from a list of (name, url) tuples."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i + 1,
                "name": name,
                "item": url,
            }
            for i, (name, url) in enumerate(items)
        ],
    }
```

- [ ] **Step 4: Quick sanity-check**

```bash
python3 -c "
from src.site_builder import _business_schema, _breadcrumb_schema, _opening_hours_schema
print(_opening_hours_schema({'mon': '16:00-22:00', 'tue': None}))
print(_breadcrumb_schema([('Home', 'https://aville.net/'), ('Vincent', 'https://aville.net/business/vincent/')]))
"
```

Expected: lists/dicts print with correct Schema.org structure.

- [ ] **Step 5: Commit**

```bash
git add src/site_builder.py
git commit -m "feat: LocalBusiness + BreadcrumbList + OpeningHoursSpec JSON-LD helpers"
```

---

## Task 6: Business-detail HTML template

**Files:**
- Create: `templates/_business_detail.html`

- [ ] **Step 1: Create the template**

Template is structured top→bottom per the spec. Uses the same `<base href="/">` trick as `_event_detail.html` for relative asset loading, and reuses the same fonts/preload pattern.

```html
{% from "_tower.html" import tower %}
<!DOCTYPE html>
<html lang="en">
<head>
  <base href="/" />
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,500;0,700;0,900;1,500;1,700&family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Rubik+Mono+One&display=swap" onload="this.rel='stylesheet'">
  <noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,500;0,700;0,900;1,500;1,700&family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Rubik+Mono+One&display=swap"></noscript>
  <title>{{ biz.name }} — events & happy hours in Andersonville, Chicago | A'ville.net</title>

  <meta name="description" content="{{ biz.metadata.description if biz.metadata and biz.metadata.description else (biz.name ~ ' — events, happy hours, and specials in Andersonville, Chicago.') }}" />
  <meta property="og:title" content="{{ biz.name }} — Andersonville" />
  <meta property="og:description" content="{{ biz.metadata.description if biz.metadata and biz.metadata.description else ('Events and happy hours at ' ~ biz.name) }}" />
  <meta property="og:image" content="{{ site_url }}/images/og-home.jpg" />
  <meta property="og:url" content="{{ site_url }}/business/{{ biz.slug }}/" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="A'ville.net" />
  <meta name="twitter:card" content="summary_large_image" />
  <link rel="canonical" href="{{ site_url }}/business/{{ biz.slug }}/" />
  <link rel="alternate" type="text/markdown" href="/business/{{ biz.slug }}/index.md" title="Markdown version for AI agents" />
  <link rel="describedby" type="text/plain" href="/llms.txt" />
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon.ico">
  <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">
  <meta name="theme-color" content="#e8dec4">

  <script type="application/ld+json">{{ business_schema | tojson }}</script>
  <script type="application/ld+json">{{ breadcrumb_schema | tojson }}</script>

  <link rel="stylesheet" href="{{ event_css_href }}">
  <script async src="https://plausible.io/js/pa-narblFIcGa8B52d1H1XsM.js" data-domain="aville.net"></script>
  <script>
    window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};
    plausible.init()
  </script>
</head>
<body>

<div class="top">
  <div class="top-row">
    <a href="/">← Back to the board</a>
    <div class="crumbs">
      <a href="/">A'ville.net</a> · <b>{{ biz.name }}</b>
    </div>
    <div>{{ build_date.strftime('%a %b %-d') }}</div>
  </div>
</div>

<header class="masthead masthead-biz">
  <a href="/" class="mast-logo" aria-label="A'ville.net">{{ tower() }}</a>
  <h1 class="biz-title">{{ biz.name }}</h1>
  {% if biz.metadata and biz.metadata.description %}
  <p class="biz-address">{{ biz.address }}</p>
  {% endif %}
  <div class="biz-actions">
    {% if biz.metadata and biz.metadata.telephone %}<a href="tel:{{ biz.metadata.telephone }}">Call</a>{% endif %}
    {% if biz.website %}<a href="{{ biz.website }}" rel="noopener" target="_blank">Website ↗</a>{% endif %}
    {% if biz.address %}<a href="https://www.google.com/maps/search/?api=1&query={{ biz.address | urlencode }}" rel="noopener" target="_blank">Map ↗</a>{% endif %}
  </div>
</header>

<section id="spotlight" class="spotlight" data-show-when-empty="hide" hidden>
  <div class="spotlight-label">Happening right now</div>
  <div id="spotlight-slot"></div>
</section>

{% if biz.metadata and biz.metadata.description %}
<section class="biz-description">
  <p>{{ biz.metadata.description }}</p>
</section>
{% endif %}

<section class="biz-whats-on">
  <h2>What's happening</h2>
  {% if upcoming_dated %}
  <h3 class="biz-subhead">Coming up</h3>
  <div class="card-grid">
    {% for ev in upcoming_dated %}{% include "_event_card.html" %}{% endfor %}
  </div>
  {% endif %}
  {% if weekly_regulars %}
  <h3 class="biz-subhead">Weekly regulars</h3>
  <div class="card-grid">
    {% for ev in weekly_regulars %}{% include "_event_card.html" %}{% endfor %}
  </div>
  {% endif %}
  {% if not upcoming_dated and not weekly_regulars %}
  <p class="biz-empty">No current events listed at {{ biz.name }}. Check back soon.</p>
  {% endif %}
</section>

{% if biz.hours %}
<section class="biz-hours">
  <h2>Hours</h2>
  <table class="hours-table">
    {% for day_key, day_name in [('mon','Monday'),('tue','Tuesday'),('wed','Wednesday'),('thu','Thursday'),('fri','Friday'),('sat','Saturday'),('sun','Sunday')] %}
    <tr>
      <th scope="row">{{ day_name }}</th>
      <td>{% if biz.hours.get(day_key) %}{{ fmt_hours_range(biz.hours[day_key]) }}{% else %}Closed{% endif %}</td>
    </tr>
    {% endfor %}
  </table>
</section>
{% endif %}

{% if recent_flyers %}
<section class="biz-flyers">
  <h2>Recent flyers</h2>
  <div class="card-grid">
    {% for ev in recent_flyers[:4] %}{% include "_event_card.html" %}{% endfor %}
  </div>
  {% if recent_flyers | length > 4 %}
  <details class="flyers-more">
    <summary>See {{ recent_flyers | length - 4 }} more past event{{ '' if recent_flyers | length - 4 == 1 else 's' }}</summary>
    <div class="card-grid">
      {% for ev in recent_flyers[4:] %}{% include "_event_card.html" %}{% endfor %}
    </div>
  </details>
  {% endif %}
</section>
{% endif %}

{% if biz.website %}
<section class="biz-cta">
  <a href="{{ biz.website }}" class="cta-button" rel="noopener" target="_blank">Visit {{ biz.name }} ↗</a>
</section>
{% endif %}

<!-- Reuse the homepage happening-now JS: the event cards already carry
     data-start-time / data-end-time / data-recurrence-days attrs. -->
<script>
(function () {
  // Minimal copy of isHappeningNow + spotlight hoist from index.html.
  // If this gets complex, extract to a shared .js file in a follow-up.
  function chicagoNow() {
    const fmt = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Chicago', weekday: 'long',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
    const parts = Object.fromEntries(fmt.formatToParts(new Date()).map(p => [p.type, p.value]));
    const dow = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday']
      .indexOf(parts.weekday.toLowerCase());
    const nowMins = parseInt(parts.hour, 10) * 60 + parseInt(parts.minute, 10);
    return { dow, nowMins, prevDow: (dow + 6) % 7 };
  }
  function toMins(t) {
    if (!t) return null;
    const [h, m] = t.split(':').map(Number);
    return h * 60 + m;
  }
  function isHappeningNow(card) {
    const start = toMins(card.dataset.startTime);
    if (start === null) return false;
    const end = toMins(card.dataset.endTime);
    const days = (card.dataset.recurrenceDays || '')
      .split(',').filter(Boolean).map(Number);
    const { dow, nowMins, prevDow } = chicagoNow();
    if (days.length) {
      if (end !== null && end < start) {
        if (days.includes(dow) && nowMins >= start) return true;
        if (days.includes(prevDow) && nowMins < end) return true;
        return false;
      }
      if (!days.includes(dow)) return false;
    } else {
      const date = card.dataset.eventDate;
      if (!date) return false;
      const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Chicago' });
      if (date !== today) return false;
    }
    if (end !== null) return nowMins >= start && nowMins < end;
    return nowMins >= start && nowMins < start + 180;
  }
  const slot = document.getElementById('spotlight-slot');
  const container = document.getElementById('spotlight');
  if (!slot || !container) return;
  const liveCards = Array.from(document.querySelectorAll('.f')).filter(isHappeningNow);
  if (!liveCards.length) return;
  const first = liveCards[0].cloneNode(true);
  const img = first.querySelector('img');
  if (img) { img.loading = 'eager'; img.setAttribute('fetchpriority', 'high'); }
  slot.appendChild(first);
  container.hidden = false;
})();
</script>

</body>
</html>
```

- [ ] **Step 2: Confirm Jinja parses**

This is checked implicitly when we render in Task 9. No separate check needed.

- [ ] **Step 3: Commit**

```bash
git add templates/_business_detail.html
git commit -m "feat: business-detail HTML template with spotlight + flyer gallery"
```

---

## Task 7: Business-detail markdown template

**Files:**
- Create: `templates/_business.md`

- [ ] **Step 1: Create the template**

```markdown
# {{ biz.name }}

{% if biz.metadata and biz.metadata.description %}{{ biz.metadata.description }}
{% endif %}
{% if biz.address %}**Address:** {{ biz.address }}
{% endif %}{% if biz.metadata and biz.metadata.telephone %}**Phone:** {{ biz.metadata.telephone }}
{% endif %}{% if biz.website %}**Website:** {{ biz.website }}
{% endif %}{% if biz.metadata and biz.metadata.price_range %}**Price range:** {{ biz.metadata.price_range }}
{% endif %}{% if biz.metadata and biz.metadata.same_as %}**Social:** {% for url in biz.metadata.same_as %}<{{ url }}>{% if not loop.last %}, {% endif %}{% endfor %}
{% endif %}

{% if biz.hours %}## Hours

{% for day_key, day_name in [('mon','Monday'),('tue','Tuesday'),('wed','Wednesday'),('thu','Thursday'),('fri','Friday'),('sat','Saturday'),('sun','Sunday')] %}- **{{ day_name }}:** {% if biz.hours.get(day_key) %}{{ fmt_hours_range(biz.hours[day_key]) }}{% else %}Closed{% endif %}
{% endfor %}
{% endif %}
{% if upcoming_dated %}## Coming up

{% for ev in upcoming_dated %}- [{{ ev.title }}]({{ site_url }}/event/{{ ev.id }}/) — {{ when_text(ev) }}
{% endfor %}
{% endif %}
{% if weekly_regulars %}## Weekly regulars

{% for ev in weekly_regulars %}- [{{ ev.title }}]({{ site_url }}/event/{{ ev.id }}/) — {{ when_text(ev) }}
{% endfor %}
{% endif %}
{% if recent_flyers %}## Recent flyers

{% for ev in recent_flyers %}- [{{ ev.title }}]({{ site_url }}/event/{{ ev.id }}/) — {{ when_text(ev) }}
{% endfor %}
{% endif %}
---

- Canonical URL: {{ site_url }}/business/{{ biz.slug }}/
- HTML version: {{ site_url }}/business/{{ biz.slug }}/
- Back to event listing: {{ site_url }}/
```

- [ ] **Step 2: Commit**

```bash
git add templates/_business.md
git commit -m "feat: business-detail markdown template"
```

---

## Task 8: `_build_business_pages()` + wire into `build_site()`

**Files:**
- Modify: `src/site_builder.py`

- [ ] **Step 1: Add `fmt_hours_range()` helper**

Add near `_fmt_time()` (top of file). Templates use it to render `"16:00-22:00"` as `"4pm–10pm"`.

```python
def _fmt_hours_range(rng: str | None) -> str:
    """'16:00-22:00' → '4pm–10pm'. Returns '' on parse failure."""
    if not rng or "-" not in rng:
        return ""
    try:
        opens, closes = rng.split("-", 1)
        return _humanrange(opens, closes)
    except Exception:
        return ""
```

- [ ] **Step 2: Add the builder function**

Add before `_build_sitemap()`:

```python
def _build_business_pages(
    html_template,
    md_template,
    businesses: list[dict],
    all_rows: list,
    public_dir: Path,
    build_date: date,
    event_css_href: str,
    site_url: str,
) -> None:
    """Render /business/{slug}/index.html + index.md for each business."""
    # Group events by business_slug
    events_by_slug: dict[str, list[dict]] = defaultdict(list)
    for row in all_rows:
        ev = dict(row)
        ev["tags"] = json.loads(ev.get("tags") or "[]")
        ev["performers"] = json.loads(ev.get("performers") or "[]")
        events_by_slug[ev["business_slug"]].append(ev)

    count = 0
    for biz in businesses:
        slug = biz["slug"]
        biz_events = events_by_slug.get(slug, [])

        # Bucket by kind + status
        active = [e for e in biz_events if e["status"] == "active"]
        stale = [e for e in biz_events if e["status"] == "stale"]
        upcoming_dated = sorted(
            [e for e in active if e["kind"] == "dated" and e.get("start_datetime")],
            key=lambda e: e["start_datetime"],
        )
        weekly_regulars = sorted(
            [e for e in active if e["kind"] == "recurring"
             and not _is_ended_series(e, build_date)],
            key=lambda e: _recurrence_sort_key(e.get("recurrence_pattern")),
        )
        # Recent flyers: stale events, most-recent-first by last_seen_at
        recent_flyers = sorted(
            stale,
            key=lambda e: (e.get("last_seen_at") or ""),
            reverse=True,
        )

        business_schema = _business_schema(biz, upcoming_dated)
        breadcrumb_schema = _breadcrumb_schema([
            ("Home", f"{site_url}/"),
            (biz["name"], f"{site_url}/business/{slug}/"),
        ])

        page_dir = public_dir / "business" / slug
        page_dir.mkdir(parents=True, exist_ok=True)

        html = html_template.render(
            biz=biz,
            upcoming_dated=upcoming_dated,
            weekly_regulars=weekly_regulars,
            recent_flyers=recent_flyers,
            business_schema=business_schema,
            breadcrumb_schema=breadcrumb_schema,
            build_date=build_date,
            site_url=site_url,
            event_css_href=event_css_href,
        )
        (page_dir / "index.html").write_text(html)

        md = md_template.render(
            biz=biz,
            upcoming_dated=upcoming_dated,
            weekly_regulars=weekly_regulars,
            recent_flyers=recent_flyers,
            site_url=site_url,
        )
        (page_dir / "index.md").write_text(md)
        count += 1

    print(f"  {count} business page(s) written to public/business/ (html + md)")
```

- [ ] **Step 3: Wire into `build_site()`**

Inside `build_site()`, find where templates are loaded (near the existing `index_md_template = env.get_template("index.md")` line). Add:

```python
    business_html_template = env.get_template("_business_detail.html")
    business_md_template = env.get_template("_business.md")
```

Find the `env.globals[...]` block and add:

```python
    env.globals["fmt_hours_range"] = _fmt_hours_range
```

Near the top of `build_site()` (before the DB read), add:

```python
    businesses_doc = _ensure_geocoded(CONFIG_DIR / "businesses.yaml")
    businesses = businesses_doc["businesses"]
```

Then find the line `_build_event_pages(detail_template, event_md_template, all_rows, ...)` and add right after it:

```python
    _build_business_pages(
        business_html_template,
        business_md_template,
        businesses,
        all_rows,
        PUBLIC_DIR,
        build_date,
        event_css_href,
        SITE_URL,
    )
```

- [ ] **Step 4: First full build**

```bash
python3 scripts/build_site.py
```

Expected output includes:
```
  23 business page(s) written to public/business/ (html + md)
```

Plus possibly `geocoding …` lines on first run (≈25s) if lat/lng are not already in YAML.

- [ ] **Step 5: Spot-check a page**

```bash
ls public/business/ && cat public/business/vincent/index.md | head -30
```

Expected: 23 directories; Vincent's markdown renders with description, hours, events.

- [ ] **Step 6: Spot-check the JSON-LD**

```bash
grep -A 1 "application/ld+json" public/business/vincent/index.html | head -10
```

Expected: JSON-LD blocks for LocalBusiness and BreadcrumbList present.

- [ ] **Step 7: Commit (include any YAML lat/lng updates)**

```bash
git add src/site_builder.py config/businesses.yaml
git commit -m "feat: build /business/{slug}/ pages (HTML + markdown) with LocalBusiness JSON-LD"
```

---

## Task 9: Re-target event card business link

**Files:**
- Modify: `templates/_event_card.html`

- [ ] **Step 1: Find the current link**

```bash
grep -n "business_website\|business_name" templates/_event_card.html
```

Expected: shows the `<a>` wrapping the business name, currently pointing at `e.business_website` or similar.

- [ ] **Step 2: Rewrite the link**

Open `templates/_event_card.html`. Locate the anchor around the business name — typically structured like:

```html
<a class="f-venue" href="{{ e.business_website }}" rel="noopener" target="_blank">{{ e.business_name }}</a>
```

Replace with:

```html
<a class="f-venue" href="/business/{{ e.business_slug }}/">{{ e.business_name }}</a>
```

(No more `target="_blank"` — this is an internal link.)

- [ ] **Step 3: Rebuild + spot-check**

```bash
python3 scripts/build_site.py && grep -c 'href="/business/' public/index.html
```

Expected: nonzero count (one per event card showing the venue).

- [ ] **Step 4: Commit**

```bash
git add templates/_event_card.html
git commit -m "feat: event cards link business names to internal /business/{slug}/ pages"
```

---

## Task 10: Event detail page — breadcrumb + link rewrite + BreadcrumbList

**Files:**
- Modify: `templates/_event_detail.html`
- Modify: `src/site_builder.py` (pass breadcrumb schema into event pages)

- [ ] **Step 1: Add breadcrumb schema to `_build_event_pages()`**

In `src/site_builder.py`, locate the existing `html = template.render(...)` call inside `_build_event_pages()`. Just before it, add:

```python
        breadcrumb_schema = _breadcrumb_schema([
            ("Home", f"{SITE_URL}/"),
            (ev.get("business_name", ""), f"{SITE_URL}/business/{ev.get('business_slug', '')}/"),
            (ev["title"], event_url),
        ])
```

Then pass it to the template:

```python
        html = template.render(
            e=ev,
            is_stale=is_stale,
            related_events=related,
            event_when=event_when,
            kicker=_kicker(ev, build_date),
            site_url=SITE_URL,
            build_date=build_date,
            issue_number=issue_number,
            event_css_href=event_css_href,
            breadcrumb_schema=breadcrumb_schema,
        )
```

- [ ] **Step 2: Inject the JSON-LD into `_event_detail.html`**

Find the existing `<script type="application/ld+json">` block containing the Event schema. Just after its closing `</script>`, add:

```html
  <script type="application/ld+json">{{ breadcrumb_schema | tojson }}</script>
```

- [ ] **Step 3: Rewrite the visible crumbs to link the business**

Find the existing top-bar crumb line:

```html
<div class="crumbs">A'ville.net · <b>{{ e.business_name }}</b> · {{ e.title | truncate(40, true, '…') }}</div>
```

Replace with:

```html
<div class="crumbs">
  <a href="/">A'ville.net</a>
  · <a href="/business/{{ e.business_slug }}/">{{ e.business_name }}</a>
  · <b>{{ e.title | truncate(40, true, '…') }}</b>
</div>
```

- [ ] **Step 4: Rewrite any other business-name links in the body**

Search for business-name anchors in `_event_detail.html`:

```bash
grep -n "business_website\|business_slug" templates/_event_detail.html
```

For each match that wraps `e.business_name` or variant, replace the `href` with `/business/{{ e.business_slug }}/` and drop `target="_blank"`/`rel="noopener"` (now internal). If the business's *external* website is still rendered separately as a "Visit [venue] ↗" CTA, keep that external link — only the business-as-entity links get rewritten.

- [ ] **Step 5: Rebuild + verify**

```bash
python3 scripts/build_site.py
grep -c 'href="/business/vincent/"' public/event/*/index.html | head -5
```

Expected: any Vincent event's detail page contains the internal business link at least once.

```bash
grep -A 0 "BreadcrumbList" public/event/41/index.html
```

(Event 41 is a Vincent event per the earlier extraction.) Expected: at least one hit.

- [ ] **Step 6: Commit**

```bash
git add templates/_event_detail.html src/site_builder.py
git commit -m "feat: breadcrumbs + BreadcrumbList JSON-LD on event detail pages"
```

---

## Task 11: Sitemap includes business URLs

**Files:**
- Modify: `src/site_builder.py`

- [ ] **Step 1: Extend `_build_sitemap()`**

Find the existing `_build_sitemap(all_rows, public_dir)` function. Change its signature to accept `businesses`, and add the business URLs to the URL list:

```python
def _build_sitemap(all_rows: list, businesses: list[dict], public_dir: Path) -> None:
    active_rows = [row for row in all_rows if row["status"] == "active"]

    def _lm(dt_str: str | None) -> str:
        if not dt_str:
            return ""
        try:
            return datetime.fromisoformat(dt_str).astimezone(CHICAGO).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return ""

    site_lm = max(
        (_lm(row["last_extracted_at"]) for row in active_rows if row["last_extracted_at"]),
        default="",
    )

    def _url(loc: str, lastmod: str) -> str:
        inner = f"<loc>{loc}</loc>"
        if lastmod:
            inner += f"<lastmod>{lastmod}</lastmod>"
        return f"  <url>{inner}</url>"

    urls = [_url(f"{SITE_URL}/", site_lm)]
    urls += [
        _url(f"{SITE_URL}/business/{biz['slug']}/", site_lm)
        for biz in businesses
    ]
    urls += [
        _url(f"{SITE_URL}/event/{row['id']}/", _lm(row["last_extracted_at"]))
        for row in active_rows
    ]
    active_ids = [row["id"] for row in active_rows]
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    (public_dir / "sitemap.xml").write_text(sitemap)
    # Content-Signal: opt in to AI training, search indexing, and real-time AI
    # retrieval. The site exists to surface neighborhood events — being found
    # by agents and LLMs is the goal. See contentsignals.org.
    (public_dir / "robots.txt").write_text(
        "User-agent: *\n"
        "Content-Signal: ai-train=yes, search=yes, ai-input=yes\n"
        "Allow: /\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    print(f"  sitemap.xml ({len(active_ids)} event URLs + {len(businesses)} business URLs) + robots.txt written")
```

- [ ] **Step 2: Update the call site in `build_site()`**

Find the existing `_build_sitemap(all_rows, PUBLIC_DIR)` call and change to:

```python
    _build_sitemap(all_rows, businesses, PUBLIC_DIR)
```

- [ ] **Step 3: Rebuild + verify**

```bash
python3 scripts/build_site.py && grep -c "/business/" public/sitemap.xml
```

Expected: 23.

- [ ] **Step 4: Commit**

```bash
git add src/site_builder.py
git commit -m "feat: sitemap includes /business/{slug}/ URLs"
```

---

## Task 12: `/llms.txt` links venue entries to business pages

**Files:**
- Modify: `src/site_builder.py`

- [ ] **Step 1: Change `_build_llms_txt()` signature + body**

Replace the current function definition with:

```python
def _build_llms_txt(
    public_dir: Path,
    businesses: list[dict],
    last_updated: str,
    build_date: date,
) -> None:
    """Write /llms.txt — a compact orientation page for LLM agents."""
    lines: list[str] = [
        "# A'ville.net",
        "",
        "> Andersonville, Chicago events aggregator. Pulls events, happy hours, live music, drag shows, trivia, theater, and food/drink specials daily from neighborhood bar, restaurant, and venue websites. All times are local to America/Chicago.",
        "",
        f"Last updated: {last_updated or build_date.strftime('%A, %B %-d, %Y')}.",
        "",
        "## Primary resources",
        "",
        f"- [Event listing (markdown)]({SITE_URL}/index.md) — all current events grouped by tonight / this weekend / later / weekly regulars",
        f"- [Event listing (HTML)]({SITE_URL}/) — human-facing homepage, same content",
        f"- [Sitemap]({SITE_URL}/sitemap.xml) — every event has a canonical URL at `{SITE_URL}/event/{{id}}/` and every venue at `{SITE_URL}/business/{{slug}}/`",
        "",
        "## Per-event pages",
        "",
        f"Each event has both an HTML page at `{SITE_URL}/event/{{id}}/` and a markdown sibling at `{SITE_URL}/event/{{id}}/index.md` with the same content. Detail pages include the canonical URL, venue, address, when, performers, price, description, and a link to the source event page on the business's own website.",
        "",
        "## Per-venue pages",
        "",
        f"Each venue has a canonical entity page at `{SITE_URL}/business/{{slug}}/` (and a markdown sibling at `index.md`) with a `LocalBusiness` JSON-LD block, address, hours, and the list of current + recent events at that venue.",
        "",
        "## Structured data",
        "",
        f"- Every event page embeds Schema.org `Event` JSON-LD plus `BreadcrumbList` (Home → Business → Event).",
        f"- Every business page embeds Schema.org `LocalBusiness` JSON-LD plus `BreadcrumbList` (Home → Business).",
        f"- The homepage embeds `WebSite` + `ItemList` JSON-LD.",
        "",
        "## Venues currently covered",
        "",
    ]
    for biz in sorted(businesses, key=lambda b: b["name"].lower()):
        lines.append(f"- [{biz['name']}]({SITE_URL}/business/{biz['slug']}/)")
    lines.extend(
        [
            "",
            "## Usage",
            "",
            "Content on this site is explicitly opted in to AI training, search indexing, and real-time AI retrieval (see `/robots.txt` Content-Signal). Freely cite events and venues with their canonical URLs. The site is non-commercial and has no API auth.",
            "",
        ]
    )
    (public_dir / "llms.txt").write_text("\n".join(lines))
    print(f"  llms.txt written ({len(businesses)} venues listed, linked)")
```

- [ ] **Step 2: Update the call site in `build_site()`**

Replace the existing:

```python
    _build_llms_txt(PUBLIC_DIR, venue_list, last_updated, build_date)
```

with:

```python
    _build_llms_txt(PUBLIC_DIR, businesses, last_updated, build_date)
```

- [ ] **Step 3: Rebuild + verify**

```bash
python3 scripts/build_site.py && grep -c "business/" public/llms.txt
```

Expected: ≥23 (venue list + the structured-data references).

- [ ] **Step 4: Commit**

```bash
git add src/site_builder.py
git commit -m "feat: llms.txt venue list links to /business/{slug}/ canonical pages"
```

---

## Task 13: CSS for new business-detail elements

**Files:**
- Modify: `styles/event.css` (business pages share this stylesheet via `event_css_href`)

- [ ] **Step 1: Append business-detail styles**

Append to `styles/event.css`:

```css
/* ── Business detail page ── */
.masthead-biz {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 2rem 1rem 1rem;
  text-align: center;
}
.masthead-biz .mast-logo { display: inline-block; width: 64px; height: auto; opacity: 0.9; }
.biz-title { font-family: 'Fraunces', serif; font-size: clamp(2rem, 5vw, 3rem); margin: 0.25rem 0; }
.biz-address { font-family: 'Space Grotesk', sans-serif; color: var(--ink-2, #4a4338); margin: 0; }
.biz-actions { display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; margin-top: 0.75rem; }
.biz-actions a { font-family: 'Space Grotesk', sans-serif; font-weight: 600; text-decoration: underline; }

.biz-description { max-width: 42rem; margin: 1.5rem auto; padding: 0 1rem; font-family: 'Fraunces', serif; font-size: 1.15rem; line-height: 1.6; }

.biz-whats-on { max-width: 72rem; margin: 2rem auto; padding: 0 1rem; }
.biz-whats-on h2, .biz-hours h2, .biz-flyers h2 { font-family: 'Rubik Mono One', sans-serif; font-size: 1.25rem; margin-bottom: 1rem; }
.biz-subhead { font-family: 'Space Grotesk', sans-serif; text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.9rem; margin: 1.5rem 0 0.75rem; opacity: 0.75; }
.biz-empty { font-style: italic; opacity: 0.7; }

.biz-hours { max-width: 30rem; margin: 2rem auto; padding: 0 1rem; }
.hours-table { width: 100%; border-collapse: collapse; font-family: 'Space Grotesk', sans-serif; }
.hours-table th, .hours-table td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--ink-4, #e8dec4); text-align: left; }
.hours-table th { font-weight: 600; width: 8rem; }

.biz-flyers { max-width: 72rem; margin: 2rem auto; padding: 0 1rem; }
.flyers-more { margin-top: 1.5rem; }
.flyers-more summary { cursor: pointer; font-family: 'Space Grotesk', sans-serif; font-weight: 600; padding: 0.5rem 0; }
.flyers-more summary:hover { text-decoration: underline; }

.biz-cta { text-align: center; margin: 3rem auto 2rem; }
.cta-button {
  display: inline-block;
  background: var(--ink-0, #1a1812);
  color: var(--bg, #e8dec4);
  padding: 0.9rem 1.75rem;
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 700;
  text-decoration: none;
  border-radius: 4px;
  transition: transform 0.15s;
}
.cta-button:hover { transform: translateY(-2px); }
```

- [ ] **Step 2: Rebuild**

```bash
python3 scripts/build_site.py
```

`_publish_css()` will produce a fresh hash for `event.css`. Business pages already reference it via `event_css_href`.

- [ ] **Step 3: Open a page in the browser**

```bash
open public/business/vincent/index.html
```

Visual check: masthead centered, description legible, card grid renders, hours table rows laid out, CTA button visible. Minor spacing tweaks are fine to iterate.

- [ ] **Step 4: Commit**

```bash
git add styles/event.css
git commit -m "feat: minimal styles for business-detail page layout"
```

---

## Task 14: Final build + spot-check + update .gitignore if needed

**Files:**
- Modify: `.gitignore` (conditionally)

- [ ] **Step 1: Full clean build**

```bash
python3 scripts/build_site.py 2>&1 | tail -15
```

Expected output ends with:
```
  23 business page(s) written to public/business/ (html + md)
  ...
  sitemap.xml (N event URLs + 23 business URLs) + robots.txt written
  llms.txt written (23 venues listed, linked)
  Build assertions: OK (...)
```

- [ ] **Step 2: Check git status for business artifacts**

```bash
git status --short | grep -E "public/business|public/llms|public/index\.md"
```

`public/business/` is likely untracked. Decide: follow the `public/index.html` pattern (build artifacts excluded from git) or commit with the repo (consistent with `public/event/` which is already untracked but not gitignored).

If matching the `public/index.html` pattern, append to `.gitignore`:

```
public/business/
```

(Per this project's convention: `public/index.html`, `public/index.md`, `public/llms.txt`, `public/*.css` are gitignored; other build outputs in `public/` are untracked but not explicitly ignored. `public/business/` fits the former pattern — per-page HTML/MD regenerated on every build.)

- [ ] **Step 3: Spot-check three business pages in the browser**

```bash
open public/business/vincent/index.html
open public/business/hopleaf/index.html
open public/business/atmosphere/index.html
```

Check each:
- Masthead renders with name + address + action row
- Description paragraph present (if metadata extracted)
- "What's happening" populated or empty-state shown
- Hours table correct
- Recent flyers show past events (if any) with `<details>` disclosure beyond 4
- CTA button at bottom links to external site

- [ ] **Step 4: Validate a business page's JSON-LD with Google Rich Results Test**

Since the site is not yet deployed with this change, paste the page HTML directly:
- Open https://search.google.com/test/rich-results
- Click "Code snippet" tab
- Paste contents of `public/business/vincent/index.html`
- Expected: `LocalBusiness` and `BreadcrumbList` both detected with no errors.

Note any warnings (e.g., "missing telephone") — acceptable if the extraction didn't find that field.

- [ ] **Step 5: Spot-check an event page for breadcrumbs**

```bash
open public/event/41/index.html
```

- Top-bar crumbs: `A'ville.net › Vincent › Half Off Mussels` (all links except last)
- Page HTML contains two JSON-LD blocks: Event + BreadcrumbList

- [ ] **Step 6: Spot-check one business markdown sibling**

```bash
cat public/business/vincent/index.md
```

Check: clean markdown, description paragraph, hours table rendered as bullet list, upcoming/regular/stale events listed with canonical URLs.

- [ ] **Step 7: Curl the homepage to verify Link headers still work (optional, if a local server is running)**

Link headers apply in production via `.htaccess`; can't verify from `file://`. Deferred to post-deploy verification.

- [ ] **Step 8: Commit final artifacts**

```bash
git add .gitignore   # if modified
git status           # confirm clean beyond any intentional config/businesses.yaml updates
git diff --stat HEAD~12  # show all changes in this feature
```

No separate commit needed if `.gitignore` wasn't modified. If it was:

```bash
git add .gitignore
git commit -m "chore: gitignore public/business/ build artifacts"
```

- [ ] **Step 9: Push and trigger site-rebuild deploy**

```bash
git push origin main
gh workflow run "Site rebuild"
gh run list --workflow="Site rebuild" --limit 1
```

Expected: workflow queued. After it completes (~5 min), open https://aville.net/business/vincent/ and verify it's live.

- [ ] **Step 10: Post-deploy verification**

On the live site:

```bash
curl -s -I https://aville.net/business/vincent/ | grep -i "link\|content-type"
```

Expected: `Link:` headers for sitemap / describedby / alternate markdown; `Content-Type: text/html`.

```bash
curl -s -I https://aville.net/business/vincent/index.md | grep -i "content-type"
```

Expected: `Content-Type: text/markdown; charset=utf-8`.

Then hit the Google Rich Results Test with the live URL `https://aville.net/business/vincent/` for a final confirmation.

---

## Definition of done

- [ ] 23 business pages at `/business/{slug}/` render HTML + markdown cleanly.
- [ ] Every page has `LocalBusiness` and `BreadcrumbList` JSON-LD with no Rich Results Test errors.
- [ ] Event cards' business-name links now point at internal `/business/{slug}/` pages.
- [ ] Event detail pages show a visible 3-level breadcrumb + `BreadcrumbList` JSON-LD.
- [ ] `/sitemap.xml` includes 23 new business URLs.
- [ ] `/llms.txt` venue list has 23 linked entries.
- [ ] Site-rebuild workflow succeeds; live site serves the new pages with expected Link headers.
- [ ] Updated `CLAUDE.md` handoff entry (session log — handled separately, not part of this plan).
