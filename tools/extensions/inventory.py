#!/usr/bin/env python3
"""Keep exactly one current build of every extension, and say where it is.

This folder once held the same extension in up to six places at once: a
versioned folder name ("Stocks AI Signals V 1.0.1"), a newer one under new/, a
retired third-party build in dist/, a dated snapshot, a staging bundle, and a
bundle inside that bundle. Nobody could tell which one was current without
opening every manifest. So the layout is now a rule, and this script is the
rule's enforcement:

    <family>/<slug>/<browser>/manifest.json                 the build
    <family>/<slug>/<browser>/<slug>-<browser>-<v>.zip      its one package

where the family, the browser (chrome, firefox or edge) and the layout itself
are defined once in layout.py, and <v> is the folder's own version.
Any other unpacked extension, any other package, a second package in one
folder, or a package for a version the folder no longer carries is an error.
VERSIONS.md is written from what is on disk, never by hand, so it cannot drift.

Usage:
  inventory.py                          report builds, versions and problems
  inventory.py --write                  also rewrite VERSIONS.md
  inventory.py --check                  fail on any problem or a stale VERSIONS.md
  inventory.py guard <folder> <version> refuse a build that would go backwards
  inventory.py prune <package.zip>      delete every other package in its folder
"""
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout  # noqa: E402
from listing import get as listing_get  # noqa: E402

import brand  # noqa: E402

ROOT = layout.ROOT
DOC = os.path.join(ROOT, "VERSIONS.md")
# How the generated text names these tools: the repo's tools/ links to them.
TOOLS = "tools"
SHARED = "~/www/keel-base/tools/extensions"
# Not extensions: build tooling and documentation.
IGNORED_TOP = {".git", ".githooks", "tools", "docs"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# The last dotted number in a package name is its version: iq-otc-bot-edge-1.3.0.2.zip.
ZIP_VERSION = re.compile(r"-(\d+(?:\.\d+)*)\.zip$")
MOBILE = brand.MOBILE_REPO

# "<Title> \u2014 <about>" per family, in brand.json order.
FAMILY_TITLE = {f: "%s \u2014 %s" % (v["title"], v["about"]) for f, v in brand.FAMILIES.items()}

RETIRED = brand.VERSIONS_NOTE


def vtuple(v):
    return tuple(int(n) for n in v.split("."))


def read_manifest(path):
    try:
        with open(path, encoding="utf-8") as fh:
            m = json.load(fh)
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) and "manifest_version" in m else None


def rel(path):
    return os.path.relpath(path, ROOT)


def is_build_path(parts):
    return (len(parts) == 3 and parts[0] in layout.FAMILIES and SLUG.match(parts[1])
            and parts[2] in layout.BROWSERS)


def scan():
    """Every build and every problem, from what is on disk."""
    builds = {}      # (browser, slug) -> {"version", "name", "zip", "drift", "family"}
    problems = []
    notes = {}       # slug -> [note]

    for dirpath, dirnames, filenames in os.walk(ROOT):
        r = rel(dirpath)
        parts = [] if r == "." else r.split(os.sep)
        if parts and parts[0] in IGNORED_TOP:
            dirnames[:] = []
            continue
        if len(parts) == 3 and parts[0] in layout.FAMILIES and parts[2] == "screenshots":
            # Raw store-cover shots (tools/flow-shots.py): pictures and a zip of them, never a build.
            dirnames[:] = []
            continue
        if len(parts) == 1 and parts[0] not in layout.FAMILIES:
            problems.append("unknown top-level folder: %s/ (families are %s)"
                            % (r, ", ".join(layout.FAMILIES)))
        if len(parts) == 2 and parts[0] in layout.FAMILIES and not SLUG.match(parts[1]):
            problems.append("folder name is not a slug: %s/ (no spaces, no version in the name)" % r)
        if len(parts) == 3 and parts[0] in layout.FAMILIES and parts[2] not in layout.BROWSERS:
            problems.append("unknown browser folder: %s/ (one of %s)" % (r, ", ".join(layout.BROWSERS)))
        build_here = is_build_path(parts) and os.path.isfile(os.path.join(dirpath, "manifest.json"))
        if "manifest.json" in filenames and read_manifest(os.path.join(dirpath, "manifest.json")) \
                and not is_build_path(parts):
            problems.append("stray unpacked copy: %s/" % r)
        for f in filenames:
            is_listings = len(parts) == 2 and parts[0] in layout.FAMILIES \
                and os.path.join(dirpath, f) == layout.listings_zip(dirpath)
            if f.endswith(".zip") and not build_here and not is_listings:
                problems.append("stray package: %s" % rel(os.path.join(dirpath, f)))
            if f.endswith((".apk", ".aab")):
                problems.append("Android app in the extensions repo: %s (it belongs in %s)"
                                % (rel(os.path.join(dirpath, f)), MOBILE))

    for family, slug in layout.products():
        for browser in layout.BROWSERS:
            folder = layout.build_dir(slug, browser)
            m = read_manifest(os.path.join(folder, "manifest.json"))
            if not m:
                continue
            version = m["version"]
            zips = sorted(f for f in os.listdir(folder) if f.endswith(".zip"))
            expected = layout.package_name(slug, browser, version)
            if len(zips) > 1:
                problems.append("%s holds %d packages: %s" % (rel(folder), len(zips), ", ".join(zips)))
            for z in zips:
                if z != expected:
                    problems.append("%s/%s is not the package of this folder's version (%s)"
                                    % (rel(folder), z, expected))
            package = expected if expected in zips else None
            drift = package_drift(folder, package) if package else []
            builds[(browser, slug)] = {"version": version, "name": m.get("name", slug),
                                       "zip": package, "drift": drift, "family": family}
            if drift:
                notes.setdefault(slug, []).append(
                    "%s: the folder has changes the package does not (%s). Bump the version "
                    "and rebuild before the next upload." % (browser_label(browser), ", ".join(drift)))
            if not package:
                notes.setdefault(slug, []).append("%s: not packaged yet." % browser_label(browser))

    for _family, slug in layout.products():
        chrome = builds.get(("chrome", slug))
        if not chrome:
            continue
        for browser in ("firefox", "edge"):
            port = builds.get((browser, slug))
            if not port:
                continue
            want = derived_version(browser, slug, chrome["version"])
            if port["version"] != want:
                notes.setdefault(slug, []).append(
                    "%s is %s, but tools/build-%s.sh would make %s from Chrome %s: this "
                    "build was changed by hand, and the build script refuses to overwrite it "
                    "with an older version." % (browser_label(browser), port["version"], browser,
                                                want, chrome["version"]))
            if port["name"] != chrome["name"]:
                notes.setdefault(slug, []).append(
                    "%s lists it as \u201c%s\u201d." % (browser_label(browser), port["name"]))
    return builds, problems, notes


def browser_label(browser):
    return {"chrome": "Chrome", "firefox": "Firefox", "edge": "Edge"}[browser]


def derived_version(browser, slug, chrome_version):
    """The version build-from-chrome.sh produces for this port."""
    if browser == "edge" and listing_get("edge", slug, "signal_only") and len(chrome_version.split(".")) == 3:
        return chrome_version + ".1"
    return chrome_version


def package_drift(folder, package):
    """Files whose bytes in the folder differ from the same file in the package."""
    out = []
    with zipfile.ZipFile(os.path.join(folder, package)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                out.append(name + " (missing)")
                continue
            with open(path, "rb") as fh:
                if fh.read() != zf.read(name):
                    out.append(name)
    return out


def render(builds, notes):
    lines = [
        "# Extension versions",
        "",
        "Generated by `%s/inventory.py --write` from what is on disk. Do not edit it by hand." % TOOLS,
        "The build scripts rewrite it after every package they make.",
        "",
        "## Where everything is",
        "",
        "Every extension has **one folder**, and inside it **one folder per browser**, each",
        "holding the build and **one package** for the store:",
        "",
        "```",
        "<family>/<slug>/chrome/    the source      <slug>-chrome-<version>.zip",
        "<family>/<slug>/firefox/   Firefox port    <slug>-firefox-<version>.zip",
        "<family>/<slug>/edge/      Edge build      <slug>-edge-<version>.zip",
        "```",
        "",
        "| Family folder | What is in it |",
        "|---|---|",
    ]
    for family in layout.FAMILIES:
        lines.append("| `%s/` | %s |" % (family, (lambda t: t[0].upper() + t[1:])(FAMILY_TITLE[family].split(" \u2014 ", 1)[1])))
    lines += [
        "",
        "`tools/` links to the build scripts and checkers every site's extension repo shares",
        "(`%s/`); `brand.json` holds this repo's brand, `store-listings.json` its" % SHARED,
        "per-store names and ids, and `docs/` its Firefox, Edge and store notes.",
        "",
        "Nothing else in this repository holds an extension: no `dist/`, no `new/`, no dated",
        "snapshot, no bundle zip. Building a new version deletes the old package in the same",
        "folder, and `tools/inventory.py --check` (the pre-commit hook) fails on any second copy.",
    ]
    if MOBILE:
        lines += ["", "The Android apps of the same markets are not here: they live in `%s`." % MOBILE]
    if RETIRED:
        lines += ["", RETIRED]
    for family in layout.FAMILIES:
        slugs = [s for f, s in layout.products() if f == family]
        if not slugs:
            continue
        lines += ["", "## " + FAMILY_TITLE[family], "",
                  "| Extension | Folder | Chrome | Firefox | Edge |", "|---|---|---|---|---|"]
        for slug in slugs:
            names = [builds[(b, slug)]["name"] for b in layout.BROWSERS if (b, slug) in builds]
            if not names:
                continue
            cells = []
            for b in layout.BROWSERS:
                info = builds.get((b, slug))
                cells.append("`%s`" % info["version"] if info else "\u2014")
            lines.append("| %s | `%s/%s/` | %s |" % (names[0], family, slug, " | ".join(cells)))
    slugs = [s for _f, s in layout.products()]
    if any(notes.get(s) for s in slugs):
        lines += ["", "## Notes", ""]
        for slug in slugs:
            for n in notes.get(slug, []):
                lines.append("- **`%s`** \u2014 %s" % (slug, n))
    lines.append("")
    return "\n".join(lines)


def guard(folder, version):
    """Refuse to build <version> into a folder that already holds a newer one."""
    newest = None
    m = read_manifest(os.path.join(folder, "manifest.json"))
    candidates = [m["version"]] if m else []
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            hit = ZIP_VERSION.search(f)
            if hit:
                candidates.append(hit.group(1))
    for c in candidates:
        if vtuple(c) > vtuple(version) and (newest is None or vtuple(c) > vtuple(newest)):
            newest = c
    if newest:
        sys.exit("%s already holds %s, newer than the %s this build would make. Bump the Chrome "
                 "version past it, or delete that build on purpose first." % (rel(folder), newest, version))


def prune(package):
    folder, keep = os.path.split(os.path.abspath(package))
    for f in sorted(os.listdir(folder)):
        if f.endswith(".zip") and f != keep:
            os.remove(os.path.join(folder, f))
            print("removed the older package %s" % rel(os.path.join(folder, f)))


def main(argv):
    if argv[:1] == ["guard"] and len(argv) == 3:
        return guard(os.path.abspath(argv[1]), argv[2])
    if argv[:1] == ["prune"] and len(argv) == 2:
        return prune(argv[1])
    if argv not in ([], ["--write"], ["--check"]):
        sys.exit(__doc__)

    builds, problems, notes = scan()
    text = render(builds, notes)
    if argv == ["--write"]:
        with open(DOC, "w", encoding="utf-8") as fh:
            fh.write(text)
    stale = False
    if argv == ["--check"]:
        try:
            with open(DOC, encoding="utf-8") as fh:
                stale = fh.read() != text
        except OSError:
            stale = True
    if argv == []:
        sys.stdout.write(text)
    for p in problems:
        print("ERROR  " + p, file=sys.stderr)
    if stale:
        print("ERROR  VERSIONS.md is stale: run %s/inventory.py --write" % TOOLS, file=sys.stderr)
    if problems or stale:
        sys.exit(1)
    if argv == ["--write"]:
        print("VERSIONS.md: %d builds, one package each" % len(builds))


if __name__ == "__main__":
    main(sys.argv[1:])
