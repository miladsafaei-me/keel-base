#!/usr/bin/env bash
# Housekeeping across every project in the workspace, for the timer to run.
#
# The same sweep runs at SessionStart, but only while somebody has a session
# open, and only against whatever origin/<base> each repo happened to have
# fetched last. A timer removes both conditions: it fetches first, so "already
# merged" is measured against what is really on the remote, and it runs on a
# laptop nobody has opened Claude on all week.
#
# Nothing here can remove unshipped work. A worktree is collected under the
# rules in README.md; a wt/* branch goes only when origin/<base> contains every
# commit on it. A failed fetch makes both tests stricter, never looser.
#
# Usage: bash sweep-all.sh [--quiet]

set -u
. "$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)/lib.sh"

quiet=0
[ "${1:-}" = "--quiet" ] && quiet=1

# Every session Claude Code currently has open. Their worktrees are in use, so
# they are protected regardless of age; the 48h guard alone would not do it,
# because a session can outlive two days easily.
live_sids() {
  local f sid
  for f in "$HOME"/.claude/sessions/*.json; do
    [ -f "$f" ] || continue
    sid="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("sessionId",""))' "$f" 2>/dev/null)"
    [ -n "$sid" ] || continue
    kill -0 "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("pid",0))' "$f" 2>/dev/null)" 2>/dev/null \
      && printf '%s ' "$sid" "${sid%%-*}"
  done
}
KEEL_WT_KEEP="$(live_sids)"
export KEEL_WT_KEEP

branches() { git -C "$1" for-each-ref --format='x' 'refs/heads/wt/*' 2>/dev/null | wc -l; }
trees()    { keel_wt_list_secondary "$1" | grep -c . ; }

total_b=0 total_t=0
for repo in "$KEEL_WT_WORKSPACE"/*/; do
  repo="${repo%/}"
  [ -e "$repo/.git" ] || continue
  keel_wt_load_conf "$repo"
  timeout 30 git -C "$repo" fetch --quiet --prune origin 2>/dev/null
  b0="$(branches "$repo")"; t0="$(trees "$repo")"
  keel_wt_sweep "$repo" "" 2>/dev/null
  b1="$(branches "$repo")"; t1="$(trees "$repo")"
  db=$((b0 - b1)); dt=$((t0 - t1))
  total_b=$((total_b + db)); total_t=$((total_t + dt))
  if [ "$quiet" = 0 ] || [ $((db + dt)) -gt 0 ]; then
    printf '%-24s branches %3d -> %-3d (-%d)   worktrees %2d -> %-2d (-%d)\n' \
      "$(basename "$repo")" "$b0" "$b1" "$db" "$t0" "$t1" "$dt"
  fi
done
echo "swept $total_b landed wt/* branches and $total_t collected worktrees"
