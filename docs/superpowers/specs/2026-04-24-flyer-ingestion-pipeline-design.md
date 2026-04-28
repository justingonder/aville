# Flyer-ingestion pipeline (web-search-seeded)
**Date:** 2026-04-24 (started) / 2026-04-27 (resumed and completed)
**Status:** READY FOR REVIEW — full design captured across Sections A, B, C. Awaiting user sign-off, then transition to writing-plans.
**Branch:** `flyer-ingestion-design`

---

## Goal

Build a pipeline that ingests photos of paper flyers (taken on Clark St walks) into the same `events` table the website-scraping pipeline writes to. The flyer photo is a **seed**, not the source: the pipeline uses it to identify the event, runs a web search to find an authoritative source, and extracts from THAT source. Flyers without a web trace are skipped — too niche for aville.net is the right filter.

## Why this shape (key insight)

Treating the flyer as a seed instead of a source unlocks a clean architecture:
- `source_page_url` stays a real URL (no synthetic conventions, no schema changes).
- Cross-verification: the web source disambiguates flyer noise (e.g., nail-salon "MANICURE" decals around a Mother's Day market flyer don't appear in the search results, so they're noise).
- Self-filtering: if the event isn't on the web at all, it's probably too low-profile to bother with.
- Existing `extract_events()` pipeline + multimodal Claude call do most of the heavy lifting unchanged.
- Same pattern could later help the existing CLAUDE.md item "Nav-link discovery for new special pages" — where businesses we already track occasionally publish events at URLs not in `businesses.yaml`.

## Decisions made (don't re-litigate)

1. **Treat flyer as seed, not source.** Web-search-confirmed extraction; skip if no web trace. (User affirmed 2026-04-24 after considering simpler "ingest flyer directly as primary source" alternative.)
2. **On dedup match: pause + check for enrichment.** When a flyer matches an existing DB event, the CLI pauses and offers `[s]kip / [e]nrich / [p]roceed-as-new`. The "enrich" path runs the full web-extraction pipeline anyway and applies only the fields that fill gaps in the existing record. (User chose this over silent-skip or auto-merge.)
3. **Auto-add new businesses inline.** When the web search confirms an event at a venue not in `businesses.yaml`, the CLI auto-adds the business, runs `extract_business_metadata.py` and `geocode_businesses.py` against it, and continues. Truly silent — no per-business confirmation prompt; the sidecar log records "added new business: <slug>" so adds are auditable post-run via `git diff config/businesses.yaml`. Justification: the project is in build-up phase; new venues are common and equally legitimate.
4. **Batch ergonomics: directory mode, with Claude identifying business per photo.** User points the CLI at a folder of phone-named photos (`IMG_20260424_143022.jpg`-style). For each photo, Claude extracts seeds including a venue name; CLI fuzzy-matches against `businesses.yaml`. Only prompts when uncertain. No pre-renaming or manifest required.
5. **Phone photo is signal-only, never displayed.** The flyer photo is fed to Claude as multimodal context (seed extraction + Step 5 cross-verification) but never written to `image_local_path`. If the web source has no clean image, the event is upserted with no image and renders with the existing poster fallback. Phone photos are too unreliable for display (window reflections, perspective skew, decorative shadows, surrounding storefront branding). (User decision 2026-04-27.)
6. **Sidecar log per run for resumability.** Each batch writes a `<dir>/.ingest_log.json` recording each photo's outcome. Re-running the same `--dir` skips photos already in the log unless `--force`. Doubles as the data source for the per-walk summary. (User decision 2026-04-27.)
7. **No-web-trace = silent skip + log.** When the web search returns nothing meeting the allowlist bar, the CLI logs `skipped:no-web-trace` (with the queries tried) and moves on. No interactive pause. To retry a specific flyer with manual help, re-run that one photo with `--source-url` (see Section B). (User decision 2026-04-27.)
8. **Two preview flags: `--dry-run` and `--seed-only`.** `--dry-run` runs the full pipeline (Claude calls + web search + extraction) but skips all writes (DB, YAML, sidecar log). `--seed-only` runs Step 1 only — cheap preview for "is this photo readable?" / iterating on the seed-extraction prompt. (User decision 2026-04-27.)
9. **Hybrid file layout.** Single `scripts/ingest_flyer.py` orchestrates. Seed-extraction prompt lives in `src/prompts.py`. Web-search-result-ranking helper lives in a new `src/web_search.py` (positioned for reuse by the CLAUDE.md "Nav-link discovery for new special pages" follow-up). Fuzzy business matching stays inline in the script (single use case for now). Allowlist lives in `config/web_search_allowlist.yaml` (config-over-code). (User decision 2026-04-27.)
10. **Authoritative-source allowlist v1.** Venue's own domain (always Tier 1) + Eventbrite + Do312 + Time Out Chicago + Chicago Reader + Andersonville Chamber + Block Club Chicago + Patch.com + Choose Chicago. The list is meant to evolve based on what actually returns useful results in practice; the YAML config makes it easy to add/remove without code changes. (User decision 2026-04-27.)

## Section A — Per-photo pipeline

For each photo in the walk folder:

### Step 1 — Cheap seed extraction
Single Claude Haiku call (~$0.002). Prompt explicitly says "the flyer content is the authoritative signal; ignore window decals, surrounding store branding, decorative shadows, anything not part of the flyer itself." Returns:

```json
{
  "event_title":          "Wander Home Holiday Market",
  "venue_name":           "The Guesthouse Hotel",
  "date_hint":            "May 2nd",
  "time_hint":            "12pm–6pm",
  "kind_guess":           "dated",
  "distinctive_strings":  ["Mother's Day Edition", "10+ local vendors"],
  "flyer_image_is_clean": true,
  "seed_confidence":      "high"
}
```

### Step 2 — Resolve the business
Fuzzy-match `venue_name` against `businesses.yaml`. Three outcomes: confident match → use slug; ambiguous → show top 2–3 candidates and ask; no match → flag as new (Step 6 will handle).

### Step 3 — Dedup against DB (the cheap gate)
Query existing events at this business. Match rule:
- Dated: same business + date within ±2 days + fuzzy title similarity ≥ threshold.
- Recurring: same business + matching `recurrence_pattern` + start-time within 30 min.

If match: pause. Show the candidate with a field-by-field comparison vs. seeds. Prompt `[s]kip / [e]nrich / [p]roceed-as-new / [q]uit`.

If no match: continue.

### Step 4 — Web search for the authoritative source
Query built from seeds (event title + venue, plus distinctive strings as fallback). Run WebSearch. Rank against the two-tier allowlist (full list in Decision 10, full domain spec in Section C):
1. **Tier 1** — venue's own domain (computed dynamically: `businesses.yaml` `website` for known venues; the seed-extracted result's domain for unknown venues).
2. **Tier 2** — the curated list of Chicago aggregators in `config/web_search_allowlist.yaml`.

Tier 1 wins if present. Otherwise the highest-ranked Tier 2 hit. Anything outside the allowlist is rejected. If no result clears the bar: skip with `"no web trace — skipping"`.

### Step 5 — Full extraction from the authoritative URL
Fetch the URL. Run existing `extract_events()` with multimodal context: HTML text + the flyer photo. Prompt note: "the flyer is a signal; the web source is authoritative; cross-reference and prefer web for ambiguity."

Image asset: only the web source is considered for the displayed flyer image. The phone photo is signal-only and is never written to `image_local_path` — it's too unreliable (window reflections, perspective skew, decorative shadows, surrounding storefront branding). If the web source has no clean image, the event is upserted with no image and renders with the existing poster fallback. (User decision 2026-04-27.)

### Step 6 — Auto-add business if new
If Step 2 found no match: now (with the web search result as a confirmed signal), append to `businesses.yaml`:
- `name` — from the seed.
- `website` — derived from the search result's domain (or, if the search result is itself the venue's homepage, the result URL).
- `address` — best-effort: if the search result page (Eventbrite, Block Club, Do312, etc.) exposes a venue address, capture it; otherwise leave null. The existing `LocalBusiness` schema and `/business/{slug}/` landing page tolerate a missing address; we'd rather have a null we can backfill manually than a wrong one auto-extracted.

Then run `python3 scripts/extract_business_metadata.py <slug>` (description, telephone, price_range, sameAs) and `python3 scripts/geocode_businesses.py <slug>` (lat/lng) as subprocesses. Continue with the resolved slug for Step 5.

### Step 7 — Upsert
- "New event" path: standard `upsert_event()`.
- "Enrich existing" path: read existing row, diff against extracted data, upsert only the gap-filling fields. Always update `last_seen_at`.

---

## Section B — CLI UX

### Invocation

```
# Single photo (iteration / one-off testing)
python3 scripts/ingest_flyer.py path/to/photo.jpg

# Directory batch (a Clark St walk)
python3 scripts/ingest_flyer.py --dir walks/2026-04-27/

# Manual URL override — bypasses Step 4 (web search) and goes straight to Step 5.
# Use this for flyers that hit "skipped:no-web-trace" in a prior run after
# you've done your own Google search and found the authoritative source.
python3 scripts/ingest_flyer.py path/to/photo.jpg --source-url https://example.com/event-page

# Cheap preview — Step 1 only. Prints what Claude sees in each photo. Iterate
# on the seed-extraction prompt without burning the full pipeline cost.
python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --seed-only

# Full pipeline, no writes. Reports what *would* happen. Same Claude/web cost
# as a real run; only side effects are skipped (DB, businesses.yaml, sidecar log).
python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --dry-run

# Re-process photos already in the sidecar log (default skips them).
python3 scripts/ingest_flyer.py --dir walks/2026-04-27/ --force
```

When given a single photo path, the sidecar log lives in the photo's parent directory: `<photo_parent_dir>/.ingest_log.json`. When given `--dir`, the log lives at `<dir>/.ingest_log.json`. `--source-url` is incompatible with `--dir` (single-photo only).

### Sidecar log shape

`<dir>/.ingest_log.json` — append-only, one entry per photo processed:

```json
{
  "version": 1,
  "started_at": "2026-04-27T15:30:12-05:00",
  "entries": [
    {
      "photo": "IMG_20260424_143022.jpg",
      "started_at": "2026-04-27T15:30:14-05:00",
      "finished_at": "2026-04-27T15:30:42-05:00",
      "outcome": "ingested",
      "event_id": 247,
      "business_slug": "guesthouse-hotel",
      "business_added": true,
      "source_url": "https://www.blockclubchicago.org/...",
      "seed": { "...": "..." }
    },
    {
      "photo": "IMG_20260424_143058.jpg",
      "outcome": "skipped:no-web-trace",
      "queries_tried": ["Wander Home Holiday Market Andersonville", "..."],
      "seed": { "...": "..." }
    },
    {
      "photo": "IMG_20260424_143112.jpg",
      "outcome": "skipped:dedup-match",
      "matched_event_id": 198,
      "match_score": 0.91
    }
  ]
}
```

Outcome values: `ingested`, `enriched`, `proceeded-as-new`, `skipped:dedup-match`, `skipped:no-web-trace`, `skipped:user-quit`, `failed:<reason>`.

### Interactive prompts

The pipeline runs autonomously through the easy cases (clean business match, no DB dedup match, web search succeeds, new business auto-added). Two situations pause for input:

**Ambiguous business match (Step 2).** Multiple candidates from `businesses.yaml` fuzzy-match the flyer's `venue_name`:

```
Photo: IMG_20260424_143022.jpg
Flyer says: "The Guesthouse Hotel"

Closest matches in businesses.yaml:
  [1] guesthouse-hotel  — The Guesthouse Hotel  (score 0.94)
  [2] guesthouse-bar    — Guesthouse Bar         (score 0.71)
  [3] none of these — treat as new business
  [s] skip this photo
  [q] quit batch

Pick:
```

Single-key input. `[1]` and `[2]` use the matched slug for Step 3. `[3]` flags new-business and Step 6 will run after the web search confirms.

**Dedup match (Step 3).** A flyer's seeds match an existing DB event at the resolved business:

```
Photo: IMG_20260424_143058.jpg
Flyer seed: "Drag Brunch — Saturday May 4, 12pm" at replay-andersonville
Existing event #198: "Drag Brunch" (recurring weekly:saturday, 12:00–14:00)
Match score: 0.89

Field-by-field comparison:
  title:      seed='Drag Brunch'        existing='Drag Brunch'             ✓
  start_time: seed='12:00'              existing='12:00'                   ✓
  end_time:   seed=null                 existing='14:00'                   (existing fills)
  price:      seed='$25 cover'          existing=null                      (seed fills)
  performers: seed=['Aunty Kim (host)'] existing=[]                        (seed fills)

Action:
  [s] skip      — log and move on
  [e] enrich    — run full web extraction; apply only gap-filling fields to event #198
  [p] proceed   — treat as a new event (override; rare)
  [q] quit      — stop the batch

Pick:
```

The "proceed-as-new" path is for the rare case where the seed-and-existing comparison surfaces that they're actually different events that happen to look similar (e.g., two different drag brunches at the same venue on the same day). Most of the time it's `s` (already have it) or `e` (improve it).

### Per-walk summary

Printed at the end of every run (including `--dry-run`). Derived from the sidecar log:

```
─── Walk summary: walks/2026-04-27/ ───
Photos processed: 9
  ingested:                3 (events #245–247)
  enriched:                2 (events #198, #211)
  proceeded-as-new:        0
  skipped:dedup-match:     2
  skipped:no-web-trace:    1 (IMG_20260424_143058.jpg — "Wander Home Holiday Market")
  failed:                  1 (IMG_20260424_143200.jpg — fetch_html error)

New businesses added: 1
  guesthouse-hotel  — The Guesthouse Hotel  (4872 N Clark St)
  → review with: git diff config/businesses.yaml

Cost estimate: $0.084
Sidecar log: walks/2026-04-27/.ingest_log.json
```

Reasons surfaced inline (rather than just counts) for the categories where you might want to act: no-web-trace (do a manual search) and failed (retry or investigate).

---

## Section C — Technical components + testing

### File layout

**New files:**
- `scripts/ingest_flyer.py` — CLI entry point + orchestration
- `src/web_search.py` — web-search-result ranking + allowlist loader
- `config/web_search_allowlist.yaml` — domain allowlist for authoritative sources

**Modified files:**
- `src/prompts.py` — add `SEED_EXTRACTION_PROMPT` and a new variant of the existing extraction prompt that takes flyer-photo cross-verification context
- `requirements.txt` — possibly add `rapidfuzz` for sequence-similarity (lightweight, ~200 KB; stdlib `difflib.SequenceMatcher` is an alternative if we'd rather avoid the dep)

**Reused unchanged:**
- `src/extractor.py` — `extract_events()` for Step 5
- `src/fetcher.py` — `fetch_html()` / `playwright_session()` for Step 5
- `src/db.py` — `connect()`, `upsert_event()`, query helpers
- `scripts/extract_business_metadata.py` — invoked as a subprocess from Step 6
- `scripts/geocode_businesses.py` — invoked as a subprocess from Step 6

### Component specs

**Seed extraction (Step 1).** New `extract_flyer_seeds(image_bytes) -> dict` in `src/extractor.py` (or co-located helper). Single Claude Haiku call, multimodal, JSON-mode output matching the schema in Section A. Prompt explicitly anchors "the flyer is the authoritative signal — ignore window decals, surrounding storefront branding, decorative shadows" and asks Claude to set `flyer_image_is_clean: false` when the photo includes substantial non-flyer content. Cost: ~$0.002 per photo.

**Business resolver (Step 2).** Inline helper in `scripts/ingest_flyer.py`:
```python
def resolve_business(venue_name: str, businesses: list[dict]) -> tuple[str, float] | list[tuple[str, float]] | None:
    # Returns: (slug, score) for confident match (≥ 0.85);
    # list of top 2-3 candidates for ambiguous (0.6 ≤ best < 0.85);
    # None for no candidate above 0.6.
```
Match score uses `rapidfuzz.fuzz.WRatio` (or `difflib.SequenceMatcher.ratio()`) against each business's `name` field. Thresholds are top-of-script constants for easy retuning.

**DB dedup (Step 3).** Inline helper that queries `events WHERE business_id = ? AND status IN ('active', 'stale')` and applies the match rule from Section A:
- Dated events: title-similarity ≥ 0.7 AND date within ±2 days.
- Recurring events: title-similarity ≥ 0.7 AND `recurrence_pattern` matches AND start-time within ±30 min (or both null).

In-batch duplicates: handled for free by sequential processing. After Step 7's commit for photo N, photo N+1's Step 3 query sees the just-inserted event. Match-threshold tuning is the safety net for slightly-different-angle photos that produce slightly-different seeds.

**Web search (Step 4).** New `src/web_search.py`:
```python
def search_for_event(seed: dict, allowlist: dict) -> SearchResult | None:
    # Builds 1-3 queries from seed, runs WebSearch, ranks results against
    # allowlist tiers, returns the highest-tier result above the bar (or None).
```

Query construction: primary query is `"{event_title}" "{venue_name}" Andersonville Chicago`. Fallback queries swap in distinctive strings if the primary returns no allowlist matches. Cap at 3 queries per photo to bound cost.

Ranking: each result's domain is mapped to its allowlist tier. Tier 1 (venue's own domain — derived from `businesses.yaml` `website` field for known venues; for unknown venues the domain in the seed-extracted result, if any) ranks above Tier 2 (named aggregators). Anything not in the allowlist is rejected.

**`config/web_search_allowlist.yaml` shape:**
```yaml
# Tier 1 is computed dynamically (venue's own domain). Tier 2 is the curated list below.
tier_2:
  - eventbrite.com
  - do312.com
  - timeout.com           # Time Out Chicago lives under timeout.com/chicago
  - chicagoreader.com
  - andersonville.org     # Andersonville Chamber
  - blockclubchicago.org
  - patch.com             # Andersonville Patch lives under patch.com/illinois/rogers-park-edgewater
  - choosechicago.com
```

**Multimodal full extraction (Step 5).** Wraps the existing `extract_events()` call with a flyer-cross-verification context. Implementation: extend `extract_events()` to optionally accept `cross_verify_image: bytes | None`. When supplied, it's added to the multimodal message alongside the existing image discovery results, and the prompt gains a note: "the additional image is a flyer photographed in the wild; treat it as a corroborating signal — prefer the web source's text/images for any conflict."

**Auto-add business (Step 6).** New `add_business_from_search(seed, search_result) -> str`:
1. Compute slug from venue name (existing slug-derivation logic; re-use whatever `businesses.yaml` editor scripts already use).
2. Append a new entry to `config/businesses.yaml` using the surgical text-level YAML editor pattern from `scripts/extract_business_metadata.py` and `scripts/geocode_businesses.py` (preserves the comment header + field ordering).
3. Run `python3 scripts/extract_business_metadata.py <slug>` as a subprocess (already supports the positional-slug single-target invocation per CLAUDE.md).
4. Run `python3 scripts/geocode_businesses.py <slug>` as a subprocess.
5. Return the slug for use by Step 5.

If steps 3 or 4 fail, the business stays in `businesses.yaml` (geocoder can be re-run later); the photo's outcome is `failed:business-add-failed:<step>` and the run continues.

**Upsert (Step 7).**
- New event: existing `upsert_event()` — no changes.
- Enrich: read existing row, build a field-by-field diff, apply only gap-filling fields (where existing is null/empty AND seed-extracted is non-null). Always update `last_seen_at` and `last_extracted_at`. Never overwrite an existing non-null value.

**Sidecar log writer.** Append-only JSON. Atomic append via "read full file, mutate in memory, write to `.tmp` sibling, rename" — this avoids partial writes if the user Ctrl-Cs mid-write.

### Testing approach

The project has no pytest suite (per CLAUDE.md: "No frameworks. Procedural Python, stdlib-preferred."). Verification follows the existing project pattern of `scripts/test_extraction.py` — manual targeted runs against known cases:

1. **Smoke test on the Guesthouse photo** (sitting at `/Users/jgonder/Downloads/20260422_202538.jpg`). Expected: `seed_confidence: high`, no DB match, web search returns Block Club Chicago or similar, new business `guesthouse-hotel` auto-added, event ingested. End-to-end run with `--dry-run` first, then a real run.
2. **Synthetic case: confident DB match.** Photograph (or screenshot) an existing flyer for a known recurring event (e.g., Bearaoke at SoFo Tap). Expected: Step 3 dedup gate fires, prompt offers `[s/e/p/q]`. Verify the field-by-field comparison renders correctly.
3. **Synthetic case: ambiguous business match.** Run a photo where `venue_name` is short or generic (e.g., "Rooftop"). Expected: Step 2 ambiguity prompt fires.
4. **Synthetic case: no-web-trace.** A photo of a flyer for an event so niche it has no web presence (a community-board pickup-band rehearsal, etc.). Expected: silent skip, log entry with the queries tried.
5. **`--seed-only` smoke test.** Run on the same Guesthouse photo. Expected: prints seeds only, no web search, no DB queries.
6. **Resume smoke test.** Run the Guesthouse photo, Ctrl-C between Step 4 and Step 5. Re-run; expected: photo is processed normally (sidecar log only records *completed* outcomes, not in-progress ones).

`--dry-run` and `--seed-only` are essential prerequisites for any of the above — they let you confirm pipeline behavior without writing to the DB or `businesses.yaml` while iterating.

### Cost ceiling estimate

Per-photo cost in a typical batch:
- Step 1 seed extraction (Haiku, multimodal): ~$0.002
- Step 4 web search: free (WebSearch tool)
- Step 5 full extraction (Haiku, multimodal): ~$0.005
- Step 6 metadata extraction (only when new business; Haiku, text): ~$0.002

Typical 8-photo Clark St walk with 2 new businesses: 8 × $0.007 + 2 × $0.002 ≈ $0.06. Worst case (15 photos, 5 new businesses): 15 × $0.007 + 5 × $0.002 ≈ $0.115. Well within tolerable bounds.

---

## Open questions deferred to implementation (non-blocking)

- **Match-threshold tuning** — Section C ships with sequence-similarity ≥ 0.7 for title comparison and ≥ 0.85 / ≥ 0.6 for confident/ambiguous business match. Constants live at the top of `scripts/ingest_flyer.py` for easy retuning. Calibrate against real walks once we have data.
- **`rapidfuzz` vs. stdlib `difflib`** — `rapidfuzz` is faster and more idiomatic for fuzzy matching but adds a dependency. `difflib.SequenceMatcher` is in the stdlib. Either works at the v1 scale (~150 active events, ~25 businesses). Implementation chooses; default to `difflib` to honor the project's stdlib-preferred convention.
- **In-batch dedup for slightly-different-angle duplicate photos** — the sequential-processing approach handles exact-same-flyer duplicates. If two angles of the same flyer produce seeds different enough to slip past the 0.7 threshold, it'll insert two events. Acceptable for v1; surface it in walk-summary review if it becomes a pattern.
- **Phone-photo retention policy** — leave originals in their input folder. Sidecar log records state; no need to move/rename/delete files. User can manually archive after a run.

---

## Related items in CLAUDE.md to revisit when this lands

- **"Nav-link discovery for new special pages"** (low priority) — same web-search-from-distinctive-strings pattern could discover events at known businesses' un-tracked URLs. Consider as a follow-up.
- **"Holiday-events representation"** — separate design thread, captured under follow-ups (NOT this spec). User flagged the Mother's Day market as a trigger for thinking about how holiday-tied events surface.
