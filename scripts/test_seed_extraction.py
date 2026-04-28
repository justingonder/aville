#!/usr/bin/env python3
"""Smoke test for src/extractor.py::extract_flyer_seeds.

Runs against a real flyer photo. Requires ANTHROPIC_API_KEY.

Usage:
  python3 scripts/test_seed_extraction.py [path/to/photo.jpg]

Default photo: /Users/jgonder/Downloads/20260422_202538.jpg (Guesthouse flyer).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.extractor import extract_flyer_seeds  # noqa: E402

DEFAULT_PHOTO = Path("/Users/jgonder/Downloads/20260422_202538.jpg")


def main() -> int:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("SKIPPED: no ANTHROPIC_API_KEY in env")
        return 0

    photo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PHOTO
    if not photo_path.exists():
        print(f"FAIL: photo not found at {photo_path}")
        return 1

    media_type = "image/jpeg" if photo_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    seed = extract_flyer_seeds(photo_path.read_bytes(), media_type=media_type)
    print(json.dumps(seed, indent=2))

    # Structural assertions — content varies but shape is fixed.
    expected_keys = {
        "event_title", "venue_name", "date_hint", "time_hint",
        "kind_guess", "distinctive_strings", "flyer_image_is_clean", "seed_confidence",
    }
    missing = expected_keys - set(seed.keys())
    assert not missing, f"missing keys: {missing}"
    assert seed["seed_confidence"] in ("high", "medium", "low"), \
        f"bad seed_confidence: {seed['seed_confidence']}"
    assert isinstance(seed["distinctive_strings"], list), "distinctive_strings must be a list"
    assert isinstance(seed["flyer_image_is_clean"], bool), "flyer_image_is_clean must be bool"

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
