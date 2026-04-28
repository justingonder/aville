#!/usr/bin/env python3
"""Regression test: extract_events with cross_verify_image=None must be
identical to the prior signature. Inspects the function signature only;
does not call Claude.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.extractor import extract_events


def test_signature_keeps_existing_kwargs():
    sig = inspect.signature(extract_events)
    params = sig.parameters
    # Required kwargs from the prior signature must still exist.
    for name in ("business", "page", "page_text", "images", "tag_vocab"):
        assert name in params, f"missing kwarg: {name}"
        assert params[name].kind == inspect.Parameter.KEYWORD_ONLY, \
            f"{name} must be keyword-only"
    # The new kwarg must default to None so existing callers are unaffected.
    assert "cross_verify_image" in params, "missing cross_verify_image kwarg"
    cvi = params["cross_verify_image"]
    assert cvi.default is None, f"cross_verify_image default must be None, got {cvi.default}"
    assert cvi.kind == inspect.Parameter.KEYWORD_ONLY, "cross_verify_image must be keyword-only"
    print("  signature backward compat: OK")


if __name__ == "__main__":
    test_signature_keeps_existing_kwargs()
    print("PASS")
