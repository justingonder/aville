#!/usr/bin/env python3
"""Regenerate public/index.html from the current database state.

Run this after run_extraction.py, or any time you want to re-render
(e.g. after tweaking the template).

Usage:
    python scripts/build_site.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.site_builder import build_site  # noqa: E402


if __name__ == "__main__":
    build_site()
