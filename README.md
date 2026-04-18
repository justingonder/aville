# Andersonville Happenings

A proof-of-concept pipeline that extracts events, happy hours, and specials
from a curated list of Andersonville business websites, stores them in a
database, and publishes a simple static site.

**Status:** v1 / proof of concept. Scope is intentionally tiny (under 10
businesses, websites only, shareable link for friends and the Chamber).

## Architecture

```
   ┌───────────────────┐
   │ config/           │
   │  businesses.yaml  │◄── hand-edited list of sites to scrape
   │  tags.yaml        │◄── controlled vocabulary for faceting
   └────────┬──────────┘
            │
            ▼
   ┌───────────────────┐        ┌──────────────────┐
   │ fetch (httpx)     │───────►│ discover + cache │
   │                   │        │ images           │
   └────────┬──────────┘        └─────────┬────────┘
            │                             │
            ▼                             ▼
         ┌─────────────────────────────────┐
         │ extract (Claude Haiku, vision)  │──► JSON list of events
         └─────────────────┬───────────────┘
                           ▼
                  ┌────────────────┐
                  │ upsert → SQLite│
                  └────────┬───────┘
                           ▼
                ┌──────────────────────┐
                │ render static HTML   │──► public/index.html + public/images/
                └──────────┬───────────┘
                           ▼
                ┌──────────────────────┐
                │ deploy (rsync/SFTP)  │──► Namecheap public_html/
                └──────────────────────┘
```

Extraction runs on GitHub Actions (free, scheduled, good logs). The output
(static HTML + cached images) is deployed via rsync to your Namecheap shared
hosting. Namecheap only serves static files; it doesn't run any of the
pipeline.

## Project layout

```
.
├── config/
│   ├── businesses.yaml     # the sites to scrape (edit this)
│   └── tags.yaml           # controlled tag vocabulary
├── src/
│   ├── db.py               # SQLite schema + upserts
│   ├── fetcher.py          # httpx-based HTML/image fetching
│   ├── images.py           # image discovery, filtering, download
│   ├── prompts.py          # extraction prompt
│   ├── extractor.py        # Claude API call (vision)
│   ├── pipeline.py         # orchestrator
│   └── site_builder.py     # Jinja → static site
├── scripts/
│   ├── init_db.py
│   ├── run_extraction.py   # the daily job
│   ├── test_extraction.py  # iterate on a single URL
│   └── build_site.py
├── templates/
│   ├── index.html
│   └── _event_card.html
├── data/app.db             # SQLite (gitignored; or commit if you want history)
├── public/                 # generated output
│   ├── index.html
│   └── images/<slug>/*.jpg
└── .github/workflows/scheduled.yml
```

## Quickstart (local)

You'll need Python 3.11+ and an Anthropic API key.

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# edit .env and paste in your ANTHROPIC_API_KEY

# 3. Initialize DB
python scripts/init_db.py

# 4. Test against a single URL FIRST. This is how you iterate on the prompt.
python scripts/test_extraction.py meeting-house-tavern \
    https://meetinghousetavern.com/events

# 5. When extraction looks right, run the full pipeline.
python scripts/run_extraction.py

# 6. Build the site and open it in a browser.
python scripts/build_site.py
open public/index.html     # or: xdg-open / start
```

## Iterating on the extraction prompt

**Do this before anything else.** The project lives or dies by whether
Claude extracts events correctly from messy real-world pages. Don't wire up
automation until the prompt is solid.

1. Pick a site you're skeptical about (e.g. Meeting House, because the text
   is buried inside stylized images).
2. Run `test_extraction.py` against it and read the JSON output carefully.
3. Look for: wrong titles, hallucinated prices, events extracted from
   decorative images, happy hours missed, recurrence pattern misread.
4. Tweak `src/prompts.py` (the `SYSTEM_PROMPT`) OR `config/businesses.yaml`
   (the `hints` field for that business) — whichever fits the issue.
5. Re-run. Repeat until you're happy.
6. Add another business. Re-check that your prompt changes didn't regress
   the first business.

Things you'll likely need to iterate on:

- **Ambiguous recurrence.** "Weekends" vs "Friday & Saturday" vs "Fri–Sun".
  The prompt specifies a format but the source is often sloppy.
- **Missing year in dates.** The prompt says "use the nearest future date".
  Verify this actually happens, especially around year boundaries.
- **Decorative images making it through.** If you see an event based on a
  food photo or staff portrait, tighten the "skip" rules in `SYSTEM_PROMPT`.
- **Sub-events inside one flyer.** A "Pride Week" flyer might list multiple
  days of events. Decide whether that becomes one event or many — I'd argue
  many, and update the prompt to say so.

## Adding a business

1. Append to `config/businesses.yaml`.
2. Include a `hints` field — it meaningfully improves extraction quality.
3. Run `test_extraction.py <slug> <url>` to see what Claude does.
4. If the site is JavaScript-rendered (content missing from the HTML), you'll
   need to add Playwright as a fetcher. Not needed for the two Squarespace
   sites in the initial config.

## Tags

Controlled vocabulary lives in `config/tags.yaml`. The prompt forces Claude
to pick only from the list. Claude can propose new tags in a
`suggested_new_tags` field on each event; review those and promote them to
the vocabulary as you see patterns.

## Deploying to Namecheap

Set up in GitHub repo settings → Secrets / Variables:

| Type     | Name                   | Value                                             |
| -------- | ---------------------- | ------------------------------------------------- |
| Secret   | `ANTHROPIC_API_KEY`    | your API key                                      |
| Secret   | `NAMECHEAP_SSH_HOST`   | e.g. `server123.web-hosting.com`                  |
| Secret   | `NAMECHEAP_SSH_USER`   | your cPanel username                              |
| Secret   | `NAMECHEAP_SSH_KEY`    | private SSH key (contents, not path)              |
| Variable | `NAMECHEAP_SSH_PATH`   | e.g. `/home/USER/public_html/andersonville/`      |
| Variable | `EXTRACTION_MODEL`     | optional, defaults to `claude-haiku-4-5-20251001` |

Then enable Actions and the workflow in `.github/workflows/scheduled.yml`
will run daily at 6am Chicago time and deploy to Namecheap.

**Namecheap SSH note:** Namecheap shared hosting typically uses port **21098**
(not 22) for SSH. The workflow already passes `-p 21098`. Adjust if your
plan differs.

## What's deliberately NOT in v1

- **Instagram / Facebook.** Shelved after research — see earlier design notes.
  Worth revisiting once there's Chamber buy-in and a reason to go through
  Meta App Review.
- **User submissions.** Spam moderation is its own project.
- **Admin UI.** Edit `businesses.yaml` and re-run. If you need to kill a
  bad extraction, `UPDATE events SET status='rejected' WHERE id = ...`
  in sqlite3.
- **Search, calendar view, multiple pages.** One page that lists
  "what's happening" is enough to show the Chamber.
- **Separate tables for recurring vs. dated events.** Considered it;
  rolled back for v1 simplicity. Revisit if queries get awkward.

## Cost sanity check

Haiku 4.5 at current rates, ~10 pages per daily run with images:
expect **well under $5/month**. Namecheap hosting you already have.
GitHub Actions free tier is more than enough for a daily job.

## What breaks and how

- **Site redesign** → HTML structure changes → extraction may go sideways.
  Mitigation: `status='stale'` flag flips events that disappear between
  runs, so you'll notice.
- **JS-rendered site added to config** → empty page_text, no images found.
  Mitigation: swap `fetcher.fetch_html` for a Playwright-based version for
  that specific site.
- **Claude API outage** → pipeline logs the error and continues with the
  other businesses. Previous events stay in the DB, marked stale.
- **Namecheap down** → deploy step fails but extraction and DB update
  already succeeded. Next successful run re-deploys.
