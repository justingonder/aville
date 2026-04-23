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
