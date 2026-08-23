#!/usr/bin/env bash
# Wire worktree isolation into Claude Code for this machine, globally: one set of
# hooks in ~/.claude covers every project in the workspace, so no project needs
# its own copy. Idempotent; merges into settings.json and never replaces it.
#
# Usage: bash install.sh

set -eu
IMPL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
mkdir -p "$CLAUDE_DIR/hooks"

declare -A STUBS=(
  [keel-worktree-session-start]=session-start.sh
  [keel-worktree-session-end]=session-end.sh
  [keel-worktree-guard]=guard-shared-tree.sh
  [keel-deploy-guard]=guard-bash.sh
)

for name in "${!STUBS[@]}"; do
  cat > "$CLAUDE_DIR/hooks/$name.sh" <<EOF
#!/usr/bin/env bash
# Stub for the shared worktree-isolation implementation in keel-base. Kept here
# so settings.json can reference a stable path; if keel-base is not cloned on
# this machine the hook silently does nothing.
IMPL="$IMPL_DIR/${STUBS[$name]}"
if [ ! -r "\$IMPL" ]; then cat >/dev/null; exit 0; fi
exec bash "\$IMPL"
EOF
  chmod +x "$CLAUDE_DIR/hooks/$name.sh"
done

mkdir -p "$HOME/.local/bin"
ln -sfn "$IMPL_DIR/wt" "$HOME/.local/bin/wt"

CLAUDE_DIR="$CLAUDE_DIR" python3 - <<'PY'
import collections, json, os

path = os.path.join(os.environ["CLAUDE_DIR"], "settings.json")
data = json.load(open(path), object_pairs_hook=collections.OrderedDict) if os.path.exists(path) else collections.OrderedDict()
hooks = data.setdefault("hooks", collections.OrderedDict())

def present(event, needle):
    return any(needle in h.get("command", "")
               for group in hooks.get(event, []) for h in group.get("hooks", []))

def command(stub, timeout):
    return collections.OrderedDict([
        ("type", "command"),
        ("command", f"bash {os.environ['CLAUDE_DIR']}/hooks/{stub}.sh"),
        ("timeout", timeout),
    ])

added = []
if not present("SessionStart", "keel-worktree-session-start"):
    hooks.setdefault("SessionStart", []).append(collections.OrderedDict([
        ("matcher", "startup|resume|clear"),
        ("hooks", [command("keel-worktree-session-start", 25)]),
    ]))
    added.append("SessionStart")
if not present("SessionEnd", "keel-worktree-session-end"):
    hooks.setdefault("SessionEnd", []).append(collections.OrderedDict([
        ("hooks", [command("keel-worktree-session-end", 25)]),
    ]))
    added.append("SessionEnd")
pre = hooks.setdefault("PreToolUse", [])
if not present("PreToolUse", "keel-worktree-guard"):
    pre.insert(0, collections.OrderedDict([
        ("matcher", "Write|Edit|MultiEdit|NotebookEdit"),
        ("hooks", [command("keel-worktree-guard", 25)]),
    ]))
    added.append("PreToolUse/write")
if not present("PreToolUse", "keel-deploy-guard"):
    pre.insert(1, collections.OrderedDict([
        ("matcher", "Bash"),
        ("hooks", [command("keel-deploy-guard", 15)]),
    ]))
    added.append("PreToolUse/bash")

json.dump(data, open(path, "w"), indent=2, ensure_ascii=False)
open(path, "a").write("\n")
print("settings.json:", ", ".join(added) if added else "already wired")
PY

echo "hooks installed in $CLAUDE_DIR/hooks; wt on PATH at $HOME/.local/bin/wt"
echo "Open a new session for the hooks to take effect."
