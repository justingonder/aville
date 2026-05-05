#!/usr/bin/env python3
"""Extract entity metadata (description, phone, price_range, same_as)
for each business in config/businesses.yaml using Claude.

Writes results into a top-level `metadata:` block inside each business
entry. Idempotent: skips businesses that already have a metadata block
unless --force is passed.

Usage:
    python3 scripts/extract_business_metadata.py               # all missing
    python3 scripts/extract_business_metadata.py vincent       # one by slug
    python3 scripts/extract_business_metadata.py --force       # refresh all
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
from src.prompts import BUSINESS_METADATA_PROMPT, build_business_metadata_prompt

YAML_PATH = ROOT / "config" / "businesses.yaml"
MODEL = os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")
MAX_PAGE_CHARS = 20000  # truncate long pages before sending to Claude


def _extract_json_object(text: str) -> dict:
    """Parse a JSON object out of Claude's response, tolerating code fences."""
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
    """Strip script/style and collapse whitespace. Good enough for metadata extraction."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_PAGE_CHARS]


def extract_one(business: dict, client: Anthropic) -> dict:
    """Fetch the business homepage and call Claude. Returns the metadata dict."""
    website = business.get("website") or ""
    if not website:
        raise ValueError(f"{business['slug']}: no website URL")

    # Respect per-business Playwright hint (look at pages list for `use_playwright`).
    needs_playwright = any(
        p.get("use_playwright") for p in (business.get("pages") or [])
    )
    print(f"  fetching {website} ({'playwright' if needs_playwright else 'httpx'})...")
    html, _, _ = fetch_html_playwright(website) if needs_playwright else fetch_html(website)

    user_prompt = build_business_metadata_prompt(
        business_name=business["name"],
        business_category=business.get("category") or "",
        website=website,
        page_text=_page_text(html),
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=BUSINESS_METADATA_PROMPT,
        temperature=0.0,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return _extract_json_object(text)


def _metadata_yaml_block(md: dict, indent: str = "      ") -> str:
    """Render a metadata dict as an indented YAML block (no outer key)."""
    lines = []
    for key, val in md.items():
        if val is None:
            lines.append(f"{indent}{key}: null")
        elif isinstance(val, list):
            if not val:
                lines.append(f"{indent}{key}: []")
            else:
                lines.append(f"{indent}{key}:")
                for item in val:
                    escaped = str(item).replace("'", "''")
                    lines.append(f"{indent}  - '{escaped}'")
        else:
            escaped = str(val).replace("'", "''")
            lines.append(f"{indent}{key}: '{escaped}'")
    return "\n".join(lines)


def _insert_metadata_in_yaml(raw: str, slug: str, md: dict) -> str:
    """Insert (or replace) a metadata: block for a given slug in raw YAML text.

    Finds the line '  - slug: <slug>' and either:
      - Inserts a new metadata block after the last top-level key of that entry
        (detected as the line just before the next '  - slug:' or end of file).
      - Replaces an existing metadata: ... block in place.

    Returns the modified raw text.
    """
    lines = raw.splitlines(keepends=True)

    # Find the line index where this slug's entry starts.
    slug_line_idx = None
    for i, line in enumerate(lines):
        if re.match(rf"^  - slug:\s*{re.escape(slug)}\s*$", line):
            slug_line_idx = i
            break
    if slug_line_idx is None:
        raise ValueError(f"slug '{slug}' not found in YAML")

    # Find the start of the NEXT entry (next '  - slug:' at the same indent level)
    # or end of file. This bounds the current entry.
    next_entry_idx = len(lines)
    for i in range(slug_line_idx + 1, len(lines)):
        if re.match(r"^  - slug:\s*\S", lines[i]):
            next_entry_idx = i
            break

    entry_lines = lines[slug_line_idx:next_entry_idx]

    # Check if metadata block already exists within this entry.
    meta_start = None
    meta_end = None
    for j, line in enumerate(entry_lines):
        if re.match(r"^    metadata:\s*$", line):
            meta_start = j
            # Find end: next top-level key at indent 4 (i.e. "    word:") or end.
            for k in range(j + 1, len(entry_lines)):
                if re.match(r"^    \w", entry_lines[k]) and not re.match(r"^      ", entry_lines[k]):
                    meta_end = k
                    break
            if meta_end is None:
                meta_end = len(entry_lines)
            break

    md_block = "    metadata:\n" + _metadata_yaml_block(md, indent="      ") + "\n"

    if meta_start is not None:
        # Replace existing block.
        entry_lines[meta_start:meta_end] = [md_block]
    else:
        # Append before the next entry (i.e. at the end of the current entry).
        entry_lines.append(md_block)

    lines[slug_line_idx:next_entry_idx] = entry_lines
    return "".join(lines)


def main(argv: list[str]) -> int:
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    target_slug = argv[0] if argv else None

    raw_yaml = YAML_PATH.read_text()
    doc = yaml.safe_load(raw_yaml)
    businesses = doc["businesses"]

    client = Anthropic()  # uses ANTHROPIC_API_KEY

    updated: list[tuple[str, dict]] = []  # (slug, metadata) pairs written

    for biz in businesses:
        slug = biz["slug"]
        if target_slug and slug != target_slug:
            continue
        if "metadata" in biz and not force:
            print(f"skip {slug} (already has metadata; --force to refresh)")
            continue
        print(f"-> {slug}: {biz['name']}")
        try:
            md = extract_one(biz, client)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue
        updated.append((slug, md))
        print(f"  got: {json.dumps(md, indent=2)[:200]}")

    if not updated:
        print("\nnothing to write.")
        return 0

    # Apply all updates to raw YAML text (comment-preserving).
    for slug, md in updated:
        raw_yaml = _insert_metadata_in_yaml(raw_yaml, slug, md)

    YAML_PATH.write_text(raw_yaml)
    print(f"\nwrote {YAML_PATH} ({len(updated)} business(es) updated)")

    # Sanity-check: the updated file must still parse.
    yaml.safe_load(YAML_PATH.read_text())
    print("YAML parse check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
