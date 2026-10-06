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
# src="x.js" / href="x.css" in the popup, and url(x) in the stylesheets it loads.
_HTML_ASSET = re.compile(r"""(?:src|href)\s*=\s*['"]([^'"]+)['"]""")
_CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""")


def _local(ref):
    """A path inside the build, or None for a URL, an absolute path, a fragment or data."""
    ref = ref.split("?")[0].split("#")[0].strip()
    if not ref or ":" in ref or ref.startswith("/"):
        return None
    return ref


def popup_loads(build_dir):
    """Every file popup.html loads by a relative path, and every file those stylesheets
    load, in order. icons/ is left out: the packagers ship that folder whole. A popup
    built from a site's own app keeps its stylesheet, fonts and scripts in a folder
    beside it, and the manifest names none of them."""
    try:
        html = open(os.path.join(build_dir, "popup.html"), encoding="utf-8").read()
    except OSError:
        return []
    out = []
    for ref in _HTML_ASSET.findall(html):
        ref = _local(ref)
        if not ref or ref.startswith("icons/") or ref in out:
            continue
        out.append(ref)
        if ref.endswith(".css"):
            try:
                css = open(os.path.join(build_dir, ref), encoding="utf-8").read()
            except OSError:
                continue
            for url in _CSS_URL.findall(css):
                url = _local(url)
                if url:
                    url = os.path.normpath(os.path.join(os.path.dirname(ref), url))
                    if not url.startswith("icons/") and url not in out:
                        out.append(url)
    return out


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
    files += popup_loads(os.path.dirname(manifest_path))

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
