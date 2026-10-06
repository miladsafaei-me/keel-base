#!/usr/bin/env python3
"""Name the model for a new extension: the family's most recently built member.

A new extension is built from the latest one before it, never from a fixed
reference, because every member teaches the family something (a layout rule, a
store-policy fix, a licence edge case) and the newest carries all of it. The
newest is the member whose Chrome build was created last in git; a tie (one
commit that added several) goes to the one changed last. A build not yet
committed counts by its file time. Its current version is the model.

With --all-repos it also looks in every sibling extension repo (each folder of
~/products that holds a brand.json). Use that only when this repo has no member
of the family yet: the model's code is then taken from another brand, so every
brand string in it is rewritten and check-brand.py must pass before packaging.

Usage: newest-member.py <family> [--all-repos] [--list]
Prints: <repo root>  <family>/<slug>  <version>  created <date>
"""
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402

PRODUCTS = os.path.expanduser("~/products")


def _git_times(root, rel, *flags):
    out = subprocess.run(["git", "-C", root, "log", "--format=%ct"] + list(flags) + ["--", rel],
                         capture_output=True, text=True).stdout.split()
    return [int(t) for t in out]


def dates(root, manifest):
    """(created, changed) of a Chrome build, from git, else from the file."""
    rel = os.path.relpath(manifest, root)
    mtime = int(os.path.getmtime(manifest))
    # The popup is each member's own code, so following it through the repo's
    # folder moves finds when the member was born; manifests look too alike
    # for git's rename detection to follow reliably.
    popup = os.path.join(os.path.dirname(rel), "popup.js")
    created = _git_times(root, popup, "--follow", "--diff-filter=A") \
        or _git_times(root, rel, "--follow", "--diff-filter=A")
    if not created:
        return mtime, mtime
    dirty = subprocess.run(["git", "-C", root, "status", "--porcelain", "--", rel],
                           capture_output=True, text=True).stdout.strip()
    changed = mtime if dirty else _git_times(root, rel, "-1")[0]
    return created[-1], changed


def members(root, family):
    base = os.path.join(root, family)
    if not os.path.isdir(base):
        return []
    out = []
    for slug in sorted(os.listdir(base)):
        manifest = os.path.join(base, slug, "chrome", "manifest.json")
        if os.path.isfile(manifest):
            version = json.load(open(manifest, encoding="utf-8")).get("version", "?")
            out.append((dates(root, manifest), root, "%s/%s" % (family, slug), version))
    return out


def repos(all_repos):
    roots = [brand.ROOT]
    if all_repos and os.path.isdir(PRODUCTS):
        for d in sorted(os.listdir(PRODUCTS)):
            root = os.path.join(PRODUCTS, d)
            if os.path.isfile(os.path.join(root, "brand.json")) and os.path.abspath(root) != brand.ROOT:
                roots.append(root)
    return roots


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    found = []
    for root in repos("--all-repos" in argv):
        found += members(root, args[0])
    if not found:
        sys.exit("no member of %s in %s" % (args[0], ", ".join(repos("--all-repos" in argv))))
    found.sort(reverse=True)
    for (created, _changed), root, path, version in (found if "--list" in argv else found[:1]):
        day = datetime.datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M")
        print("%s  %s  %s  created %s" % (root, path, version, day))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
