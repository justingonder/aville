#!/usr/bin/env python3
"""Regenerate public/index.html from the current database state.

Run this after run_extraction.py, or any time you want to re-render
(e.g. after tweaking the template).

Usage:
    python scripts/build_site.py
    python scripts/build_site.py --skip-og  # skips Playwright/OG generation
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.site_builder import build_site  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-og",
        action="store_true",
        help="Skip per-event/homepage OG image generation (no Playwright needed)",
    )
    args = parser.parse_args()
    build_site(skip_og=args.skip_og)
