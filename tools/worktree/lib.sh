#!/usr/bin/env bash
# Shared helpers for per-session git worktree isolation across the whole
# workspace that holds every project (the parent of this keel-base checkout).
#
# Sourced by the SessionStart / SessionEnd / PreToolUse hooks and by the `wt`
# CLI so every entry point agrees on paths, per-project config and cleanup.
#
# Layout: <workspace>/.worktrees/<project>/<session-id-8>  on branch wt/<id-8>.
# Legacy per-project roots (<workspace>/.<slug>-worktrees) keep working and are
# still swept; only new worktrees use the unified root.

_KEEL_WT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEEL_WT_WORKSPACE="${KEEL_WT_WORKSPACE:-$(cd "$_KEEL_WT_DIR/../../.." && pwd)}"
KEEL_WT_ROOT="$KEEL_WT_WORKSPACE/.worktrees"
KEEL_WT_LOCKS="${TMPDIR:-/tmp}/keel-worktree-$(id -u 2>/dev/null || echo 0)"
mkdir -p "$KEEL_WT_LOCKS" 2>/dev/null

# Eight hex chars of the Claude session id: short enough for a folder name,
# wide enough that two live tabs never collide.
keel_wt_sid() {
  local raw="${1:-${CLAUDE_CODE_SESSION_ID:-}}"
  [ -n "$raw" ] || return 1
  printf '%s' "${raw:0:8}"
}

# Pull .session_id out of a hook's stdin payload, falling back to the env var
# Claude Code exports into every Bash call.
keel_wt_sid_from_payload() {
  local payload="$1" sid=""
  if command -v jq >/dev/null 2>&1; then
    sid="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)"
  fi
  [ -n "$sid" ] || sid="${CLAUDE_CODE_SESSION_ID:-}"
  [ -n "$sid" ] || return 1
  printf '%s' "${sid:0:8}"
}

# Repo root of the top-level project that owns an absolute path, or nothing.
# A path inside .worktrees/ or a legacy .<slug>-worktrees/ resolves to nothing
# on purpose: those are already isolated checkouts, never the shared tree.
keel_wt_project_root() {
  local p rest top
  p="$(realpath -m -- "${1:-}" 2>/dev/null)" || return 1
  case "$p" in
    "$KEEL_WT_WORKSPACE"/*) ;;
    *) return 1 ;;
  esac
  rest="${p#"$KEEL_WT_WORKSPACE"/}"
  top="${rest%%/*}"
  [ -n "$top" ] || return 1
  [ -e "$KEEL_WT_WORKSPACE/$top/.git" ] || return 1
  printf '%s' "$KEEL_WT_WORKSPACE/$top"
}

# Accepts a project name, a repo path or any path inside a repo.
keel_wt_resolve_repo() {
  local arg="${1:-}"
  [ -n "$arg" ] || return 1
  if [ -e "$KEEL_WT_WORKSPACE/$arg/.git" ]; then
    printf '%s' "$KEEL_WT_WORKSPACE/$arg"; return 0
  fi
  keel_wt_project_root "$arg"
}

# Per-project knobs, all optional, in <repo>/.claude/worktree.conf:
#   DATA_DIRS         space/newline separated git-ignored dirs to bridge in
#   DATA_GITIGNORE    a .gitignore whose entries become DATA_DIRS (relative to it)
#   DEPLOY_WORKFLOW   GitHub Actions workflow file or name for `wt deploy`
#   LOCAL_SYNC        repo-relative script run after a successful ship
#   BASE_BRANCH       defaults to main
keel_wt_load_conf() {
  local repo="$1"
  DATA_DIRS="backend/media"
  DATA_GITIGNORE=""
  DEPLOY_WORKFLOW=""
  LOCAL_SYNC=""
  BASE_BRANCH="main"
  if [ -f "$repo/.claude/worktree.conf" ]; then
    . "$repo/.claude/worktree.conf"
  fi
  if [ -f "$repo/.claude/worktree-data-dirs" ]; then
    local entry
    while IFS= read -r entry; do
      case "$entry" in ''|'#'*) continue ;; esac
      DATA_DIRS="$DATA_DIRS ${entry%/}"
    done < "$repo/.claude/worktree-data-dirs"
  fi
  if [ -z "$DEPLOY_WORKFLOW" ] && [ -f "$repo/.github/workflows/build-image.yml" ]; then
    DEPLOY_WORKFLOW="build-image.yml"
  fi
  if [ -z "$LOCAL_SYNC" ] && [ -x "$repo/.claude/hooks/sync-local-to-main.sh" ]; then
    LOCAL_SYNC=".claude/hooks/sync-local-to-main.sh"
  fi
}

keel_wt_path() {
  printf '%s/%s/%s' "$KEEL_WT_ROOT" "$(basename "$1")" "$2"
}

# Symlink a git-ignored data dir from the shared tree into the worktree, then
# add it to the worktree-LOCAL exclude. Without that exclude the symlink shows
# as untracked, the worktree never reads clean, and auto-cleanup never fires.
_keel_wt_link_data() {
  local repo="$1" wt="$2" rel="$3" wt_exclude="$4"
  local src="$repo/$rel" dst="$wt/$rel"
  [ -e "$src" ] || return 0
  [ -e "$dst" ] && [ ! -L "$dst" ] && return 0
  mkdir -p "$(dirname "$dst")" 2>/dev/null
  ln -sfn "$src" "$dst" 2>/dev/null || return 0
  if [ -n "$wt_exclude" ] && ! grep -qxF "/$rel" "$wt_exclude" 2>/dev/null; then
    echo "/$rel" >> "$wt_exclude"
  fi
}

keel_wt_bridge_data() {
  local repo="$1" wt="$2" wt_exclude rel base entry
  wt_exclude="$(git -C "$wt" rev-parse --git-path info/exclude 2>/dev/null)"
  for rel in $DATA_DIRS; do
    _keel_wt_link_data "$repo" "$wt" "${rel%/}" "$wt_exclude"
  done
  if [ -n "$DATA_GITIGNORE" ] && [ -f "$repo/$DATA_GITIGNORE" ]; then
    base="$(dirname "$DATA_GITIGNORE")"
    [ "$base" = "." ] && base=""
    while IFS= read -r entry; do
      case "$entry" in ''|'#'*|'!'*|*'*'*) continue ;; esac
      entry="${entry%/}"
      entry="${entry#/}"
      [ -n "$entry" ] || continue
      if [ -n "$base" ]; then
        _keel_wt_link_data "$repo" "$wt" "$base/$entry" "$wt_exclude"
      else
        _keel_wt_link_data "$repo" "$wt" "$entry" "$wt_exclude"
      fi
    done < "$repo/$DATA_GITIGNORE"
  fi
}

# 0 = safe to garbage-collect: clean tree AND either no unique commits, or its
# commits shipped (upstream branch deleted after merge). Unmerged work is kept.
keel_wt_collectable() {
  local d="$1" ahead b had_upstream
  [ -z "$(git -C "$d" status --porcelain 2>/dev/null)" ] || return 1
  ahead="$(git -C "$d" rev-list --count "origin/${BASE_BRANCH:-main}..HEAD" 2>/dev/null || echo 1)"
  [ "$ahead" = "0" ] && return 0
  b="$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  had_upstream="$(git -C "$d" config --get "branch.$b.merge" 2>/dev/null)"
  if [ -n "$had_upstream" ] && ! git -C "$d" rev-parse --verify --quiet "origin/$b" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# Every worktree of a repo except its main checkout.
keel_wt_list_secondary() {
  git -C "$1" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree /{print substr($0,10)}' | tail -n +2
}

# Collect other sessions' worktrees that are shipped-or-empty and untouched for
# more than $KEEL_WT_MAX_AGE_MIN (default 48h). The age gate avoids racing a
# live sibling; only paths we own are ever touched, so an editor's or another
# agent's worktree elsewhere on disk is never removed.
keel_wt_sweep() {
  local repo="$1" keep="${2:-}" d b age="${KEEL_WT_MAX_AGE_MIN:-2880}"
  git -C "$repo" worktree prune 2>/dev/null
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    [ "$d" = "$keep" ] && continue
    case "$d" in
      "$KEEL_WT_ROOT"/*) ;;
      "$KEEL_WT_WORKSPACE"/.*-worktrees/*) ;;
      *) continue ;;
    esac
    [ -d "$d" ] || continue
    [ -n "$(find "$d" -maxdepth 0 -mmin "+$age" 2>/dev/null)" ] || continue
    if keel_wt_collectable "$d"; then
      b="$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null)"
      git -C "$repo" worktree remove --force "$d" 2>/dev/null \
        && git -C "$repo" branch -D "$b" 2>/dev/null
    fi
  done < <(keel_wt_list_secondary "$repo")
}

# Create (or reuse) this session's worktree for one repo and print its path.
# Return 3 when the repo opted out via .no-worktree, 1 on failure.
keel_wt_ensure() {
  local repo="$1" sid="$2" mode="${3:-fetch}" wt branch base lock
  [ -n "$repo" ] && [ -n "$sid" ] || return 1
  [ -f "$repo/.no-worktree" ] && return 3
  git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 1
  keel_wt_load_conf "$repo"
  wt="$(keel_wt_path "$repo" "$sid")"
  branch="wt/$sid"
  if [ -d "$wt" ]; then printf '%s' "$wt"; return 0; fi

  lock="$KEEL_WT_LOCKS/create-$(basename "$repo").lock"
  exec 8>"$lock"
  flock -w 30 8 2>/dev/null
  if [ -d "$wt" ]; then exec 8>&-; printf '%s' "$wt"; return 0; fi

  mkdir -p "$(dirname "$wt")" 2>/dev/null
  [ "$mode" = "fetch" ] && timeout 8 git -C "$repo" fetch --quiet --prune origin 2>/dev/null
  base="$(git -C "$repo" rev-parse --verify --quiet "origin/$BASE_BRANCH" \
          || git -C "$repo" rev-parse --verify --quiet "$BASE_BRANCH" \
          || git -C "$repo" rev-parse HEAD)"
  if ! git -C "$repo" worktree add --quiet -b "$branch" "$wt" "$base" 2>/dev/null; then
    # Branch already exists (resumed session) -> attach the worktree to it.
    if ! git -C "$repo" worktree add --quiet "$wt" "$branch" 2>/dev/null; then
      exec 8>&-
      return 1
    fi
  fi
  exec 8>&-
  keel_wt_bridge_data "$repo" "$wt"
  printf '%s' "$wt"
  return 0
}

# The instruction block injected into a session once it has a worktree.
keel_wt_rules() {
  local repo="$1" wt="$2" sid="$3" proj
  proj="$(basename "$repo")"
  cat <<EOF
[worktree-isolation ACTIVE] $proj
This session owns an isolated checkout of \`$proj\`; parallel Claude tabs share
the tree at $repo, so editing there mixes your work into theirs.

  worktree: $wt
  branch:   wt/$sid   (based on origin/${BASE_BRANCH:-main})

- Read / Edit / Write only under $wt (absolute paths).
- Every git command: git -C $wt ...
- Never edit $repo directly; a PreToolUse guard blocks it.
- Ship (rebase onto origin/main, push to main, sync local): wt ship $proj
- Deploy (locked, one at a time across sessions):           wt deploy $proj
- Need the shared tree (local podman run, .env, untracked): wt off $proj
EOF
}
