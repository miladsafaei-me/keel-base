#!/usr/bin/env python3
"""Audit every packaged build against the store-listing declarations.

The build scripts read the repo's store-listings.json, so a normal rebuild is
correct by construction. This is the check for everything else: a package
built before the declarations existed, one produced by an older script, one
copied by hand, or a declaration edited after the fact and never rebuilt.

Three things have to line up for a listing to be right, and each has been
wrong at least once in this repo:

  store name    what the listing is called. Chrome approved the Quotex and IQ
                real-market bots under their old names; Firefox and Edge did
                not, so those two stores carry new ones.
  in-app name   config.js APP_NAME, the title the app shows its own user. A
                package whose store says one thing and whose window says
                another is a split nobody notices until a customer asks.
  add-on id     Firefox only. AMO keys an update to the id, never to the name,
                so a drifted id opens a SECOND listing instead of updating the
                first.

Exits non-zero on the first mismatch, so it can gate a release.

Usage: check-listings.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from listing import get  # noqa: E402
import layout  # noqa: E402
import brand  # noqa: E402

STORES = ("firefox", "edge")


def chrome_name(slug):
    path = os.path.join(layout.build_dir(slug, "chrome"), "manifest.json")
    if not os.path.exists(path):
        return None
    return json.load(open(path, encoding="utf-8")).get("name")


def app_name(build_dir):
    path = os.path.join(build_dir, "config.js")
    if not os.path.exists(path):
        return None
    m = re.search(r'APP_NAME:\s*"([^"]*)"', open(path, encoding="utf-8").read())
    return m.group(1) if m else None


def main():
    problems = []
    rows = []
    for store in STORES:
        for _family, slug in layout.products():
            build = layout.build_dir(slug, store)
            mpath = os.path.join(build, "manifest.json")
            if not os.path.isfile(mpath):
                continue
            if not os.path.isfile(os.path.join(layout.build_dir(slug, "chrome"), "manifest.json")):
                continue
            m = json.load(open(mpath, encoding="utf-8"))
            want = get(store, slug, "name") or chrome_name(slug)
            got = m.get("name")
            if got != want:
                problems.append("%s/%s: store name is %r, declared %r" % (store, slug, got, want))
            inapp = app_name(build)
            if inapp and inapp != got:
                problems.append("%s/%s: the app calls itself %r but the store says %r"
                                % (store, slug, inapp, got))
            gid = ""
            if store == "firefox":
                want_id = get(store, slug, "id", slug + "@" + brand.GECKO_ID_DOMAIN)
                gid = ((m.get("browser_specific_settings") or {}).get("gecko") or {}).get("id")
                if gid != want_id:
                    problems.append("%s/%s: add-on id is %r, declared %r - a different id opens "
                                    "a second listing" % (store, slug, gid, want_id))
            rows.append((store, slug, got, gid))

    width = max((len(r[1]) for r in rows), default=10)
    for store, slug, name, gid in rows:
        print("%-8s %-*s %-30s %s" % (store, width, slug, name, gid))

    if problems:
        print()
        for p in problems:
            print("MISMATCH: " + p)
        sys.exit(1)
    print("\n%d listings match store-listings.json" % len(rows))


if __name__ == "__main__":
    main()
