# Design note: recurring series + weekly editions (themed occurrences)

**Date:** 2026-06-07
**Status:** design note only — NOT yet brainstormed/spec'd. Captured from the
Instagram-ingestion experiment (`experiment/instagram-ingestion`).
**Related:** spec `2026-06-07-instagram-ingestion-design.md`; handoff 2026-06-07.

## The insight

Our two event sources carry different, complementary information:

- **Website crawling** gives us the **container**: the stable recurring series —
  "Karaoke every Thursday, 8pm" (a `recurring` row).
- **Instagram** gives us the **weekly edition / theme**: what *this* week's karaoke
  actually is — "Catsuit or Fatsuit?", "April Showers", "POP'D". These currently land
  as standalone `dated` rows with `source_type='instagram'`.

Surfacing the theme on top of the recurring container is what makes the site feel
fresh and "in the know" rather than a static listing. The desired render is a single
card: **"Karaoke Cabaret — this week: Catsuit or Fatsuit?"** instead of two disconnected
cards ("Karaoke (recurring)" + "Catsuit or Fatsuit? (dated)") competing on the same night.

This generalizes well beyond karaoke: themed trivia, drag nights, monthly dance parties
all have the same shape — a stable series with a rotating per-occurrence identity.

## The relationship

One-to-many: **one recurring series → many themed occurrences over time.** The schema has
no way to express this today; the series and its editions are independent rows (and, in
the experiment, even different `source_type`s — website series, Instagram editions).

## Minimal structural shape (sketch, not a spec)

- One nullable self-referential column on `events`: `series_id` (or `parent_event_id`)
  pointing a themed `dated` row at its `recurring` parent. Single table preserved; matches
  existing philosophy; small migration.
- Display layer shows the series' **next upcoming** edition on the recurring card, only
  while fresh — reuse the existing date-freshness machinery (`_is_past_today`,
  `ends_on`/`starts_on`, build-date shift).
- The link should be **stored and admin-correctable**, not recomputed blindly each build,
  because the matching is fuzzy (see below).

## The hard parts (the schema is the easy part)

1. **Series canonicalization is step zero.** The experiment proved the recurring layer
   isn't clean enough to attach themes to yet. Example from the ingest: "Trivia Is A Drag"
   landed as *three* near-duplicate recurring rows (Tue 19:30, Tue 20:00, Wed 19:30);
   "Let's Get Glam Bingo" twice; "POP'D" as both monthly:3rd-saturday and monthly:1st-sunday.
   These aren't exact duplicates — they're *conflicting extractions* (different day/time),
   so they can't be auto-collapsed; they need reconciliation (partly the website data,
   partly IG variance). There must be exactly **one canonical series per real event** before
   editions can hang off it. **This is a prerequisite project, not part of this one.**

2. **Theme→series linking is fuzzy.** Matching "Catsuit or Fatsuit? (dated, Thursday)" to
   "Karaoke weekly:thursday" needs day-of-week + venue + tag-overlap matching, and it's
   probabilistic — it can mis-link. Options: a Claude pass at ingest time, a heuristic
   matcher, or admin-assisted linking. Whatever does it, the result is a stored link a
   human can correct.

3. **Themes have a shelf life.** "April Showers" (Apr 9) is past; the value is the
   *upcoming* edition. Display must show only the next fresh theme and retire stale ones —
   more display logic, akin to the existing series-gating columns.

## Recommended sequencing (when this gets picked up)

1. **Series canonicalization** — dedup/reconcile the recurring layer to one row per real
   series (own spec). Improves the site regardless of this feature.
2. **`series_id` link + admin linking UI** — let an edition point at its series.
3. **Theme-aware display** — render "this week: <theme>" on the series card, fresh-only.
4. **Auto-linking at ingest** — optional, after the manual path proves the model.

## Why not now

This is a real v2 feature with a hard dependency (canonicalization). It should go through
the normal brainstorm → spec → plan flow on its own, not get bolted onto the ingestion
experiment. Capturing here so the insight isn't lost.
