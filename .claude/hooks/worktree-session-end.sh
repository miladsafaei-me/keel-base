#!/usr/bin/env bash
#
# SessionEnd hook: remove this session's worktree when its work is shipped or it is
# empty. "Shipped" = clean tree + its remote branch was deleted on merge (the
# squash-merge + --delete-branch signal). Worktrees with uncommitted or
# unmerged-committed work are kept so nothing is lost; the SessionStart sweep later
# collects anything that becomes shipped/empty.
#
# REPO derives from this script's own location so a fork needs no path edits.

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SLUG="$(basename "$REPO")"
WT_ROOT="$(dirname "$REPO")/.${SLUG}-worktrees"

input="$(cat)"

sid="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)"
[ -z "$sid" ] && exit 0

short="${sid:0:8}"
wt="$WT_ROOT/$short"
[ -d "$wt" ] || exit 0

# Prune deleted remote branch refs so the shipped signal is current.
timeout 8 git -C "$REPO" fetch --quiet --prune origin 2>/dev/null

# Keep if there is uncommitted work.
[ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ] && exit 0

b="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null)"
ahead="$(git -C "$wt" rev-list --count origin/main..HEAD 2>/dev/null || echo 1)"

remove=0
if [ "$ahead" = "0" ]; then
  remove=1
else
  had_upstream="$(git -C "$wt" config --get "branch.$b.merge" 2>/dev/null)"
  if [ -n "$had_upstream" ] && ! git -C "$wt" rev-parse --verify --quiet "origin/$b" >/dev/null 2>&1; then
    remove=1
  fi
fi

if [ "$remove" = "1" ]; then
  git -C "$REPO" worktree remove --force "$wt" 2>/dev/null \
    && git -C "$REPO" branch -D "$b" 2>/dev/null
fi
exit 0
