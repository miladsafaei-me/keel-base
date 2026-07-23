#!/usr/bin/env bash
#
# SessionStart hook: map each Claude session (each editor tab) to its own private
# git worktree, so parallel tabs never collide on the shared working tree. Each
# session edits/commits in an isolated checkout on its own branch; nobody sweeps
# anybody else's uncommitted work into their push.
#
# Output (stdout) is injected into the session as context, instructing the model to
# operate exclusively inside the assigned worktree path.
#
# Escape hatch: create $REPO/.no-worktree to disable isolation for a session that
# needs the full main tree (local podman run, untracked files, .env-dependent
# manage.py commands). Worktrees only contain TRACKED files.
#
# Generalized from SignalBots. REPO derives from this script's own location
# (REPO/.claude/hooks/worktree-session.sh) so a fork needs no path edits. Extra
# git-ignored DATA dirs to bridge into the worktree are listed one-per-line in
# $REPO/.claude/worktree-data-dirs (default: backend/media).

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SLUG="$(basename "$REPO")"
WT_ROOT="$(dirname "$REPO")/.${SLUG}-worktrees"
KILL_SWITCH="$REPO/.no-worktree"

input="$(cat)"

sid="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
if [ -z "$sid" ]; then
  # No session id -> cannot isolate deterministically; stay on main tree silently.
  exit 0
fi

if [ -f "$KILL_SWITCH" ]; then
  exit 0
fi

short="${sid:0:8}"
wt="$WT_ROOT/$short"
branch="wt/$short"

mkdir -p "$WT_ROOT"

# One fetch refreshes the base for new worktrees AND prunes refs of remote branches
# deleted on merge (the shipped-cleanup signal below).
timeout 8 git -C "$REPO" fetch --quiet --prune origin 2>/dev/null

# Returns 0 if the worktree at $1 is safe to garbage-collect: clean tree AND either
# no unique commits, or its commits are shipped (remote branch deleted after a
# squash-merge + --delete-branch). Unmerged committed work is kept.
worktree_is_collectable() {
  local d="$1"
  [ -z "$(git -C "$d" status --porcelain 2>/dev/null)" ] || return 1
  local ahead
  ahead="$(git -C "$d" rev-list --count origin/main..HEAD 2>/dev/null || echo 1)"
  [ "$ahead" = "0" ] && return 0
  local b had_upstream
  b="$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  had_upstream="$(git -C "$d" config --get "branch.$b.merge" 2>/dev/null)"
  if [ -n "$had_upstream" ] && ! git -C "$d" rev-parse --verify --quiet "origin/$b" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# Housekeeping: drop refs for deleted worktrees, and collect other sessions'
# worktrees that are shipped-or-empty and untouched for >48h (covers a SessionEnd
# that did not fire). The age gate avoids racing an active sibling.
git -C "$REPO" worktree prune 2>/dev/null
for d in "$WT_ROOT"/*; do
  [ -d "$d" ] || continue
  [ "$d" = "$wt" ] && continue
  [ -n "$(find "$d" -maxdepth 0 -mmin +2880 2>/dev/null)" ] || continue
  if worktree_is_collectable "$d"; then
    b="$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    git -C "$REPO" worktree remove --force "$d" 2>/dev/null \
      && git -C "$REPO" branch -D "$b" 2>/dev/null
  fi
done

if [ ! -d "$wt" ]; then
  base="$(git -C "$REPO" rev-parse --verify --quiet origin/main \
          || git -C "$REPO" rev-parse --verify --quiet main \
          || git -C "$REPO" rev-parse HEAD)"
  if ! git -C "$REPO" worktree add --quiet -b "$branch" "$wt" "$base" 2>/dev/null; then
    # Branch already exists (resumed/renamed session) -> attach to it.
    if ! git -C "$REPO" worktree add --quiet "$wt" "$branch" 2>/dev/null; then
      echo "[worktree-isolation] could not create a worktree; this session stays on the main tree at $REPO"
      exit 0
    fi
  fi
fi

# Bridge git-ignored local DATA into the worktree so a session never has to leave
# it (and risk reading stale code from the long-lived shared tree) just to reach
# data. These dirs exist only in the shared tree ($REPO); link them in. They are
# git-ignored, so the links stay invisible to git here. Never link a path that
# holds TRACKED files (it would shadow them).
wt_exclude="$(git -C "$wt" rev-parse --git-path info/exclude 2>/dev/null)"
link_data() {
  local src="$REPO/$1" dst="$wt/$1"
  [ -e "$src" ] || return 0
  [ -e "$dst" ] && [ ! -L "$dst" ] && return 0
  mkdir -p "$(dirname "$dst")" 2>/dev/null
  ln -sfn "$src" "$dst" 2>/dev/null || return 0
  # The repo's ignore patterns use trailing slashes (match real dirs, not symlinks),
  # so git would show these links as untracked and keep the worktree permanently
  # "dirty", blocking auto-cleanup. Add the exact path to the worktree-LOCAL exclude.
  if [ -n "$wt_exclude" ] && ! grep -qxF "/$1" "$wt_exclude" 2>/dev/null; then
    echo "/$1" >> "$wt_exclude"
  fi
}
if [ -f "$REPO/.claude/worktree-data-dirs" ]; then
  while IFS= read -r entry; do
    case "$entry" in ''|'#'*) continue ;; esac
    link_data "${entry%/}"
  done < "$REPO/.claude/worktree-data-dirs"
else
  link_data "backend/media"
fi

cat <<EOF
[worktree-isolation ACTIVE]
This session is mapped to its own isolated git worktree so parallel editor tabs
never collide. Operate EXCLUSIVELY inside:

  $wt
  (branch: $branch, based on origin/main)

Hard rules for this session:
- Use ABSOLUTE paths under $wt for every Read / Edit / Write.
- Run EVERY git command as: git -C $wt ...
- Never edit files under $REPO directly (that is the shared tree other tabs use).
- Ship at task end by landing on main directly (accumulate-on-main model, no
  per-task PR): git -C $wt fetch origin main, rebase onto origin/main, then
  git -C $wt push origin HEAD:main. Pushing to main does NOT deploy — changes
  accumulate on main undeployed. Deploy is a separate, BATCHED, user-triggered
  step: only on the word "deploy", run gh workflow run "Build & push web image".
- Once this session's commits are on origin/main, its worktree becomes collectable
  and a later session auto-cleans it.
EOF
exit 0
