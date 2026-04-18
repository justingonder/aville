#!/usr/bin/env python3
"""Initialize (or re-initialize) the SQLite database.

Running this is idempotent — existing data is NOT wiped. To start from scratch,
delete data/app.db first.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import init_db, DB_PATH  # noqa: E402


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
