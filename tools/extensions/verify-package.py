#!/usr/bin/env python3
"""Check a packaged extension zip against its own manifest, without unpacking it.

A zip missing one file looks exactly like a healthy zip until it is installed —
and a Chromium service worker whose importScripts target is absent does not fail
softly, it fails to register at all: no background, no action handler, no popup.
That shipped once (config.js is named nowhere in the Chrome manifest), so the
build now proves the package before anyone uploads it.

Usage: verify-package.py <path/to/package.zip>
"""
import json
import os
import re
import sys
import zipfile



_IMPORT_SCRIPTS = re.compile(r"""importScripts\s*\(([^)]*)\)""")


def required(zf):
    """Every path the package must contain, derived from what it declares."""
    m = json.loads(zf.read("manifest.json").decode("utf-8"))
    need = ["manifest.json"]

    bg = m.get("background") or {}
    workers = [bg["service_worker"]] if bg.get("service_worker") else []
    workers += list(bg.get("scripts") or [])
    need += workers

    for worker in workers:
        try:
            src = zf.read(worker).decode("utf-8")
        except KeyError:
            continue
        for call in _IMPORT_SCRIPTS.findall(src):
            need += re.findall(r"""['"]([^'"]+)['"]""", call)

    for cs in m.get("content_scripts", []):
        need += cs.get("js", []) + cs.get("css", [])
    for res in m.get("web_accessible_resources", []):
        need += [r for r in res.get("resources", []) if "*" not in r]

    icons = m.get("icons") or {}
    need += list(icons.values())
    need += list(((m.get("action") or {}).get("default_icon") or {}).values())
    popup = (m.get("action") or {}).get("default_popup")
    if popup:
        need.append(popup)

    out, seen = [], set()
    for f in need:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


# src="x.js" / href="x.css" in the popup, skipping absolute and data URLs.
_HTML_ASSET = re.compile(r"""(?:src|href)\s*=\s*['"]([^'"]+)['"]""")


def popup_assets(zf):
    """What popup.html loads. The manifest never names the popup — it opens in
    its own window rather than as an action popup — so nothing else checks it."""
    if "popup.html" not in zf.namelist():
        return []
    html = zf.read("popup.html").decode("utf-8", "replace")
    out = []
    for ref in _HTML_ASSET.findall(html):
        ref = ref.split("?")[0].split("#")[0]
        if not ref or ":" in ref or ref.startswith("/"):
            continue
        if ref not in out:
            out.append(ref)
    return out


_CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""")


def stylesheet_assets(zf, sheets):
    """What the popup's stylesheets load by a relative url(): a font, an image."""
    out = []
    for sheet in sheets:
        if not sheet.endswith(".css") or sheet not in zf.namelist():
            continue
        css = zf.read(sheet).decode("utf-8", "replace")
        for ref in _CSS_URL.findall(css):
            ref = ref.split("?")[0].split("#")[0].strip()
            if not ref or ":" in ref or ref.startswith("/"):
                continue
            ref = os.path.normpath(os.path.join(os.path.dirname(sheet), ref))
            if ref not in out:
                out.append(ref)
    return out


def main(path):
    with zipfile.ZipFile(path) as zf:
        have = set(zf.namelist())
        loads = popup_assets(zf)
        need = required(zf) + ["popup.html"] + loads + stylesheet_assets(zf, loads)
        missing, seen = [], set()
        for f in need:
            if f not in have and f not in seen:
                seen.add(f)
                missing.append(f)
    if missing:
        print(f"{os.path.basename(path)}: MISSING {' '.join(missing)}", file=sys.stderr)
        return 1
    print(f"{os.path.basename(path)}: ok")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
