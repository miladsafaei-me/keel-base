# Worktree isolation and serialized deploys

Several Claude Code sessions run at once against the shared checkouts in
`~/www`. Without isolation they edit the same files, so one session's `git add`
sweeps up another's half-finished work, and two sessions dispatching an image
build at the same time race on the same tag — the run that finishes last wins,
even when it carries the older commit.

This directory is the single implementation for both problems, shared by every
project in the workspace. It replaces the per-project copies that used to live
in `‹project›/.claude/hooks/worktree-session*.sh` and had already drifted apart.

## What a session gets

| Layer | Effect |
| --- | --- |
| SessionStart hook | Creates this session's worktree for the project it opened in, or arms workspace mode when it opened at `~/www`. Sweeps shipped worktrees. |
| PreToolUse guard (Write/Edit) | Blocks a write to a project's shared checkout and names the worktree path to use instead. |
| PreToolUse guard (Bash) | Same block for shell writes, plus routes image-build dispatches through `wt deploy`. |
| SessionEnd hook | Removes this session's worktrees whose work is shipped or empty; keeps anything with commits or uncommitted changes. |
| `wt` CLI | Everything a session does by hand: get a worktree, ship, deploy, inspect, opt out. |

Worktrees live at `~/www/.worktrees/‹project›/‹session-id-8›` on branch
`wt/‹session-id-8›`, always branched from `origin/main`.

## The CLI

```
wt [<project>]        print (creating if needed) this session's worktree
wt ls                 this session's worktrees and every sibling's unlanded work
wt status <project>   detail for one project, including any deploy in flight
wt ship <project>     rebase onto origin/main, push to main, sync the local preview
wt deploy <project>   locked deploy: one build at a time across all sessions
wt off|on <project>   toggle isolation for a project
wt sweep              collect shipped/empty worktrees now
```

`wt ship` refuses a dirty worktree, rebases, pushes to `main` under a per-project
lock, and runs the project's local-sync script if it has one. Pushing to `main`
still does not deploy — the accumulate-on-main model is unchanged.

`wt deploy` holds a per-project lock for the **whole build**, so a second session
queues instead of racing. Before dispatching it refuses to run while this session
has uncommitted or unlanded commits, and it lists the sibling sessions whose work
is *not* in the deploy, so a batch is never shipped under a wrong assumption
about what it contains.

It also refuses outright when the project's deploy job runs on a **self-hosted
runner and the GitHub repository has become public**. A public repository lets
anyone open a pull request, and a workflow aimed at a self-hosted runner will run
that person's code as this user on the production host. The check reads the
workflows out of `origin/main` (not the shared checkout, which `wt ship` never
updates) and asks `gh` for the repository's visibility; when the lookup itself
fails it says so and lets the deploy through, so being offline never blocks
shipping. `wt status ‹project›` runs the same check without deploying.

## Per-project configuration

Optional, at `‹project›/.claude/worktree.conf`:

```sh
DATA_DIRS="backend/media docs/keywords"   # git-ignored data to bridge into the worktree
DATA_GITIGNORE="docs/seo/.gitignore"      # or take the list from a .gitignore
DEPLOY_WORKFLOW="build-image.yml"         # auto-detected when absent
LOCAL_SYNC=".claude/hooks/sync-local-to-main.sh"   # auto-detected when executable
BASE_BRANCH="main"
```

A worktree holds only **tracked** files, so git-ignored local data (media,
keyword exports, crawl output) is symlinked in from the shared tree and added to
the worktree-local `info/exclude`. Without that exclude the links read as
untracked, the worktree never looks clean, and auto-cleanup never fires.

## Escape hatches

- `wt off <project>` writes `‹project›/.no-worktree`; every guard then leaves that
  project alone. Needed for a local podman run, `.env` work, or manage.py
  commands that depend on untracked files. Turn it back on when done — while it
  is off, sessions collide there again.
- `KEEL_WT_ALLOW_SHARED=1 <command>` allows one deliberate shell write to a
  shared tree.
- `KEEL_WT_DEPLOY_INNER=1 <command>` allows one workflow dispatch outside `wt deploy`.

## Cleanup rules

A worktree is collected only when it is **clean** and either has no commits
beyond `origin/main` or its work has shipped. Anything else is kept, so nothing
is ever lost to housekeeping. Other sessions' worktrees are additionally left
alone until they are untouched for 48h, which avoids racing a live sibling.
Only paths under `~/www/.worktrees/` or a legacy `~/www/.‹slug›-worktrees/` are
ever removed, so worktrees created by other tools elsewhere on disk are safe.

## Tests

`bash selftest.sh` runs the command-inspector regression suite (25 cases). The
guard is only as useful as its false-positive rate, so read-only and
out-of-scope commands are covered as heavily as the writes it must catch.
