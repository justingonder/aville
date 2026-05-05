"""Extraction prompt.

Design notes:
- We tell Claude today's date explicitly so it can resolve ambiguous dates.
- We hand it the full flat tag list (from config/tags.yaml) and require it to
  pick FROM that list only — this keeps the taxonomy controlled and the
  faceting UI clean. Claude can suggest new tags via a separate field.
- We require JSON-only output. The caller parses; no free-form text.
- source_image_index lets us associate each event back to a specific image
  so we can display the right flyer next to the event on the site.
"""
from __future__ import annotations

from datetime import date
from textwrap import dedent

SYSTEM_PROMPT = dedent("""
    You are extracting structured event, special, and happy-hour information
    from a small business website in Andersonville, a neighborhood in Chicago.

    You will receive:
      1. Business metadata (name, category, page kind, extraction hints).
      2. Today's date, for resolving ambiguous dates (e.g. "April 18" with no year).
      3. The page's visible text content.
      4. A numbered list of content images from the page. Each image has:
         - section_header: the nearest heading above the image on the page,
           e.g. "WEEKLY EVENTS", "MONTHLY EVENTS", "SPECIAL EVENTS". Use this
           to decide the recurrence shape (weekly vs monthly vs one-off).
         - caption: the text that immediately follows the image on the page.
           THIS CAPTION BELONGS ONLY TO THIS IMAGE. Do not mix captions
           across images. If the caption says "EVERY TUESDAY • 7:30-10PM",
           that is the day and time for THIS image's event, not anyone
           else's.
         Event flyers often contain the event NAME and DETAILS entirely
         inside the image — read text from the images carefully.

    Your job is to return a JSON array of event objects. No preamble, no
    commentary, no markdown fences — just a JSON array.

    EVENT SCHEMA
    Each event is an object with these fields:
      - title: string. The event / special / happy hour name. For image-based
        flyers, extract the title exactly as shown in the image. For happy hour
        menus, use a title like "Happy Hour".
      - kind: "recurring" or "dated".
      - description: 1-2 factual sentences. Do not invent details.
      - recurrence_pattern: (recurring only) one of:
          "weekly:<dayname>"           e.g. "weekly:tuesday"
          "weekly:<day>-<day>"         e.g. "weekly:tuesday-friday"
          "weekly:<day>,<day>"         e.g. "weekly:friday,saturday"
          "monthly:1st-<dayname>"      e.g. "monthly:1st-saturday"
          "monthly:2nd-<dayname>", "monthly:3rd-<dayname>", "monthly:4th-<dayname>"
          "monthly:last-<dayname>"     e.g. "monthly:last-friday"  (use when source says "last <day> of the month")
          "daily"
        Use lowercase English day names.
      - start_time, end_time: (recurring only) "HH:MM" 24-hour format. Null if not given.
      - start_datetime, end_datetime: (dated only) ISO8601 in Central Time
        ("YYYY-MM-DDTHH:MM:00-05:00" or "-06:00" depending on DST). If the
        source omits the year, pick the NEAREST FUTURE occurrence relative
        to today's date. If the time is unknown, use T00:00:00. If the end
        time is missing, leave end_datetime null. For multi-day events where
        you know the end date but not the end time, use T00:00:00 for the
        end datetime — never use T23:59:00.
      - price_info: short string like "$5 cover", "$3 domestics", "Free",
        or null if not mentioned.
      - source_image_index: 1-based index of the image this event came from,
        or null if the event came from text only. If multiple images relate to
        one event, pick the most representative.
      - performers: array of objects for named people credited on the flyer
        or in the page text (hosts, DJs, headliners, drag performers, etc.).
        Each object: {"name": "<stage or full name>", "role": "<role>"}.
        Role must be one of: host, dj, headliner, featured, performer, drag.
        Use "host" for "Hosted by", "dj" for DJ credits, "headliner" for
        top-billed acts, "featured" for "Featuring", "drag" for drag
        performers not otherwise labeled, "performer" as a catch-all.
        Empty array if no named individuals are credited.
      - tags: array of tag strings, chosen ONLY from the provided controlled
        vocabulary. Pick every tag that clearly applies. Prefer under-tagging
        to wrong-tagging.
      - suggested_new_tags: array of tag strings you think SHOULD exist but
        don't. Empty array is fine. Do not put these in `tags`.
      - confidence: number between 0 and 1. How sure are you the record is
        correct and really is an event? Use < 0.6 when you're guessing.
      - notes: short free-text string explaining edge cases or uncertainty,
        or null.

    RULES
    - Use the section_header for each image to determine the event's
      `kind` and recurrence shape:
        * "WEEKLY EVENTS"  -> kind=recurring, recurrence_pattern=weekly:*
        * "MONTHLY EVENTS" -> kind=recurring, recurrence_pattern=monthly:*
        * "SPECIAL EVENTS" -> kind=dated
      If section_header disagrees with the caption, TRUST the section_header.
    - The caption tells you the SPECIFIC day and time for this one image.
      Do not reuse a caption from another image.
    - If the page kind is "menu", extract ONLY happy hour, daily specials, or
      limited-time specials. Do NOT extract entire dinner or dessert menus as
      events.
    - Do not extract operating hours, contact info, decorative images,
      reservation links, or generic "visit us" content.
    - If an image is clearly not an event flyer (food photos, interior shots,
      logos that survived the filter, staff portraits), skip it.
    - Never invent a date, price, or detail not visible in the source.
    - Return ONLY the JSON array. If there are zero events, return [].
""").strip()


def build_user_prompt(
    *,
    business_name: str,
    business_category: str,
    business_subcategory: str,
    page_url: str,
    page_kind: str,
    hints: str,
    tag_vocab: list[str],
    page_text: str,
    images_summary: str,
) -> str:
    today = date.today().isoformat()
    tag_list = ", ".join(tag_vocab)
    return dedent(f"""
        TODAY: {today}
        BUSINESS: {business_name} ({business_category} / {business_subcategory})
        PAGE URL: {page_url}
        PAGE KIND: {page_kind}
        HINTS: {hints}

        CONTROLLED TAG VOCABULARY (pick from this list only):
        {tag_list}

        ---
        PAGE TEXT CONTENT (truncated):
        {page_text}

        ---
        IMAGES ON PAGE:
        {images_summary}

        ---
        Return the JSON array of events now.
    """).strip()


BUSINESS_METADATA_PROMPT = dedent("""
    You are extracting canonical entity metadata about a single small
    business in Andersonville, Chicago, from its homepage HTML.

    Return ONE JSON object with exactly these fields:
      - description: string. 2 or 3 neutral, factual sentences describing
        what the venue is and what it's known for. No marketing fluff,
        no superlatives, no second-person ("you'll love..."). Prefer
        concrete specifics over vague adjectives. Max ~350 characters.
      - telephone: string in E.164 format if possible
        (e.g. "+1-773-334-7402"), otherwise as written on the page,
        or null if no phone number is visible.
      - price_range: one of "$", "$$", "$$$", "$$$$", or null.
        Infer from menu prices if visible, or from the venue type.
        Use null when genuinely unclear.
      - same_as: array of absolute URLs to the venue's own profiles on
        Instagram, Facebook, X/Twitter, Threads, TikTok, YouTube,
        LinkedIn. Include only profiles that obviously belong to THIS
        venue. Empty array if none visible.

    Return ONLY the JSON object. No preamble, no code fences, no commentary.
""").strip()


def build_business_metadata_prompt(
    *,
    business_name: str,
    business_category: str,
    website: str,
    page_text: str,
) -> str:
    return dedent(f"""
        BUSINESS: {business_name} ({business_category})
        WEBSITE: {website}

        ---
        HOMEPAGE TEXT (truncated):
        {page_text}

        ---
        Return the JSON object now.
    """).strip()


EDITORIAL_COPY_PROMPT = dedent("""
    You are writing brief editorial copy for a small business in Andersonville,
    Chicago, for a neighborhood events bulletin (aville.net).

    Audience: Andersonville and Chicago residents who already know the
    neighborhood. Conventions:
    - Casual-but-not-slangy tone. Warm, plain-spoken, specific.
    - Third-person voice. NO second-person ("you'll love...", "you can find...").
    - No marketing fluff and no superlatives. Avoid "iconic", "beloved",
      "must-visit", "vibrant", "amazing", "hidden gem", "cozy", "vibe".
      Earn descriptive language with concrete specifics from the source.
    - Don't fabricate. If the homepage doesn't mention an award, a chef's
      name, a specific decor detail, a menu item, a year founded, etc.,
      do NOT invent it. Stick to what the source supports.

    Return ONE JSON object with exactly these fields:

      - tagline: string. ONE sentence, ~80-130 characters, that captures
        what the venue IS in plain terms. This renders directly under the
        venue's name as the editorial lede. Examples of the right register:
          "A neighborhood French bistro doing seasonal small plates and
           a daily 4-6pm happy hour."
          "Andersonville's longtime Belgian beer bar — 380 bottles
           and a tight tap list."
        Avoid starting with "Located in...". Avoid superlatives.

      - vibe_quote: string. A short, memorable line (~6-14 words) that
        could be lifted as a pull quote. Should feel quotable, not
        promotional. Atmospheric/observational is fine — but it must
        feel true to the venue based on the page. Examples:
          "Quiet enough to read, loud enough to dance."
          "Stop in for one and stay for three."
          "Sundays are for brunch and bottomless mimosas."

      - about: string. Exactly TWO paragraphs separated by a single '\\n\\n'.
        - Paragraph 1: what the venue is and what it's known for. 3-4
          sentences. Concrete specifics from the page (cuisine, beer
          program, type of programming, neighborhood context).
        - Paragraph 2: what the experience is like — atmosphere, hours
          if notable, who fits in there, what kind of programming you'd
          find there. 3-4 sentences. Don't repeat paragraph 1.
        Keep both paragraphs informative; this is reference text, not
        a marketing pitch.

    Return ONLY the JSON object. No preamble, no code fences, no commentary.
""").strip()


def build_editorial_copy_prompt(
    *,
    business_name: str,
    business_category: str,
    website: str,
    existing_description: str | None,
    page_text: str,
) -> str:
    extra = ""
    if existing_description:
        extra = f"\n\nEXISTING NEUTRAL DESCRIPTION (already extracted, factual; use as grounding):\n{existing_description}"
    return dedent(f"""
        BUSINESS: {business_name} ({business_category})
        WEBSITE: {website}{extra}

        ---
        HOMEPAGE TEXT (truncated):
        {page_text}

        ---
        Return the JSON object now.
    """).strip()


SEED_EXTRACTION_PROMPT = dedent("""
    You are looking at a phone-camera photo of a paper flyer or window sign
    in Andersonville, a Chicago neighborhood. The photo is NOT clean — it
    likely contains window reflections, surrounding storefront branding,
    nail-salon decals, decorative shadows, perspective skew, and other noise.

    The FLYER is the authoritative signal. Ignore everything else in the
    photo. Extract a small set of seeds we can use to web-search for an
    authoritative source for this event.

    Return ONE JSON object with exactly these fields:
      - event_title: string. The event name as it appears on the flyer.
        Null if you can't read it.
      - venue_name: string. The venue / business hosting the event, as it
        appears on the flyer (NOT the surrounding storefront, which may be
        a different business). Null if the flyer doesn't name a venue.
      - date_hint: string. The date as it appears on the flyer
        (e.g., "May 2", "Mother's Day", "Every Tuesday"). Null if absent.
      - time_hint: string. The time as it appears (e.g., "12pm-6pm").
        Null if absent.
      - kind_guess: "dated" or "recurring" or null. "Dated" for a one-off
        event with a specific date; "recurring" for "every Tuesday" /
        "monthly" / etc.
      - distinctive_strings: array of 1-4 short, distinctive strings from
        the flyer text that would make good fallback search queries
        (e.g., a tagline, sponsor name, sub-event name). Empty array if
        nothing stands out.
      - flyer_image_is_clean: boolean. True if the photo is dominated by
        the flyer (could plausibly be cropped and used as an image).
        False if the photo has substantial non-flyer content (storefront
        glass, decals, reflections, etc.). When in doubt, false.
      - seed_confidence: "high" | "medium" | "low". Your confidence that
        the seeds are correct enough to drive a useful web search.

    Return ONLY the JSON object. No preamble, no markdown fences, no
    commentary.
""").strip()


CROSS_VERIFY_NOTE = dedent("""
    Additionally, you have been given a phone-camera photo of a paper
    flyer for this event (labeled '--- CROSS-VERIFY FLYER ---' below).
    The flyer is a CORROBORATING SIGNAL only — the web source above is
    authoritative. Use the flyer to cross-check ambiguous fields (date,
    time, performers, price). When the web source and the flyer
    disagree, prefer the web source. Do NOT pick the flyer photo as
    `source_image_index`; it is not in the indexed images list.
""").strip()
