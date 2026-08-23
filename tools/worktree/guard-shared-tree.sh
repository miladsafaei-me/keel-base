#!/usr/bin/env bash
# PreToolUse guard for Write / Edit / MultiEdit / NotebookEdit.
#
# Blocks a write to a project's SHARED checkout while parallel sessions exist,
# and points the session at its own worktree instead (creating it on the spot so
# the denial is actionable). Prompt-level rules are not enough here: one edit in
# the shared tree is enough to fold half-finished work into a sibling session's
# commit and ship it.
#
# Always allowed: paths outside the workspace, paths already inside a worktree,
# git-ignored files (they exist only in the shared tree and are bridged in by
# symlink), and any repo that opted out with .no-worktree.

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

payload="$(cat)"
path="$(printf '%s' "$payload" | jq -r '
  (.tool_input.file_path // .tool_input.notebook_path // .tool_input.path // empty)' 2>/dev/null)"
[ -n "$path" ] || exit 0

repo="$(keel_wt_project_root "$path" 2>/dev/null)" || exit 0
[ -n "$repo" ] || exit 0

proj="$(basename "$repo")"
[ -f "$repo/.no-worktree" ] && exit 0
[ "$(basename "$path")" = ".no-worktree" ] && exit 0
git -C "$repo" check-ignore -q -- "$path" 2>/dev/null && exit 0

sid="$(keel_wt_sid_from_payload "$payload")" || exit 0
wt="$(keel_wt_ensure "$repo" "$sid" nofetch)" || exit 0
[ -n "$wt" ] || exit 0

abs="$(realpath -m -- "$path" 2>/dev/null)"
rel="${abs#"$repo"/}"

cat >&2 <<EOF
Blocked: $rel is in the SHARED checkout of \`$proj\` ($repo).

Parallel Claude sessions all edit that one tree, so a write here lands in a
sibling session's \`git add\` and ships inside its commit. This session has its
own isolated worktree of \`$proj\`, fresh from origin/main:

  $wt

Redo this edit at:

  $wt/$rel

and run every git command as \`git -C $wt ...\`.
Ship with \`wt ship $proj\`; deploy with \`wt deploy $proj\` (locked, so parallel
deploys queue instead of racing).

If this session genuinely needs the shared tree (running the local podman stack,
.env or other untracked files), run \`wt off $proj\` and retry.
EOF
exit 2
