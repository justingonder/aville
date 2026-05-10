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

## Caveat — extraction can overwrite admin edits

The daily extraction pipeline upserts events from each source page. Fields
that get re-written each run:

`title`, `description`, `recurrence_pattern`, `start_time`, `end_time`,
`start_datetime`, `end_datetime`, `price_info`, `tags`, `performers`

So if you hand-set `start_time = "17:00"` on an event (because the source page
doesn't include a time), the next extraction will write `start_time = NULL`
back as long as the source still doesn't mention a time. Your edit lasts
until the source page changes meaningfully.

Fields the pipeline **never touches** (safe to hand-edit forever):

`featured`, `ends_on`, `price_short`, `status`

If you want a manual time to stick permanently, the right long-term fix is in
`config/businesses.yaml`'s `hints` field (telling Claude where to find it on
the page) — not the admin. Use the admin for "fix this for the next ~24h"
type edits to fields the pipeline writes, and for the four "manual-only"
fields above.

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
