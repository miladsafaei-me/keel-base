#!/usr/bin/env bash
# Regression suite for the shell-command inspector behind the Bash guard.
# Every case is a real shape seen in this workspace; the guard is only as good
# as its false-positive rate, so read-only and out-of-scope commands are tested
# as heavily as the writes it must catch.
#
# Usage: bash selftest.sh   (exit 0 = all green)

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
W="/home/milad/www"
pass=0; fail=0

check() {
  local want="$1" desc="$2" cmd="$3" got
  got="$(python3 cmd-inspect.py "$cmd" | sed -n 1p)"
  got="${got:-CLEAN}"
  if [ "$got" = "$want" ]; then
    pass=$((pass+1))
  else
    fail=$((fail+1))
    printf "FAIL  %-52s want=%-6s got=%s\n" "$desc" "$want" "$got"
  fi
}

check WRITE "heredoc write into a shared tree"      "cat > $W/martiland/x.py <<EOF
hi
EOF"
check WRITE "redirect into a shared tree"           "echo hi > $W/revenika/README.md"
check WRITE "append into a shared tree"             "echo hi >> $W/revenika/README.md"
check WRITE "tee into a shared tree"                "echo x | tee $W/keel-cms/README.md"
check WRITE "sed -i on a shared file"               "sed -i s/a/b/ $W/martiland/README.md"
check WRITE "cp destination in a shared tree"       "cp /tmp/a.txt $W/martiland/README.md"
check WRITE "rm inside a shared tree"               "rm -f $W/revenika/README.md"
check WRITE "write reached through a second stmt"   "cd /tmp && echo x > $W/martiland/a.txt"
check WRITE "new file in a shared tree"             "echo x > $W/martiland/brand-new.txt"

check WRITE "quoted decoy does not hide a real write" "echo \"a > b\" > $W/revenika/README.md"

check CLEAN "read-only cat of a shared tree"        "cat $W/revenika/README.md"
check CLEAN "ASCII arrow inside a quoted echo"      "echo \"   -> wt exit 0\""
check CLEAN "ASCII arrow in single quotes"          "echo 'deploy -> done'"
check CLEAN "stderr redirected onto stdout"         "wt deploy revenika 2>&1 | tail -6"
check CLEAN "grep whose pattern looks like a path"  "grep -n s/a/b/ $W/martiland/README.md"
check CLEAN "git command against a shared tree"     "git -C $W/revenika status"
check CLEAN "git worktree remove"                   "git -C $W/revenika worktree remove --force $W/.worktrees/revenika/aaaa1111"
check CLEAN "loop reading every project"            "for p in $W/*/; do git -C \"\$p\" status; done"
check CLEAN "podman bind-mounting a shared tree"    "podman run -v $W/signalbots:/app:z img"
check CLEAN "write into this session worktree"      "echo x > $W/.worktrees/ai-chat-switch/aaaa1111/x.txt"
check CLEAN "write into a legacy worktree root"     "echo x > $W/.sb-worktrees/tgbot/x.txt"
check CLEAN "write outside any project"             "echo x > $W/TODO.md"
check CLEAN "write into a git-ignored data dir"     "echo x > $W/signalbots/backend/media/x.png"
check CLEAN "rm outside, assignment on next line"   "rm -f /tmp/x
b=\$(git -C $W/revenika rev-parse HEAD)
echo \$b"
check CLEAN "heredoc body quoting a blocked write"  "cat > /tmp/doc <<EOF
echo x > $W/revenika/x
EOF"

check DEPLOY "image workflow dispatch"              "cd $W/revenika && gh workflow run build-image.yml"
check DEPLOY "dispatch by workflow name"            "gh workflow run \"Build & push web image\""
check CLEAN  "non-deploy workflow dispatch"         "gh workflow run version-guard.yml"
check CLEAN  "heredoc body quoting a dispatch"      "cat > /tmp/doc <<EOF
gh workflow run build-image.yml
EOF"

printf "\n%d passed, %d failed\n" "$pass" "$fail"
[ "$fail" = "0" ]
