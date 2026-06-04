# Neighborhood Highlights — multi-event banner + admin curation

**Date:** 2026-06-04
**Status:** Design approved, pending spec review
**Supersedes:** the single-festival implementation shipped 2026-06-03
(`config/festival.yaml`, `_festival_state`, the hardcoded Midsommarfest header/
advisory/specials in `templates/index.html` + `_happy_hours_page.html`).

## Context & motivation

The 2026-06-03 session shipped a Midsommarfest "featured header" + advisory +
curated specials, driven by a single-festival `config/festival.yaml` and a build-
time phase function with a client-side cutoff. It works, but two limitations
surfaced in review:

1. **Single festival only.** Andersonville has several neighborhood-scale events a
   year (Midsommarfest, a Wine Walk, Halloween, holiday markets). The structure
   should hold a *collection*, each surfacing automatically in its own window.
2. **No admin path for the curated specials.** The specials are hand-maintained in
   YAML today. The local admin tool (`scripts/admin.py`) should manage them like it
   manages businesses, events, and tags.

This spec generalizes the feature into **Highlights**: a collection of curated
neighborhood events, each with rich per-event display copy, that take over the
top-of-page banner slot during their window. "Highlight" is the chosen umbrella
term — `featured`/`featured_events` collides with the existing `events.featured`
column and the `featured_events` render var; `spotlight`/`marquee` collide with the
`#spotlight` section and the dev-notice marquee. "Highlight" is collision-free and
fits any big neighborhood happening.

Visual output for Midsommarfest must remain **pixel-identical** — only the data
source changes (hardcoded strings → config fields).

## Goals

- Support N highlights in one config file; the build auto-selects which (if any) to
  show based on the current date.
- Each highlight carries its own rich display copy so a Wine Walk doesn't inherit
  Midsommarfest's "60th annual"/"festival" language.
- Add a Highlights section to the local admin tool: list + per-highlight editor +
  curated-specials editor + a faithful preview that ignores the live-gate.
- Preserve all existing timing behavior (countdown → live → retire; Chicago-time
  client-side cutoff) and the per-save auto-commit admin pattern.

## Non-goals (YAGNI)

- Image uploads for specials cards (the design has none).
- Drag-drop reorder (↑/↓ buttons suffice for specials; highlights need no ordering —
  selection is date-driven).
- Showing more than one highlight at once (the banner is a single slot).
- Renaming the `.mqc` / `.fspec` / `.advis` CSS classes (opaque visual identifiers
  from the design bundle; renaming is churn with no functional gain).
- A general "any number of overlapping highlights" engine — overlap is resolved by a
  simple nearest-start rule, not a layout system.

## Data model — `config/highlights.yaml`

Rename `config/festival.yaml` → `config/highlights.yaml`. Top-level key
`highlights:` is a list. Each entry:

```yaml
highlights:
  - enabled: true
    name: Midsommarfest                       # internal label + advisory {name}
    link_url: https://andersonville.org/midsommarfest/
    starts_on: 2026-06-12                      # countdown -> live
    ends_on:   2026-06-14                      # last day, inclusive
    ends_at:   2026-06-15T00:00                # exact client-side cutoff (Chicago)
    countdown_days: 21                         # optional lead; header shows only within N days of start

    # ---- header display copy (rich, per-highlight) ----
    headline: Midsommarfest                    # default = name
    accent: fest                               # optional substring of headline, shown in accent color
    eyebrow: 60th annual                       # optional; countdown eyebrow tail
    seal_big: "60"                             # optional seal numeral; omit -> no seal
    seal_label: years                          # optional seal label
    tagline: Andersonville's biggest weekend   # countdown dateline lead-in
    location: Clark Street                     # used in datelines + advisory {location}; default "Andersonville"
    hours: 11am–10pm daily                     # optional; live dateline tail
    meta:                                      # optional chips row
      - 4 stages
      - Food & vendors
      - Kids' area
      - $10 at the gate

    # ---- advisory copy ({dates}/{name}/{location} placeholders auto-filled) ----
    advisory_heading: Some of these regulars may take the weekend off
    advisory_body: >
      From {dates}, {location} belongs to the fest. A lot of the weekly happy hours
      and recurring specials below won't run as usual — many spots will be pouring
      special menus instead. For day-of details, check each spot's own page.

    # ---- curated specials module copy + cards ----
    specials_tape: Festival specials           # green tape label; default "Featured specials"
    specials_heading: What's actually pouring, fest weekend   # module h2; default "What's on this weekend"
    specials_handnote: "Hand-picked by us — confirmed, not scraped"   # default as shown
    specials:
      - venue: Replay Andersonville
        where: Bar · 5358 N Clark
        when: ALL
        when_sub: weekend
        note: Confirmed for Fri–Sun
        lines:
          - text: "<b>Midsommar beer garden</b> on the patio"
          - { text: Frozen rosé, price: $7 }
          - { text: Swedish meatball sliders, price: $6 }
```

**Field semantics & defaults** (resolved in `_highlight_state`, not the template, so
templates stay dumb):

| Field | Required | Default / fallback |
|---|---|---|
| `enabled` | — | `false` |
| `name` | yes | — |
| `link_url` | — | none (CTA omitted if absent) |
| `starts_on` / `ends_on` | yes | — |
| `ends_at` | — | `{ends_on + 1 day}T00:00` |
| `countdown_days` | — | `null` → countdown shows whenever enabled & before start |
| `headline` | — | `name` |
| `accent` | — | none (plain headline) |
| `eyebrow` | — | none → eyebrow is just "Aville spotlight" |
| `seal_big` / `seal_label` | — | none → seal hidden, rail shows CTA only |
| `tagline` | — | none |
| `location` | — | `"Andersonville"` |
| `hours` | — | none |
| `meta` | — | `[]` → meta row omitted |
| `advisory_heading` / `advisory_body` | — | generic fallback using `{name}`/`{dates}` |
| `specials_tape` | — | `"Featured specials"` |
| `specials_heading` | — | `"What's on this weekend"` |
| `specials_handnote` | — | `"Hand-picked by us — confirmed, not scraped"` |
| `specials` | — | `[]` → specials module omitted |

Dates are stored as strings (matches how `_load_festival`/PyYAML already treats
`ends_at`; `site_builder` wraps with `str()`+`date.fromisoformat`, so quoted or
unquoted is safe).

**`specials_heading` renders plain (no `<em>` split needed for parity):** the shipped
markup wraps the first clause in `<em>`, but `.fspec h2` and `.fspec h2 em` resolve to
identical styles (both `font-style:italic; color:var(--ink)`), so the `<em>` is a
visual no-op. A plain config heading is therefore pixel-identical — no need to model
the emphasis span.

## Selection logic — `_highlight_state(cfg, today)`

Replaces `_festival_state`. Returns the single highlight to display, fully resolved,
or an "off" state.

Factor the per-entry phase decision into a small shared helper
`_highlight_phase(h, today) -> "countdown"|"live"|None` (None = not currently
displayable: disabled, ended, or dormant beyond `countdown_days`). Both
`_highlight_state` (selection) and the admin list page (phase badge) call it, so the
rule lives in exactly one place.

```
def _highlight_phase(h, today):
    if not h.enabled: return None
    start = date(h.starts_on); end = date(h.ends_on)
    if today > end: return None                   # ended -> retired
    if today < start:
        lead = h.countdown_days
        if lead is not None and (start - today).days > lead:
            return None                           # too far out -> dormant
        return "countdown"
    return "live"                                 # start <= today <= end

candidates = []
for h in cfg.get("highlights", []):
    phase = _highlight_phase(h, today)
    if phase is None: continue
    candidates.append((date(h.starts_on), phase, h))

if not candidates:
    return {"phase": "off", "show_header": False, "show_advisory": False}

# nearest start wins: a live highlight (start <= today) naturally sorts before an
# upcoming one; among multiple live, earliest start wins; among upcoming, soonest.
candidates.sort(key=lambda c: c[0])
start, phase, h = candidates[0]
return _resolve_highlight(h, phase, today)        # all derived copy below
```

`_resolve_highlight` computes:

- `phase`, `show_header` (countdown|live), `show_advisory` (live only),
  `days_until = (start - today).days`
- `date_range` — "June 12–14, 2026" (reuse/adapt `_daterange_str` /
  `_humandaterange` helpers in `site_builder.py`)
- `last_day` — `ends_on` as "Sunday, June 14" (`strftime('%A, %B %-d')`)
- `eyebrow_countdown` = "Aville spotlight" + (` · {eyebrow}` if set)
- `eyebrow_live` = "Aville spotlight · happening now"
- `dateline_countdown` = join non-empty of `tagline`, then `{location}, {date_range}`
- `dateline_live` = `On {location} now through {last_day}` + (` · {hours}` if set)
- `headline_before` / `headline_accent` / `headline_after` via
  `headline.partition(accent)` when `accent` is a non-empty substring, else
  `(headline, "", "")`
- `advisory_heading` / `advisory_body` with `{dates}`→`date_range`, `{name}`→`name`,
  `{location}`→`location` substituted
- `specials_*`, `link_url`, `seal_big`, `seal_label`, `meta`, `name`
- `starts_at` = `{start}T00:00`, `ends_at`

The render var passed into templates is `highlight` (singular).

## Template changes

The header/advisory markup becomes field-driven (no hardcoded Midsommarfest
strings). Visual structure is unchanged from the shipped version.

- **`templates/index.html`** — `{% if highlight and highlight.show_header %}` header
  block using `highlight.eyebrow_countdown`/`eyebrow_live`,
  `headline_before`/`accent`/`after`, `dateline_countdown`/`dateline_live`,
  `meta` loop (omit if empty), seal guarded by `highlight.seal_big`,
  `link_url` CTA. Advisory block uses `advisory_heading`/`advisory_body`; home CTA
  links `/happy-hours/`. Client-side cutoff script updated to
  `data-highlight-header` / `data-highlight-advisory`.
- **`templates/_happy_hours_page.html`** — advisory (HH CTA links
  `highlight.link_url`) + `{% include '_highlight_specials.html' %}` for the module.
  Cutoff script updated to the new data attributes.
- **`templates/_highlight_specials.html`** (new) — shared partial for the `.fspec`
  module, parameterized by a `specials`, `tape`, `heading`, `handnote` context so it
  renders identically in production and in the admin preview. Production includes it
  with `{% with specials=highlight.specials, tape=highlight.specials_tape, … %}`.

`src/site_builder.py`: `_load_festival`→`_load_highlights` (reads
`config/highlights.yaml`), `_festival_state`→`_highlight_state`, the render var
`festival`→`highlight` in both the index render context and
`_build_happy_hours_page`. Migrate the timing-doc reference comments.

## Admin UI — `scripts/admin.py` + `templates/admin/`

Follows the existing Businesses/Events pattern (list + per-item editor), since there
can now be several highlights.

**Constants/loader:**
- `HIGHLIGHTS_PATH = CONFIG_DIR / "highlights.yaml"`.
- Extend the admin Flask Jinja loader with a `ChoiceLoader` adding
  `templates/` (production) as a fallback search path, so the admin preview can
  `{% include '_highlight_specials.html' %}`. One line after app creation; existing
  `render_template("…")` calls still resolve from `templates/admin/` first.

**Nav:** add `Highlights` link in `templates/admin/base.html` (between Tags and
Series end-dates).

**Routes:**
- `GET /highlights/` — list page (`highlight_list.html`): each highlight's name,
  enabled badge, window, **computed phase** (via `_highlight_state`-style logic
  imported/duplicated minimally), specials count; Edit/Delete links; **Add
  highlight** button.
- `GET|POST /highlights/<int:idx>` — editor (`highlight_edit.html`): window settings
  (enabled, name, link_url, starts_on, ends_on, ends_at via `datetime-local`,
  countdown_days) + all rich copy fields + the **specials repeater**. Save validates
  via `validate_iso_date` / `validate_iso_datetime`, writes through
  `load_yaml`/`dump_yaml`/`atomic_write`, and `commit_file("config/highlights.yaml",
  …)`.
- `POST /highlights/add` — append a blank highlight, redirect to its editor.
- `POST /highlights/<int:idx>/delete` — remove the entry, commit.
- `GET /highlights/<int:idx>/preview` — standalone preview page
  (`highlight_preview.html`): renders that highlight's header in **both** the
  countdown and live states (labeled), then the advisory and specials, with the
  live-gate **ignored** so the curator sees everything regardless of today's date.
  Banner: "Preview only — live during the window." CSS = source `styles/index.css` +
  `styles/happy_hours.css` inlined into a `<style>` block (works regardless of build
  state); Google Fonts linked. Specials use the shared `_highlight_specials.html`
  partial. Reuses `_resolve_highlight` for both phases so preview copy matches
  production exactly.

**Specials editor (within the highlight editor):** each card is a sub-block with
`venue`, `where`, `when`, `when_sub`, `note`, and a **lines repeater** — each line a
row of `text` input + small `price` input, with `+ add line` / `–` remove via a
small vanilla-JS snippet. Per card: ↑/↓ move (drives the `r-a/r-b/r-c` tilt),
delete. **Add special** appends a blank card. On submit, parallel arrays
(`special_<i>_line_text[]`, `special_<i>_line_price[]`) are zipped into `lines`,
dropping empty-text rows.

**Lines round-trip** (isolated helper pair):
- `line_text_to_storage(s)`: `html.escape(s)` then `**x**` → `<b>x</b>`.
- `line_text_from_storage(s)`: `<b>`/`</b>` → `**` then `html.unescape`.
- Round-trips `Kitchen & bar open **til 2am**` ⇄ `Kitchen &amp; bar open <b>til
  2am</b>` with no raw-HTML typing and bold anywhere in the line.

## Migration of the shipped Midsommarfest data

The shipped `config/festival.yaml` single entry becomes `highlights[0]` in
`config/highlights.yaml`, with the hardcoded template strings relocated into fields:
`eyebrow: 60th annual`, `seal_big: "60"`, `seal_label: years`, `tagline:
Andersonville's biggest weekend`, `location: Clark Street`, `hours: 11am–10pm
daily`, `meta: [...]`, `accent: fest`, the advisory copy, and `specials_tape:
Festival specials` / `specials_heading: What's actually pouring, fest weekend`.
Delete `config/festival.yaml`. A render diff before/after must show the Midsommarfest
home + happy-hours output unchanged (countdown phase today).

## Testing

- **`_highlight_state` unit cases** (extend the 5 existing handoff cases):
  - single enabled highlight: countdown/live/ended transitions (Jun 3/11/12/14/15)
  - two enabled, one live + one upcoming → live wins
  - two enabled upcoming → nearest start wins
  - `countdown_days` lead: upcoming beyond lead → dormant (off); within lead →
    countdown
  - disabled highlight → never selected
- **Render parity:** full `build_site.py` build in countdown phase; assert
  Midsommarfest header renders identically (diff vs. the 2026-06-03 output) and the
  advisory/specials are absent (countdown). A temporary live-window build confirms
  header/advisory/specials render on both pages.
- **Admin round-trip:** create → edit (incl. a `**bold**` line + a priced line) →
  save → reload: the form repopulates exactly; `config/highlights.yaml` round-trips
  through ruamel preserving the header comment; the commit lands. Delete removes the
  entry. Preview renders the cards with real CSS.

## File touch list

- `config/festival.yaml` → **renamed** `config/highlights.yaml` (restructured)
- `src/site_builder.py` — loader + `_highlight_state` + render-var rename
- `templates/index.html`, `templates/_happy_hours_page.html` — field-driven markup +
  data-attr rename
- `templates/_highlight_specials.html` — **new** shared partial
- `scripts/admin.py` — routes, helpers, loader change, `HIGHLIGHTS_PATH`
- `templates/admin/base.html` — nav link
- `templates/admin/highlight_list.html`, `highlight_edit.html`,
  `highlight_preview.html` — **new**
- `docs/shipped.md`, `docs/midsommarfest-timing.md` (note generalization), `CLAUDE.md`
  pointer, `handoffs.md`
