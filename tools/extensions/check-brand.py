#!/usr/bin/env python3
"""Refuse a build that carries another brand's name or domain.

Several sites build their extensions with these same tools, and a new
extension is modelled on the newest member of the family, which may be another
site's. That is how a trace crosses over: the other brand's name in a footer,
its domain in a manifest, a disclosure naming the wrong brand. Each repo
lists the strings that must never reach a user in its brand.json
(forbidden_traces: the other brands' names and domains), and this script fails
on any of them, case-insensitively. A partner URL whose tracking id contains
one is exempt when brand.json lists it in trace_exceptions: tracking ids stay
as the partner issued them, and a visitor does not read them.

What it reads, for one build folder or package: every text file in it (code,
markup, styles, the manifest, inline SVG, the README beside the code), never a
tests/ folder, plus the product's store-listing.md, which is what the store
shows. Icons are images and are not read.

Usage:
  check-brand.py <build-folder-or-package.zip> [...]
  check-brand.py --all      every build and listing in the repo (the pre-commit hook)
"""
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402
import layout  # noqa: E402

TEXT = (".js", ".html", ".css", ".json", ".svg", ".md", ".txt")


def pattern():
    if not brand.FORBIDDEN_TRACES:
        return None
    return re.compile("|".join(re.escape(t) for t in brand.FORBIDDEN_TRACES), re.I)


def texts(path):
    """{relative name: text} of every text file in a build folder or package."""
    out = {}
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith(TEXT) and not name.startswith("tests/"):
                    out[name] = zf.read(name).decode("utf-8", "replace")
        return out
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in ("tests", "__pycache__")]
        for f in filenames:
            if f.endswith(TEXT):
                full = os.path.join(dirpath, f)
                out[os.path.relpath(full, path)] = open(full, encoding="utf-8", errors="replace").read()
    return out


def listing_of(path):
    """The product's store-listing.md, from <family>/<slug>/<browser>[/x.zip]."""
    folder = os.path.dirname(path) if path.endswith(".zip") else path
    product = os.path.dirname(os.path.abspath(folder))
    listing = os.path.join(product, "store-listing.md")
    return listing if os.path.isfile(listing) else None


def hits(rx, name, text):
    for n, line in enumerate(text.splitlines(), 1):
        for allowed in brand.TRACE_EXCEPTIONS:
            line = line.replace(allowed, "")
        for m in rx.finditer(line):
            yield "%s:%d: %r in %s" % (name, n, m.group(0), line.strip()[:120])


def check(path, rx):
    found = []
    for name, text in sorted(texts(path).items()):
        found += list(hits(rx, name, text))
    listing = listing_of(path)
    if listing:
        found += list(hits(rx, "store-listing.md", open(listing, encoding="utf-8").read()))
    return found


def targets_all():
    out = []
    for _family, slug in layout.products():
        for browser in layout.BROWSERS:
            d = layout.build_dir(slug, browser)
            if os.path.isfile(os.path.join(d, "manifest.json")):
                out.append(d)
    return out


def main(argv):
    if not argv:
        sys.exit(__doc__)
    rx = pattern()
    if rx is None:
        print("brand.json lists no forbidden_traces: nothing to check", file=sys.stderr)
        return 0
    targets = targets_all() if argv == ["--all"] else argv
    failed = False
    for t in targets:
        found = check(t, rx)
        if found:
            failed = True
            print("brand trace: %s" % os.path.relpath(os.path.abspath(t), brand.ROOT), file=sys.stderr)
            for f in found:
                print("  - " + f, file=sys.stderr)
    if failed:
        print("these strings belong to another brand (brand.json forbidden_traces); "
              "rewrite them as %s's own before packaging" % brand.BRAND, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
