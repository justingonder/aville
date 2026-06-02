#!/usr/bin/env python3
"""Local-only admin UI for editing config/*.yaml and data/app.db.

Single-user, localhost-bound Flask app. Eases the anxiety of hand-editing
YAML and SQLite by rendering forms with validation, a diff preview, and
auto-commit per save.

Run:    python3 scripts/admin.py
Open:   http://127.0.0.1:5050/

The app refuses any non-loopback request, never pushes to git, and keeps
every save isolated to a single file via `git commit --only`.
"""
from __future__ import annotations

import difflib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, flash, redirect, render_template, request, send_from_directory, url_for
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    LiteralScalarString,
    SingleQuotedScalarString,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import build_match_key, connect, init_db, now_iso, LOCKABLE_FIELDS  # noqa: E402
from src.images import store_event_image_from_url  # noqa: E402
from scripts.list_series_candidates import find_candidates  # noqa: E402

CONFIG_DIR = ROOT / "config"
BUSINESSES_PATH = CONFIG_DIR / "businesses.yaml"
PENDING_PATH = CONFIG_DIR / "businesses_pending.yaml"
TAGS_PATH = CONFIG_DIR / "tags.yaml"
DB_PATH = ROOT / "data" / "app.db"
ADMIN_STATE_PATH = ROOT / "data" / "admin_state.json"  # gitignored; per-machine UI state

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
KIND_CHOICES = ["recurring", "dated"]
STATUS_CHOICES = ["active", "stale", "expired", "rejected"]

# Regex matching everything we currently store in events.recurrence_pattern.
# Validation: token before colon is daily/weekly/monthly; right side is
# free-form day/ordinal slug. Tightening this will reject unusual but
# legitimate values (e.g., 'monthly:1st-friday') so we keep it permissive.
RE_RECURRENCE = re.compile(r"^(daily|weekly:[a-z,\-]+|monthly:[a-z0-9,\-]+)$")
RE_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")  # HH:MM 24-hour


# ---- Flask app ----

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates" / "admin"),
    static_folder=None,
)
app.secret_key = "admin-localhost-only"  # used only for flash messages


@app.before_request
def _localhost_only() -> None:
    """Hard refusal of any non-loopback request."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        abort(403)


@app.route("/_public/<path:subpath>")
def serve_public_image(subpath: str):
    """Serve files out of public/ for in-form image previews.

    Localhost-only (enforced by the global before_request). The pipeline-built
    site uses these same files on aville.net via rsync; in admin we just need
    to display them inline next to the URL field. send_from_directory handles
    path-traversal protection.
    """
    return send_from_directory(ROOT / "public", subpath)


# ---- YAML round-trip ----


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096  # don't wrap long strings
    y.indent(mapping=2, sequence=4, offset=2)
    # Emit explicit `null` instead of empty so existing files round-trip cleanly
    # — the project's YAML uses `null` everywhere and an empty value would
    # produce diff noise on every save.
    y.representer.add_representer(
        type(None),
        lambda dumper, _: dumper.represent_scalar("tag:yaml.org,2002:null", "null"),
    )
    return y


def load_yaml(path: Path) -> tuple[Any, str, float]:
    """Return (parsed_data, raw_text, mtime). Raw text is used for diff."""
    raw = path.read_text()
    data = _yaml().load(io.StringIO(raw))
    return data, raw, path.stat().st_mtime


def dump_yaml(data: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def yaml_diff(old: str, new: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"{label} (current)",
            tofile=f"{label} (after save)",
            n=3,
        )
    )


# ---- git auto-commit ----


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def commit_file(rel_path: str, message: str) -> str:
    """Commit a single file's working-tree state. Returns commit hash on success.

    Uses `git commit --only <path>` so any unrelated staged changes elsewhere
    in the index stay staged for the user's next commit.
    """
    diff = _git("diff", "--", rel_path)
    if not diff.stdout.strip():
        # Nothing actually changed (e.g. user hit save with no edits).
        return ""

    res = _git("commit", "--only", rel_path, "-m", message)
    if res.returncode != 0:
        raise RuntimeError(f"git commit failed:\n{res.stdout}\n{res.stderr}")
    sha = _git("rev-parse", "--short", "HEAD").stdout.strip()
    return sha


def commit_files(rel_paths: list[str], message: str) -> str:
    """Commit a working-tree state spanning multiple files. Returns commit hash.

    Stages the listed paths (covers both modified and new untracked files),
    then `git commit --only` to ignore unrelated staged changes elsewhere in
    the index. Returns "" if none of the listed paths actually have changes.
    """
    if not rel_paths:
        return ""
    _git("add", "--", *rel_paths)
    cached = _git("diff", "--cached", "--", *rel_paths)
    if not cached.stdout.strip():
        return ""
    res = _git("commit", "--only", *rel_paths, "-m", message)
    if res.returncode != 0:
        raise RuntimeError(f"git commit failed:\n{res.stdout}\n{res.stderr}")
    return _git("rev-parse", "--short", "HEAD").stdout.strip()


# ---- session-state helpers (dashboard banners + publish gate) ----

# In-process cache keyed by signal name. Each entry: (value, fetched_at_epoch).
# Avoids hammering git/gh on every dashboard render. Cache hit = instant;
# miss = one subprocess call (~50ms for git, ~1s for gh).
_STATE_CACHE: dict[str, tuple[Any, float]] = {}
_STATE_TTL_SECS = 10


def _cached(key: str, fn: Callable[[], Any], ttl: float = _STATE_TTL_SECS) -> Any:
    now = time.time()
    if key in _STATE_CACHE:
        val, fetched = _STATE_CACHE[key]
        if now - fetched < ttl:
            return val
    val = fn()
    _STATE_CACHE[key] = (val, now)
    return val


def _invalidate_state_cache() -> None:
    _STATE_CACHE.clear()


def _git_status() -> dict:
    """Working-tree state. Returns {clean, files: [{path, code}], error}."""
    try:
        res = _git("status", "--porcelain")
        if res.returncode != 0:
            return {"clean": True, "files": [], "error": res.stderr.strip()}
        lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
        files = []
        for ln in lines:
            # porcelain v1: 2 status chars, space, path
            code = ln[:2].strip() or "??"
            path = ln[3:].strip()
            files.append({"code": code, "path": path})
        return {"clean": not files, "files": files, "error": None}
    except Exception as e:
        return {"clean": True, "files": [], "error": str(e)}


def _git_sync() -> dict:
    """Branch + ahead/behind vs. origin/main. Fetches first (quiet).
    Returns {branch, on_main, ahead, behind, commits: [{sha, subject}], error}.
    """
    out: dict[str, Any] = {
        "branch": "?", "on_main": False, "ahead": 0, "behind": 0,
        "commits": [], "error": None,
    }
    try:
        branch_res = _git("rev-parse", "--abbrev-ref", "HEAD")
        if branch_res.returncode == 0:
            out["branch"] = branch_res.stdout.strip()
            out["on_main"] = out["branch"] == "main"

        # Fetch only if we're plausibly online; failure is non-fatal.
        fetch_res = _git("fetch", "origin", "main", "--quiet")
        if fetch_res.returncode != 0:
            # Treat as a soft warning; downstream counts use last-known remote.
            out["error"] = "couldn't reach origin (offline?); using last fetch"

        # left-right count: <behind>\t<ahead>
        count_res = _git("rev-list", "--left-right", "--count", "origin/main...HEAD")
        if count_res.returncode == 0 and count_res.stdout.strip():
            parts = count_res.stdout.split()
            out["behind"], out["ahead"] = int(parts[0]), int(parts[1])

        # Commit subjects for the "ready to publish" expander
        if out["ahead"] > 0 and out["on_main"]:
            log_res = _git("log", "--format=%h %s", f"origin/main..HEAD")
            if log_res.returncode == 0:
                out["commits"] = [
                    {"sha": ln.split(" ", 1)[0], "subject": ln.split(" ", 1)[1]}
                    for ln in log_res.stdout.splitlines() if " " in ln
                ]
    except Exception as e:
        out["error"] = str(e)
    return out


def _gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def _extraction_status() -> dict:
    """Is a scheduled extraction run in progress?
    Returns {running, run_id, url, error}.
    """
    out: dict[str, Any] = {"running": False, "run_id": None, "url": None, "error": None}
    try:
        res = _gh(
            "run", "list",
            "--workflow", "Scheduled extraction + deploy",
            "--status", "in_progress",
            "--json", "databaseId,url",
            "--limit", "1",
        )
        if res.returncode != 0:
            out["error"] = res.stderr.strip() or "gh CLI unavailable"
            return out
        runs = json.loads(res.stdout or "[]")
        if runs:
            out["running"] = True
            out["run_id"] = runs[0]["databaseId"]
            out["url"] = runs[0]["url"]
    except Exception as e:
        out["error"] = str(e)
    return out


def _publish_run_status(run_id: int) -> dict:
    """Poll endpoint backing data. Cached 3s to avoid hammering gh."""
    def _fetch():
        res = _gh("run", "view", str(run_id),
                  "--json", "status,conclusion,url,updatedAt,displayTitle")
        if res.returncode != 0:
            return {"error": res.stderr.strip() or "gh unavailable", "run_id": run_id}
        try:
            data = json.loads(res.stdout)
        except json.JSONDecodeError:
            return {"error": "couldn't parse gh output", "run_id": run_id}
        data["run_id"] = run_id
        data["error"] = None
        return data
    return _cached(f"publish_status_{run_id}", _fetch, ttl=3)


def _session_state() -> dict:
    """Aggregate the three signals for dashboard rendering. Each is cached
    independently so a partial failure (e.g. gh down) doesn't poison the others.
    """
    return {
        "git_status": _cached("git_status", _git_status),
        "git_sync": _cached("git_sync", _git_sync),
        "extraction": _cached("extraction", _extraction_status),
    }


def _load_admin_state() -> dict:
    """Persistent UI state across browser/computer crashes. Single-user, single-machine.
    Currently stores the last publish run id so the dashboard can re-attach polling
    after a navigate-away or freeze."""
    if not ADMIN_STATE_PATH.exists():
        return {}
    try:
        return json.loads(ADMIN_STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_admin_state(state: dict) -> None:
    ADMIN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ADMIN_STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, ADMIN_STATE_PATH)


# ---- vocab helpers ----


def tags_vocab() -> list[str]:
    """Flat list of all tags from tags.yaml, alphabetised."""
    data, _, _ = load_yaml(TAGS_PATH)
    out: list[str] = []
    for cat in data.get("categories", {}).values():
        out.extend(cat.get("tags") or [])
    return sorted(set(out))


def _merge_unknown(vocab: list[str], present: list[str]) -> list[str]:
    """Vocab plus any `present` tags not in vocab (so the form preserves them)."""
    seen = set(vocab)
    return list(vocab) + [t for t in present if t not in seen]


def tags_categories() -> dict[str, list[str]]:
    """Category name → tag list, in source-file order (CommentedMap preserves it)."""
    data, _, _ = load_yaml(TAGS_PATH)
    return {name: list(cat.get("tags") or []) for name, cat in data.get("categories", {}).items()}


# ---- validation ----


def validate_time(s: str | None) -> str | None:
    if not s:
        return None
    if not RE_TIME.match(s):
        raise ValueError(f"invalid time {s!r} (need HH:MM, 24-hour)")
    return s


def validate_hours_range(s: str | None) -> str | None:
    """Accepts 'HH:MM-HH:MM' or empty/None."""
    if s is None or s.strip() == "":
        return None
    s = s.strip()
    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(f"hours range {s!r} must be HH:MM-HH:MM")
    validate_time(parts[0])
    validate_time(parts[1])
    return s


def validate_recurrence(s: str | None) -> str | None:
    if not s:
        return None
    if not RE_RECURRENCE.match(s):
        raise ValueError(
            f"recurrence pattern {s!r} doesn't look right "
            "(expected daily, weekly:<days>, or monthly:<ordinal-day>)"
        )
    return s


def validate_tags(tags: list[str]) -> list[str]:
    vocab = set(tags_vocab())
    bad = [t for t in tags if t not in vocab]
    if bad:
        raise ValueError(f"unknown tag(s): {bad}. Add them to tags.yaml first.")
    return tags


def validate_iso_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"invalid date {s!r}: {e}") from None
    return s


def validate_iso_datetime(s: str | None) -> str | None:
    """HTML datetime-local sends 'YYYY-MM-DDTHH:MM' (no seconds, no tz)."""
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            datetime.fromisoformat(s)
        except ValueError as e:
            raise ValueError(f"invalid datetime {s!r}: {e}") from None
    return s


def validate_json(s: str | None, expected_type: type) -> Any:
    """Parse a JSON textarea; raise if the parsed value isn't `expected_type`."""
    if not s or not s.strip():
        return expected_type()  # empty list/dict
    try:
        v = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse error: {e}") from None
    if not isinstance(v, expected_type):
        raise ValueError(f"expected JSON {expected_type.__name__}, got {type(v).__name__}")
    return v


# ---- business form <-> YAML mapping ----


def _styled(old, new):
    """Wrap `new` in the same ruamel scalar-style class as `old`.

    Without this, replacing a SingleQuotedScalarString with a plain str
    drops the quotes on round-trip and produces churn in every commit.
    """
    if new is None or not isinstance(new, str):
        return new
    if isinstance(old, DoubleQuotedScalarString):
        return DoubleQuotedScalarString(new)
    if isinstance(old, SingleQuotedScalarString):
        return SingleQuotedScalarString(new)
    if isinstance(old, LiteralScalarString):
        return LiteralScalarString(new)
    return new


def _set_or_delete(mapping, key: str, value) -> None:
    """Set a key on a CommentedMap, preserving original scalar style.

    Empty strings/lists/dicts unset the key. But if the key was already
    *explicitly* None in the file (e.g. `telephone: null` to mark a known
    absent value), keep it as None instead of deleting — the file's shape
    matters for downstream consumers like JSON-LD generators.
    """
    is_empty = value is None or value == "" or value == [] or value == {}
    if is_empty:
        if key in mapping and mapping[key] is None:
            return  # preserve explicit null
        if key in mapping:
            del mapping[key]
    else:
        old = mapping.get(key)
        mapping[key] = _styled(old, value)


def business_to_form(b: dict) -> dict:
    """Turn a CommentedMap business entry into flat form values."""
    hours = b.get("hours") or {}
    return {
        "slug": b.get("slug", ""),
        "name": b.get("name", ""),
        "category": b.get("category", "") or "",
        "subcategory": b.get("subcategory", "") or "",
        "website": b.get("website", "") or "",
        "address": b.get("address", "") or "",
        "lat": "" if b.get("lat") is None else str(b["lat"]),
        "lng": "" if b.get("lng") is None else str(b["lng"]),
        "default_tags": list(b.get("default_tags") or []),
        "hours": {d: (hours.get(d) or "") for d in DAYS},
        "pages_json": json.dumps(_plain(b.get("pages") or []), indent=2),
        "metadata_description": (b.get("metadata") or {}).get("description") or "",
        "metadata_telephone": (b.get("metadata") or {}).get("telephone") or "",
        "metadata_price_range": (b.get("metadata") or {}).get("price_range") or "",
        "metadata_same_as_json": json.dumps(
            _plain((b.get("metadata") or {}).get("same_as") or []), indent=2
        ),
        "tagline": b.get("tagline") or "",
        "vibe_quote": b.get("vibe_quote") or "",
        "about": b.get("about") or "",
    }


def _plain(obj):
    """ruamel CommentedMap/Seq → plain dict/list for json.dumps."""
    if hasattr(obj, "items"):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list) or hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes)):
        try:
            return [_plain(x) for x in obj]
        except TypeError:
            return obj
    return obj


def form_to_business(form, b) -> None:
    """Mutate the CommentedMap business entry in place from form values.

    Mutate-in-place rather than replacing sub-mappings/sequences so that
    ruamel's per-key scalar-style metadata survives the round-trip.
    """
    _set_or_delete(b, "name", form["name"].strip() or None)
    _set_or_delete(b, "category", form["category"].strip() or None)
    _set_or_delete(b, "subcategory", form["subcategory"].strip() or None)
    _set_or_delete(b, "website", form["website"].strip() or None)
    _set_or_delete(b, "address", form["address"].strip() or None)

    lat = form.get("lat", "").strip()
    lng = form.get("lng", "").strip()
    _set_or_delete(b, "lat", float(lat) if lat else None)
    _set_or_delete(b, "lng", float(lng) if lng else None)

    default_tags = form.getlist("default_tags") if hasattr(form, "getlist") else (form.get("default_tags") or [])
    if default_tags:
        existing = list(b.get("default_tags") or [])
        # Only validate NEW tags against the vocabulary — pre-existing tags
        # that are out of sync with tags.yaml are surfaced as warnings on the
        # form and round-trip unchanged.
        validate_tags([t for t in default_tags if t not in set(existing)])
        if set(default_tags) != set(existing):
            b["default_tags"] = default_tags
    elif "default_tags" in b:
        del b["default_tags"]

    # Hours — mutate the existing dict so DoubleQuotedScalarString style sticks.
    if "hours" not in b:
        b["hours"] = {}
    hours_map = b["hours"]
    any_hours = False
    for d in DAYS:
        raw = form.get(f"hours_{d}", "").strip()
        new_value = validate_hours_range(raw)
        old = hours_map.get(d)
        hours_map[d] = _styled(old, new_value) if new_value is not None else None
        if new_value is not None:
            any_hours = True
    if not any_hours:
        del b["hours"]

    # Pages (JSON textarea). If the submitted JSON is logically identical to
    # the existing list, leave the original CommentedSeq alone so folded-scalar
    # style on `hints` survives the round-trip. Only intentional page edits
    # take the wholesale-replace path.
    pages = validate_json(form.get("pages_json"), list)
    for p in pages:
        if not isinstance(p, dict) or "url" not in p:
            raise ValueError("each page must be a dict with a 'url' field")
    existing_canon = json.loads(json.dumps(_plain(b.get("pages") or [])))
    if existing_canon != pages:
        if pages:
            b["pages"] = pages
        elif "pages" in b:
            del b["pages"]

    # Metadata block — mutate in place to preserve SingleQuotedScalarString styles.
    if "metadata" not in b:
        b["metadata"] = {}
    meta = b["metadata"]
    _set_or_delete(meta, "description", form.get("metadata_description", "").strip() or None)
    _set_or_delete(meta, "telephone", form.get("metadata_telephone", "").strip() or None)
    _set_or_delete(meta, "price_range", form.get("metadata_price_range", "").strip() or None)
    submitted_same_as = validate_json(form.get("metadata_same_as_json"), list)
    existing_same_as = json.loads(json.dumps(_plain(meta.get("same_as") or [])))
    if existing_same_as != submitted_same_as:
        meta["same_as"] = submitted_same_as
    elif "same_as" not in meta:
        meta["same_as"] = submitted_same_as
    if not meta:
        del b["metadata"]

    _set_or_delete(b, "tagline", form.get("tagline", "").strip() or None)
    _set_or_delete(b, "vibe_quote", form.get("vibe_quote", "").strip() or None)

    # `about` uses YAML's `|` literal-block style and the chomp indicator
    # depends on whether the value ends with a newline. Existing files use
    # `|` (single trailing newline kept) — make sure we round-trip to that.
    about = form.get("about", "").strip()
    if about and isinstance(b.get("about"), LiteralScalarString):
        about = about + "\n"
    _set_or_delete(b, "about", about or None)


def find_business(data, slug: str):
    for b in data.get("businesses") or []:
        if b.get("slug") == slug:
            return b
    return None


# ---- routes: dashboard ----


@app.route("/")
def dashboard():
    with connect(DB_PATH) as conn:
        counts = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM events WHERE status='active') AS active,
                 (SELECT COUNT(*) FROM events WHERE status='active'
                    AND start_time IS NULL AND start_datetime IS NULL) AS missing_time,
                 (SELECT COUNT(*) FROM events WHERE status='active' AND featured=1) AS featured,
                 (SELECT COUNT(*) FROM events WHERE status='stale') AS stale
              """
        ).fetchone()
        # Suggested-tag count (distinct values)
        sugg = conn.execute(
            """SELECT raw_extraction FROM events
               WHERE status='active' AND raw_extraction IS NOT NULL"""
        ).fetchall()
        series = find_candidates(conn)

    seen = set()
    for r in sugg:
        try:
            payload = json.loads(r["raw_extraction"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        for t in payload.get("suggested_new_tags") or []:
            seen.add(t)
    suggested_count = len(seen)

    pending_data, _, _ = load_yaml(PENDING_PATH)
    pending_count = len(pending_data.get("businesses") or [])

    state = _session_state()
    publish_gate = _publish_gate(state)
    saved_state = _load_admin_state()
    resume_run = _resume_run(saved_state)

    return render_template(
        "dashboard.html",
        counts=dict(counts),
        suggested_count=suggested_count,
        series_count=len(series),
        pending_count=pending_count,
        state=state,
        publish_gate=publish_gate,
        resume_run=resume_run,
    )


def _publish_gate(state: dict) -> dict:
    """Decide whether the Publish card is enabled, and why not.
    Returns {ok: bool, reason: str | None, ahead: int, commits: [...]}.
    """
    sync = state["git_sync"]
    git = state["git_status"]
    extraction = state["extraction"]
    out = {"ok": False, "reason": None, "ahead": sync["ahead"], "commits": sync["commits"]}
    if extraction.get("running"):
        out["reason"] = "Scheduled extraction is running — wait for it to finish."
        return out
    if not sync["on_main"]:
        out["reason"] = (
            f"You're on `{sync['branch']}` — switch to main first "
            "(or merge your branch and pull)."
        )
        return out
    if not git["clean"]:
        out["reason"] = (
            "Your working tree has uncommitted changes. Commit or stash them first "
            "(the admin auto-commits its own edits, so this is something else)."
        )
        return out
    if sync["behind"] > 0:
        out["reason"] = (
            f"You're {sync['behind']} commit(s) behind origin/main. "
            "Pull first, then come back."
        )
        return out
    if sync["ahead"] == 0:
        out["reason"] = "Nothing to publish — you're in sync with origin/main."
        return out
    out["ok"] = True
    return out


def _resume_run(saved_state: dict) -> dict | None:
    """Option-A nicety: if a publish run was started recently and we have its id,
    re-fetch its status so the dashboard can re-attach the polling panel after
    a navigate-away or computer freeze. Drops the reference after 30 minutes."""
    run_id = saved_state.get("last_publish_run_id")
    started_at = saved_state.get("last_publish_started_at")  # epoch
    if not run_id or not started_at:
        return None
    if time.time() - started_at > 30 * 60:
        return None  # too old; let it fade
    info = _publish_run_status(int(run_id))
    info["started_at"] = started_at
    info["workflow"] = saved_state.get("last_publish_workflow") or "Site rebuild"
    return info


# ---- routes: publish ----


SITE_REBUILD_WORKFLOWS = {
    "full": "Site rebuild",
    "fast": "Site rebuild (fast)",
}


def _trigger_site_rebuild_and_get_run(
    before_iso: str, workflow_name: str
) -> tuple[int | None, str | None, str | None]:
    """Fire `gh workflow run <workflow_name>`, then poll briefly for the new
    run's database id. `before_iso` is the timestamp captured just before the
    dispatch so we can distinguish the new run from any prior ones.
    Returns (run_id, run_url, error)."""
    trigger = _gh("workflow", "run", workflow_name)
    if trigger.returncode != 0:
        return None, None, trigger.stderr.strip() or "gh workflow run failed"
    # gh workflow run is async — the dispatch returns before the run appears
    # in the list. Poll for up to 5s for the newer entry.
    for _ in range(10):
        time.sleep(0.5)
        res = _gh(
            "run", "list", "--workflow", workflow_name,
            "--json", "databaseId,url,createdAt", "--limit", "5",
        )
        if res.returncode != 0:
            return None, None, res.stderr.strip() or "couldn't list runs"
        try:
            runs = json.loads(res.stdout or "[]")
        except json.JSONDecodeError:
            continue
        for run in runs:
            if run.get("createdAt", "") >= before_iso:
                return run["databaseId"], run["url"], None
    return None, None, (
        "Triggered, but couldn't locate the new run in 5s. "
        "Check the Actions tab on GitHub manually."
    )


@app.route("/publish/", methods=["POST"])
def publish():
    """Push origin/main + trigger a Site rebuild workflow.

    Accepts `mode=full|fast` (JSON body or form). `full` runs the standard
    workflow (includes OG image regeneration, ~5 min). `fast` runs
    "Site rebuild (fast)" which skips Playwright + OG and finishes in ~60-90s
    — appropriate for content-only edits where the share-preview OG can lag.

    Server-side gate re-check; client's view of the state could be stale by 10s.
    """
    _invalidate_state_cache()  # force fresh status before gating
    gate = _publish_gate(_session_state())
    if not gate["ok"]:
        return {"error": gate["reason"]}, 409

    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or request.form.get("mode") or "full").lower()
    workflow_name = SITE_REBUILD_WORKFLOWS.get(mode)
    if workflow_name is None:
        return {"error": f"unknown publish mode: {mode!r}"}, 400

    # Push first; only trigger the workflow if push succeeds.
    push = _git("push", "origin", "main")
    if push.returncode != 0:
        return {"error": f"git push failed: {push.stderr.strip() or push.stdout.strip()}"}, 502

    before = datetime.now(timezone.utc).isoformat()
    run_id, run_url, err = _trigger_site_rebuild_and_get_run(before, workflow_name)
    if err:
        return {"error": err, "push_ok": True}, 502

    state = _load_admin_state()
    state["last_publish_run_id"] = run_id
    state["last_publish_started_at"] = time.time()
    state["last_publish_run_url"] = run_url
    state["last_publish_workflow"] = workflow_name
    _save_admin_state(state)
    _invalidate_state_cache()  # ahead-count just dropped to 0

    return {"run_id": run_id, "run_url": run_url, "workflow": workflow_name}


@app.route("/publish/status/<int:run_id>", methods=["GET"])
def publish_status(run_id: int):
    """Polling endpoint backing the dashboard status panel. 3s server-side cache."""
    return _publish_run_status(run_id)


@app.route("/git/sync/", methods=["POST"])
def git_sync():
    """Fetch remote and run git pull --rebase origin main."""
    status = _git_status()
    if not status["clean"]:
        flash("Cannot sync: you have uncommitted changes. Save your changes or stash them first.", "warning")
        return redirect(url_for("dashboard"))

    res = _git("pull", "--rebase", "origin", "main")
    if res.returncode == 0:
        _invalidate_state_cache()
        flash("Successfully synced with origin/main (rebase succeeded).", "success")
    else:
        err = res.stderr.strip() or res.stdout.strip()
        # Abort the rebase so the working tree isn't left in a broken state!
        _git("rebase", "--abort")
        flash(f"Sync failed due to conflicts. The rebase was aborted. Conflict details: {err}", "danger")

    return redirect(url_for("dashboard"))


# ---- routes: businesses ----


def _render_business_form(slug: str, path: Path, b, data, mtime: float, raw: str,
                          form_values=None, diff: str = "", errors=None, is_pending=False):
    form = form_values or business_to_form(b)
    vocab = tags_vocab()
    # Preserve any default_tags that aren't in tags.yaml — they're real data
    # we shouldn't silently drop. Surface them as a warning so they get
    # promoted to tags.yaml (or removed) at some point.
    selected_tags = list(form.get("default_tags") or [])
    unknown = [t for t in selected_tags if t not in vocab]
    all_tags = vocab + [t for t in unknown if t not in vocab]
    warnings = []
    if unknown:
        warnings.append(
            f"default_tags not in tags.yaml: {unknown}. "
            "They'll round-trip unchanged but you should add them to the vocabulary."
        )
    return render_template(
        "business_edit.html",
        slug=slug,
        path_label=path.name,
        is_pending=is_pending,
        form=form,
        all_tags=all_tags,
        days=DAYS,
        original_mtime=mtime,
        diff=diff,
        errors=errors or [],
        warnings=warnings,
    )


def _save_business(path: Path, slug: str, form, is_pending: bool):
    """Apply form to YAML at `path`. Returns (raw_old, raw_new, data, b, mtime)."""
    data, raw_old, mtime = load_yaml(path)

    submitted_mtime = float(form.get("original_mtime") or 0)
    if abs(submitted_mtime - mtime) > 0.001:
        raise ValueError(
            f"{path.name} changed on disk since you opened this form. "
            "Reload the page to pick up the latest content before saving."
        )

    b = find_business(data, slug)
    if b is None:
        raise ValueError(f"slug {slug!r} not found in {path.name}")

    form_to_business(form, b)
    raw_new = dump_yaml(data)
    return raw_old, raw_new, data, b, mtime


@app.route("/businesses/")
def businesses_list():
    data, _, _ = load_yaml(BUSINESSES_PATH)
    items = []
    for b in data.get("businesses") or []:
        meta = b.get("metadata") or {}
        items.append({
            "slug": b.get("slug"),
            "name": b.get("name"),
            "category": b.get("category"),
            "default_tags": list(b.get("default_tags") or []),
            "has_blurb": bool(meta.get("description")) and bool(b.get("about")),
            "missing_about": not b.get("about"),
            "missing_metadata_description": not meta.get("description"),
        })
    items.sort(key=lambda x: (x["name"] or "").lower())
    return render_template("business_list.html", items=items, title="Businesses",
                           edit_endpoint="business_edit", is_pending=False)


@app.route("/businesses/<slug>", methods=["GET", "POST"])
def business_edit(slug: str):
    return _business_edit_impl(slug, BUSINESSES_PATH, is_pending=False)


def _business_edit_impl(slug: str, path: Path, is_pending: bool):
    if request.method == "GET":
        data, raw, mtime = load_yaml(path)
        b = find_business(data, slug)
        if b is None:
            abort(404)
        return _render_business_form(slug, path, b, data, mtime, raw, is_pending=is_pending)

    action = request.form.get("action", "preview")
    try:
        raw_old, raw_new, data, b, mtime = _save_business(path, slug, request.form, is_pending)
    except ValueError as e:
        # Re-render with the user's input + error
        try:
            data, raw, fresh_mtime = load_yaml(path)
        except Exception:
            abort(500)
        # Reconstruct form from request
        form_values = _form_from_request(request.form)
        return _render_business_form(slug, path, find_business(data, slug) or {},
                                     data, fresh_mtime, raw,
                                     form_values=form_values,
                                     errors=[str(e)], is_pending=is_pending)

    if action == "save":
        atomic_write(path, raw_new)
        rel = str(path.relative_to(ROOT))
        sha = commit_file(rel, f"admin: update business {slug}")
        if sha:
            flash(f"Saved {path.name} for {slug} (commit {sha}).", "success")
        else:
            flash("No changes to save.", "info")
        target = "pending_list" if is_pending else "businesses_list"
        return redirect(url_for(target))

    # action == 'preview'
    diff = yaml_diff(raw_old, raw_new, path.name)
    form_values = _form_from_request(request.form)
    return _render_business_form(slug, path, b, data, mtime, raw_old,
                                 form_values=form_values, diff=diff,
                                 is_pending=is_pending)


def _form_from_request(form) -> dict:
    """Build the dict the template expects from a POSTed form."""
    return {
        "slug": form.get("slug", ""),
        "name": form.get("name", ""),
        "category": form.get("category", ""),
        "subcategory": form.get("subcategory", ""),
        "website": form.get("website", ""),
        "address": form.get("address", ""),
        "lat": form.get("lat", ""),
        "lng": form.get("lng", ""),
        "default_tags": form.getlist("default_tags"),
        "hours": {d: form.get(f"hours_{d}", "") for d in DAYS},
        "pages_json": form.get("pages_json", "[]"),
        "metadata_description": form.get("metadata_description", ""),
        "metadata_telephone": form.get("metadata_telephone", ""),
        "metadata_price_range": form.get("metadata_price_range", ""),
        "metadata_same_as_json": form.get("metadata_same_as_json", "[]"),
        "tagline": form.get("tagline", ""),
        "vibe_quote": form.get("vibe_quote", ""),
        "about": form.get("about", ""),
    }


# ---- routes: pending businesses ----


@app.route("/pending/")
def pending_list():
    data, _, _ = load_yaml(PENDING_PATH)
    items = []
    for b in data.get("businesses") or []:
        items.append({
            "slug": b.get("slug"),
            "name": b.get("name"),
            "category": b.get("category"),
            "default_tags": list(b.get("default_tags") or []),
            "has_blurb": bool((b.get("metadata") or {}).get("description")) and bool(b.get("about")),
            "missing_about": not b.get("about"),
            "missing_metadata_description": not (b.get("metadata") or {}).get("description"),
            "confidence": b.get("_confidence"),
        })
    items.sort(key=lambda x: (x["name"] or "").lower())
    return render_template("pending_list.html", items=items, title="Pending businesses",
                           edit_endpoint="pending_edit", is_pending=True)


@app.route("/pending/<slug>", methods=["GET", "POST"])
def pending_edit(slug: str):
    return _business_edit_impl(slug, PENDING_PATH, is_pending=True)


@app.route("/pending/<slug>/promote", methods=["POST"])
def pending_promote(slug: str):
    pending_data, _, p_mtime = load_yaml(PENDING_PATH)
    active_data, _, a_mtime = load_yaml(BUSINESSES_PATH)

    b = find_business(pending_data, slug)
    if b is None:
        flash(f"Slug {slug!r} not in pending.", "error")
        return redirect(url_for("pending_list"))
    if find_business(active_data, slug) is not None:
        flash(f"Slug {slug!r} already in businesses.yaml — won't duplicate.", "error")
        return redirect(url_for("pending_list"))

    # Strip the discovery-only keys before promoting.
    promoted = b.copy()
    for k in ("_discovery_notes", "_test_extraction", "_confidence"):
        if k in promoted:
            del promoted[k]

    active_data["businesses"].append(promoted)
    pending_data["businesses"] = [
        x for x in pending_data["businesses"] if x.get("slug") != slug
    ]

    atomic_write(BUSINESSES_PATH, dump_yaml(active_data))
    atomic_write(PENDING_PATH, dump_yaml(pending_data))

    # Two files in one commit, so we can't use --only. Stage both explicitly.
    rel_a = str(BUSINESSES_PATH.relative_to(ROOT))
    rel_p = str(PENDING_PATH.relative_to(ROOT))
    _git("add", rel_a, rel_p)
    res = _git(
        "commit",
        "--only",
        rel_a,
        rel_p,
        "-m",
        f"admin: promote {slug} from pending to businesses.yaml",
    )
    if res.returncode != 0:
        flash(f"Files written but commit failed: {res.stderr}", "error")
    else:
        sha = _git("rev-parse", "--short", "HEAD").stdout.strip()
        flash(f"Promoted {slug} (commit {sha}). Run backfill_editorial_copy if needed.", "success")
    return redirect(url_for("businesses_list"))


# ---- routes: events ----


@app.route("/events/")
def events_list():
    f = request.args.get("filter", "active")
    business_slug = request.args.get("business")

    where = ["e.status = 'active'"]
    params: list[Any] = []
    if f == "missing-time":
        where.append("e.start_time IS NULL AND e.start_datetime IS NULL")
    elif f == "featured":
        where.append("e.featured = 1")
    elif f == "stale":
        where[0] = "e.status = 'stale'"
    elif f == "all":
        where = ["e.status IN ('active','stale','expired','rejected')"]
    if business_slug:
        where.append("b.slug = ?")
        params.append(business_slug)

    sql = f"""
        SELECT e.id, e.title, e.kind, e.recurrence_pattern, e.start_time, e.end_time,
               e.start_datetime, e.featured, e.ends_on, e.status, e.tags, e.locked_fields,
               b.name AS business_name, b.slug AS business_slug
        FROM events e JOIN businesses b ON e.business_id = b.id
        WHERE {' AND '.join(where)}
        ORDER BY b.name, e.title
    """
    with connect(DB_PATH) as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        all_businesses = [
            dict(r) for r in conn.execute(
                "SELECT slug, name FROM businesses ORDER BY name"
            ).fetchall()
        ]
    for r in rows:
        r["tags"] = json.loads(r["tags"] or "[]")
        r["missing_time"] = r["start_time"] is None and r["start_datetime"] is None
        r["locked_fields"] = json.loads(r["locked_fields"] or "[]")

    return render_template(
        "event_list.html",
        rows=rows,
        all_businesses=all_businesses,
        active_filter=f,
        active_business=business_slug or "",
    )


def _event_to_form(row: dict) -> dict:
    locked = json.loads(row.get("locked_fields") or "[]")
    alt_sources = json.loads(row.get("alternate_sources") or "[]")
    return {
        "id": row["id"],
        "title": row["title"] or "",
        "description": row["description"] or "",
        "kind": row["kind"],
        "recurrence_pattern": row["recurrence_pattern"] or "",
        "start_time": row["start_time"] or "",
        "end_time": row["end_time"] or "",
        "start_datetime": (row["start_datetime"] or "")[:16],  # 'YYYY-MM-DDTHH:MM'
        "end_datetime": (row["end_datetime"] or "")[:16],
        "price_info": row["price_info"] or "",
        "price_short": row["price_short"] or "",
        "tags": json.loads(row["tags"] or "[]"),
        "performers_json": json.dumps(json.loads(row["performers"] or "[]"), indent=2),
        "featured": bool(row["featured"]),
        "starts_on": row.get("starts_on") or "",
        "ends_on": row["ends_on"] or "",
        "status": row["status"],
        "locked_fields": locked,
        "image_source_url": row.get("image_source_url") or "",
        "image_local_path": row.get("image_local_path") or "",
        # image_source_url + image_local_path lock together — UI shows one box.
        "image_locked": "image_source_url" in locked or "image_local_path" in locked,
        "ticket_url": row.get("ticket_url") or "",
        "alternate_sources": alt_sources,
        "alternate_sources_text": _alt_sources_to_text(alt_sources),
    }


def _alt_sources_to_text(entries: list[dict]) -> str:
    """Render the JSON alternate_sources list as one line per entry: `url | found`."""
    lines = []
    for e in entries:
        url = (e.get("url") or "").strip()
        if not url:
            continue
        found = (e.get("found") or "").strip()
        lines.append(f"{url} | {found}" if found else url)
    return "\n".join(lines)


def _parse_alt_sources(text: str, existing: list[dict]) -> list[dict]:
    """Parse `url | what was found` lines back into the JSON list.

    Preserves `added_at` for URLs that were already in the list so saving the
    same set on a different day doesn't churn the date. New URLs get today's
    date.
    """
    existing_by_url = {e.get("url"): e for e in existing if e.get("url")}
    today = datetime.now(timezone.utc).date().isoformat()
    out: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line:
            url, found = line.split("|", 1)
            url, found = url.strip(), found.strip()
        else:
            url, found = line, ""
        if not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError(f"alternate source URL must start with http:// or https:// ({url!r})")
        prev = existing_by_url.get(url)
        added_at = prev["added_at"] if prev and prev.get("added_at") else today
        out.append({"url": url, "found": found, "added_at": added_at})
    return out


@app.route("/events/<int:event_id>", methods=["GET", "POST"])
def event_edit(event_id: int):
    with connect(DB_PATH) as conn:
        row = conn.execute(
            """SELECT e.*, b.name AS business_name, b.slug AS business_slug
               FROM events e JOIN businesses b ON e.business_id = b.id
               WHERE e.id = ?""",
            (event_id,),
        ).fetchone()
    if row is None:
        abort(404)
    row = dict(row)

    if request.method == "GET":
        form = _event_to_form(row)
        return render_template(
            "event_edit.html",
            row=row,
            form=form,
            all_tags=_merge_unknown(tags_vocab(), form["tags"]),
            recurrence_examples=_recurrence_examples(),
            status_choices=STATUS_CHOICES,
            diff_rows=[],
            errors=[],
        )

    # image_source_url and image_local_path are exposed in the UI as a single
    # logical lock ("Image"). Build the locks set: every other lockable field
    # from its own checkbox, plus the image pair iff `lock_image` is on.
    non_image_lockable = [
        f for f in LOCKABLE_FIELDS if f not in ("image_source_url", "image_local_path")
    ]
    locks_set = {
        f for f in non_image_lockable if request.form.get(f"lock_{f}") == "on"
    }
    if request.form.get("lock_image") == "on":
        locks_set.update({"image_source_url", "image_local_path"})
    submitted_locks = sorted(locks_set)
    ticket_url_value = request.form.get("ticket_url", "").strip()

    existing_alt_sources = json.loads(row.get("alternate_sources") or "[]")
    form_values = {
        "id": event_id,
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "kind": request.form.get("kind", row["kind"]),
        "recurrence_pattern": request.form.get("recurrence_pattern", "").strip(),
        "start_time": request.form.get("start_time", "").strip(),
        "end_time": request.form.get("end_time", "").strip(),
        "start_datetime": request.form.get("start_datetime", "").strip(),
        "end_datetime": request.form.get("end_datetime", "").strip(),
        "price_info": request.form.get("price_info", "").strip(),
        "price_short": request.form.get("price_short", "").strip(),
        "tags": request.form.getlist("tags"),
        "performers_json": request.form.get("performers_json", "[]"),
        "featured": request.form.get("featured") == "on",
        "starts_on": request.form.get("starts_on", "").strip(),
        "ends_on": request.form.get("ends_on", "").strip(),
        "status": request.form.get("status", row["status"]),
        "locked_fields": submitted_locks,
        "ticket_url": ticket_url_value,
        "image_source_url": request.form.get("image_source_url", "").strip(),
        # image_local_path is server-managed: it tracks whatever the most
        # recent image download produced. Carry the existing value through
        # the form-validation cycle so the diff display is meaningful.
        "image_local_path": row.get("image_local_path") or "",
        "image_locked": request.form.get("lock_image") == "on",
        "alternate_sources_text": request.form.get("alternate_sources_text", ""),
        # Parsed-JSON form is filled below once validation runs.
        "alternate_sources": existing_alt_sources,
    }

    errors: list[str] = []
    try:
        if form_values["kind"] not in KIND_CHOICES:
            raise ValueError(f"kind must be one of {KIND_CHOICES}")
        if form_values["status"] not in STATUS_CHOICES:
            raise ValueError(f"status must be one of {STATUS_CHOICES}")
        validate_recurrence(form_values["recurrence_pattern"] or None)
        validate_time(form_values["start_time"] or None)
        validate_time(form_values["end_time"] or None)
        validate_iso_datetime(form_values["start_datetime"] or None)
        validate_iso_datetime(form_values["end_datetime"] or None)
        validate_iso_date(form_values["ends_on"] or None)
        validate_iso_date(form_values["starts_on"] or None)
        tk = form_values["ticket_url"]
        if tk and not (tk.startswith("http://") or tk.startswith("https://")):
            raise ValueError("ticket URL must start with http:// or https://")
        existing_tags = set(json.loads(row["tags"] or "[]"))
        validate_tags([t for t in form_values["tags"] if t not in existing_tags])
        performers = validate_json(form_values["performers_json"], list)
        for p in performers:
            if not isinstance(p, dict) or "name" not in p:
                raise ValueError("each performer must be a dict with at least a 'name' field")
        img_url = form_values["image_source_url"]
        if img_url and not (img_url.startswith("http://") or img_url.startswith("https://")):
            raise ValueError("image source URL must start with http:// or https://")
        form_values["alternate_sources"] = _parse_alt_sources(
            form_values["alternate_sources_text"], existing_alt_sources
        )
    except ValueError as e:
        errors.append(str(e))

    if errors:
        return render_template(
            "event_edit.html",
            row=row, form=form_values,
            all_tags=_merge_unknown(tags_vocab(), form_values["tags"]),
            recurrence_examples=_recurrence_examples(),
            status_choices=STATUS_CHOICES, diff_rows=[], errors=errors,
        )

    # Preserve original tag order if the set is unchanged — the multi-select
    # always submits options in alphabetical (DOM) order, which would
    # otherwise produce a fake diff for an unrelated edit.
    existing_tags_list = json.loads(row["tags"] or "[]")
    if set(form_values["tags"]) == set(existing_tags_list):
        form_values["tags"] = existing_tags_list

    # Resolve the image side-effects before computing the final diff so the
    # diff reflects the post-download image_local_path.
    image_files_to_commit: list[str] = []
    new_image_source_url: str | None = form_values["image_source_url"] or None
    new_image_local_path: str | None = row.get("image_local_path")
    old_image_source_url = row.get("image_source_url") or ""
    if request.form.get("action") == "save" and not errors:
        try:
            if new_image_source_url and new_image_source_url != old_image_source_url:
                _, new_image_local_path = store_event_image_from_url(
                    new_image_source_url,
                    row["business_slug"],
                    ROOT / "public",
                )
                image_files_to_commit = _image_file_paths_for_commit(new_image_local_path)
            elif not new_image_source_url:
                # User cleared the URL → drop the on-disk pointer too.
                # We leave the existing file in place (it may still be the right
                # asset for the next extraction run); just NULL the column.
                new_image_local_path = None
        except Exception as exc:  # noqa: BLE001  -- network, decode, or PIL errors
            errors.append(f"image download failed: {exc}")

    form_values["image_local_path"] = new_image_local_path or ""
    diff_rows = _event_diff(row, form_values)

    if errors:
        return render_template(
            "event_edit.html",
            row=row, form=form_values,
            all_tags=_merge_unknown(tags_vocab(), form_values["tags"]),
            recurrence_examples=_recurrence_examples(),
            status_choices=STATUS_CHOICES, diff_rows=[], errors=errors,
        )

    if request.form.get("action") == "save":
        new_values = {
            "title": form_values["title"],
            "description": form_values["description"] or None,
            "kind": form_values["kind"],
            "recurrence_pattern": form_values["recurrence_pattern"] or None,
            "start_time": form_values["start_time"] or None,
            "end_time": form_values["end_time"] or None,
            "start_datetime": _to_iso(form_values["start_datetime"], row["start_datetime"]),
            "end_datetime": _to_iso(form_values["end_datetime"], row["end_datetime"]),
            "price_info": form_values["price_info"] or None,
            "price_short": form_values["price_short"] or None,
            "tags": json.dumps(form_values["tags"]),
            "performers": json.dumps(validate_json(form_values["performers_json"], list)),
            "featured": 1 if form_values["featured"] else 0,
            "starts_on": form_values["starts_on"] or None,
            "ends_on": form_values["ends_on"] or None,
            "status": form_values["status"],
            "locked_fields": json.dumps(form_values["locked_fields"]) if form_values["locked_fields"] else None,
            "ticket_url": form_values["ticket_url"] or None,
            "image_source_url": new_image_source_url,
            "image_local_path": new_image_local_path,
            "alternate_sources": json.dumps(form_values["alternate_sources"]) if form_values["alternate_sources"] else None,
        }
        with connect(DB_PATH) as conn:
            conn.execute(
                """UPDATE events SET
                     title=:title, description=:description, kind=:kind,
                     recurrence_pattern=:recurrence_pattern,
                     start_time=:start_time, end_time=:end_time,
                     start_datetime=:start_datetime, end_datetime=:end_datetime,
                     price_info=:price_info, price_short=:price_short,
                     tags=:tags, performers=:performers,
                     featured=:featured,
                     starts_on=:starts_on, ends_on=:ends_on,
                     status=:status,
                     locked_fields=:locked_fields,
                     ticket_url=:ticket_url,
                     image_source_url=:image_source_url,
                     image_local_path=:image_local_path,
                     alternate_sources=:alternate_sources
                   WHERE id=:id""",
                {**new_values, "id": event_id},
            )
        message = _event_commit_message(event_id, diff_rows)
        sha = commit_files(["data/app.db", *image_files_to_commit], message)
        if sha:
            flash(f"Saved event {event_id} (commit {sha}).", "success")
        else:
            flash("No DB changes detected.", "info")
        return redirect(url_for("events_list"))

    return render_template(
        "event_edit.html",
        row=row, form=form_values,
        all_tags=_merge_unknown(tags_vocab(), form_values["tags"]),
        recurrence_examples=_recurrence_examples(),
        status_choices=STATUS_CHOICES, diff_rows=diff_rows, errors=[],
    )


def _unique_copy_title(conn, business_id: int, source_title: str) -> str:
    """Find a (copy)-suffixed title that doesn't collide within this business.

    Title uniqueness implies match_key uniqueness for the duplicate (kind +
    recurrence + time are copied verbatim from the source, so the differing
    title is what disambiguates).
    """
    candidate = f"{source_title} (copy)"
    n = 2
    while conn.execute(
        "SELECT 1 FROM events WHERE business_id=? AND title=?",
        (business_id, candidate),
    ).fetchone():
        candidate = f"{source_title} (copy {n})"
        n += 1
    return candidate


@app.route("/events/<int:event_id>/duplicate", methods=["POST"])
def event_duplicate(event_id: int):
    """Clone an event row so the admin can build schedule variants.

    Use case: a show that plays different times on different days of the
    week (e.g. CML Close-Up Show 7pm Mon-Thu, 7pm + 10pm Fri-Sat). Split
    by editing the original to one schedule and duplicating it for each
    other schedule.

    Copies all editable fields verbatim except: title gains " (copy)"
    (or "(copy 2)" if needed) so match_key stays unique; featured resets
    to 0; status resets to 'active'; timestamps reset to now. Source-page
    metadata + locked_fields + alternate_sources + image/ticket fields
    carry through so research isn't lost.
    """
    with connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT e.*, b.slug AS business_slug FROM events e "
            "JOIN businesses b ON e.business_id=b.id WHERE e.id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            abort(404)
        row = dict(row)
        new_title = _unique_copy_title(conn, row["business_id"], row["title"])
        # Construct just enough of an event-shaped dict for build_match_key.
        match_event = {
            "kind": row["kind"],
            "title": new_title,
            "recurrence_pattern": row["recurrence_pattern"],
            "start_time": row["start_time"],
            "start_datetime": row["start_datetime"],
        }
        new_match_key = build_match_key(match_event)
        now = now_iso()
        cur = conn.execute(
            """
            INSERT INTO events (
                business_id, kind, title, description,
                recurrence_pattern, start_time, end_time,
                start_datetime, end_datetime,
                price_info, price_short, tags, performers,
                image_source_url, image_local_path, external_link,
                source_page_url, source_page_hash, confidence, raw_extraction,
                status, featured, starts_on, ends_on,
                first_seen_at, last_seen_at, last_extracted_at,
                match_key, locked_fields, ticket_url, alternate_sources
            )
            SELECT
                business_id, kind, :new_title, description,
                recurrence_pattern, start_time, end_time,
                start_datetime, end_datetime,
                price_info, price_short, tags, performers,
                image_source_url, image_local_path, external_link,
                source_page_url, source_page_hash, confidence, raw_extraction,
                'active', 0, starts_on, ends_on,
                :now, :now, :now,
                :match_key, locked_fields, ticket_url, alternate_sources
            FROM events WHERE id = :source_id
            """,
            {
                "new_title": new_title,
                "now": now,
                "match_key": new_match_key,
                "source_id": event_id,
            },
        )
        new_id = cur.lastrowid
    sha = commit_file("data/app.db", f"admin: duplicate event {event_id} as event {new_id}")
    if sha:
        flash(
            f"Duplicated event {event_id} as event {new_id} ({new_title!r}, commit {sha}). "
            "Editing the new copy — change the recurrence or time to differentiate.",
            "success",
        )
    else:
        flash(f"Duplicated event {event_id} as event {new_id} (no commit — nothing changed).", "info")
    return redirect(url_for("event_edit", event_id=new_id))


_TZ_RE = re.compile(r"(Z|[+\-]\d{2}:?\d{2})$")


def _tz_suffix(s: str | None) -> str:
    """Pull the trailing tz offset off an ISO datetime, or '' if naive."""
    if not s:
        return ""
    m = _TZ_RE.search(s)
    return m.group(1) if m else ""


def _to_iso(s: str, original: str | None = None) -> str | None:
    """HTML datetime-local 'YYYY-MM-DDTHH:MM' → ISO string for DB.

    If `original` had a timezone suffix (e.g. '-05:00' for Chicago), reapply
    it so a no-op edit round-trips byte-identical and so user edits keep
    the same Chicago offset that the rest of the pipeline produces.
    """
    if not s:
        return None
    if len(s) == 16:
        s = s + ":00"
    tz = _tz_suffix(original)
    if tz and not _TZ_RE.search(s):
        s = s + tz
    return s


def _event_diff(row: dict, form: dict) -> list[dict]:
    """Build a list of {field, old, new} dicts for the changed columns."""
    existing_locks = sorted(json.loads(row.get("locked_fields") or "[]"))
    existing_alt = json.loads(row.get("alternate_sources") or "[]")
    pairs = [
        ("title", row["title"], form["title"]),
        ("description", row["description"], form["description"]),
        ("kind", row["kind"], form["kind"]),
        ("recurrence_pattern", row["recurrence_pattern"], form["recurrence_pattern"]),
        ("start_time", row["start_time"], form["start_time"]),
        ("end_time", row["end_time"], form["end_time"]),
        ("start_datetime", row["start_datetime"], _to_iso(form["start_datetime"], row["start_datetime"])),
        ("end_datetime", row["end_datetime"], _to_iso(form["end_datetime"], row["end_datetime"])),
        ("price_info", row["price_info"], form["price_info"]),
        ("price_short", row["price_short"], form["price_short"]),
        ("tags", json.loads(row["tags"] or "[]"), form["tags"]),
        ("performers", json.loads(row["performers"] or "[]"),
         validate_json(form["performers_json"], list)),
        ("featured", bool(row["featured"]), form["featured"]),
        ("starts_on", row.get("starts_on"), form["starts_on"] or None),
        ("ends_on", row["ends_on"], form["ends_on"] or None),
        ("status", row["status"], form["status"]),
        ("locked_fields", existing_locks, form["locked_fields"]),
        ("ticket_url", row.get("ticket_url"), form["ticket_url"] or None),
        ("image_source_url", row.get("image_source_url"), form["image_source_url"] or None),
        ("image_local_path", row.get("image_local_path"), form["image_local_path"] or None),
        ("alternate_sources", existing_alt, form.get("alternate_sources") or []),
    ]
    out = []
    for field, old, new in pairs:
        if (old or "") != (new or "") and old != new:
            out.append({"field": field, "old": old, "new": new})
    return out


def _image_file_paths_for_commit(image_local_path: str) -> list[str]:
    """Return repo-relative paths for the base webp + any srcset variants that exist.

    image_local_path is what the DB stores: e.g. 'images/kopi-cafe/abc.webp'
    (relative to public/). On-disk siblings produced by `_generate_srcset_variants`
    follow `<stem>-400w.webp`, `<stem>-800w.webp` naming.
    """
    base_rel = f"public/{image_local_path}"
    paths = [base_rel] if (ROOT / base_rel).exists() else []
    stem = Path(image_local_path).stem
    parent = Path(image_local_path).parent
    for w in (400, 800):
        variant = f"public/{parent}/{stem}-{w}w.webp"
        if (ROOT / variant).exists():
            paths.append(variant)
    return paths


def _event_commit_message(event_id: int, diff_rows: list[dict]) -> str:
    """Craft an `admin: …` commit message that distinguishes lock-only edits
    from value edits, so `git log` reads cleanly:
        admin: lock fields on event 29 (start_time, end_time)
        admin: unlock fields on event 29 (status)
        admin: update event 29 (start_time, locked_fields)
    """
    if not diff_rows:
        return f"admin: update event {event_id} (no-op)"
    fields = [d["field"] for d in diff_rows]
    if fields == ["locked_fields"]:
        lock_diff = diff_rows[0]
        old_set = set(lock_diff["old"] or [])
        new_set = set(lock_diff["new"] or [])
        added = sorted(new_set - old_set)
        removed = sorted(old_set - new_set)
        if added and not removed:
            return f"admin: lock fields on event {event_id} ({', '.join(added)})"
        if removed and not added:
            return f"admin: unlock fields on event {event_id} ({', '.join(removed)})"
    return f"admin: update event {event_id} ({', '.join(fields)})"


def _recurrence_examples() -> list[str]:
    """Distinct values currently in the DB, for the datalist in the form."""
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT DISTINCT recurrence_pattern FROM events
               WHERE recurrence_pattern IS NOT NULL ORDER BY 1"""
        ).fetchall()
    return [r["recurrence_pattern"] for r in rows]


# ---- routes: tags vocab + suggested-tag promotion ----


@app.route("/tags/", methods=["GET", "POST"])
def tags_edit():
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "add":
            cat = request.form.get("category", "").strip()
            tag = request.form.get("tag", "").strip().lower()
            if not cat or not tag:
                flash("Category and tag both required.", "error")
                return redirect(url_for("tags_edit"))
            data, _, _ = load_yaml(TAGS_PATH)
            cats = data.get("categories") or {}
            if cat not in cats:
                flash(f"Unknown category {cat!r}.", "error")
                return redirect(url_for("tags_edit"))
            # Mutate the ruamel CommentedSeq in place so inline tag comments
            # (e.g. `- tabletop-gaming    # D&D, Magic, etc.`) and blank-line
            # separators between categories survive the round-trip. Converting
            # to a plain Python list via list(...) would strip both.
            seq = cats[cat].get("tags")
            if seq is None:
                cats[cat]["tags"] = []
                seq = cats[cat]["tags"]
            if tag in seq:
                flash(f"{tag!r} already in {cat}.", "info")
                return redirect(url_for("tags_edit"))
            seq.append(tag)
            atomic_write(TAGS_PATH, dump_yaml(data))
            sha = commit_file("config/tags.yaml", f"admin: add tag {tag} to {cat}")
            flash(f"Added {tag} to {cat} (commit {sha}).", "success")
            return redirect(url_for("tags_edit"))
        if action == "remove":
            cat = request.form.get("category", "").strip()
            tag = request.form.get("tag", "").strip()
            data, _, _ = load_yaml(TAGS_PATH)
            cats = data.get("categories") or {}
            if cat not in cats:
                flash(f"Unknown category {cat!r}.", "error")
                return redirect(url_for("tags_edit"))
            seq = cats[cat].get("tags")
            if seq is None or tag not in seq:
                flash(f"{tag!r} not in {cat}.", "error")
                return redirect(url_for("tags_edit"))
            seq.remove(tag)  # CommentedSeq supports .remove(), preserves rest
            atomic_write(TAGS_PATH, dump_yaml(data))
            sha = commit_file("config/tags.yaml", f"admin: remove tag {tag} from {cat}")
            flash(f"Removed {tag} from {cat} (commit {sha}).", "success")
            return redirect(url_for("tags_edit"))

    cats = tags_categories()

    # Suggested tags from raw_extraction across active events
    with connect(DB_PATH) as conn:
        rows = conn.execute(
            """SELECT id, raw_extraction FROM events
               WHERE status='active' AND raw_extraction IS NOT NULL"""
        ).fetchall()
    counter: Counter[str] = Counter()
    for r in rows:
        try:
            payload = json.loads(r["raw_extraction"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        for t in payload.get("suggested_new_tags") or []:
            counter[t] += 1
    vocab = set(tags_vocab())
    suggestions = sorted(
        [(t, n) for t, n in counter.items() if t not in vocab],
        key=lambda x: (-x[1], x[0]),
    )

    return render_template(
        "tags.html",
        categories=cats,
        suggestions=suggestions,
    )


# ---- routes: series candidates ----


@app.route("/series-candidates/", methods=["GET", "POST"])
def series_candidates_view():
    if request.method == "POST":
        event_id = int(request.form["event_id"])
        ends_on = validate_iso_date(request.form.get("ends_on", "").strip())
        if not ends_on:
            flash("ends_on date required.", "error")
            return redirect(url_for("series_candidates_view"))
        with connect(DB_PATH) as conn:
            conn.execute("UPDATE events SET ends_on = ? WHERE id = ?", (ends_on, event_id))
        sha = commit_file(
            "data/app.db",
            f"admin: set ends_on={ends_on} on event {event_id}",
        )
        flash(f"Set ends_on={ends_on} on event {event_id} (commit {sha}).", "success")
        return redirect(url_for("series_candidates_view"))

    with connect(DB_PATH) as conn:
        cands = find_candidates(conn, include_already_set=True)
    return render_template("series_candidates.html", candidates=cands)


# ---- main ----


def main() -> None:
    # Run idempotent migrations so admin-only features (alternate_sources,
    # image-field locking) work even on a DB that hasn't seen an extraction
    # run yet.
    init_db(DB_PATH)
    print("Starting admin on http://127.0.0.1:5050/  (loopback only, Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5050, debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
