# Freshness / verification agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scheduled pass that re-checks already-extracted events against their source and records whether the source still asserts them — so the site can stop showing events nobody has confirmed in weeks.

**Architecture:** A deterministic Python pre-pass handles everything that is arithmetic (past-dated expiry, series windows, weekday validation, unchanged-page short-circuit) and costs nothing. Only what survives reaches a model, which answers one closed question per event and returns one of six verdicts. Verdicts that would *remove or alter* an event escalate to a second model from a different family; agreement still only writes a **proposal** to an append-only `event_verifications` queue, never to `events`. Two metadata columns (`last_verified_at`, `last_verified_result`) are the sole direct writes. The site consumes freshness by refusing to spotlight an unverified event — the same "we'd rather show nothing than a false positive" rule already applied to events with no `start_time`.

**Tech Stack:** Python 3 (stdlib + existing deps: `httpx`, `anthropic`, `pyyaml`), SQLite, Jinja2. No test framework in this repo — verification uses throwaway temp-DB assertion scripts in `scripts/test_*.py` with plain `assert`, plus `--dry-run` against real data. NOT pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-freshness-verification-agent-design.md`

**Branch:** `verification-agent`

---

## File Structure

- `src/db.py` (modify) — two `events` columns + migrations; `event_verifications` table in `SCHEMA`; queue helpers; `events_needing_verification()` reader.
- `src/prompts.py` (modify) — `VERIFICATION_PROMPT` + `build_verification_user_prompt()`.
- `src/verifier.py` (create) — pre-pass, fetch wrapper, model call, verdict parsing, escalation.
- `scripts/run_verification.py` (create) — CLI entry point.
- `scripts/test_verifier_helpers.py` (create) — assertion tests for the pure functions.
- `src/site_builder.py` (modify) — `_is_verify_stale()` + set on each event dict.
- `templates/_event_card.html` (modify) — emit `data-verify-stale`.
- `templates/index.html` (modify) — one-line guard in `isHappeningNow`.
- `config/verification.yaml` (create) — thresholds.
- `.github/workflows/verification.yml` (create) — scheduled run at 10:00 UTC.

**Out of scope for this plan (Phase 2):** the `scripts/admin.py` review-queue UI. Until it exists, the queue is read with `sqlite3`. `admin.py` is 79 KB and deserves its own plan; blocking Phase 1 on it delays every benefit.

---

## Task 1: Schema — verification columns + queue table

**Files:** Modify `src/db.py`

- [ ] **Step 1: Add the two metadata columns to `SCHEMA`**

In the `events` `CREATE TABLE`, after the `starts_on` / `ticket_url` block, add:

```python
    last_verified_at   TEXT,    -- ISO8601; last time a verification pass CONFIRMED
                                -- this event against its source. Metadata about
                                -- verification, never event content.
    last_verified_result TEXT,  -- the verdict from that pass (see verifier.VERDICTS)
```

- [ ] **Step 2: Add idempotent migrations**

In `init_db`, after the existing `source_type` migration `try/except`, append two more in the same style:

```python
        try:
            conn.execute("ALTER TABLE events ADD COLUMN last_verified_at TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE events ADD COLUMN last_verified_result TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
```

- [ ] **Step 3: Add the queue table to `SCHEMA`**

Append to the `SCHEMA` string (it is executed with `IF NOT EXISTS`, so existing DBs pick it up on the next `init_db()` with no migration needed):

```sql
CREATE TABLE IF NOT EXISTS event_verifications (
    id            INTEGER PRIMARY KEY,
    event_id      INTEGER NOT NULL,
    checked_at    TEXT    NOT NULL,
    verdict       TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    page_hash     TEXT,
    proposed      TEXT,
    evidence      TEXT,
    reasoning     TEXT,
    resolution    TEXT,
    FOREIGN KEY (event_id) REFERENCES events(id)
);
CREATE INDEX IF NOT EXISTS idx_verifications_event ON event_verifications (event_id);
CREATE INDEX IF NOT EXISTS idx_verifications_open  ON event_verifications (resolution)
    WHERE resolution IS NULL;
```

- [ ] **Step 4: Helpers**

```python
def record_verification(conn, event_id: int, *, verdict: str, model: str,
                        page_hash: str | None = None, proposed: dict | None = None,
                        evidence: str | None = None, reasoning: str | None = None,
                        resolution: str | None = None) -> int:
    """Append one verification result. Returns the new row id."""
    cur = conn.execute(
        """INSERT INTO event_verifications
           (event_id, checked_at, verdict, model, page_hash, proposed,
            evidence, reasoning, resolution)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, now_iso(), verdict, model, page_hash,
         json.dumps(proposed) if proposed else None,
         evidence, reasoning, resolution),
    )
    return cur.lastrowid


def touch_verified(conn, event_id: int, verdict: str) -> None:
    """Record that this event was checked. The ONLY direct write to events."""
    conn.execute(
        "UPDATE events SET last_verified_at = ?, last_verified_result = ? WHERE id = ?",
        (now_iso(), verdict, event_id),
    )


def open_proposals(conn) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT v.*, e.title, e.kind, b.name AS business_name
           FROM event_verifications v
           JOIN events e ON v.event_id = e.id
           JOIN businesses b ON e.business_id = b.id
           WHERE v.resolution IS NULL AND v.proposed IS NOT NULL
           ORDER BY v.checked_at DESC""",
    ).fetchall()
```

- [ ] **Step 5: The work-queue reader**

```python
def events_needing_verification(conn, *, limit: int) -> list[sqlite3.Row]:
    """Active events, oldest-verified first, never-verified first of all.

    Ordering IS the prioritisation: NULLs sort first under ASC in SQLite, so
    the initial sweep naturally covers everything before re-checking anything.
    Dated events inside their lead window are lifted to the very front by the
    caller (see verifier.prioritise) rather than here — keeping this query dumb.
    """
    return conn.execute(
        """SELECT e.*, b.slug AS business_slug, b.name AS business_name
           FROM events e JOIN businesses b ON e.business_id = b.id
           WHERE e.status = 'active'
           ORDER BY e.last_verified_at ASC, e.id ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()
```

> Note: deliberately **not** filtered by `PUBLISHED_SOURCE_TYPES`. Verifying quarantined rows is cheap and keeps their metadata honest for whenever they're promoted.

**Verification:**
- [ ] `python3 scripts/init_db.py` twice in a row — no error.
- [ ] `sqlite3 data/app.db "PRAGMA table_info(events)"` shows both new columns; existing rows have `NULL`.
- [ ] `sqlite3 data/app.db ".schema event_verifications"` shows the table + both indexes.
- [ ] `sqlite3 data/app.db "SELECT count(*) FROM events"` unchanged (538-ish — confirm against pre-migration count).

---

## Task 2: Deterministic pre-pass (no model calls)

**Files:** Create `src/verifier.py`; create `scripts/test_verifier_helpers.py`

This task must land and be verified **before** any model code exists. It delivers real value on its own — it is the never-built IG-aware expiry pass, generalised.

- [ ] **Step 1: Module header + verdict vocabulary**

```python
"""Freshness verification: re-check stored events against their source.

Unlike extraction (open question: "what events are on this page?"), verification
asks a closed one per event and returns one of VERDICTS. Anything that is
arithmetic is done here in Python, before a model is ever called.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")

VERDICTS = (
    "confirmed",       # source still asserts the event, schedule matches
    "changed",         # still listed, decision-critical field differs
    "absent",          # page loaded cleanly, event not on it
    "ended",           # page explicitly states the series has ended
    "unreachable",     # fetch failed — non-2xx, timeout, empty/challenge body
    "indeterminate",   # page loaded, model cannot tell
)

# Verdicts that would remove or alter an event. These escalate to a second
# model (different family) and NEVER auto-apply in Phase 1.
DESTRUCTIVE_VERDICTS = ("changed", "absent", "ended")

# Verdicts that must never change event state, only be logged.
INERT_VERDICTS = ("unreachable", "indeterminate")

# Fields a `changed` verdict may propose. Prose fields are excluded on purpose:
# description/notes vary run-to-run even at temperature=0.0 (see CLAUDE.md).
DECISION_CRITICAL_FIELDS = (
    "title", "recurrence_pattern", "start_time", "end_time",
    "start_datetime", "price_info",
)

MIN_BODY_CHARS = 400   # below this, a 200 response is a shell/challenge page
```

- [ ] **Step 2: Past-dated expiry — the free win**

```python
def expire_past_dated(conn, today: date) -> list[int]:
    """Expire dated events whose date has passed. Returns affected event ids.

    Applies to EVERY source_type. This is the durable replacement for the
    one-off Instagram cleanup noted in the 2026-06-07 handoff: the daily
    pipeline only scrapes website pages, so mark_missing_events_stale never
    touches IG rows and they would otherwise stay 'active' forever.

    Respects locked_fields: an admin who locked `status` has asserted it.
    """
    rows = conn.execute(
        """SELECT id, locked_fields FROM events
           WHERE kind = 'dated' AND status = 'active'
             AND start_datetime IS NOT NULL
             AND substr(start_datetime, 1, 10) < ?""",
        (today.isoformat(),),
    ).fetchall()
    changed = []
    for row in rows:
        locked = set(json.loads(row["locked_fields"] or "[]"))
        if "status" in locked:
            continue
        conn.execute("UPDATE events SET status = 'expired' WHERE id = ?", (row["id"],))
        changed.append(row["id"])
    return changed
```

- [ ] **Step 3: Skip rules for hidden rows**

```python
def is_hidden_series(ev: dict, today: date) -> bool:
    """True if a recurring event is already invisible via starts_on/ends_on.

    Mirrors site_builder._series_inactive. Don't spend a model call on a row
    the site isn't showing.
    """
    if ev.get("kind") != "recurring":
        return False
    ends_on, starts_on = ev.get("ends_on"), ev.get("starts_on")
    try:
        if ends_on and date.fromisoformat(ends_on) < today:
            return True
        if starts_on and date.fromisoformat(starts_on) > today:
            return True
    except ValueError:
        return False
    return False
```

- [ ] **Step 4: Day-of-week validation**

```python
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday",
             "friday", "saturday", "sunday")


def weekday_mismatch(ev: dict) -> str | None:
    """Return a description if starts_on's weekday contradicts recurrence_pattern.

    Closes the BEARAOKE-class bug (extracted weekly:saturday, actually Sunday).

    LIMITATION, deliberately not papered over: this only fires when `starts_on`
    is set, because that is the ONLY real occurrence date we store. `first_seen_at`
    is when *we* scraped the page, not when the event happens, and using it would
    manufacture false positives. Broader coverage needs an observed-occurrence
    date we do not currently record — note it, don't fake it.
    """
    if ev.get("kind") != "recurring":
        return None
    pattern, starts_on = ev.get("recurrence_pattern"), ev.get("starts_on")
    if not pattern or not starts_on or not pattern.startswith("weekly:"):
        return None
    try:
        actual = _WEEKDAYS[date.fromisoformat(starts_on).weekday()]
    except ValueError:
        return None
    claimed = {d.strip().lower() for d in pattern.split(":", 1)[1].split(",")}
    if "-" in pattern:      # ranges like weekly:tue-fri — out of scope, skip
        return None
    if actual not in claimed:
        return (f"starts_on {starts_on} is a {actual.title()}, "
                f"but recurrence_pattern says {pattern}")
    return None
```

- [ ] **Step 5: Prioritisation**

```python
def prioritise(rows: list, today: date, lead_days: int) -> list:
    """Dated events inside their lead window first, then oldest-verified."""
    def key(r):
        if r["kind"] == "dated" and r["start_datetime"]:
            try:
                d = date.fromisoformat(r["start_datetime"][:10])
                if today <= d <= today + timedelta(days=lead_days):
                    return (0, r["last_verified_at"] or "")
            except ValueError:
                pass
        return (1, r["last_verified_at"] or "")
    return sorted(rows, key=key)
```

- [ ] **Step 6: Tests — `scripts/test_verifier_helpers.py`**

Follow the shape of `scripts/test_session3_helpers.py` (plain asserts, temp DB via `sqlite3.connect(":memory:")`, print a pass count at the end). Cover at minimum:

- `expire_past_dated`: expires a yesterday-dated active row; leaves tomorrow's alone; leaves an already-`expired` row alone; **skips a row with `status` in `locked_fields`**; expires an `instagram` row (the regression this whole function exists for).
- `is_hidden_series`: past `ends_on` → True; future `starts_on` → True; both null → False; malformed date → False; `kind='dated'` → False.
- `weekday_mismatch`: `weekly:saturday` + a Sunday `starts_on` → message; matching day → None; `starts_on` null → None; range pattern → None; CSV pattern containing the actual day → None.
- `prioritise`: a dated event 2 days out sorts ahead of a never-verified recurring event; ties break on `last_verified_at`.

**Verification:**
- [ ] `python3 scripts/test_verifier_helpers.py` — all assertions pass.
- [ ] Against a **copy** of the real DB: `expire_past_dated` reports a plausible count and `SELECT count(*) FROM events WHERE status='active' AND kind='dated' AND substr(start_datetime,1,10) < date('now')` returns 0 afterward.

---

## Task 3: Fetch wrapper + the unchanged-hash short-circuit

**Files:** Modify `src/verifier.py`

- [ ] **Step 1: Fetch, reusing the pipeline's Playwright decision**

```python
from .fetcher import fetch_html, fetch_html_playwright
from .images import page_text


def fetch_for_verification(url: str, *, use_playwright: bool) -> tuple[str | None, str | None, str | None]:
    """Return (text, content_hash, failure_reason).

    A non-None failure_reason means the caller MUST record 'unreachable' and
    change nothing. Distinguishing this from 'absent' is the single most
    important behaviour in the module: 3 of 478 fetches to atmospherebar.com
    have failed with connection resets, and conflating the two would mark a
    venue's whole catalogue stale on a blip.
    """
    fetcher = fetch_html_playwright if use_playwright else fetch_html
    try:
        html, content_hash, _status = fetcher(url)
    except Exception as exc:                      # httpx errors, timeouts, 4xx/5xx
        return None, None, f"fetch-error: {type(exc).__name__}: {exc}"
    text = page_text(html)
    if len(text.strip()) < MIN_BODY_CHARS:
        # JS shell, Cloudflare interstitial, or an empty page. NOT evidence of absence.
        return None, content_hash, f"body-too-short ({len(text.strip())} chars)"
    return text, content_hash, None
```

- [ ] **Step 2: The zero-cost verifier**

```python
def hash_confirms(ev: dict, current_hash: str | None) -> bool:
    """True if the page is byte-identical to the last CONFIRMED check.

    If the page hasn't changed since we last confirmed this event was on it,
    it is still on it. No model call. This is the cheapest verifier in the
    system and the reason source_page_hash exists — it has been stored since
    2026-04-18 and never once compared.
    """
    return bool(
        current_hash
        and ev.get("source_page_hash")
        and ev.get("last_verified_result") == "confirmed"
        and ev["source_page_hash"] == current_hash
    )
```

- [ ] **Step 3: Per-page fetch cache**

Many events share one `source_page_url`. Fetch each URL **once per run** and reuse the result across all its events — with Playwright pages this is the difference between a 2-minute run and a 20-minute one.

```python
class PageCache:
    def __init__(self): self._cache = {}
    def get(self, url: str, *, use_playwright: bool):
        if url not in self._cache:
            self._cache[url] = fetch_for_verification(url, use_playwright=use_playwright)
        return self._cache[url]
```

**Verification:**
- [ ] `fetch_for_verification` on a known-good business URL returns text and a hash, no reason.
- [ ] On `https://aville.net/definitely-not-a-page` returns a reason, and the reason mentions the status/exception.
- [ ] `hash_confirms` returns False when `last_verified_result` is anything but `confirmed` (a previously-`absent` event must not be confirmed by an unchanged page).
- [ ] `PageCache` issues exactly one fetch for two events sharing a URL — assert via a counter-wrapped fake.

---

## Task 4: The model call

**Files:** Modify `src/prompts.py`; modify `src/verifier.py`

- [ ] **Step 1: `VERIFICATION_PROMPT` in `src/prompts.py`**

```python
VERIFICATION_PROMPT = """You verify whether a previously-recorded event is STILL asserted by its source page.

You are NOT extracting events. Do not report events other than the one described. Do not
infer, guess, or fill gaps — you are checking a specific claim against a specific page.

Return exactly one JSON object, no prose, no code fences:

{
  "verdict": "confirmed" | "changed" | "absent" | "ended" | "indeterminate",
  "evidence": "<the shortest verbatim quote from the page that justifies the verdict, or null>",
  "reasoning": "<one sentence>",
  "proposed": { "<field>": "<new value>" }   // ONLY for "changed" / "ended"; else {}
}

Verdict rules:

- "confirmed"  — the page still advertises this event and the schedule matches. Minor
                 wording differences in the description are NOT a change.
- "changed"    — the page still advertises this event, but one of these differs:
                 title, recurrence_pattern, start_time, end_time, start_datetime, price_info.
                 Put ONLY the differing fields in "proposed", using the page's values.
- "absent"     — the page loads and clearly does not advertise this event at all.
- "ended"      — the page explicitly states the series has finished or names a final date.
                 Put the last date in "proposed" as {"ends_on": "YYYY-MM-DD"}.
                 An event simply not being mentioned is "absent", NOT "ended".
- "indeterminate" — you cannot tell. Use this freely. It is always safe.

Critical: prefer "indeterminate" to a wrong "absent". Removing a real event from a
neighbourhood listing is worse than leaving a doubtful one up for another day. If the page
looks like a navigation shell, a cookie wall, or a calendar that renders elsewhere, that is
"indeterminate".

Times are 24-hour "HH:MM". Dates are ISO "YYYY-MM-DD". All times are America/Chicago.
"""


def build_verification_user_prompt(*, business_name, page_url, event, today_iso):
    """Render the single closed question for one stored event."""
    if event["kind"] == "recurring":
        when = f"recurring: {event.get('recurrence_pattern') or '(no pattern recorded)'}"
    else:
        when = f"dated: {(event.get('start_datetime') or '')[:10] or '(no date recorded)'}"
    return f"""Today is {today_iso}.

VENUE: {business_name}
PAGE: {page_url}

THE RECORDED EVENT TO VERIFY:
  title:      {event['title']}
  when:       {when}
  start_time: {event.get('start_time') or '(none recorded)'}
  end_time:   {event.get('end_time') or '(none recorded)'}
  price_info: {event.get('price_info') or '(none recorded)'}

CURRENT PAGE TEXT:
\"\"\"
{{page_text}}
\"\"\"

Return the JSON object now."""
```

> Note the `{{page_text}}` placeholder is filled by the caller after truncation — keep the page text out of the f-string so a huge page can be trimmed independently.

- [ ] **Step 2: The call, in `src/verifier.py`**

Reuse `extractor._extract_json_object` rather than writing a second tolerant parser.

```python
MAX_PAGE_CHARS = 20_000   # verification needs the listing, not the whole site


def verify_one(*, business_name, page_url, event, page_text_str,
               model=None, today=None) -> dict:
    """One model call. Returns a normalised result dict; never raises on a bad verdict."""
    from anthropic import Anthropic
    from .extractor import _extract_json_object

    client = Anthropic()
    model = model or os.environ.get("VERIFICATION_MODEL",
                                    os.environ.get("EXTRACTION_MODEL",
                                                   "claude-haiku-4-5-20251001"))
    today = today or datetime.now(CHICAGO).date()

    template = build_verification_user_prompt(
        business_name=business_name, page_url=page_url,
        event=event, today_iso=today.isoformat(),
    )
    user_text = template.replace("{page_text}", page_text_str[:MAX_PAGE_CHARS])

    resp = client.messages.create(
        model=model, max_tokens=1024, system=VERIFICATION_PROMPT,
        temperature=0.0, messages=[{"role": "user", "content": user_text}],
    )
    text_out = "".join(b.text for b in resp.content if b.type == "text")
    try:
        data = _extract_json_object(text_out)
    except ValueError as exc:
        return {"verdict": "indeterminate", "model": model, "proposed": {},
                "evidence": None, "reasoning": f"unparseable response: {exc}"}
    return normalise_result(data, model)


def normalise_result(data: dict, model: str) -> dict:
    """Coerce a model response into the closed vocabulary. Unknown ⇒ indeterminate."""
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS or verdict == "unreachable":
        # 'unreachable' is a fetch outcome, never a model opinion.
        verdict = "indeterminate"
    proposed = data.get("proposed") or {}
    if not isinstance(proposed, dict):
        proposed = {}
    allowed = set(DECISION_CRITICAL_FIELDS) | {"ends_on"}
    proposed = {k: v for k, v in proposed.items() if k in allowed}
    if verdict in ("changed", "ended") and not proposed:
        # A destructive verdict with nothing to act on is not actionable.
        verdict = "indeterminate"
    return {"verdict": verdict, "model": model, "proposed": proposed,
            "evidence": data.get("evidence"), "reasoning": data.get("reasoning")}
```

**Verification:**
- [ ] `normalise_result` unit assertions (add to the Task 2 test file): unknown verdict → `indeterminate`; `unreachable` from the model → `indeterminate`; `changed` with empty `proposed` → `indeterminate`; `proposed` containing `description` → that key stripped.
- [ ] Live single-event check via the Task 6 CLI `--event-id` against a known-good recurring event → `confirmed` with a real quote in `evidence`.
- [ ] Live check against an event whose `start_time` you temporarily corrupted in a DB copy → `changed`, `proposed.start_time` matching the page.

---

## Task 5: Escalation — consensus only where it's destructive

**Files:** Modify `src/verifier.py`

- [ ] **Step 1: The escalation rule**

```python
def resolve_with_escalation(*, first: dict, rerun, ) -> dict:
    """Confirmations stand alone; destructive verdicts need a second opinion.

    `rerun` is a zero-arg callable performing the same check with a different
    model. Two models from the SAME family share failure modes, so the second
    model must come from a different family (config: escalation_model) or this
    is theatre.
    """
    if first["verdict"] not in DESTRUCTIVE_VERDICTS:
        return first
    second = rerun()
    if second["verdict"] == first["verdict"]:
        return {**first, "model": f"{first['model']}+{second['model']}",
                "reasoning": f"{first['reasoning']} | agreed: {second['reasoning']}"}
    return {"verdict": "indeterminate",
            "model": f"{first['model']}+{second['model']}", "proposed": {},
            "evidence": first.get("evidence"),
            "reasoning": (f"disagreement — {first['model']}: {first['verdict']}; "
                          f"{second['model']}: {second['verdict']}")}
```

- [ ] **Step 2: Second-family plumbing**

`escalation_model` comes from `config/verification.yaml`. If it is unset or names the same family as the primary, `resolve_with_escalation` still runs but **logs a warning that consensus is degraded** — silence here would let a same-family rerun masquerade as a second opinion.

If no second provider is configured yet, set `escalation_model: null` and the destructive verdict is queued with `model` recording that it was unescalated. It still does not auto-apply, so this is safe — just weaker.

**Verification:**
- [ ] `confirmed` never calls `rerun` (assert with a counter).
- [ ] Two agreeing `absent` results → `absent`, `model` contains both names.
- [ ] `absent` then `confirmed` → `indeterminate`, empty `proposed`, reasoning names both.

---

## Task 6: The run loop + CLI

**Files:** Create `scripts/run_verification.py`; create `config/verification.yaml`

- [ ] **Step 1: `config/verification.yaml`**

```yaml
# Freshness verification thresholds. Config over code (CLAUDE.md).
stale_after_days: 10          # last_verified_at older than this → no spotlight
treat_unverified_as_stale: false   # ← see the warning below
verify_within_days: 7         # target re-check interval
dated_event_lead_days: 3      # dated events this close get priority
max_events_per_run: 40        # cost + runtime ceiling
unreachable_alert_streak: 3   # consecutive unreachable per PAGE → alert
escalation_model: null        # e.g. a non-Claude model id; null = unescalated
```

> **`treat_unverified_as_stale` must start `false`.** On day one every row has
> `last_verified_at IS NULL`. Flipping this to `true` before the first full sweep
> completes would empty the spotlight on the entire site. Flip it only once
> `SELECT count(*) FROM events WHERE status='active' AND last_verified_at IS NULL` is 0.

- [ ] **Step 2: The loop**

Order of operations per run — the cheap passes first, so the model budget is spent on what's left:

1. `expire_past_dated(conn, today)` — log the ids.
2. Load candidates via `events_needing_verification(conn, limit=max_events_per_run * 3)`, then `prioritise(...)`, then truncate to `max_events_per_run`.
3. Per event: skip if `is_hidden_series`; skip if `status` is in `locked_fields`.
4. Non-`website` `source_type` → record `indeterminate` with reasoning
   `"source_type=instagram: permalink not verifiable"`, **do not fetch**, and seed
   `last_verified_at` from `first_seen_at` if it is NULL. (Spec §8.)
5. Fetch via `PageCache` using the business's `use_playwright` flag for that page
   (look it up from `businesses.yaml` by matching `page["url"]`; fall back to `False`).
6. Fetch failed → `record_verification(..., verdict="unreachable")`, no state change,
   bump the per-page failure counter.
7. `hash_confirms` → `touch_verified(..., "confirmed")`, no model call, count it separately
   in the summary so the short-circuit's value is visible.
8. Else `verify_one` → `resolve_with_escalation` → `record_verification`; `touch_verified`
   only when the verdict is `confirmed`.
9. `weekday_mismatch` on recurring events → queue a `changed` proposal for
   `recurrence_pattern` with `model="deterministic"`.
10. Print a summary: checked / confirmed-by-hash / confirmed-by-model / queued / unreachable
    / skipped, plus any page hitting `unreachable_alert_streak`.

- [ ] **Step 3: CLI**

```
python3 scripts/run_verification.py
    --dry-run            fetch + call + print, no DB writes at all
    --limit N            override max_events_per_run
    --event-id N         verify exactly one event (ignores prioritisation)
    --business <slug>    restrict to one business
    --no-model           deterministic passes only (free; good for CI smoke)
```

Use `load_dotenv()` at the top — `scripts/extract_business_metadata.py` is the known outlier that omits it and fails on a fresh shell (drift log, 2026-05-04). Don't repeat that.

**Verification:**
- [ ] `--dry-run --limit 5` against the real DB: prints five decisions, and
      `SELECT count(*) FROM event_verifications` is still 0 afterward.
- [ ] `--no-model` on a DB copy: past-dated events expire, zero API calls (confirm with a
      network-off run or by asserting the Anthropic client is never constructed).
- [ ] `--event-id <a CML show>`: the run completes and records a verdict even though
      `start_time` is NULL — no crash on missing fields.
- [ ] Full `--limit 40` run on a DB copy: summary numbers add up to 40; re-running
      immediately shows a high confirmed-by-hash count (the short-circuit working).

---

## Task 7: Site-side freshness gate

**Files:** Modify `src/site_builder.py`, `templates/_event_card.html`, `templates/index.html`

**This is where the correction to the spec matters:** "happening now" is decided **client-side** by `isHappeningNow()` in `templates/index.html`. The gate is therefore a data attribute plus a one-line JS guard — not a filter in `build_site`.

> **Verified against the code 2026-08-22, and CLAUDE.md is wrong here.** CLAUDE.md's
> "Mobile LCP optimization (Shipped 2026-06-04)" entry says the fix was "pre-rendering
> spotlight cards on the server." It wasn't. What actually shipped is build-time selection
> of an **LCP image candidate** plus a `<link rel="preload" as="image" imagesrcset=...>`
> in the `<head>` (`site_builder.py` ~line 1872; `templates/index.html` lines 79–80).
> Spotlight promotion is still entirely client-side. Relatedly, CLAUDE.md's "Spotlight
> priority" section references an `#spotlight` element with `data-show-when-empty` — neither
> exists in `templates/index.html` any more. Flag both to Justin; fix CLAUDE.md in this PR.

- [ ] **Step 1: `_is_verify_stale` in `src/site_builder.py`**

Place beside `_is_ended_series` / `_series_inactive` (~line 991):

```python
def _is_verify_stale(ev: dict, now: datetime, cfg: dict) -> bool:
    """True ⇒ this event may still be listed, but may NOT enter the spotlight.

    Mirrors the existing rule that an event with no start_time is excluded from
    "happening now": listing an unverified event is low-risk (the visitor is
    browsing); spotlighting one is high-risk (they're deciding where to go now).
    """
    lv = ev.get("last_verified_at")
    if not lv:
        return bool(cfg.get("treat_unverified_as_stale", False))
    try:
        checked = datetime.fromisoformat(lv)
    except ValueError:
        return True
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=CHICAGO)
    return (now - checked).days > int(cfg.get("stale_after_days", 10))
```

- [ ] **Step 2: Set it in `build_site`**

In the `for row in rows:` loop (~line 1731), after the `performers` line:

```python
        ev["verify_stale"] = _is_verify_stale(ev, now_chicago, verify_cfg)
```

Load `verify_cfg` once near the `businesses.yaml` load, tolerating a missing file so the build never breaks on a fresh checkout:

```python
    verify_cfg = {}
    verify_path = CONFIG_DIR / "verification.yaml"
    if verify_path.exists():
        with open(verify_path) as f:
            verify_cfg = yaml.safe_load(f) or {}
```

- [ ] **Step 3: Emit the attribute — `templates/_event_card.html`**

In the `<article class="f ...">` attribute block, after `data-event-id`:

```jinja
         {% if e.verify_stale %}data-verify-stale="1"{% endif %}
```

- [ ] **Step 4: The guard — `templates/index.html`**

In `isHappeningNow(card, chicago)` (~line 493), make it the very first statement:

```js
  function isHappeningNow(card, chicago) {
    // Unverified/stale-verification events may be listed but never spotlighted.
    // Same philosophy as the !startTime bails below: show nothing rather than
    // a false positive.
    if (card.dataset.verifyStale === '1') return false;

    const days      = card.dataset.recurrenceDays;
```

- [ ] **Step 5: Keep the LCP preload honest**

`build_site` picks the LCP image candidate by walking `featured_events` → `today_events` →
… in priority order (~line 1872). A verify-stale event can win that walk and get its image
preloaded even though it can never be spotlighted — wasted bytes on the critical path, the
exact thing that optimization existed to fix. Add the same guard to each loop:

```python
        if ev.get("verify_stale"):
            continue
```

Only relevant once `treat_unverified_as_stale` is `true`; harmless before that.

> Do **not** also patch `isStartingSoon` in this task. "Starting soon" is a weaker claim than "happening now"; decide it separately once there's real data on how often the gate fires.

**Verification:**
- [ ] `python3 scripts/build_site.py` with `treat_unverified_as_stale: false` → **zero**
      `data-verify-stale` attributes in `public/index.html` (`grep -c` returns 0), and the
      rendered page is byte-comparable to the pre-change build except for that.
- [ ] Set `treat_unverified_as_stale: true`, rebuild → the attribute appears on cards, the
      page still renders every bucket, and the spotlight is empty. Revert the flag.
- [ ] Hand-set `last_verified_at` to now on one currently-live recurring event, rebuild with
      the flag on → that card has no attribute and can still spotlight.
- [ ] `_assert_build()` passes (it runs at the end of `build_site`).

---

## Task 8: Scheduled workflow

**Files:** Create `.github/workflows/verification.yml`

- [ ] **Step 1: Schedule it an hour *before* extraction**

The daily extraction + deploy runs at 11:00 UTC. Run verification at **10:00 UTC** and have it commit only `data/app.db`. The 11:00 run then builds and deploys the verified state — so this workflow needs **no build, no rsync, no Cloudflare purge**, and there is no second deploy path to keep in sync.

- [ ] **Step 2: Structure**

Model it on `.github/workflows/scheduled.yml`, keeping:
- `git pull --rebase origin main` before pushing the DB (the race fix from 2026-04-18).
- `if: failure()` on any artifact upload (the quota fix from 2026-04-30 — do not reintroduce a steady-state upload).
- `ANTHROPIC_API_KEY` from secrets.

Add `workflow_dispatch` so it can be triggered by hand, and a `--limit` input defaulting to the config value.

- [ ] **Step 3: Guard the window**

Set `timeout-minutes: 45`. If verification is still running at 11:00 the extraction workflow will pull a DB mid-write; the cap plus `max_events_per_run: 40` keeps a normal run to a few minutes.

**Verification:**
- [ ] `gh workflow run "Freshness verification"` → run succeeds.
- [ ] The run commits `data/app.db` with a non-zero diff on `last_verified_at`.
- [ ] A forced failure (bad API key in a test branch) does **not** leave the DB half-written —
      writes are inside the `connect()` context manager, so confirm the commit step is skipped.
- [ ] The next scheduled 11:00 extraction run succeeds afterward (no rebase conflict).

---

## Self-Review

Run through these before opening the PR:

- [ ] **No path writes to `events` content.** `grep -n "UPDATE events" src/verifier.py` should
      show exactly two: `expire_past_dated` (status only, lock-respecting) and `touch_verified`
      (metadata only). Anything else is a bug against the spec's core promise.
- [ ] **`absent` cannot come from a failed fetch.** Trace every path that records `absent` and
      confirm each requires a successful fetch with `>= MIN_BODY_CHARS` of text.
- [ ] **Locked fields honoured everywhere**, matching `mark_missing_events_stale`.
- [ ] **Prose fields never compared** — `description`/`notes` appear nowhere in
      `DECISION_CRITICAL_FIELDS` or the prompt's change list.
- [ ] **`treat_unverified_as_stale` is still `false`** in the committed config.
- [ ] **No new pip dependencies** unless `escalation_model` required one — if so, it is in
      `requirements.txt` and called out in the PR description.
- [ ] **Print-logging, not `logging`**; procedural style; `python3` in all docs.
- [ ] **Docs updated:** `docs/shipped.md` entry, `docs/drift-log.md` entry noting the two new
      columns + `event_verifications` table (schema migrations belong in the drift log), and
      CLAUDE.md's schema-migrations line extended.
- [ ] **Fix the two CLAUDE.md inaccuracies found while writing this plan** (Task 7 note):
      the 2026-06-04 LCP entry describes server-prerendered spotlight cards that don't exist,
      and the "Spotlight priority" section references `#spotlight` / `data-show-when-empty`
      which are gone from the template. Correct both; the code is authoritative.
- [ ] **Workflow note in `handoffs.md`:** pipeline code changed → run **Scheduled extraction +
      deploy**, not Site rebuild. And `git push` before triggering.

### Deliberately deferred

- `scripts/admin.py` review-queue UI (Phase 2). Until then: `SELECT * FROM event_verifications WHERE resolution IS NULL`.
- Auto-apply of any verdict. Phase 1 queues everything; revisit once there's a track record worth reading.
- `isStartingSoon` gating.
- A verification path for Instagram rows — genuinely blocked (spec §8), and the right input to the Instagram-cadence decision rather than something to solve here.
