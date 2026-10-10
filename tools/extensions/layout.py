#!/usr/bin/env python3
"""Where every extension build lives. The one place that knows the layout.

    <family>/<slug>/<browser>/                                the build
    <family>/<slug>/<browser>/<slug>-<browser>-<version>.zip  its one package
    <family>/<slug>/<slug>-store-listings.zip                 its store text, one
                                                              store-listing.<lang>.md
                                                              per language, en first

Every product sits in one folder, and its builds for each browser sit inside
it, so everything about one extension is in one place. The family says what
kind of product it is; the repo's families, in display order, are declared in
its brand.json (see brand.py).

chrome/ is the canonical source. firefox/ and edge/ are derived from it by
build-firefox.sh and build-edge.sh, for every family brand.json marks
"derived"; the others are ported by hand (see the repo's CLAUDE.md).

Usage (for the shell scripts):
  layout.py dir <slug> <browser>                 print the build folder
  layout.py package <slug> <browser> <version>   print the package file name
"""
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402

ROOT = brand.ROOT
FAMILIES = tuple(brand.FAMILIES)
BROWSERS = ("chrome", "firefox", "edge")
# Families whose Firefox and Edge builds come out of the build scripts, and so
# can be audited against their Chrome source byte for byte.
DERIVED = tuple(f for f, v in brand.FAMILIES.items() if v.get("derived"))


def products():
    """Every (family, slug) with a folder, in family order."""
    out = []
    for family in FAMILIES:
        base = os.path.join(ROOT, family)
        if os.path.isdir(base):
            out += [(family, s) for s in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, s))]
    return out


def family_of(slug):
    for family, s in products():
        if s == slug:
            return family
    return None


def build_dir(slug, browser):
    """The folder a build of <slug> for <browser> lives in (it may not exist yet)."""
    family = family_of(slug)
    return os.path.join(ROOT, family, slug, browser) if family else None


def listings_zip(product_dir):
    """The zip that holds a product's store text, one store-listing.<lang>.md per language."""
    return os.path.join(product_dir, os.path.basename(os.path.normpath(product_dir)) + "-store-listings.zip")


def listing_texts(product_dir):
    """Every store listing text of a product, as {name: text}.

    A product keeps its listings either as a loose store-listing.md (the older
    form) or inside <slug>-store-listings.zip; both are read when both exist."""
    out = {}
    loose = os.path.join(product_dir, "store-listing.md")
    if os.path.isfile(loose):
        out["store-listing.md"] = open(loose, encoding="utf-8").read()
    z = listings_zip(product_dir)
    if os.path.isfile(z):
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if re.fullmatch(r"store-listing(\.[a-z-]+)?\.md", os.path.basename(n)):
                    out[n] = zf.read(n).decode("utf-8", "replace")
    return out


def listing_text(product_dir):
    """The English store listing the policy checks read, or None."""
    texts = listing_texts(product_dir)
    for name in ("store-listing.md", "store-listing.en.md"):
        for n, text in texts.items():
            if os.path.basename(n) == name:
                return text
    return None


def package_name(slug, browser, version):
    return "%s-%s-%s.zip" % (slug, browser, version)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == "dir" and args[2] in BROWSERS:
        d = build_dir(args[1], args[2])
        if not d:
            sys.exit("no product folder for %r: create <family>/%s/chrome/ first, family one of %s"
                     % (args[1], args[1], ", ".join(FAMILIES)))
        print(d)
    elif len(args) == 4 and args[0] == "package" and args[2] in BROWSERS:
        print(package_name(args[1], args[2], args[3]))
    else:
        sys.exit(__doc__)
