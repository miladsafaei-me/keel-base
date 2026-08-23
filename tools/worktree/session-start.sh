#!/usr/bin/env bash
# SessionStart hook. Two modes, one implementation:
#
#  * repo mode      the session opened inside a project -> create its worktree now
#  * workspace mode the session opened at the workspace root, where the project
#                   is not known yet -> sweep, then instruct the session to call
#                   `wt <project>` before touching any repo. The PreToolUse
#                   guard creates the worktree lazily if the model forgets.
#
# Never blocks a session: any failure degrades to "stay on the shared tree".

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

payload="$(cat)"
sid="$(keel_wt_sid_from_payload "$payload")" || exit 0

# Keep `wt` reachable on PATH without asking the user to install anything.
if [ -d "$HOME/.local/bin" ] && [ ! -e "$HOME/.local/bin/wt" ]; then
  ln -sfn "$_KEEL_WT_DIR/wt" "$HOME/.local/bin/wt" 2>/dev/null
fi

cwd="${CLAUDE_PROJECT_DIR:-$PWD}"
cwd_repo="$(keel_wt_resolve_repo "$cwd" 2>/dev/null)"

# A session opened somewhere else entirely (a dotfiles repo, /tmp, another tree)
# has nothing to isolate here: stay silent rather than explain a workspace it is
# not in. The guards are unaffected; they key off the path being written.
case "$(realpath -m -- "$cwd" 2>/dev/null)" in
  "$KEEL_WT_WORKSPACE"|"$KEEL_WT_WORKSPACE"/*) ;;
  *) exit 0 ;;
esac

# Housekeeping across every project that has session worktrees on disk. No
# fetch here: it stays fast, and skipping it only makes cleanup more cautious.
sweep_all() {
  local repo
  for repo in "$KEEL_WT_WORKSPACE"/*/; do
    repo="${repo%/}"
    [ -e "$repo/.git" ] || continue
    keel_wt_load_conf "$repo"
    keel_wt_sweep "$repo" "$(keel_wt_path "$repo" "$sid")"
  done
}
sweep_all 2>/dev/null

if [ -n "$cwd_repo" ]; then
  if [ -f "$cwd_repo/.no-worktree" ]; then
    echo "[worktree-isolation OFF] $(basename "$cwd_repo") opted out via .no-worktree; this session edits the shared tree. Re-enable with: wt on $(basename "$cwd_repo")"
    exit 0
  fi
  wt="$(keel_wt_ensure "$cwd_repo" "$sid" fetch)"
  if [ -n "$wt" ]; then
    keel_wt_rules "$cwd_repo" "$wt" "$sid"
    exit 0
  fi
  echo "[worktree-isolation] could not create a worktree for $(basename "$cwd_repo"); this session stays on the shared tree at $cwd_repo"
  exit 0
fi

cat <<EOF
[worktree-isolation ACTIVE] workspace mode
Several Claude sessions run against the shared checkouts under $KEEL_WT_WORKSPACE
at the same time. Editing a project's shared tree mixes your work into a sibling
session's commit and breaks its deploy, so every project you touch must be worked
on in this session's own git worktree.

Before the FIRST edit in any project, run:

  wt <project>

It prints this session's isolated worktree path for that project
($KEEL_WT_ROOT/<project>/$sid, branch wt/$sid, fresh from origin/main), creating
it if needed. Do all Read / Edit / Write there with absolute paths, and run git as
\`git -C <that path> ...\`. A PreToolUse guard blocks writes to a project's shared
tree, so an edit that lands there is a mistake, not a shortcut.

  wt ls                 what this session owns, and which siblings hold WIP
  wt ship <project>     rebase onto origin/main, push to main, sync local preview
  wt deploy <project>   locked deploy; parallel sessions queue instead of racing
  wt off <project>      opt one project out (local podman run, .env, untracked)

Pushing to main does NOT deploy: work accumulates on main until you say "deploy".
Files outside a project repo (workspace-level docs, ~/.claude, /tmp) are unaffected.
EOF
exit 0
