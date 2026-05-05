#!/usr/bin/env python3
"""Draft editorial copy (tagline, vibe_quote, about) for each business via Haiku.

Fetches each business's homepage (Playwright when configured) and asks Claude
Haiku for a JSON object with three fields:
  - tagline: one-sentence editorial lede (~80-130 chars).
  - vibe_quote: short pull quote (~6-14 words).
  - about: two paragraphs, separated by '\\n\\n'.

Writes the three fields as flat top-level keys on each business entry in
config/businesses.yaml, using a comment-preserving raw-text editor so
field ordering and the file's header comments survive.

Idempotent: skips businesses that already have all three fields set unless
--force. Optional positional slug arg targets one business.

Usage:
    python3 scripts/backfill_editorial_copy.py                # all missing
    python3 scripts/backfill_editorial_copy.py vincent        # one by slug
    python3 scripts/backfill_editorial_copy.py --dry-run      # preview only
    python3 scripts/backfill_editorial_copy.py --force        # refresh all
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from src.fetcher import fetch_html, fetch_html_playwright
from src.prompts import EDITORIAL_COPY_PROMPT, build_editorial_copy_prompt

YAML_PATH = ROOT / "config" / "businesses.yaml"
MODEL = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")
MAX_PAGE_CHARS = 20000
EDITORIAL_KEYS = ("tagline", "vibe_quote", "about")


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start != -1:
        depth = 0
        in_str = False
        escape_next = False
        for i, ch in enumerate(text[start:], start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_str:
                escape_next = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    text = text[start:i + 1]
                    break
    return json.loads(text)


def _page_text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_PAGE_CHARS]


def extract_one(business: dict, client: Anthropic) -> dict:
    website = business.get("website") or ""
    if not website:
        raise ValueError(f"{business['slug']}: no website URL")

    needs_playwright = any(p.get("use_playwright") for p in (business.get("pages") or []))
    print(f"  fetching {website} ({'playwright' if needs_playwright else 'httpx'})...")
    html, _, _ = fetch_html_playwright(website) if needs_playwright else fetch_html(website)

    existing = (business.get("metadata") or {}).get("description")
    user_prompt = build_editorial_copy_prompt(
        business_name=business["name"],
        business_category=business.get("category") or "",
        website=website,
        existing_description=existing,
        page_text=_page_text(html),
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=EDITORIAL_COPY_PROMPT,
        temperature=0.0,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    obj = _extract_json_object(text)
    for key in EDITORIAL_KEYS:
        if key not in obj or not isinstance(obj[key], str) or not obj[key].strip():
            raise ValueError(f"{business['slug']}: model omitted '{key}' field; got: {obj!r}")
    return obj


def _render_yaml_block(data: dict, indent: str = "    ") -> str:
    """Render the three editorial keys with appropriate YAML formatting.

    tagline + vibe_quote -> single-quoted single-line strings.
    about -> literal block ('|') so paragraph breaks survive.
    """
    lines = []
    for key in ("tagline", "vibe_quote"):
        if key in data:
            escaped = str(data[key]).replace("'", "''")
            lines.append(f"{indent}{key}: '{escaped}'")
    if "about" in data:
        about = str(data["about"]).rstrip()
        about_lines = about.split("\n")
        lines.append(f"{indent}about: |")
        for ln in about_lines:
            lines.append(f"{indent}  {ln}" if ln else "")
    return "\n".join(lines)


def _entry_bounds(lines: list[str], slug: str) -> tuple[int, int]:
    slug_idx = None
    for i, line in enumerate(lines):
        if re.match(rf"^  - slug:\s*{re.escape(slug)}\s*$", line):
            slug_idx = i
            break
    if slug_idx is None:
        raise ValueError(f"slug '{slug}' not found in YAML")
    next_idx = len(lines)
    for i in range(slug_idx + 1, len(lines)):
        if re.match(r"^  - slug:\s*\S", lines[i]):
            next_idx = i
            break
    return slug_idx, next_idx


def _strip_existing_keys(entry_lines: list[str], keys: tuple[str, ...]) -> list[str]:
    """Remove any existing top-level entries (at indent 4) for the given keys.
    Handles both inline-scalar and block-scalar (|, >) forms by skipping
    deeper-indented continuation lines that follow a block-scalar header."""
    out = []
    skip = False
    for line in entry_lines:
        if skip:
            if line.strip() == "":
                continue
            if re.match(r"^      ", line):
                continue
            skip = False
        if any(re.match(rf"^    {re.escape(k)}\s*:", line) for k in keys):
            skip = True
            continue
        out.append(line)
    return out


def _insert_editorial_in_yaml(raw: str, slug: str, data: dict) -> str:
    lines = raw.splitlines(keepends=True)
    slug_idx, next_idx = _entry_bounds(lines, slug)
    entry_lines = lines[slug_idx:next_idx]
    entry_lines = _strip_existing_keys(entry_lines, EDITORIAL_KEYS)
    block = _render_yaml_block(data, indent="    ") + "\n"
    if entry_lines and not entry_lines[-1].endswith("\n"):
        entry_lines[-1] = entry_lines[-1] + "\n"
    entry_lines.append(block)
    lines[slug_idx:next_idx] = entry_lines
    return "".join(lines)


def main(argv: list[str]) -> int:
    force = "--force" in argv
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a not in ("--force", "--dry-run")]
    target_slug = argv[0] if argv else None

    raw_yaml = YAML_PATH.read_text()
    doc = yaml.safe_load(raw_yaml)
    businesses = doc["businesses"]

    client = Anthropic()
    updated: list[tuple[str, dict]] = []

    for biz in businesses:
        slug = biz["slug"]
        if target_slug and slug != target_slug:
            continue
        already = all(biz.get(k) for k in EDITORIAL_KEYS)
        if already and not force:
            print(f"skip {slug} (already has all 3 editorial fields; --force to refresh)")
            continue
        print(f"-> {slug}: {biz['name']}")
        try:
            data = extract_one(biz, client)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue
        updated.append((slug, data))
        preview = data["tagline"][:90]
        print(f"  tagline: {preview!r}")
        print(f"  vibe_quote: {data['vibe_quote']!r}")

    if not updated:
        print("\nnothing to write.")
        return 0

    if dry_run:
        print(f"\ndry-run: {len(updated)} update(s) NOT written")
        for slug, data in updated:
            print(f"\n--- {slug} ---")
            print(json.dumps(data, indent=2))
        return 0

    for slug, data in updated:
        raw_yaml = _insert_editorial_in_yaml(raw_yaml, slug, data)

    YAML_PATH.write_text(raw_yaml)
    print(f"\nwrote {YAML_PATH} ({len(updated)} business(es) updated)")

    yaml.safe_load(YAML_PATH.read_text())
    print("YAML parse check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
