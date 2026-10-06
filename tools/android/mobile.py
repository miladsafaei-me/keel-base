"""Find the brand repo and read its brand.json and member.json files. Every Android tool imports this.

A tool finds its repo from $MOBILE_ROOT, else from the tools/ folder it was invoked through (the repo's tools/ links
here), else from the nearest brand.json above the current folder.
"""
import json
import os
import sys


def repo_root():
    env = os.environ.get("MOBILE_ROOT")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    invoked = os.path.dirname(os.path.abspath(sys.argv[0]))
    if os.path.isfile(os.path.join(invoked, "..", "brand.json")):
        return os.path.abspath(os.path.join(invoked, ".."))
    here = os.getcwd()
    while here != "/":
        if os.path.isfile(os.path.join(here, "brand.json")):
            return here
        here = os.path.dirname(here)
    sys.exit("no brand.json found: run from inside a mobile apps repo, or set MOBILE_ROOT")


ROOT = repo_root()


def expand(path):
    return os.path.abspath(os.path.expanduser(path))


def brand():
    with open(os.path.join(ROOT, "brand.json"), encoding="utf-8") as f:
        return json.load(f)


def members():
    """Every member folder: <family>/<slug>/member.json."""
    found = {}
    for family in sorted(os.listdir(ROOT)):
        fdir = os.path.join(ROOT, family)
        if family.startswith(".") or not os.path.isdir(fdir):
            continue
        for slug in sorted(os.listdir(fdir)):
            if os.path.isfile(os.path.join(fdir, slug, "member.json")):
                found[slug] = os.path.join(fdir, slug)
    return found


def member(slug):
    dirs = members()
    if slug not in dirs:
        sys.exit("no member %r here; members: %s" % (slug, ", ".join(dirs) or "none"))
    with open(os.path.join(dirs[slug], "member.json"), encoding="utf-8") as f:
        return json.load(f), dirs[slug]


def flavour(slug):
    """The Gradle flavour name of a slug, as android/app/build.gradle.kts derives it."""
    words = slug.split("-")
    return words[0] + "".join(w[:1].upper() + w[1:] for w in words[1:])


def cap(word):
    return word[:1].upper() + word[1:]
