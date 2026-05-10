# Using the admin tool

Day-to-day workflow guide for `scripts/admin.py`. For implementation details
(round-trip preservation, scope decisions, anxiety guardrails), see
[`docs/shipped.md`](shipped.md).

## Quick start

```
python3 scripts/admin.py
```

Open `http://127.0.0.1:5050/`. Server is loopback-only — every non-`127.0.0.1`
request gets a 403.

## Before each session

1. **Working tree clean** — `git status --short`. Admin auto-commits, so
   anything sitting in your working tree can get entangled with admin commits
   if you stage by accident. Commit, stash, or revert other changes first.
2. **Pull latest** — `git pull origin main`. The scheduled extraction runs
   daily at 6am Chicago and commits the updated DB; if you don't pull, the
   admin's mtime guard will eventually catch you.
3. **Confirm no extraction is running** — `gh run list --workflow "Scheduled
   extraction + deploy" --status in_progress`. Both the admin and the pipeline
   write to `data/app.db`; concurrent writes can clobber each other.

## Branch strategy

Admin commits land on whatever branch you're checked out on. Two reasonable
patterns:

- **Small session (1–5 edits, vocabulary cleanup, fixing a few event times):**
  stay on `main`. Push directly after. The auto-commit format `admin: …` is
  descriptive enough to read as a normal commit (e.g. `admin: update event 29
  (start_time)`).
- **Long editorial session (10+ blurb edits across many businesses) or
  anything you want a single PR for:** `git checkout -b admin/blurb-cleanup-YYYY-MM-DD`
  first, work, then `git push -u origin <branch>` and `gh pr create`.
  Squash-merge bundles all the tiny commits into one.

There's no wrong answer; the per-save commits are an audit trail either way.

## During the session

- Every save is a separate commit (`admin: update business <slug>`, `admin:
  update event <id> (<fields>)`, etc.). The diff preview always renders before
  write — click Preview, scroll the diff, then Save & commit.
- **Don't open the same file in another editor while the admin is up.** The
  mtime guard will refuse saves with "file changed on disk." Reload the admin
  page after external edits and you're fine.
- The admin **never pushes** — your commits stay local until you push manually.

## After the session — getting changes to aville.net

Three steps:

1. **Review and (optionally) trim** — `git log --oneline -15`. Anything you
   regret: `git reflog` to find the prior state, then `git reset --hard <sha>`
   (only if commits are unpushed and you actually want them gone).
2. **Push** — `git push origin main` (or push the branch and open a PR).
3. **Trigger a rebuild only if your edits change what's on aville.net:**

   | What you edited                                                                  | Run                                                                |
   | -------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
   | Editorial copy (`about`, `tagline`, `vibe_quote`, `metadata.description`)        | **Site rebuild**                                                   |
   | Event fields (`title`, `description`, time, tags, `featured`, `ends_on`, etc.)   | **Site rebuild**                                                   |
   | Series `ends_on` via `/series-candidates/`                                       | **Site rebuild**                                                   |
   | Tag vocabulary (`tags.yaml`)                                                     | **Nothing** — affects the *next* extraction, not the rendered site |
   | Hours / lat-lng / address                                                        | **Site rebuild**                                                   |

   ```
   gh workflow run "Site rebuild"
   gh run list --workflow "Site rebuild" --limit 1     # grab the run id
   gh run watch <id> --exit-status                     # ~4–5 minutes
   ```

   Never run **Scheduled extraction + deploy** just to publish admin edits —
   it'd burn API credits re-extracting everything and might overwrite some of
   your manual fields (see caveat below).

## Field locks — making admin edits stick

Each writable field on `/events/<id>` has a small 🔒 toggle next to its
label. Click it to mark that field as "researched, don't overwrite." The
daily extraction pipeline skips locked fields on UPDATE, so your value
survives every scheduled run thereafter.

Use case: you call a business, confirm end_time is 21:00 (even though the
website never says so), set it in the admin, click 🔒 next to End time,
Save. The next scheduled extraction will read the page, find no end time,
emit `end_time = NULL` for the upsert — and the upsert will skip the
locked field, leaving 21:00 in place.

**Visual cues:**

- Locked field's input gets a gold left border + cream background.
- The events list view shows a `🔒 N` badge in the Flags column,
  tooltip-listing the locked field names.
- Lock-only saves get clean commit messages: `admin: lock fields on
  event 29 (end_time)` / `admin: unlock fields on event 29 (status)`.

**Lockable fields (11):** `title`, `description`, `recurrence_pattern`,
`start_time`, `end_time`, `start_datetime`, `end_datetime`, `price_info`,
`tags`, `performers`, `status`.

**Always preserved across extraction (no lock needed):** `featured`,
`ends_on`, `price_short`. These are admin-only fields the pipeline
never writes.

**Always overwritten on every extraction (not lockable):**
`image_source_url`, `image_local_path`, `external_link`,
`source_page_url`, `source_page_hash`, `confidence`, `raw_extraction`,
and the `*_at` timestamps. These are system metadata, not values worth
hand-curating.

### One caveat about `title` / `recurrence_pattern` / `start_time` / `start_datetime`

Those four fields are part of the event's `match_key` — the identity the
pipeline uses to find an existing row vs. insert a new one. If the source
page produces a different value than the locked row stores, the
extraction's match_key won't find your locked row and will insert a
brand-new event instead (your locked row goes stale over time and shows
up in the Stale filter). Locking these four still works as long as the
source page keeps producing the same value the row was originally created
from — which is the common case.

For other lockable fields (description, end_time, end_datetime,
price_info, tags, performers, status), there's no match_key interaction —
locks are unconditional.

### When to lock vs. when to edit `businesses.yaml` hints

- **Lock the field** when you have ground truth (you called the venue,
  saw a flyer at the bar, etc.) that the website doesn't reflect, and
  you don't expect the website to ever reflect it.
- **Add a hint** in `config/businesses.yaml` when the value IS on the
  page but Claude is missing it — adjusting the hint helps the pipeline
  find it correctly on every run, no lock needed.

Locks are for asserting truth; hints are for improving extraction.

## Things to avoid

- Running `python3 scripts/run_extraction.py` (or letting the scheduled run
  fire) while the admin is open.
- Pushing to main without reviewing `git log` — auto-commits accumulate
  quickly during a vocab-cleanup spree.
- `git reset --hard` without `git reflog` first — admin commits are quick to
  make, but quick to lose too.
- Editing `data/app.db` with `sqlite3` directly while the admin is open.
  Either works, just not simultaneously.

## When something goes wrong

- **A save's diff preview looks wrong:** click Cancel (or just navigate away).
  Nothing's been written.
- **You saved and immediately regret it, no push yet:** `git reset --hard
  HEAD~1` undoes the last admin commit. Reflog keeps it for ~30 days if you
  change your mind.
- **You pushed and regret it:** open a PR that reverts, or `git revert <sha>`
  on a branch and PR that. Don't force-push to main.
- **mtime guard refuses to save:** the file changed on disk since you opened
  the form. Reload the page. If it keeps happening, something else in another
  terminal is touching the file (extraction running? second admin instance?).
- **Round-trip diff has unexpected noise** (e.g. comments disappear,
  formatting shifts): this is a bug in the admin's YAML handler. File an
  issue, restore from the last good commit, fix the handler. Last seen
  2026-05-10 — the `/tags/` handler stripped CommentedSeq metadata; fixed in
  PR #33.
