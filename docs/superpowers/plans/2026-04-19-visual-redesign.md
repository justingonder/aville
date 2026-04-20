# Visual Redesign — Andersonville Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the Andersonville visual theme (Swedish blue + flag yellow, Albert Sans, Nordic cross stripe motif) across all three templates.

**Architecture:** Pure CSS/HTML changes — no Python touched. All neighborhood-specific values live in `:root` CSS custom properties so future neighborhoods can theme by variable swap. The yellow Nordic cross is formed by `html { border-left }` (vertical stripe, full page height) meeting `border-bottom` on the blue header band. Three template files are updated independently; `_event_card.html` requires only one markup addition; `_event_detail.html` requires a full CSS rewrite as it has its own independent stylesheet.

**Tech Stack:** Jinja2 templates, vanilla CSS custom properties, Albert Sans via Google Fonts, `python scripts/build_site.py` to verify output.

**Note on testing:** These are HTML/CSS template changes — there are no unit tests. Each task's verification step is: build the site, open `public/index.html` in a browser, and visually confirm the described outcome. The approved mockup is at `.superpowers/brainstorm/3764-1776641972/content/full-design-v3.html` — use it as the reference.

**Spec:** `docs/superpowers/specs/2026-04-19-visual-redesign.md`

---

## File map

| File | What changes |
|---|---|
| `templates/index.html` | Full CSS rewrite: new `:root` variables, Albert Sans font link, yellow stripe on `html`, blue header band wrapper, spotlight gap, yellow throughout (filter pill, h2, buckets, price badge, footer), blue-tint placeholders and tags |
| `templates/_event_card.html` | One markup change: add `style="container-type:inline-size"` to `.event-placeholder` div |
| `templates/_event_detail.html` | Full CSS rewrite: same palette + font as index, blue nav band, updated detail-specific styles (title font, placeholder, share button, tags, related cards) |

---

## Task 1: Update `index.html` — full CSS + header markup

**Files:**
- Modify: `templates/index.html`

This is the main work. The existing CSS block gets replaced in full and a wrapper div is added around the header content.

- [ ] **Step 1: Replace the Google Fonts link**

In `templates/index.html`, find and remove any existing Google Fonts `<link>` tags (there are none currently — the site uses system fonts). Add Albert Sans immediately after `<meta name="viewport" .../>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
```

- [ ] **Step 2: Replace the entire `<style>` block**

The full `<style>` block currently starts at line 8 and ends at line 233. Replace the entire block with:

```html
  <style>
    /* ── Design system — swap these variables for other neighborhoods ── */
    :root {
      --font:         'Albert Sans', sans-serif;
      --fg:           #1a1a1a;
      --fg-muted:     #5a5a5a;
      --bg:           #faf8f4;
      --card-bg:      #ffffff;
      --border:       #e5e0d5;
      --blue:         #006AA7;
      --blue-dark:    #004f7c;
      --blue-tint:    #e8f3fa;
      --yellow:       #FECC02;
      --yellow-dark:  #3a2800;
      --yellow-mid:   #d4a800;
      --yellow-tint:  #fffbe6;
      --stripe-w:     4px;
    }

    /* ── Full-height Nordic cross vertical arm ── */
    html {
      border-left: var(--stripe-w) solid var(--yellow);
      min-height: 100%;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font);
      background: var(--bg);
      color: var(--fg);
      line-height: 1.5;
    }

    /* ── Header band — horizontal arm of the Nordic cross ── */
    .site-header-band {
      background: var(--blue);
      border-bottom: var(--stripe-w) solid var(--yellow);
    }
    header {
      padding: 1.4rem 1.5rem 1.2rem;
      max-width: 1200px;
      margin: 0 auto;
    }
    h1 {
      font-size: 2rem;
      font-weight: 800;
      color: #fff;
      letter-spacing: -0.03em;
      line-height: 1;
      margin: 0 0 0.3rem;
    }
    .subtitle {
      font-size: 0.88rem;
      font-weight: 600;
      color: rgba(255,255,255,0.88);
      margin: 0 0 0.2rem;
    }
    .last-updated {
      font-size: 0.75rem;
      font-weight: 500;
      color: rgba(255,255,255,0.65);
      margin: 0;
    }

    /* ── Spotlight ── */
    .spotlight {
      max-width: 1200px;
      margin: 1.25rem auto 0;
      padding: 0 1.5rem;
    }
    .spotlight-inner {
      background: var(--yellow-tint);
      border: 1px solid #f0dc5a;
      border-top: var(--stripe-w) solid var(--yellow);
      border-radius: 0 0 10px 10px;
      padding: 1rem 1.25rem 1.25rem;
    }
    .spotlight-label {
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #5a3d00;
      margin-bottom: 0.75rem;
      display: flex;
      align-items: center;
      gap: 0.45rem;
    }
    .spotlight-label.live::before {
      content: '';
      display: inline-block;
      width: 7px; height: 7px;
      border-radius: 50%;
      background: var(--yellow);
      box-shadow: 0 0 0 2px #f0dc5a;
      animation: livepulse 2s ease-in-out infinite;
    }
    @keyframes livepulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.45; transform: scale(1.4); }
    }
    .spotlight-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 1rem;
    }
    .spotlight-event-link {
      text-decoration: none;
      color: inherit;
      display: block;
    }
    .spotlight-event-link .event { height: 100%; }

    /* ── Filter bar ── */
    .filter-bar {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin: 1.5rem 0;
      padding: 0.85rem 1rem;
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      align-items: center;
    }
    .filter-bar strong {
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--fg-muted);
      margin-right: 0.25rem;
    }
    .tag-button {
      font: inherit;
      font-family: var(--font);
      font-size: 0.8rem;
      font-weight: 500;
      padding: 0.25rem 0.75rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: #fff;
      cursor: pointer;
      color: var(--fg-muted);
      transition: all 0.15s;
    }
    .tag-button.active {
      background: var(--yellow);
      color: var(--yellow-dark);
      border-color: var(--yellow-mid);
      font-weight: 700;
    }
    .tag-button.reset { background: transparent; border-style: dashed; }
    .tag-button:hover:not(.active) { border-color: var(--blue); color: var(--blue); }

    /* ── Section headings ── */
    h2 {
      margin: 2.5rem 0 1rem;
      font-size: 1.25rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      border-bottom: 3px solid var(--yellow);
      padding-bottom: 0.4rem;
    }
    .bucket-heading {
      margin: 2rem 0 0.75rem;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--blue);
      border-left: 3px solid var(--yellow);
      padding-left: 0.65rem;
      border-bottom: none;
    }
    .bucket-heading:first-of-type { margin-top: 0; }

    /* ── Event grid & cards ── */
    .events {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 1.25rem;
    }
    .event {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      position: relative;
      transition: box-shadow 0.15s, transform 0.15s;
    }
    .event:hover {
      box-shadow: 0 4px 20px rgba(0,106,167,0.1);
      transform: translateY(-1px);
    }
    .event-image {
      background: #0d2a3a;
      aspect-ratio: 4 / 5;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .event-image img { max-width: 100%; max-height: 100%; width: auto; height: auto; }
    .event-body { padding: 0.85rem 1rem 1rem; flex: 1; display: flex; flex-direction: column; }
    .event-title { font-weight: 700; font-size: 1rem; letter-spacing: -0.015em; line-height: 1.25; margin: 0 0 0.2rem; }
    .event-when { color: var(--fg-muted); font-size: 0.85rem; margin: 0 0 0.4rem; }
    .event-business { font-size: 0.72rem; font-weight: 600; color: var(--fg-muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 0.15rem; }
    .event-desc { font-size: 0.85rem; margin: 0.2rem 0; flex: 1; line-height: 1.5; }
    .event-price {
      display: inline-block;
      align-self: flex-start;
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--yellow-dark);
      background: var(--yellow-tint);
      border: 1px solid #f0dc5a;
      border-radius: 4px;
      padding: 0.05rem 0.45rem;
      margin: 0.3rem 0;
    }
    .event-tags { margin-top: 0.6rem; display: flex; flex-wrap: wrap; gap: 0.3rem; }
    .event-tags .tag {
      font-size: 0.68rem;
      font-weight: 500;
      padding: 0.1rem 0.5rem;
      border-radius: 999px;
      background: var(--blue-tint);
      color: var(--blue);
    }
    .event-source { font-size: 0.72rem; color: var(--fg-muted); margin-top: 0.55rem; }
    .event-source a { color: var(--fg-muted); }

    .event--no-image { border-left: 3px solid var(--no-image-accent, var(--border)); }
    [data-category="bar"].event--no-image        { --no-image-accent: var(--blue); }
    [data-category="restaurant"].event--no-image { --no-image-accent: #5a8a60; }

    .event-placeholder {
      aspect-ratio: 4 / 5;
      background: var(--blue-tint);
      border-bottom: 1px solid #c8dff0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 1.5rem 1.25rem;
      text-align: center;
      gap: 0.6rem;
    }
    .event-placeholder .ph-business {
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--blue);
      opacity: 0.65;
    }
    .event-placeholder .ph-rule {
      width: 1.75rem; height: 1px;
      background: var(--blue); opacity: 0.2;
    }
    .event-placeholder .ph-title {
      font-size: clamp(1.1rem, 5cqi, 1.75rem);
      font-weight: 800;
      letter-spacing: -0.02em;
      line-height: 1.2;
      color: var(--blue);
      opacity: 0.45;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
    }

    /* ── Share button ── */
    .card-share-btn {
      position: absolute;
      top: 0.5rem; right: 0.5rem;
      width: 1.9rem; height: 1.9rem;
      border-radius: 50%;
      border: 1px solid rgba(255,255,255,0.4);
      background: rgba(255,255,255,0.88);
      display: flex; align-items: center; justify-content: center;
      cursor: pointer;
      color: var(--blue);
      transition: background 0.15s, color 0.15s, border-color 0.15s;
      z-index: 1; padding: 0;
    }
    .card-share-btn:hover { background: var(--yellow); color: var(--yellow-dark); border-color: var(--yellow-mid); }
    .card-share-btn.copied { background: #2d7a3a; color: #fff; border-color: #2d7a3a; font-size: 0.75rem; }

    .hidden { display: none !important; }
    .spotlight-hidden { display: none !important; }
    .empty { color: var(--fg-muted); font-style: italic; padding: 1rem 0; }

    footer {
      color: var(--fg-muted);
      font-size: 0.78rem;
      max-width: 1200px;
      margin: 0 auto 1rem;
      padding: 1.25rem 1.5rem 2rem;
      border-top: 3px solid var(--yellow);
    }
  </style>
```

- [ ] **Step 3: Wrap the `<header>` element in a band div**

The `<header>` element currently sits directly inside `<body>`. Wrap it:

```html
<!-- Before (current): -->
  <header>
    <h1>Andersonville Happenings</h1>
    ...
  </header>

<!-- After: -->
  <div class="site-header-band">
    <header>
      <h1>Andersonville Happenings</h1>
      ...
    </header>
  </div>
```

- [ ] **Step 4: Build and verify**

```bash
python scripts/build_site.py
```

Open `public/index.html` in a browser. Verify:
- Yellow left stripe runs full page height
- Blue header band spans full width with yellow bottom border
- Header subtitle and last-updated are clearly readable (not faint) on blue
- 1.25rem gap between header and spotlight strip (two yellow lines don't touch)
- Yellow live dot in spotlight
- Active "All" filter pill is yellow with dark text
- Section heading (`h2`) bottom border is yellow
- Bucket headings have a yellow left bar
- Price badges are yellow-tinted with dark text
- Tag pills are light blue with blue text
- No-image placeholder cards are light blue (not warm beige)
- Footer has a yellow top border
- Share button hover turns yellow

- [ ] **Step 5: Commit**

```bash
git add templates/index.html
git commit -m "feat: apply Andersonville visual theme to index.html

Swedish blue header band + flag yellow Nordic cross stripe, Albert Sans
font, yellow throughout (filter pill, h2 divider, bucket heading bar,
price badge, footer border). Blue-tint placeholders and tag pills."
```

---

## Task 2: Update `_event_card.html` — placeholder container-type

**Files:**
- Modify: `templates/_event_card.html`

The `.event-placeholder` div needs `container-type: inline-size` for the `clamp(1.1rem, 5cqi, 1.75rem)` font size on `.ph-title` to work. Without it `5cqi` resolves to 0 and the title uses the minimum size only.

- [ ] **Step 1: Add container-type to the placeholder div**

Find the no-image branch in `_event_card.html` (line 25). The current markup is:

```html
    <div class="event-placeholder">
```

Change it to:

```html
    <div class="event-placeholder" style="container-type:inline-size">
```

- [ ] **Step 2: Build and verify**

```bash
python scripts/build_site.py
```

Open `public/index.html`. Find an event card that has no image (e.g., Hopleaf's Zwanze Day or Vincent's Happy Hour). The title inside the blue placeholder area should scale up for short titles and clamp down for long ones. Resize the browser window — the title font size should respond to card width.

- [ ] **Step 3: Commit**

```bash
git add templates/_event_card.html
git commit -m "fix: add container-type to event placeholder for cqi font sizing"
```

---

## Task 3: Update `_event_detail.html` — full CSS rewrite

**Files:**
- Modify: `templates/_event_detail.html`

This template has its own fully independent stylesheet. It currently loads `DM Serif Display` and uses `--accent: #8b3a2f`. The full `<head>` CSS section (lines 21–287) needs replacing. The detail page gets the same yellow stripe and blue header treatment as the main page, adapted for its single-event layout.

- [ ] **Step 1: Replace the Google Fonts link**

Find the existing Google Fonts link (line 22):

```html
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&display=swap" rel="stylesheet">
```

Replace with:

```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
```

- [ ] **Step 2: Replace the entire `<style>` block**

The style block runs from line 24 to line 287. Replace the entire block with:

```html
  <style>
    :root {
      --font:         'Albert Sans', sans-serif;
      --fg:           #1a1a1a;
      --fg-muted:     #5a5a5a;
      --bg:           #faf8f4;
      --card-bg:      #ffffff;
      --border:       #e5e0d5;
      --blue:         #006AA7;
      --blue-dark:    #004f7c;
      --blue-tint:    #e8f3fa;
      --yellow:       #FECC02;
      --yellow-dark:  #3a2800;
      --yellow-mid:   #d4a800;
      --yellow-tint:  #fffbe6;
      --stripe-w:     4px;
    }

    html {
      border-left: var(--stripe-w) solid var(--yellow);
      min-height: 100%;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font);
      background: var(--bg);
      color: var(--fg);
      line-height: 1.5;
    }

    /* Nav band — matches main page header style */
    .detail-nav-band {
      background: var(--blue);
      border-bottom: var(--stripe-w) solid var(--yellow);
    }
    .detail-nav {
      padding: 0.9rem 1.5rem;
      max-width: 680px;
      margin: 0 auto;
    }
    .back-link {
      font-size: 0.85rem;
      font-weight: 600;
      color: rgba(255,255,255,0.9);
      text-decoration: none;
      letter-spacing: 0.01em;
    }
    .back-link:hover { color: #fff; text-decoration: underline; }

    /* Stale notice */
    .stale-notice {
      max-width: 680px;
      margin: 1.25rem auto 0;
      padding: 0.75rem 1.5rem;
      background: var(--yellow-tint);
      border-left: 3px solid var(--yellow);
      font-size: 0.9rem;
      color: #5a3d00;
    }

    /* Main layout */
    .detail-main {
      max-width: 680px;
      margin: 1.25rem auto 0;
      padding: 0 1.5rem 4rem;
    }

    /* Hero image */
    .detail-image {
      background: #0d2a3a;
      border-radius: 10px;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 1.5rem;
      max-height: 520px;
    }
    .detail-image img {
      max-width: 100%; max-height: 520px;
      width: auto; height: auto; display: block;
    }
    .detail-image.is-stale img { filter: grayscale(40%) opacity(0.75); }

    /* Placeholder for no-image events */
    .detail-placeholder {
      background: var(--blue-tint);
      border: 1px solid #c8dff0;
      border-radius: 10px;
      padding: 3rem 2rem;
      text-align: center;
      margin-bottom: 1.5rem;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.75rem;
    }
    .detail-placeholder.is-stale { filter: grayscale(30%) opacity(0.8); }
    .detail-placeholder .ph-business {
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--blue);
      opacity: 0.65;
    }
    .detail-placeholder .ph-rule {
      width: 2.5rem; height: 1px;
      background: var(--blue); opacity: 0.2;
    }
    .detail-placeholder .ph-title {
      font-size: clamp(1.4rem, 5vw, 2.2rem);
      font-weight: 800;
      letter-spacing: -0.025em;
      line-height: 1.15;
      color: var(--blue);
      opacity: 0.5;
    }

    /* Detail card */
    .detail-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.5rem 1.75rem 1.75rem;
    }
    .detail-business {
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--fg-muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 0.4rem;
    }
    .detail-title {
      font-family: var(--font);
      font-size: clamp(1.5rem, 5vw, 2.2rem);
      font-weight: 800;
      letter-spacing: -0.03em;
      line-height: 1.15;
      margin: 0 0 0.5rem;
      color: var(--fg);
    }
    .detail-when {
      font-size: 1rem;
      color: var(--fg-muted);
      margin: 0 0 0.5rem;
    }
    .detail-price {
      display: inline-block;
      font-size: 0.88rem;
      font-weight: 700;
      color: var(--yellow-dark);
      background: var(--yellow-tint);
      border: 1px solid #f0dc5a;
      border-radius: 4px;
      padding: 0.1rem 0.5rem;
      margin: 0 0 0.5rem;
    }
    .detail-desc {
      font-size: 0.95rem;
      margin: 0.75rem 0;
      line-height: 1.6;
    }
    .detail-tags {
      display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.75rem 0;
    }
    .detail-tags .tag {
      font-size: 0.72rem;
      font-weight: 500;
      padding: 0.1rem 0.55rem;
      border-radius: 999px;
      background: var(--blue-tint);
      color: var(--blue);
    }
    .detail-source {
      font-size: 0.78rem;
      color: var(--fg-muted);
      margin-top: 1rem;
      padding-top: 1rem;
      border-top: 1px solid var(--border);
    }
    .detail-source a { color: var(--fg-muted); }

    /* Share button */
    .share-btn {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      margin-top: 1.25rem;
      padding: 0.55rem 1.25rem;
      background: var(--blue);
      color: #fff;
      border: none;
      border-radius: 999px;
      font: inherit;
      font-family: var(--font);
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }
    .share-btn:hover { background: var(--blue-dark); }

    /* Related events section */
    .related-section { margin-top: 2.5rem; }
    .related-heading {
      font-size: 1.1rem;
      font-weight: 800;
      letter-spacing: -0.01em;
      margin: 0 0 1rem;
      padding-bottom: 0.4rem;
      border-bottom: 3px solid var(--yellow);
    }
    .related-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 1rem;
    }

    /* Card styles for related-grid (mirrors index.html) */
    .event {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      position: relative;
      text-decoration: none;
      color: inherit;
    }
    .event-image {
      background: #0d2a3a;
      aspect-ratio: 4 / 5;
      display: flex; align-items: center; justify-content: center;
    }
    .event-image img { max-width: 100%; max-height: 100%; width: auto; height: auto; }
    .event-body { padding: 0.85rem 1rem 1rem; flex: 1; display: flex; flex-direction: column; }
    .event-title { font-weight: 700; font-size: 1rem; letter-spacing: -0.015em; line-height: 1.25; margin: 0 0 0.2rem; }
    .event-when { color: var(--fg-muted); font-size: 0.85rem; margin: 0 0 0.4rem; }
    .event-business { font-size: 0.72rem; font-weight: 600; color: var(--fg-muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 0.15rem; }
    .event-desc { font-size: 0.85rem; margin: 0.2rem 0; flex: 1; line-height: 1.5; }
    .event-price {
      display: inline-block; align-self: flex-start;
      font-size: 0.78rem; font-weight: 700;
      color: var(--yellow-dark);
      background: var(--yellow-tint);
      border: 1px solid #f0dc5a;
      border-radius: 4px;
      padding: 0.05rem 0.45rem;
      margin: 0.3rem 0;
    }
    .event-tags { margin-top: 0.6rem; display: flex; flex-wrap: wrap; gap: 0.3rem; }
    .event-tags .tag {
      font-size: 0.68rem; font-weight: 500; padding: 0.1rem 0.5rem;
      border-radius: 999px; background: var(--blue-tint); color: var(--blue);
    }
    .event-source { font-size: 0.72rem; color: var(--fg-muted); margin-top: 0.55rem; }
    .event-source a { color: var(--fg-muted); }
    .event--no-image { border-left: 3px solid var(--no-image-accent, var(--border)); }
    [data-category="bar"].event--no-image        { --no-image-accent: var(--blue); }
    [data-category="restaurant"].event--no-image { --no-image-accent: #5a8a60; }
    .event-placeholder {
      aspect-ratio: 4 / 5;
      background: var(--blue-tint);
      border-bottom: 1px solid #c8dff0;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      padding: 1.5rem 1.25rem; text-align: center; gap: 0.6rem;
      container-type: inline-size;
    }
    .event-placeholder .ph-business { font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; color: var(--blue); opacity: 0.65; }
    .event-placeholder .ph-rule { width: 1.75rem; height: 1px; background: var(--blue); opacity: 0.2; }
    .event-placeholder .ph-title { font-size: clamp(1.1rem, 5cqi, 1.75rem); font-weight: 800; letter-spacing: -0.02em; line-height: 1.2; color: var(--blue); opacity: 0.45; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }

    /* Back CTA */
    .back-cta { margin-top: 2rem; text-align: center; }
    .back-cta-link {
      font-size: 0.9rem; font-weight: 500;
      color: var(--blue); text-decoration: none;
    }
    .back-cta-link:hover { text-decoration: underline; }

    footer {
      color: var(--fg-muted); font-size: 0.78rem;
      max-width: 680px; margin: 0 auto 2rem;
      padding: 1.25rem 1.5rem 0;
      border-top: 3px solid var(--yellow);
    }
  </style>
```

- [ ] **Step 3: Wrap the `<nav>` in a band div**

The `<nav class="detail-nav">` sits directly inside `<body>`. Wrap it:

```html
<!-- Before: -->
  <nav class="detail-nav">
    <a href="/" class="back-link">← Andersonville Happenings</a>
  </nav>

<!-- After: -->
  <div class="detail-nav-band">
    <nav class="detail-nav">
      <a href="/" class="back-link">← Andersonville Happenings</a>
    </nav>
  </div>
```

- [ ] **Step 4: Build and verify**

```bash
python scripts/build_site.py
```

Open any per-event page in `public/event/` (e.g., `public/event/1/index.html`). Verify:
- Yellow left stripe runs full page height
- Blue nav band spans full width with yellow bottom border
- Back link is white/light text on blue, readable
- Gap between nav band and content (1.25rem from `.detail-main`)
- Stale notice (if visible on that event) uses yellow-tinted background
- Detail title is Albert Sans bold, not serif
- Price is a yellow-tinted badge with dark text
- Tags are light blue with blue text
- Related events section heading has a yellow bottom border
- Footer has a yellow top border
- On a stale event page, related cards in the grid use blue-tint placeholders

- [ ] **Step 5: Commit**

```bash
git add templates/_event_detail.html
git commit -m "feat: apply Andersonville visual theme to event detail page

Matches main page: yellow stripe, blue nav band, Albert Sans, yellow
price badge, blue-tint tags and placeholders. Removes DM Serif Display."
```

---

## Task 4: Deploy

- [ ] **Step 1: Push commits to remote**

```bash
git push
```

- [ ] **Step 2: Trigger Site rebuild workflow**

```bash
gh workflow run "Site rebuild"
```

Expected output: a run URL like `https://github.com/justingonder/aville/actions/runs/...`

- [ ] **Step 3: Watch the run**

```bash
gh run watch
```

Wait for the run to complete (typically ~30s). Expected: green ✓ on all steps.

- [ ] **Step 4: Verify on aville.net**

Open `https://aville.net` in a browser (hard refresh: Cmd+Shift+R). Confirm the live site matches the approved mockup at `.superpowers/brainstorm/3764-1776641972/content/full-design-v3.html`.

Check on mobile too (DevTools device mode is fine) — the yellow left stripe and blue header should look clean at narrow widths.

---

## Self-review notes

**Spec coverage check:**
- ✅ Yellow left stripe on `html` — Task 1 Step 2
- ✅ Blue header band + yellow bottom border — Task 1 Steps 2–3
- ✅ Spotlight margin gap — Task 1 Step 2 (`.spotlight { margin: 1.25rem auto 0 }`)
- ✅ Yellow live dot — Task 1 Step 2
- ✅ Active filter pill → yellow — Task 1 Step 2
- ✅ h2 bottom border → yellow — Task 1 Step 2
- ✅ Bucket heading yellow left bar — Task 1 Step 2
- ✅ Price badge yellow-tinted — Task 1 Step 2, Task 3 Step 2
- ✅ Tag pills → blue-tint — Task 1 Step 2, Task 3 Step 2
- ✅ Placeholder → blue-tint — Task 1 Step 2, Task 3 Step 2
- ✅ Share button hover → yellow — Task 1 Step 2
- ✅ Footer yellow top border — Task 1 Step 2, Task 3 Step 2
- ✅ Header subtitle/last-updated legibility — Task 1 Step 2
- ✅ Albert Sans throughout — Tasks 1, 3
- ✅ `container-type` on placeholder — Task 2
- ✅ Detail page full rewrite — Task 3
- ✅ Dark placeholder backgrounds → navy-blue family only — Task 1 Step 2 (`.event-image { background: #0d2a3a }`)
- ✅ Deploy — Task 4
