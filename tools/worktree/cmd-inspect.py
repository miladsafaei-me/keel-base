#!/usr/bin/env python3
"""Inspect one shell command for the two things parallel sessions collide on.

Reports, on stdout:
  DEPLOY                      the command dispatches an image-building workflow
  WRITE\n<repo>\n<abs path>   the command writes into a project's SHARED checkout

Nothing (exit 0) otherwise. Heredoc bodies are stripped first: a hook that greps
the raw command string mistakes documentation and file content for the command
itself, which is how the first version of this guard blocked its own author.

Deliberately narrow: only constructs that actually create or modify a file are
inspected, so read-only commands are never touched.
"""
import os
import re
import shlex
import subprocess
import sys

WORKSPACE = os.environ.get("KEEL_WT_WORKSPACE", "/home/milad/www")
WRITE_OPTS = {"-o", "--output", "-O"}
# -o is an output FILE for a handful of commands and an output FORMAT for many
# more: journalctl -o cat, podman ps -o json, kubectl get -o yaml, ps -o pid.
# Honouring it for every command turned each of those into a write to a file
# named after the format, which is how `journalctl -o cat` got blocked. So the
# option is read only when the statement actually runs a command that writes
# with it -- an allowlist, in keeping with how narrow the rest of this is.
OPT_WRITERS = {"curl", "wget", "ffmpeg", "gcc", "g++", "cc", "clang", "clang++",
               "ld", "sort", "pandoc", "yt-dlp", "youtube-dl", "convert",
               "magick", "wkhtmltopdf", "wkhtmltoimage", "objcopy", "go", "dot",
               "zip"}
DEST_LAST = {"cp", "mv", "install", "rsync"}
WRITE_FIRST = {"touch", "truncate", "unlink", "rm", "mkdir", "rmdir", "ln", "patch", "dd"}
SHELL_META = ("$", "`", "(", ")", "=", "*", "?", "{", "}")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
DISPATCH = re.compile(r"\bgh\s+workflow\s+run\b")
IMAGE_WF = re.compile(r"build-image|build-ingest-image|Build & push", re.I)


def strip_heredocs(command):
    """Drop every heredoc body, keeping the command lines that surround it."""
    lines = command.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        markers = [m.group(2) for m in HEREDOC.finditer(line)]
        out.append(HEREDOC.sub("", line))
        i += 1
        for marker in markers:
            while i < len(lines) and lines[i].strip() != marker:
                i += 1
            i += 1
    return "\n".join(out)


def project_root(path):
    """Repo root of the top-level project owning a path, else None."""
    p = os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(path)))
    if not p.startswith(WORKSPACE + os.sep):
        return None
    top = p[len(WORKSPACE) + 1:].split(os.sep)[0]
    root = os.path.join(WORKSPACE, top)
    if not top or not os.path.exists(os.path.join(root, ".git")):
        return None
    return root


def looks_like_path(candidate):
    """Filter out arguments that merely resemble a path (a sed script, a regex).

    A real target is absolute, already exists, or at least has an existing parent
    directory; nothing else can be written to without mkdir -p first.
    """
    if any(ch in candidate for ch in SHELL_META):
        return False
    if candidate.startswith(("/", "~")):
        return True
    resolved = os.path.join(os.getcwd(), candidate)
    return os.path.exists(resolved) or os.path.isdir(os.path.dirname(resolved))


def guarded(path):
    if not looks_like_path(path):
        return None
    root = project_root(path)
    if root is None:
        return None
    if os.path.exists(os.path.join(root, ".no-worktree")):
        return None
    if os.path.basename(path) == ".no-worktree":
        return None
    abs_path = os.path.realpath(os.path.join(os.getcwd(), os.path.expanduser(path)))
    if subprocess.run(["git", "-C", root, "check-ignore", "-q", "--", abs_path],
                      capture_output=True).returncode == 0:
        return None
    return root, abs_path


def mask_quoted(command):
    """Blank the inside of quoted spans, preserving length and newlines.

    The redirect scan below is a regex over the raw command, so any `>` inside a
    string literal reads as a redirection: `echo "step -> done"` was blocked as a
    write to a file named `done`. A redirect operator is never inside quotes, so
    masking the literals first removes that whole class of false positive. If the
    command ends inside an unterminated quote the masking cannot be trusted, so
    the original string is returned and the guard stays on the strict side.
    """
    out, quote, i, n = [], None, 0, len(command)
    while i < n:
        c = command[i]
        if quote is None:
            if c in "'\"":
                quote = c
                out.append(c)
                i += 1
                continue
            if c == "\\" and i + 1 < n:
                out.append(c); out.append(command[i + 1]); i += 2
                continue
            out.append(c); i += 1
        else:
            if c == quote:
                quote = None; out.append(c); i += 1
                continue
            if quote == '"' and c == "\\" and i + 1 < n:
                out.append(" "); out.append(" " if command[i + 1] != "\n" else "\n"); i += 2
                continue
            out.append("\n" if c == "\n" else " "); i += 1
    if quote is not None:
        return command
    return "".join(out)


def write_targets(command):
    """Every path the command would write to, best effort.

    The command is split into statements first: shlex drops newlines, so a single
    token list runs a `rm` argument scan straight through into the next line and
    turns whatever follows into a filename.
    """
    out = []
    for m in re.finditer(r"(?<![0-9<>])>>?\s*([^\s;|&()<>]+)", mask_quoted(command)):
        out.append(m.group(1))

    for statement in re.split(r"\n|;|&&|\|\||\||&", command):
        statement = statement.strip()
        if not statement:
            continue
        try:
            words = shlex.split(statement, comments=False)
        except ValueError:
            words = statement.split()
        opt_writer = any(os.path.basename(w) in OPT_WRITERS for w in words)
        for i, tok in enumerate(words):
            base = os.path.basename(tok)
            own = words[i + 1:]
            bare = [w for w in own if not w.startswith("-")]
            if base == "tee":
                out.extend(bare)
            elif base == "sed" and any(w.startswith("-i") for w in own[:3]):
                # The first bare argument is the sed script, not a file, unless
                # the script came in through -e/-f.
                scripted = any(w.startswith(("-e", "-f")) for w in own)
                out.extend(bare if scripted else bare[1:])
            elif base in WRITE_FIRST:
                out.extend(bare)
            elif base in DEST_LAST:
                if len(bare) >= 2:
                    out.append(bare[-1])
            elif tok in WRITE_OPTS and own and opt_writer:
                out.append(own[0])
    return out


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    command = strip_heredocs(raw)

    if DISPATCH.search(command) and IMAGE_WF.search(command):
        print("DEPLOY")
        return 0

    for target in write_targets(command):
        target = target.strip("\"'")
        if not target or target.startswith("-"):
            continue
        hit = guarded(target)
        if hit:
            print("WRITE")
            print(hit[0])
            print(hit[1])
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
