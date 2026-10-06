#!/usr/bin/env python3
"""Look up one store-listing fact for a build.

The build scripts call this instead of taking the name and the add-on id as
command-line arguments. Both are durable properties of a listing rather than
choices made at build time, and passing them by hand meant a rebuild that
forgot one produced a package that was wrong in a way no test catches: the
Quotex and IQ real-market bots reverting to names their Firefox and Edge
listings had already been rejected under, or an add-on id drifting and opening
a second AMO listing instead of updating the first.

Usage: listing.py <store> <slug> <field> [default]

Prints the value, or the default, or nothing. Never fails on a missing entry -
most builds have no override, and that is the normal case.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402

# The repo's own declarations, at its root beside brand.json.
PATH = os.path.join(brand.ROOT, "store-listings.json")


def get(store, slug, field, default=""):
    try:
        with open(PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return default
    entry = (data.get(store) or {}).get(slug) or {}
    value = entry.get(field)
    return value if value else default


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    store, slug, field = sys.argv[1:4]
    default = sys.argv[4] if len(sys.argv) > 4 else ""
    out = get(store, slug, field, default)
    if out:
        print(out)
