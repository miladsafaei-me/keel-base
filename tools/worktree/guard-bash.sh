#!/usr/bin/env bash
# PreToolUse guard for Bash. Two jobs, both about parallel sessions:
#
#  1. Route image-building workflow dispatches through `wt deploy`. Two sessions
#     dispatching at once start two builds that push the same tag; the run that
#     finishes LAST wins even when it carries the older commit. `wt deploy` holds
#     a per-project lock for the whole build.
#
#  2. Block shell commands that WRITE into a project's shared checkout. The
#     Write/Edit guard cannot see those, and auto mode makes Bash the primary
#     editing path, so without this the isolation has a hole wide enough to drive
#     a heredoc through.
#
# Command inspection lives in cmd-inspect.py, which strips heredoc bodies first
# so file content and documentation are never mistaken for the command.
#
# Escape hatches, per command: prefix with KEEL_WT_ALLOW_SHARED=1 (writes) or
# KEEL_WT_DEPLOY_INNER=1 (workflow dispatch).

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

payload="$(cat)"
cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null)"
[ -n "$cmd" ] || exit 0

verdict="$(python3 "$_KEEL_WT_DIR/cmd-inspect.py" "$cmd" 2>/dev/null)"
kind="$(printf '%s' "$verdict" | sed -n 1p)"
[ -n "$kind" ] || exit 0

if [ "$kind" = "DEPLOY" ]; then
  case "$cmd" in *KEEL_WT_DEPLOY_INNER=1*) exit 0 ;; esac
  repo="$(keel_wt_resolve_repo "${CLAUDE_PROJECT_DIR:-$PWD}" 2>/dev/null)"
  proj="${repo:+$(basename "$repo")}"
  cat >&2 <<EOF
Blocked: this dispatches an image build that is not serialized against the other
Claude sessions in this workspace. Two concurrent builds push the same image tag,
and the run that finishes LAST wins even when it carries the older commit.

Use instead:

  wt deploy ${proj:-<project>}

It takes a per-project lock held for the whole build, refuses to deploy while this
session still has unlanded commits, names the sibling sessions whose work is NOT
in the deploy, and watches the run to completion.

For a non-deploy dispatch, or a deliberate override, prefix the command with
KEEL_WT_DEPLOY_INNER=1.
EOF
  exit 2
fi

case "$cmd" in *KEEL_WT_ALLOW_SHARED=1*) exit 0 ;; esac
[ -n "${KEEL_WT_ALLOW_SHARED:-}" ] && exit 0

repo="$(printf '%s' "$verdict" | sed -n 2p)"
target="$(printf '%s' "$verdict" | sed -n 3p)"
[ -n "$repo" ] && [ -n "$target" ] || exit 0

proj="$(basename "$repo")"
sid="$(keel_wt_sid_from_payload "$payload")" || exit 0
wt="$(keel_wt_ensure "$repo" "$sid" nofetch)" || exit 0
[ -n "$wt" ] || exit 0
rel="${target#"$repo"/}"

cat >&2 <<EOF
Blocked: this command writes $rel inside the SHARED checkout of \`$proj\`
($repo).

Parallel Claude sessions all edit that one tree, so the write lands in a sibling
session's \`git add\` and ships inside its commit. This session has its own
isolated worktree of \`$proj\`, fresh from origin/main:

  $wt

Re-run the command against:

  $wt/$rel

and use \`git -C $wt ...\` for git. Ship with \`wt ship $proj\`, deploy with
\`wt deploy $proj\`.

If this session genuinely needs the shared tree (local podman run, .env, other
untracked files), run \`wt off $proj\`. For one deliberate write, prefix the
command with KEEL_WT_ALLOW_SHARED=1.
EOF
exit 2
