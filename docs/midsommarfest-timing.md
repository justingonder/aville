# Midsommarfest header + advisory — timing spec (for Claude Code)

> [!NOTE]
> This timing logic has been generalized to the timeline-based highlights system (see [highlights.yaml](file:///Users/jgonder/Development/aville/config/highlights.yaml) and [2026-06-04-neighborhood-highlights-design.md](file:///Users/jgonder/Development/aville/docs/superpowers/specs/2026-06-04-neighborhood-highlights-design.md)) as of 2026-06-04.

How the **featured header** (`.mqc`) and the **festival advisory** (`.advis`) turn
themselves on and off. Visual design lives in `Midsommarfest Featured Header.html`;
this file is just the show/hide logic.

## Behavior

All evaluation is in **`America/Chicago`** (per CLAUDE.md — never the visitor's tz).

| When (Chicago) | Featured header `.mqc` | Advisory `.advis` |
|---|---|---|
| **Before** Jun 12 | shown · **countdown** (`N days to go`) | hidden |
| **During** Jun 12–14 | shown · **live** (`.mqc.live`, "ON now") | **shown** |
| **After** Sun Jun 14 night | hidden | hidden |

So: the header leads the countdown and stays up through the fest; the advisory only
appears once the fest actually starts; both retire Sunday night. No manual cleanup.

## 1 · Config — `config/festival.yaml`

New sibling to `marquee.yaml` (same "edit YAML → rebuild" model). Keep it separate
from the marquee so the dev-notice marquee and the festival are independently toggled.

```yaml
# Festival featured-header + advisory window. Times are America/Chicago.
enabled:   true
name:      Midsommarfest
link_url:  https://andersonville.org/midsommarfest/
starts_on: 2026-06-12          # first day (countdown -> live)
ends_on:   2026-06-14          # last day, inclusive (live -> hidden after)
ends_at:   2026-06-15T00:00    # exact close for the client-side cutoff (Sun midnight)
```

## 2 · Build-time phase — `site_builder.py`

The site rebuilds daily (~6am Chicago), so build time covers day-granularity: the
countdown number and the countdown→live flip. (The exact Sunday-night disappearance
is handled client-side in §4, because the next build isn't until Mon 6am.)

```python
import datetime as dt
from datetime import date
from zoneinfo import ZoneInfo

def festival_state(cfg, today=None):
    if not cfg or not cfg.get("enabled"):
        return {"phase": "off", "show_header": False, "show_advisory": False}
    today = today or dt.datetime.now(ZoneInfo("America/Chicago")).date()
    start = date.fromisoformat(str(cfg["starts_on"]))
    end   = date.fromisoformat(str(cfg["ends_on"]))
    if   today <  start: phase = "countdown"
    elif today <= end:   phase = "live"          # inclusive through the last day
    else:                phase = "ended"
    return {
        "phase":         phase,
        "name":          cfg.get("name", "Festival"),
        "link_url":      cfg.get("link_url"),
        "days_until":    (start - today).days,    # only meaningful in countdown
        "starts_at":     f"{start}T00:00",
        "ends_at":       cfg.get("ends_at", f"{end + dt.timedelta(days=1)}T00:00"),
        "show_header":   phase in ("countdown", "live"),
        "show_advisory": phase == "live",
    }
```

Pass `festival = festival_state(load_yaml("config/festival.yaml"))` into the
`index.html` render context (same place `marquee`, `build_date`, `issue_number` are set).

## 3 · Template — `templates/index.html`

Drop the header into the existing marquee slot, the advisory just above the event
board (mirrors where it sits in the mockups). The `.mqc` / `.mqc.live` / `.advis`
markup is lifted verbatim from the design frames.

```jinja
{% if festival and festival.show_header %}
<section class="mqc {{ 'live' if festival.phase == 'live' else '' }}"
         data-festival-header
         data-starts-at="{{ festival.starts_at }}"
         data-ends-at="{{ festival.ends_at }}">
  <div class="bunting mqc-bunting"></div>
  <div class="mqc-grid">
    {% if festival.phase == 'countdown' %}
      <div class="count"><span class="n">{{ festival.days_until }}</span><span class="u">days to go</span></div>
    {% else %}
      <div class="count"><span class="dot"></span><span class="n">ON</span><span class="u">now</span></div>
    {% endif %}
    <div class="meat"> … headline / dateline / meta (from header-c-*.html) … </div>
    <div class="rail">
      <div class="seal seal60"><div class="ring"><span class="big">60</span><span class="lab">years</span></div></div>
      <a class="cta" href="{{ festival.link_url }}" target="_blank" rel="noopener">Official site →</a>
      <span class="src">andersonville.org</span>
    </div>
  </div>
</section>
{% endif %}

{% if festival and festival.show_advisory %}
<section class="advis" data-festival-advisory data-ends-at="{{ festival.ends_at }}"> … </section>
{% endif %}
```

Two copies of the dateline/eyebrow text (countdown vs live) — keep both strings in
the template branch like the two `header-c-*.html` frames do.

## 4 · Exact Sunday-night cutoff (client-side, recommended)

Build-time alone would leave the live header up until the **Mon 6am** rebuild. To make
both vanish exactly Sunday night, add a tiny Chicago-time gate — same approach as the
existing `isHappeningNow` block. It only ever *hides*; it never shows something the
build didn't render.

```html
<script>
(function () {
  // Chicago wall-clock "now"
  var now = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Chicago' }));
  function within(el) {
    var s = el.dataset.startsAt ? new Date(el.dataset.startsAt) : null;
    var e = el.dataset.endsAt   ? new Date(el.dataset.endsAt)   : null;
    if (e && now >= e) return false;            // past the close -> retire
    if (el.hasAttribute('data-festival-advisory') && s && now < s) return false;
    return true;
  }
  document.querySelectorAll('[data-festival-header],[data-festival-advisory]')
    .forEach(function (el) { if (!within(el)) el.remove(); });
})();
</script>
```

`new Date('YYYY-MM-DDTHH:MM')` parses as local wall-clock, which matches the
Chicago-normalized `now` above — so the comparison is Chicago-vs-Chicago. (No need to
juggle UTC offsets; this mirrors how the spotlight script already reasons about time.)

## 5 · Retire / reset

- After `ends_on`, the next daily build drops both (`show_*` false); the §4 script
  removes them earlier, at `ends_at`.
- To turn the whole thing off early or after the year: `enabled: false` (or delete
  `festival.yaml`) and rebuild. Nothing else references it.
- Reuse next year: bump `starts_on` / `ends_on` / `ends_at`.

## 6 · Test cases

Run `festival_state` against fixed dates:

- `2026-06-03` → `countdown`, `days_until 9`, header ✓, advisory ✗
- `2026-06-11` → `countdown`, `days_until 1`, header ✓, advisory ✗
- `2026-06-12` → `live`, header ✓, advisory ✓
- `2026-06-14` → `live`, header ✓, advisory ✓  (inclusive last day)
- `2026-06-15` → `ended`, header ✗, advisory ✗

Client gate: with `ends_at = 2026-06-15T00:00`, a Chicago clock of `2026-06-14 23:30`
keeps both; `2026-06-15 00:30` removes both. Advisory with `starts_at 2026-06-12T00:00`
stays hidden at `2026-06-11 23:00`.
