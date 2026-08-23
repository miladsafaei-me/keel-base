#!/usr/bin/env bash
# SessionEnd hook: drop this session's worktrees when their work is shipped or
# they are empty. Anything with uncommitted or unmerged commits is kept; the
# next SessionStart sweep collects it once it becomes shipped-or-empty.

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

payload="$(cat)"
sid="$(keel_wt_sid_from_payload "$payload")" || exit 0

for pdir in "$KEEL_WT_ROOT"/*/; do
  wt="${pdir}$sid"
  [ -d "$wt" ] || continue
  proj="$(basename "${pdir%/}")"
  repo="$KEEL_WT_WORKSPACE/$proj"
  [ -e "$repo/.git" ] || continue
  keel_wt_load_conf "$repo"
  timeout 8 git -C "$repo" fetch --quiet --prune origin 2>/dev/null
  if keel_wt_collectable "$wt"; then
    b="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null)"
    git -C "$repo" worktree remove --force "$wt" 2>/dev/null \
      && git -C "$repo" branch -D "$b" 2>/dev/null
  fi
done
exit 0
