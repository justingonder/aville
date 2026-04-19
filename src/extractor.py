"""Claude extraction call.

We send one multimodal request per page:
  - system prompt defines the schema and rules
  - user turn has the page text + an ordered list of images
We use Haiku by default; it's plenty for this task and ~10x cheaper than Sonnet.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from anthropic import Anthropic

from .images import PageImage
from .prompts import SYSTEM_PROMPT, build_user_prompt


def _extract_json_array(text: str) -> list[dict]:
    """Tolerant JSON extraction: strip ``` fences if Claude added them."""
    text = text.strip()
    # Strip code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # If Claude wrapped the array in prose, extract just the first [...] portion.
    # Use bracket-depth matching to avoid spanning multiple arrays when Claude
    # outputs trailing content after the JSON (greedy regex would concatenate them).
    start = text.find("[")
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
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    text = text[start:i + 1]
                    break
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Show what we got so debugging is bearable
        preview = text[:500]
        raise ValueError(f"Claude did not return valid JSON. Preview:\n{preview}") from exc
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array, got {type(data).__name__}")
    return data


def extract_events(
    *,
    business: dict,
    page: dict,
    page_text: str,
    images: list[PageImage],
    tag_vocab: list[str],
    model: str | None = None,
) -> list[dict]:
    """Call Claude to extract events from one page. Returns a list of event dicts."""
    client = Anthropic()  # uses ANTHROPIC_API_KEY from env
    model = model or os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")

    images_summary_parts = []
    for img in images:
        images_summary_parts.append(
            f"[IMAGE {img.index}] source_url={img.source_url}\n"
            f"  dimensions: {img.width}x{img.height}\n"
            f"  link_url: {img.link_url or '(none)'}\n"
            f"  section_header: {img.section_header or '(none)'}\n"
            f"  caption (text immediately following this image on the page, "
            f"belongs ONLY to this image): {img.caption}"
        )
    images_summary = "\n\n".join(images_summary_parts) if images_summary_parts else "(none)"

    user_text = build_user_prompt(
        business_name=business["name"],
        business_category=business.get("category") or "",
        business_subcategory=business.get("subcategory") or "",
        page_url=page["url"],
        page_kind=page["kind"],
        hints=page.get("hints") or "",
        tag_vocab=tag_vocab,
        page_text=page_text,
        images_summary=images_summary,
    )

    # Build multimodal content: each image inline, with a label in the text stream
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for img in images:
        content.append({
            "type": "text",
            "text": f"--- IMAGE {img.index} ---",
        })
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img.media_type,
                "data": img.b64,
            },
        })

    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        temperature=0.0,
        messages=[{"role": "user", "content": content}],
    )

    # Concatenate any text blocks in the response
    text_out = "".join(block.text for block in resp.content if block.type == "text")
    events = _extract_json_array(text_out)

    # Enrich each event with image info the model doesn't know (local path, CDN url).
    # Always set defaults FIRST so every event has all three fields even when
    # source_image_index is missing or the image has no outbound link.
    image_by_index = {img.index: img for img in images}
    for ev in events:
        ev.setdefault("image_source_url", None)
        ev.setdefault("image_local_path", None)
        ev.setdefault("external_link", None)
        idx = ev.get("source_image_index")
        if idx and idx in image_by_index:
            img = image_by_index[idx]
            ev["image_source_url"] = img.source_url
            ev["image_local_path"] = img.local_path
            if img.link_url and not ev.get("external_link"):
                ev["external_link"] = img.link_url

    return events
