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
# A word that only reads as a file command when it IS the command: `pip install x`
# and `podman rm web` name a subcommand, not coreutils install or rm. git stays out
# of this set on purpose, because `git rm` and `git mv` do touch the tree.
SUBCOMMAND_HOSTS = {"pip", "pip3", "pipx", "uv", "poetry", "conda", "npm", "pnpm",
                    "yarn", "apt", "apt-get", "dnf", "yum", "brew", "cargo", "gem",
                    "go", "flatpak", "snap", "podman", "docker", "helm", "gh",
                    "systemctl", "make"}
# A redirect split at its `&` (`2>&1` becomes `... 2>` and `1`) leaves a
# fragment like `2>` that is never a filename.
REDIRECT_FRAGMENT = re.compile(r"^[0-9]*[<>]")
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


def project_root(path, base):
    """Repo root of the project owning a path, else None.

    A project is a repo directly under the workspace, or one level down inside
    a plain folder that is not a repo itself (lib.sh keel_wt_project_root).
    """
    p = os.path.realpath(os.path.join(base, os.path.expanduser(path)))
    if not p.startswith(WORKSPACE + os.sep):
        return None
    parts = p[len(WORKSPACE) + 1:].split(os.sep)
    top = parts[0]
    if not top or top.startswith("."):
        return None
    root = os.path.join(WORKSPACE, top)
    if os.path.exists(os.path.join(root, ".git")):
        return root
    if len(parts) < 2 or not parts[1]:
        return None
    nested = os.path.join(root, parts[1])
    if os.path.exists(os.path.join(nested, ".git")):
        return nested
    return None


def looks_like_path(candidate, base):
    """Filter out arguments that merely resemble a path (a sed script, a regex).

    A real target is absolute, already exists, or at least has an existing parent
    directory; nothing else can be written to without mkdir -p first.
    """
    if any(ch in candidate for ch in SHELL_META):
        return False
    if candidate.startswith(("/", "~")):
        return True
    resolved = os.path.join(base, candidate)
    return os.path.exists(resolved) or os.path.isdir(os.path.dirname(resolved))


def guarded(path, base):
    if not looks_like_path(path, base):
        return None
    root = project_root(path, base)
    if root is None:
        return None
    if os.path.exists(os.path.join(root, ".no-worktree")):
        return None
    if os.path.basename(path) == ".no-worktree":
        return None
    abs_path = os.path.realpath(os.path.join(base, os.path.expanduser(path)))
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


ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
STATEMENT_SEP = re.compile(r"\n|;|&&|\|\||\||&")


def expand(value, env):
    """Expand $NAME and ${NAME} from variables set earlier in the command.

    Returns None when anything is left that only the shell could resolve
    (an unknown variable, a command substitution).
    """
    value = VAR_REF.sub(lambda m: env.get(m.group(1) or m.group(2), "\0"), value)
    if "\0" in value or "$" in value or "`" in value:
        return None
    return os.path.expanduser(value)


def resolve_dir(arg, cwd, env):
    """The directory `cd arg` lands in, or None when it cannot be known."""
    target = expand(arg, env)
    if target is None:
        return None
    if os.path.isabs(target):
        return os.path.normpath(target)
    if cwd is None:
        return None
    return os.path.normpath(os.path.join(cwd, target))


def statements(command):
    """Each statement as (raw text, quote-masked text), split outside quotes."""
    masked = mask_quoted(command)
    if len(masked) != len(command):
        masked = command
    start = 0
    for m in STATEMENT_SEP.finditer(masked):
        yield command[start:m.start()], masked[start:m.start()]
        start = m.end()
    yield command[start:], masked[start:]


def write_targets(command):
    """Every path the command would write to, with the directory it resolves in.

    Best effort, as (target, base) pairs. The command is walked statement by
    statement: shlex drops newlines, so a single token list runs a `rm` argument
    scan straight through into the next line and turns whatever follows into a
    filename. The walk follows `cd` and `NAME=value` assignments, so a relative
    write after `cd <worktree>` resolves inside the worktree instead of the
    session's start folder. When a directory cannot be known (an unknown
    variable, a command substitution) the base falls back to the session's
    folder, which keeps the guard on the strict side.
    """
    out, env = [], {}
    start_dir = os.getcwd()
    cwd = start_dir
    for raw, masked in statements(command):
        statement = raw.strip()
        if not statement:
            continue
        try:
            words = shlex.split(statement, comments=False)
        except ValueError:
            words = statement.split()
        base = cwd or start_dir

        if words and all(ASSIGNMENT.match(w) for w in words):
            for w in words:
                name, value = ASSIGNMENT.match(w).groups()
                expanded = expand(value, env)
                if expanded is None:
                    env.pop(name, None)
                else:
                    env[name] = expanded
            continue
        if words and words[0] == "cd":
            cwd = resolve_dir(words[1] if len(words) > 1 else "~", cwd, env)
            continue
        if len(words) > 2 and words[0] == "git" and words[1] == "-C":
            base = resolve_dir(words[2], cwd, env) or start_dir

        for m in re.finditer(r"(?<![0-9<>])>>?\s*([^\s;|&()<>]+)", masked):
            out.append((m.group(1), base))

        opt_writer = any(os.path.basename(w) in OPT_WRITERS for w in words)
        for i, tok in enumerate(words):
            base_name = os.path.basename(tok)
            if i and os.path.basename(words[i - 1]) in SUBCOMMAND_HOSTS:
                continue
            own = words[i + 1:]
            bare = [w for w in own if not w.startswith("-")]
            if base_name == "tee":
                out.extend((w, base) for w in bare)
            elif base_name == "sed" and any(w.startswith("-i") for w in own[:3]):
                # The first bare argument is the sed script, not a file, unless
                # the script came in through -e/-f.
                scripted = any(w.startswith(("-e", "-f")) for w in own)
                out.extend((w, base) for w in (bare if scripted else bare[1:]))
            elif base_name in WRITE_FIRST:
                out.extend((w, base) for w in bare)
            elif base_name in DEST_LAST:
                if len(bare) >= 2:
                    out.append((bare[-1], base))
            elif tok in WRITE_OPTS and own and opt_writer:
                out.append((own[0], base))
    return out


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    command = strip_heredocs(raw)

    if DISPATCH.search(command) and IMAGE_WF.search(command):
        print("DEPLOY")
        return 0

    for target, base in write_targets(command):
        target = target.strip("\"'")
        if not target or target.startswith("-") or REDIRECT_FRAGMENT.match(target):
            continue
        hit = guarded(target, base)
        if hit:
            print("WRITE")
            print(hit[0])
            print(hit[1])
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
