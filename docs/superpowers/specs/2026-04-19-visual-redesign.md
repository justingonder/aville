# Visual Redesign — Andersonville Theme
**Date:** 2026-04-19  
**Status:** Approved  
**Scope:** CSS + font changes only (no Python, no template structure changes)

---

## Design goal

Give the site an unmistakable Andersonville identity through color and typography, while keeping the design system reusable so a future neighborhood (without Andersonville's strong brand) can swap in a different palette via CSS custom properties.

The local signal is delivered through color. Structure and layout remain generic enough to be themed.

---

## Design decisions

### Color palette — "Bold Swedish"

| Variable | Value | Role |
|---|---|---|
| `--blue` | `#006AA7` | Swedish flag blue. Primary brand color: header background, active UI elements, tag pills, section labels. |
| `--yellow` | `#FECC02` | Swedish flag yellow. Structural accent only — never as text color (fails contrast on white). |
| `--yellow-dark` | `#3a2800` | Accessible text color for use *on* yellow backgrounds. |
| `--yellow-mid` | `#d4a800` | Mid-tone for yellow borders (spotlight, price badge border). |
| `--yellow-tint` | `#fffbe6` | Very light yellow for spotlight background and price badge background. |
| `--blue-dark` | `#004f7c` | Deep blue for hover/active states. |
| `--blue-tint` | `#e8f3fa` | Light blue for tag pill backgrounds and no-image card placeholders. |
| `--bg` | `#faf8f4` | Warm off-white page background. Unchanged from v1. |
| `--card-bg` | `#ffffff` | Card background. |
| `--border` | `#e5e0d5` | Warm gray for card borders and dividers. |
| `--fg` | `#1a1a1a` | Body text. |
| `--fg-muted` | `#5a5a5a` | Secondary text (venue names, timestamps, footer). |

**Yellow accessibility rule:** Yellow (`#FECC02`) is used exclusively as a background or border color — never as standalone text. All text that appears *on* yellow uses `--yellow-dark` (`#3a2800`), which passes WCAG AA contrast.

### The Nordic cross motif

The Swedish flag's Nordic cross is referenced structurally — not as an image or icon.

- **Vertical arm:** `border-left: 4px solid #FECC02` on the `html` element. Runs the full page height. Always visible, even on scroll.
- **Horizontal arm:** `border-bottom: 4px solid #FECC02` on the `.site-header-band`. Meets the vertical stripe at the top-left corner, forming the right half of the Nordic cross.

Together these two lines evoke the flag geometry to anyone who recognizes it. To anyone who doesn't, they read as clean structural framing.

**Spotlight gap:** `margin-top: 1.25rem` on `.spotlight-band` ensures the spotlight's own yellow top border has clear separation from the header's yellow bottom border — the two yellow lines must never bleed together.

### Typography — Albert Sans

Single variable font family throughout. Weight variation handles all hierarchy — no mixed families.

| Use | Weight |
|---|---|
| Site title (`h1`) | 800 |
| Section headings (`h2`) | 800 |
| Card titles | 700 |
| Filter pill (active) | 700 |
| Subtitle, card body, when | 400–600 |
| Muted metadata | 400 |

Albert Sans was chosen for its Scandinavian geometric design DNA — precise letterforms with enough warmth to avoid sterility. The neighborhood connection is earned, not forced.

**Google Fonts import:**
```html
<link href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
```

### Yellow applied throughout the page

Yellow appears at every scroll depth so it doesn't disappear after the header:

| Element | Treatment |
|---|---|
| Left stripe | `border-left: 4px solid #FECC02` on `html` |
| Header bottom | `border-bottom: 4px solid #FECC02` on `.site-header-band` |
| Spotlight top border | `border-top: 4px solid #FECC02` |
| Spotlight live dot | `background: #FECC02` |
| Active filter pill | `background: #FECC02; color: #3a2800` |
| `h2` section dividers | `border-bottom: 3px solid #FECC02` |
| Bucket headings | `border-left: 3px solid #FECC02` (left bar prefix) |
| Price badges | `background: #fffbe6; border: 1px solid #d4a800; color: #3a2800` |
| Share button hover | `background: #FECC02; color: #3a2800` |
| Footer top border | `border-top: 3px solid #FECC02` |

### Header legibility

The header subtitle and last-updated line were too faint in the original design against the blue background.

| Element | Before | After |
|---|---|---|
| Subtitle | `rgba(255,255,255,0.62)`, weight 400 | `rgba(255,255,255,0.88)`, weight 600 |
| Last updated | `rgba(255,255,255,0.42)`, no weight | `rgba(255,255,255,0.65)`, weight 500 |

### Card image placeholders

No-image placeholder cards use `--blue-tint` (`#e8f3fa`) as the background. Dark "flyer placeholder" backgrounds in image cards use dark navy variations only — all within `#0a1e35`–`#0d2a3a` range. No greens, purples, or off-palette darks.

### Template reusability

All neighborhood-specific values are isolated in `:root` CSS custom properties. Swapping to a different neighborhood means overriding `--blue`, `--yellow`, and their derived tints/darks. Font family is also in `--font`. No design values are hard-coded outside `:root`.

---

## What this spec does NOT cover

- Layout changes (grid, card structure, header HTML structure — these are in scope for implementation but the design is additive CSS only)
- Per-event detail page (`/event/{id}/`) — same CSS variables apply automatically
- Mobile breakpoints — existing responsive behavior is preserved; no layout changes
- Dark mode — not in scope for v1

---

## Files to change

| File | Change |
|---|---|
| `templates/index.html` | Replace `:root` CSS variables; add Albert Sans `<link>`; wrap existing `<header>` content in a `.site-header-band` div for full-width blue background; apply all new class styles throughout. |
| `templates/_event_card.html` | Add `style="container-type:inline-size"` to the `.event-placeholder` div (required for `clamp()` title sizing). No other markup changes needed — CSS classes drive the rest. |
| `templates/_event_detail.html` | **Full CSS rewrite.** This template has its own independent stylesheet (not shared with `index.html`). It currently loads `DM Serif Display` and uses `--accent: #8b3a2f`. Replace with Albert Sans, update all `:root` variables to match the new palette, apply yellow stripe + blue header, update `.detail-price`, `.detail-tags .tag`, `.detail-placeholder`, `.share-btn`, and related-cards styles to match the new system. |

---

## Reference mockup

Approved design: `.superpowers/brainstorm/3764-1776641972/content/full-design-v3.html`
