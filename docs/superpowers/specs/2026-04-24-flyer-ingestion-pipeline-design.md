# Flyer-ingestion pipeline (web-search-seeded)
**Date:** 2026-04-24 (started) / 2026-04-27 (paused mid-brainstorm)
**Status:** DRAFT — brainstorm in progress, paused at Section A awaiting user feedback. Sections B (CLI UX) and C (technical components / testing) not yet drafted.
**Branch:** `flyer-ingestion-design`
**Resume point:** Section A is presented to the user. Next step is to either get Section A approval (and move to Section B) or revise Section A based on feedback. Re-invoke `superpowers:brainstorming` to resume.

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
3. **Auto-add new businesses inline.** When the web search confirms an event at a venue not in `businesses.yaml`, the CLI auto-adds the business, runs `extract_business_metadata.py` and `geocode_businesses.py` against it, and continues. Justification: the project is in build-up phase; new venues are common and equally legitimate. (User chose this over the alternative "pause and require user to add the business first".)
4. **Batch ergonomics: directory mode, with Claude identifying business per photo.** User points the CLI at a folder of phone-named photos (`IMG_20260424_143022.jpg`-style). For each photo, Claude extracts seeds including a venue name; CLI fuzzy-matches against `businesses.yaml`. Only prompts when uncertain. No pre-renaming or manifest required. (User refined: "I want to provide a number of images but they're gonna come from my cell phone camera — I am not gonna custom name them.")

## Section A — Per-photo pipeline (presented, awaiting approval)

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
Query built from seeds (event title + venue, plus distinctive strings as fallback). Run WebSearch. Rank against an allowlist:
1. Venue's own domain
2. Recognized Chicago aggregators: Eventbrite, Do312, Time Out Chicago, Chicago Reader, Andersonville Chamber
3. Other (only if 1–2 yield nothing; needs case-by-case heuristic, TBD in Section C)

If no result clears the bar: skip with `"no web trace — skipping"`.

### Step 5 — Full extraction from the authoritative URL
Fetch the URL. Run existing `extract_events()` with multimodal context: HTML text + the flyer photo. Prompt note: "the flyer is a signal; the web source is authoritative; cross-reference and prefer web for ambiguity."

Image asset: prefer a clean image from the web source if available; fall back to the phone photo.

### Step 6 — Auto-add business if new
If Step 2 found no match: now (with the web search result as a confirmed signal), add to `businesses.yaml` with name + website + address from the search result. Run `extract_business_metadata.py` for the new slug. Run `geocode_businesses.py` for it. Then continue.

### Step 7 — Upsert
- "New event" path: standard `upsert_event()`.
- "Enrich existing" path: read existing row, diff against extracted data, upsert only the gap-filling fields. Always update `last_seen_at`.

---

## Section B — CLI UX + interactive prompts (NOT YET DRAFTED)

To-do when resuming:
- Exact command shape (`python3 scripts/ingest_flyer.py --dir walks/2026-04-24/`?)
- What the interactive prompts look like for: ambiguous business match, dedup match, new-business confirmation, no-web-trace skip
- How "resume after interruption" works (skip already-processed photos? track via a sidecar file?)
- `--dry-run` flag behavior
- Whether to output a per-walk summary at the end ("3 ingested, 4 enriched, 1 skipped")

## Section C — Technical components + testing (NOT YET DRAFTED)

To-do when resuming:
- File layout: `scripts/ingest_flyer.py` (new), reuses `src/extractor.py`, `src/fetcher.py`, `src/prompts.py`, `scripts/extract_business_metadata.py`, `scripts/geocode_businesses.py`
- New seed-extraction prompt in `src/prompts.py`
- Web-search-result-ranking heuristic — could live in `src/web_search.py` (new) or inline
- Pickling / sidecar-tracking for resumability
- Testing approach: project has no pytest suite. Manual verification with the Guesthouse photo + 1–2 synthetic cases (obvious match, ambiguous match, new-business). `--dry-run` mode is essential.
- Image dedup edge case: the flyer is in a window with reflections/decals/perspective skew; the same flyer might be photographed at multiple venues during a walk. The Step 3 dedup should catch in-batch duplicates as well as DB duplicates — confirm the batch-order processing makes this work, otherwise a small in-process cache is needed.

---

## Open questions to resolve before writing-plans

- **Match threshold tuning** — exact fuzzy-title-similarity threshold for Step 3. Probably token-level Jaccard or sequence-similarity ≥ 0.7. Calibrate against existing DB titles to find the right number. Not blocking — can ship with a reasonable default and tune later.
- **Allowlist for authoritative sources** — what's "Chicago Reader"'s exact domain shape? Are we including Block Club Chicago? Patch.com? Worth a brief survey before locking in.
- **Image dedup within a single walk** — see Section C note. Need to confirm the cheapest path.
- **Phone-photo retention policy** — once a flyer is ingested (or skipped), what happens to the photo file on disk? Keep, move to a `processed/` folder, delete? Minor UX detail.
- **Cost ceiling per walk** — order-of-magnitude estimate: 8 photos × (1 seed call + 1 full extraction + 1 metadata extraction for new businesses) ≈ <$0.10. Worth confirming before shipping.

---

## Related items in CLAUDE.md to revisit when this lands

- **"Nav-link discovery for new special pages"** (low priority) — same web-search-from-distinctive-strings pattern could discover events at known businesses' un-tracked URLs. Consider as a follow-up.
- **"Holiday-events representation"** — separate design thread, captured under follow-ups (NOT this spec). User flagged the Mother's Day market as a trigger for thinking about how holiday-tied events surface.
