#!/usr/bin/env python3
"""Run the full pipeline: fetch all configured businesses, extract events,
upsert into the database.

Usage:
    python scripts/run_extraction.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.pipeline import run  # noqa: E402


if __name__ == "__main__":
    load_dotenv()
    run()
