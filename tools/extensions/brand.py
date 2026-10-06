#!/usr/bin/env python3
"""The brand profile of the extension repo these tools are working on.

The tools in this folder are shared by every site's extension repo
(~/products/<site>-extensions). They hold no brand: every value that names a
site, a domain, a partner link or a product family is read from the repo's own
brand.json, so two sites build their extensions the same way and neither
build carries a trace of the other.

Each repo's tools/ folder links to these files (relative symlinks), so a
repo's own commands stay `tools/build-chrome.sh <slug>`. The repo is found from
$EXT_ROOT; else from the path the tool was invoked by, when its parent folder
holds a brand.json (tools/<x> inside a repo); else from the nearest folder at
or above the current directory that holds one.

brand.json fields:

  brand              the brand name a user reads ("Example Bots"); the
                     partner-link disclosure names it
  own_hosts          the brand's own hosts. A link to one is never a partner
                     link, and a signal-only build may grant no other host
  gecko_id_domain    a new Firefox listing's add-on id is <slug>@<this>
  logo_file          the popup's logo file, shipped beside popup.html
  families           {family folder: {"title", "about", "derived"}} in display
                     order. "derived": its Firefox and Edge builds come out of
                     the build scripts, so they are audited byte for byte
  family_links       {family: {"name", "url"}}: a partner link every build of
                     that family must carry
  neutral_hosts      extra hosts that are never a partner link (a flag CDN)
  forbidden_traces   strings that must never appear in a shipped file or a
                     store listing: the other brands' names and domains
  trace_exceptions   exact strings exempt from that check: a partner URL whose
                     tracking id happens to contain one (a visitor does not
                     read a tracking id)
  transforms         {"signal_only": "<repo-relative script>"}: the repo's own
                     Edge strip, run when a listing declares signal_only
  mobile_repo        where the brand's Android apps live (VERSIONS.md says so)
  versions_note      a paragraph VERSIONS.md carries under its layout section

Usage: brand.py root | brand.py get <field>
"""
import json
import os
import sys

FILE = "brand.json"


def find_root():
    env = os.environ.get("EXT_ROOT")
    if env:
        root = os.path.abspath(os.path.expanduser(env))
        if not os.path.isfile(os.path.join(root, FILE)):
            sys.exit("EXT_ROOT=%s holds no %s" % (env, FILE))
        return root
    # Invoked as <repo>/tools/<tool>: abspath, not realpath, so the symlink's
    # own folder counts rather than the shared folder it points into.
    invoked = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0] or ".")))
    if os.path.isfile(os.path.join(invoked, FILE)):
        return invoked
    here = os.path.abspath(os.getcwd())
    while True:
        if os.path.isfile(os.path.join(here, FILE)):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            sys.exit("no %s at or above %s: run this from inside an extension repo, "
                     "or set EXT_ROOT" % (FILE, os.getcwd()))
        here = parent


ROOT = find_root()

with open(os.path.join(ROOT, FILE), encoding="utf-8") as _fh:
    PROFILE = json.load(_fh)

BRAND = PROFILE["brand"]
OWN_HOSTS = tuple(PROFILE["own_hosts"])
GECKO_ID_DOMAIN = PROFILE["gecko_id_domain"]
LOGO_FILE = PROFILE["logo_file"]
FAMILIES = PROFILE["families"]
FAMILY_LINKS = {f: (v["name"], v["url"]) for f, v in PROFILE.get("family_links", {}).items()}
NEUTRAL_HOSTS = tuple(PROFILE.get("neutral_hosts", []))
FORBIDDEN_TRACES = tuple(PROFILE.get("forbidden_traces", []))
TRACE_EXCEPTIONS = tuple(PROFILE.get("trace_exceptions", []))
TRANSFORMS = PROFILE.get("transforms", {})
MOBILE_REPO = PROFILE.get("mobile_repo", "")
VERSIONS_NOTE = PROFILE.get("versions_note", "")


def own_host(host):
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in OWN_HOSTS)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["root"]:
        print(ROOT)
    elif len(args) == 2 and args[0] == "get":
        value = PROFILE.get(args[1], "")
        if isinstance(value, (list, dict)):
            value = json.dumps(value)
        print(value)
    else:
        sys.exit(__doc__)
