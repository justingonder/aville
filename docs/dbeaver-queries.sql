-- ===========================================================================
-- Manual review queries for data/app.db
-- ===========================================================================
-- Drop this file into DBeaver as a Script (right-click connection > SQL Editor
-- > Open SQL Script) and bookmark it. Each block below is independent — run
-- them one at a time with Ctrl/Cmd+Enter on the highlighted block.
--
-- Editing rule of thumb: after manual UPDATEs, commit data/app.db and push to
-- origin, otherwise the next extraction run will pull origin's older DB and
-- overwrite your edits.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1. Chicago Magic Lounge — needs start_time set after every extraction
-- ---------------------------------------------------------------------------
-- Their site doesn't expose times (handled by ThunderTix, blocks plain HTTP).
-- Without start_time, the spotlight excludes the event. After each extraction:
-- check chicagomagiclounge.com and set start_time here.
SELECT e.id, e.title, e.recurrence_pattern, e.start_time, e.last_extracted_at
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE b.slug = 'chicago-magic-lounge'
  AND e.status = 'active'
ORDER BY e.recurrence_pattern, e.title;

-- Update template (replace HH:MM and id):
-- UPDATE events SET start_time = '19:30' WHERE id = 111;


-- ---------------------------------------------------------------------------
-- 2. Recurring events missing start_time (broader)
-- ---------------------------------------------------------------------------
-- These are excluded from "happening now" spotlight logic. Magic Lounge shows
-- will dominate the list; other businesses showing up here are usually
-- all-day specials (e.g. "Tuesday Seasonal Frozen Cocktail Special") where
-- start_time could reasonably default to the business's opening time.
SELECT e.id, b.name AS business, e.title, e.recurrence_pattern, e.tags
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.status = 'active'
  AND e.kind = 'recurring'
  AND (e.start_time IS NULL OR e.start_time = '')
ORDER BY b.name, e.title;


-- ---------------------------------------------------------------------------
-- 3. Recurring events missing end_time
-- ---------------------------------------------------------------------------
-- pipeline.py's _apply_hours_cap() infers end_time from the business's
-- closing hours when null. So a null here is fine IF the business has a
-- hours: block in config/businesses.yaml. If not, the event has no upper
-- bound for "happening now" — flag for manual fix.
SELECT e.id, b.name AS business, e.title, e.recurrence_pattern,
       e.start_time, e.end_time
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.status = 'active'
  AND e.kind = 'recurring'
  AND e.start_time IS NOT NULL
  AND (e.end_time IS NULL OR e.end_time = '')
ORDER BY b.name, e.title;


-- ---------------------------------------------------------------------------
-- 4. Active events missing price_info
-- ---------------------------------------------------------------------------
-- price_info feeds the Schema.org offers block; missing values cost a
-- structured-data signal but don't break anything. Worth filling in if you
-- happen to know the price (e.g. "Free", "$10").
SELECT e.id, b.name AS business, e.title, e.kind,
       COALESCE(e.recurrence_pattern, e.start_datetime) AS when_,
       e.price_info
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.status = 'active'
  AND (e.price_info IS NULL OR e.price_info = '')
ORDER BY b.name, e.title;


-- ---------------------------------------------------------------------------
-- 5. Series-end-date candidates (mirrors scripts/list_series_candidates.py)
-- ---------------------------------------------------------------------------
-- Recurring events tied to a broadcast calendar (TV viewing parties, sports
-- watch parties, RPDR, Survivor) without an ends_on date set. Look up the
-- real season-end date and UPDATE.
-- Trivia is excluded (themed trivia is evergreen, not season-based).
SELECT e.id, b.name AS business, e.title, e.recurrence_pattern,
       e.tags, e.ends_on
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.status = 'active'
  AND e.kind = 'recurring'
  AND e.ends_on IS NULL
  AND e.tags NOT LIKE '%"trivia"%'
  AND (
        e.tags LIKE '%"tv-viewing-party"%'
     OR LOWER(e.title) LIKE '%viewing party%'
     OR LOWER(e.title) LIKE '%watch party%'
     OR LOWER(e.title) LIKE '%rpdr%'
     OR LOWER(e.title) LIKE '%rupaul%'
     OR LOWER(e.title) LIKE '%survivor%'
  )
ORDER BY b.name, e.title;

-- Update template:
-- UPDATE events SET ends_on = '2026-05-30' WHERE id = NN;


-- ---------------------------------------------------------------------------
-- 6. Events with ends_on already set — verify they're still in the future
-- ---------------------------------------------------------------------------
-- ends_on < today's date hides the event from the homepage display buckets
-- (per-event detail pages still render). Use this to audit / extend dates
-- when a series gets renewed for another season.
SELECT e.id, b.name AS business, e.title, e.recurrence_pattern,
       e.ends_on,
       CASE WHEN e.ends_on < DATE('now', 'localtime')
            THEN 'PAST (hidden)'
            ELSE 'upcoming'
       END AS status_now
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.ends_on IS NOT NULL
ORDER BY e.ends_on;


-- ---------------------------------------------------------------------------
-- 7. Currently featured events
-- ---------------------------------------------------------------------------
-- featured = 1 elevates the event to the spotlight section above all other
-- spotlight logic. Use sparingly — designed for mega-events (Midsommarfest).
SELECT e.id, b.name AS business, e.title, e.kind,
       COALESCE(e.recurrence_pattern, e.start_datetime) AS when_,
       e.status
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.featured = 1
ORDER BY b.name, e.title;

-- To feature: UPDATE events SET featured = 1 WHERE id = NN;
-- To unfeature: UPDATE events SET featured = 0 WHERE id = NN;


-- ---------------------------------------------------------------------------
-- 8. Stale events — sitting around with status='stale'
-- ---------------------------------------------------------------------------
-- Events that disappeared from the source page get marked 'stale' rather
-- than deleted. There's no auto-expiry rule yet (open question in CLAUDE.md:
-- "stale for 14 days -> expired"). This query surfaces stale-for-long
-- candidates so you can manually move them to status='expired' if confident.
SELECT e.id, b.name AS business, e.title,
       e.last_seen_at,
       JULIANDAY('now') - JULIANDAY(e.last_seen_at) AS days_stale
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.status = 'stale'
ORDER BY e.last_seen_at;


-- ---------------------------------------------------------------------------
-- 9. All active events for a single business
-- ---------------------------------------------------------------------------
-- Quick sanity check after extraction. Replace the slug below.
SELECT e.id, e.kind, e.title, e.recurrence_pattern,
       e.start_datetime, e.start_time, e.end_time, e.price_info, e.featured
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE b.slug = 'replay-andersonville'
  AND e.status = 'active'
ORDER BY e.kind, e.recurrence_pattern, e.start_datetime;


-- ---------------------------------------------------------------------------
-- 10. Recently extracted events — post-run sanity check
-- ---------------------------------------------------------------------------
-- Run after a `python3 scripts/run_extraction.py` to see what changed.
SELECT e.id, b.name AS business, e.title, e.kind, e.status,
       e.confidence, e.last_extracted_at
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.last_extracted_at >= DATETIME('now', '-1 day')
ORDER BY e.last_extracted_at DESC, b.name;


-- ---------------------------------------------------------------------------
-- 11. Low-confidence events — Claude flagged uncertainty
-- ---------------------------------------------------------------------------
-- confidence is Claude's self-reported 0..1 score. Review anything below
-- 0.7 — the structured fields may be wrong or speculative.
SELECT e.id, b.name AS business, e.title, e.kind, e.confidence,
       e.recurrence_pattern, e.start_datetime
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.status = 'active'
  AND e.confidence IS NOT NULL
  AND e.confidence < 0.7
ORDER BY e.confidence, b.name;


-- ---------------------------------------------------------------------------
-- 12. Day-of-week sanity — recurring events vs. their start_datetime
-- ---------------------------------------------------------------------------
-- CLAUDE.md notes Claude sometimes miscalculates day-of-week (BEARAOKE was
-- once stored as Saturday but is actually Sunday). For weekly:* recurring
-- events with a first-seen date, this surfaces day-name mismatches between
-- recurrence_pattern and the actual weekday of first_seen_at.
-- (Imperfect — first_seen_at is the extraction date, not the event date.
-- Treat as a starting point, not gospel.)
SELECT e.id, b.name AS business, e.title, e.recurrence_pattern,
       CASE CAST(STRFTIME('%w', e.first_seen_at) AS INTEGER)
            WHEN 0 THEN 'sunday'    WHEN 1 THEN 'monday'
            WHEN 2 THEN 'tuesday'   WHEN 3 THEN 'wednesday'
            WHEN 4 THEN 'thursday'  WHEN 5 THEN 'friday'
            WHEN 6 THEN 'saturday'
       END AS first_seen_weekday
FROM events e
JOIN businesses b ON e.business_id = b.id
WHERE e.status = 'active'
  AND e.recurrence_pattern LIKE 'weekly:%'
  AND e.recurrence_pattern NOT LIKE '%-%'   -- skip ranges like weekly:tue-thu
  AND e.recurrence_pattern NOT LIKE '%,%'   -- skip lists like weekly:mon,wed
ORDER BY b.name, e.title;
