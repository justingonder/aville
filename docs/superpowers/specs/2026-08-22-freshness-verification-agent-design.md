# Freshness / verification agent

**Date:** 2026-08-22
**Branch:** `verification-agent` (proposed)
**Status:** design draft, pre-implementation — not yet reviewed
**Scope:** a scheduled pass that re-checks already-extracted events against their
source and records whether the source still asserts them. First component of the
multi-agent quality layer; prerequisite for trusting any noisier source.

## Motivation

The site's binding quality bar is **trust**: the first time a visitor shows up to an
event that isn't happening, we've lost them. Today nothing in the system asks "is
this still true?" — extraction only ever asks "what's on this page right now."

Everything that currently defends against decay is either manual or absent:

| Decay path | Today | Cost of missing it |
| --- | --- | --- |
| Event silently dropped from its source page | `mark_missing_events_stale` (only fires if the page is scraped that run) | medium |
| `status='stale'` rows | linger forever; no expiry rule (open question since April) | 400 rows today |
| Recurring series quietly ended | `ends_on` set **by hand** via `sqlite3`; surfaced by a keyword heuristic | high — a dead weekly shows as live |
| Chicago Magic Lounge show times | re-set **by hand** after every extraction | high |
| Dated events past their date | `_is_past_today()` at build time only; **IG rows never expire at all** | high |
| Wrong day-of-week from extraction | nothing (open item since the BEARAOKE bug) | high |

Every "by hand" in that table is a single point of failure named Justin. One missed
week and the site is confidently wrong.

This spec adds the missing question, and — importantly — spends a model call only
where a model is actually needed.

## Non-goals

- **Not a re-extraction pass.** The verifier never produces new events. If a page has
  grown a new event, that's the daily pipeline's job.
- **No autonomous writes to event content.** The agent proposes; a human (or a later,
  more-trusted loop) disposes. See §4.
- **No new `status` value.** The `CHECK (status IN ('active','expired','stale','rejected'))`
  constraint stays untouched — adding a value means a 12-step table rebuild, which
  CLAUDE.md tells us to avoid. Quarantine happens in a side table instead.
- **No scheduling infrastructure.** Runs from the existing Actions workflow or manually.
  A mini-PC host is a later optimization, not a dependency.
- **Not multi-model everywhere.** Consensus is spent only on destructive conclusions (§5).

## Design

### 1. The narrow question

Extraction asks an open question ("what events are on this page?"). Verification asks a
closed one, per stored event:

> Given this page's current text, does it still assert that **{title}** happens on
> **{recurrence_pattern | date}** at **{start_time}**?

This is a dramatically easier task than extraction — it's recognition against a
candidate, not open-ended structured generation — which is why a small model handles it
reliably and cheaply, and why the output vocabulary can be closed.

### 2. Deterministic pre-pass — code, not agents

**Before any model call**, a pure-Python pass handles everything that is arithmetic.
This is the governing rule for the whole multi-agent layer: *agents for judgment, code
for arithmetic.* A model asked to compare two dates is strictly worse than `datetime`,
and costs money to be worse.

The pre-pass, in order:

1. **Dated event whose `start_datetime` is in the past** → `status='expired'`. No model.
   Applies to **every** `source_type`, which subsumes the never-built IG-aware expiry
   pass the 2026-06-07 handoff called for, and generalizes it so the next channel we add
   doesn't need its own.
2. **`ends_on < today`** or **`starts_on > today`** → already invisible to the site via
   `_is_ended_series` / `_is_unstarted_series`; skip verification entirely, don't spend
   a call on a hidden row.
3. **Day-of-week validation** — recompute the weekday of a recurring event's first
   observed date and compare it to `recurrence_pattern`. Mismatch → flag for review.
   Closes the BEARAOKE-class bug (open since 2026-04-19) with a `datetime` call.
4. **`source_page_hash` unchanged since the last `confirmed` verification** → re-affirm
   `last_verified_at` with **zero model calls**. If the page hasn't changed since we last
   confirmed the event was on it, the event is still on it.

Point 4 is the cheapest verifier in the system and it is *already half-built*: the hash
column has been populated since 2026-04-18 and has never once been compared (the very
first drift-log entry says so). It also means this spec and the `source_page_hash`
change-detection candidate are the same work approached from two ends — build the
comparison once, and both the extraction-skip and the free-verification fall out.

### 3. Closed conclusion vocabulary

The verifier must return exactly one of these. An agent with open-ended output is a
liability; a closed vocabulary is a contract the calling code can branch on.

| Verdict | Meaning | Effect |
| --- | --- | --- |
| `confirmed` | page still asserts the event, schedule matches | touch `last_verified_at` |
| `changed` | still listed, but a decision-critical field differs | queue proposal (§4) |
| `absent` | page loaded cleanly; event is not on it | queue proposal → likely `stale` |
| `ended` | page explicitly states the series has ended / names a final date | queue proposed `ends_on` |
| `unreachable` | fetch failed — non-200, timeout, empty body | **no state change**, log only |
| `indeterminate` | page loaded but the model can't tell (JS shell, ambiguous copy) | **no state change**, log only |

**The critical distinction is `absent` vs. `unreachable` vs. `indeterminate`.** Collapsing
them is how you mark a whole venue's events stale on a transient network blip — and we
know that happens here: 3 `[Errno 104] Connection reset by peer` failures on
`atmospherebar.com` out of 478 fetches. Rules:

- `unreachable` and `indeterminate` **never** change event state. They only increment a
  counter. Three consecutive `unreachable` results for the same page raise an
  operator alert, not a data change.
- `absent` requires a **200 response with non-trivial body text**. A Cloudflare challenge
  page is `unreachable`, never `absent`.
- Only "decision-critical" fields can produce `changed`: normalized `title`,
  `recurrence_pattern`, `start_time`, `end_time`, `start_datetime`, `price_info`. Prose
  fields (`description`, `notes`) are **never** compared — they vary run-to-run even at
  `temperature=0.0`, and CLAUDE.md already warns against string-matching them.

### 4. The agent proposes; it does not write

Two columns on `events` — both *metadata about verification*, never event content, so
they're safe for the agent to write directly:

```sql
ALTER TABLE events ADD COLUMN last_verified_at TEXT;      -- ISO8601
ALTER TABLE events ADD COLUMN last_verified_result TEXT;  -- the §3 verdict
```

Everything else goes to an append-only side table — the review queue:

```sql
CREATE TABLE IF NOT EXISTS event_verifications (
    id            INTEGER PRIMARY KEY,
    event_id      INTEGER NOT NULL,
    checked_at    TEXT    NOT NULL,
    verdict       TEXT    NOT NULL,
    model         TEXT    NOT NULL,   -- which model produced it
    page_hash     TEXT,               -- source_page_hash at check time
    proposed      TEXT,               -- JSON: {field: new_value} for `changed`/`ended`
    evidence      TEXT,               -- the page snippet the verdict rests on
    reasoning     TEXT,
    resolution    TEXT,               -- NULL | 'accepted' | 'rejected' | 'auto'
    FOREIGN KEY (event_id) REFERENCES events(id)
);
```

This is deliberately the same shape as the `source_type` quarantine that worked on
2026-06-07: **experimental output lands somewhere real but invisible, and promotion is a
deliberate act.** An agent misfire produces a bad row in a queue, not a wrong event on
the site. The `evidence` column matters beyond debugging — reading *why* the agent
concluded something is most of the learning value, and it's the only way to calibrate
whether the loop can eventually be trusted to auto-apply.

**Interaction with `locked_fields`:** an event with `status` locked is skipped entirely
(the admin has asserted it). A proposal touching any locked field is recorded with
`resolution='rejected'` and a note — never applied. This reuses the existing lock
semantics rather than inventing a second override mechanism.

**Graduation path.** Start with everything queued. Once there's a track record, allow
auto-apply for the narrow, low-risk case only: `absent` on a `website`-sourced event
whose page hash *changed* and which two models agree on → `status='stale'`
(`resolution='auto'`). Never auto-apply `changed` — a wrong time is worse than a missing
event, because it sends someone to a bar.

### 5. Consensus, spent only where it's destructive

Running two models on every event is waste. Running one model on a decision that removes
an event from the site is reckless. So:

- Single verifier (Haiku, `temperature=0.0`) for the first pass.
- `confirmed` → done. This is the overwhelming majority of rows.
- `changed`, `absent`, or `ended` → **escalate**: re-ask a model from a *different family*
  (Gemini Flash / a GPT-mini / a local Qwen on the mini PC). Two Claude models share
  failure modes; only family diversity is a real second opinion.
- Agree → queue the proposal with `model` recording both. Disagree → queue with verdict
  `indeterminate` and both opinions attached, and change nothing.

This is Justin's tie-breaker idea, narrowed to where it earns its cost: consensus on
destructive conclusions only. Note that agreement is still a *confidence signal*, not a
truth oracle — correlated errors are real — which is why even a 2-0 agreement queues a
proposal rather than writing to `events` in the initial version.

### 6. Site-side freshness rule

A verification date nobody acts on is just a column. The site must express it:

> An event whose `last_verified_at` is older than `stale_after_days` is **still listed**,
> but is **not eligible for the spotlight** ("Happening now" / featured).

This deliberately mirrors a rule the codebase already commits to: *events without a known
`start_time` are excluded from happening-now — we'd rather show nothing than a false
positive.* Same philosophy, new input. Listing an unverified event is low-risk (the
visitor is browsing); spotlighting one is high-risk (the visitor is deciding where to go
right now).

**Corrected against the code 2026-08-22** (an earlier draft of this spec assumed the
spotlight was server-prerendered — it is not). "Happening now" is decided **client-side**
by `isHappeningNow(card, chicago)` in `templates/index.html`, reading `data-` attributes
off each card. So the gate is two small pieces, not a `site_builder.py` filter:

1. `site_builder.py` computes staleness at build time and passes it to the card partial;
   `templates/_event_card.html` emits `data-verify-stale="1"` on affected cards.
2. `isHappeningNow` gains a first-line guard: `if (card.dataset.verifyStale === '1')
   return false;`

That guard sits exactly where the existing `if (!startTime) return false;` bails out — the
same "we'd rather show nothing than a false positive" rule, one line above it. Cards keep
rendering in their normal buckets; they simply can never be promoted to the spotlight.

Thresholds live in `config/verification.yaml` (config over code):

```yaml
stale_after_days: 10          # older than this → no spotlight
verify_within_days: 7         # target: every active event checked this often
dated_event_lead_days: 3      # verify dated events daily inside this window
max_events_per_run: 40        # cost ceiling
unreachable_alert_streak: 3
```

### 7. Cadence and cost

~158 active published events today (61 dated + 97 recurring). Verifying all of them daily
is unnecessary; a **rotation** works:

1. Deterministic pre-pass over everything (free).
2. Hash-unchanged rows auto-confirm (free).
3. Remaining rows sorted by risk: dated events inside `dated_event_lead_days` first, then
   oldest `last_verified_at`, capped at `max_events_per_run`.

Cost is page text only — no images, no vision — against Haiku. At a few thousand tokens
per check and a 40-event cap, this is cents per day; the dominant real cost is fetch time,
and most of that is avoided by the hash short-circuit. Runs as a separate Actions workflow
so a verification failure can never block the extraction deploy.

### 8. Known gap: non-website sources

IG-sourced rows have an Instagram permalink as `source_page_url`. Our fetcher can't
retrieve it, and shouldn't try — so live verification is impossible for them by design,
and they'd all return `unreachable` forever.

Interim rule: for `source_type != 'website'`, apply the deterministic pre-pass only, and
seed `last_verified_at` from the ingestion timestamp. Recurring IG events will therefore
age out of spotlight eligibility after `stale_after_days` and never age back in.

That is the correct conservative behavior, and it is also exactly the constraint that
should shape the Instagram-cadence work: a source we cannot re-verify can only ever be
trusted as far as its last ingest. Any durable IG path needs to answer "how do we
re-check?" before it answers "how do we get more?"

## Files touched

- `src/db.py` — two `ALTER TABLE` migrations (idempotent, existing try/except pattern);
  `event_verifications` table in `SCHEMA`; queue read/write helpers.
- `src/verifier.py` — **new.** Fetch (reusing `fetcher` + per-business `use_playwright`),
  build the §1 question, call the model, parse into the §3 vocabulary.
- `scripts/run_verification.py` — **new.** Entry point; `--dry-run`, `--limit N`,
  `--event-id N`, `--business <slug>`.
- `src/site_builder.py` — freshness gate on spotlight eligibility (§6).
- `config/verification.yaml` — **new.** Thresholds.
- `scripts/admin.py` — review-queue view: pending proposals, accept/reject, which writes
  through the existing per-field lock machinery.
- `.github/workflows/verification.yml` — **new.** Separate from extraction.

Conventions: procedural, stdlib-preferred, `print` logging, no new pip dependencies
(a second model family may need one — flag at implementation time rather than assuming).

## Risks / things to watch

- **False `absent` on JS-heavy pages.** Squarespace/Wix event calendars render client-side;
  a plain-httpx fetch sees an empty shell. Mitigation: the verifier must honor the same
  `use_playwright` flag the pipeline uses, and treat a body below a minimum text length as
  `indeterminate`, never `absent`.
- **Verifying against the wrong page.** Several businesses have events spread across pages
  (SoFo Tap's `/events` vs `/events-2`). An event absent from its recorded
  `source_page_url` may have simply moved. Mitigation: `absent` proposals name the page
  checked, and the nav-link-discovery idea (long-deferred) becomes the real fix.
- **Recurring events that are seasonally quiet.** A patio series absent in January isn't
  ended. `ended` requires an explicit page statement, never inference from absence.
- **The rotation hiding a systematic failure.** If one business's pages start failing, the
  rotation spreads the damage thinly and it looks like noise. Hence
  `unreachable_alert_streak` — count per *page*, not per event.
- **Scope creep into re-extraction.** The moment the verifier starts proposing *new* events
  it becomes a second, weaker extraction pipeline. Keep the question closed.

## Verification (of this feature)

- Migrations idempotent: run `init_db()` twice, no error; existing rows have
  `last_verified_at IS NULL`.
- Seed a known-good event → run → `confirmed`, `last_verified_at` set, no queue row.
- Point an event at a URL that 404s → `unreachable`, **status unchanged**, queue row logged.
- Hand-edit an event's `start_time` to a wrong value → `changed`, proposal names
  `start_time` with the page's actual value.
- Delete an event's listing from a local fixture page → `absent`, escalates to the second
  model, proposal queued, `status` still `active` until accepted.
- Backdate `last_verified_at` past `stale_after_days` → event still renders in its bucket,
  absent from spotlight.
- Lock `status` on an event → skipped entirely; no queue row, no model call.
- Full run against production data with `--dry-run`: zero writes, printed summary of what
  each verdict would have done.
