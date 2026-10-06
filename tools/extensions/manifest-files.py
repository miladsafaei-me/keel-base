#!/usr/bin/env python3
"""Print the files a browser-extension build actually ships, one per line.

Read off manifest.json rather than hand-listed, because a package missing one
script looks exactly like a package that is fine until it is installed. Three
build scripts needed this list and each had its own copy; the PocketOption
engine and tap were named literally in one of them, so running it for any other
broker would have produced a package with no socket engine at all.

A service worker's own importScripts() calls count too. Chrome names config.js
nowhere in the manifest - background.js pulls it in at runtime - so a list read
off the manifest alone shipped every Chromium package without it, and a worker
whose importScripts target is absent fails to register at all: no background, no
popup window, only "Service worker registration failed. Status code: 15".

Usage: manifest-files.py <path/to/manifest.json> [--background-first]

--background-first puts config.js and the background script at the head of the
list, which is the order a Firefox event page has to load them in.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brand  # noqa: E402

# importScripts("a.js", "b.js") with either quote style, on one line.
_IMPORT_SCRIPTS = re.compile(r"""importScripts\s*\(([^)]*)\)""")


def _imported_by(worker_path):
    """Files a service worker pulls in with importScripts(), in load order."""
    try:
        src = open(worker_path, encoding="utf-8").read()
    except OSError:
        return []
    names = []
    for call in _IMPORT_SCRIPTS.findall(src):
        for name in re.findall(r"""['"]([^'"]+)['"]""", call):
            if name not in names:
                names.append(name)
    return names


def shipped(manifest_path, background_first=False):
    m = json.load(open(manifest_path, encoding="utf-8"))
    files = []
    if background_first:
        files += ["config.js"]

    bg = (m.get("background") or {}).get("service_worker")
    if bg:
        # Whatever the worker importScripts() has to ship with it, and ahead of
        # it - the worker is dead on arrival without it.
        files += _imported_by(os.path.join(os.path.dirname(manifest_path), bg))
        files.append(bg)
    for script in (m.get("background") or {}).get("scripts", []):
        files.append(script)

    for cs in m.get("content_scripts", []):
        files.extend(cs.get("js", []))
        files.extend(cs.get("css", []))

    # Only concrete resources; a glob is a directory the packager copies whole.
    for res in m.get("web_accessible_resources", []):
        files.extend(r for r in res.get("resources", []) if "*" not in r)

    # The popup opens in its own window rather than as an action popup, so the
    # manifest never names it — but it is the whole UI. The logo's file name is
    # the repo's own (brand.json logo_file).
    files += ["popup.html", "popup.css", "popup.js", brand.LOGO_FILE]

    out, seen = [], set()
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    for name in shipped(args[0], "--background-first" in sys.argv):
        print(name)
