#!/usr/bin/env python3
"""Report which packaged Firefox/Edge zips have fallen behind their Chrome build.

The build scripts already prove a copy is a copy at the moment they run. What
nothing watched is the zip that sits on disk AFTERWARDS: Chrome moves on, the
port is not rebuilt, and the stale package is what gets uploaded. Both Olymp
Firefox packages were a generation behind that way — built before the manifest
rewrite learned to spell out wss:// hosts, which is the permission the socket
engine needs on Firefox.

Compares every shipped file in the newest port zip byte for byte against the
Chrome source, and checks the port manifest still carries what the rewrite adds.
config.js is exempt from the byte check: the product rename is allowed to touch
its two name lines.

The market signal viewers are not audited: their Firefox builds are hand-ported
(patched minified bundles), not derived by the build scripts.

Usage: audit-builds.py [<slug> ...]     (no slug = every derived build)
"""
import json
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NEVER_SHARED = {"manifest.json", "firefox-shim.js"}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from listing import get as listing_get  # noqa: E402
import layout  # noqa: E402
import brand  # noqa: E402

# A signal-only listing (the repo's brand.json transforms.signal_only) rewrites these three, so they
# are not expected to match Chrome. What IS checked there is stronger: that none
# of the trade path survived in them, and that the package grants no broker access.
STRIPPED = {"config.js", "background.js", "popup.js"}
TRADE_TOKENS = ("CB_TRADE", "CB_BROKER_STATE", "CB_SET_ACCOUNT", "chrome.scripting",
                "OPEN_TRADE", "ALLOW_AUTOTRADE: true", "data-cta-auto")


def newest_zip(directory, slug):
    if not os.path.isdir(directory):
        return None
    zips = [f for f in os.listdir(directory) if f.startswith(slug) and f.endswith(".zip")]
    if not zips:
        return None
    key = lambda f: [int(n) for n in re.findall(r"\d+", f)] or [0]
    return os.path.join(directory, max(zips, key=key))


def audit(slug, port, zip_path):
    src = layout.build_dir(slug, "chrome")
    signal_only = port == "edge" and bool(listing_get("edge", slug, "signal_only"))
    problems = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith("/") or name in NEVER_SHARED:
                continue
            if signal_only and name in STRIPPED:
                body = zf.read(name).decode("utf-8", "replace")
                for token in TRADE_TOKENS:
                    if token in body:
                        problems.append(f"{port}: {name} still carries {token}")
                continue
            local = os.path.join(src, name)
            if not os.path.exists(local):
                problems.append(f"only in {port}: {name}")
                continue
            if zf.read(name) == open(local, "rb").read():
                continue
            # The rename may rewrite config.js APP_NAME lines and nothing else.
            if name == "config.js":
                shipped = zf.read(name).decode("utf-8").splitlines()
                have = open(local, encoding="utf-8").read().splitlines()
                diff = [a for a, b in zip(shipped, have) if a != b]
                if len(shipped) == len(have) and all("APP_NAME" in d for d in diff):
                    continue
            problems.append(f"stale in {port}: {name} differs from the chrome build")

        shipped = set(zf.namelist())
        declared = subprocess.run(
            [sys.executable, os.path.join(HERE, "manifest-files.py"),
             os.path.join(src, "manifest.json")],
            capture_output=True, text=True, check=True).stdout.split()
        for f in declared:
            if f in shipped:
                continue
            # A popup asset the Chrome build does not have either is not missing
            # from the port; the build scripts skip it on the same rule.
            if (f.startswith("popup.") or f == brand.LOGO_FILE) and not os.path.exists(os.path.join(src, f)):
                continue
            # The socket engine and the main-world tap are exactly what a
            # signal-only package must NOT contain, so their absence is the
            # pass condition there rather than a missing file.
            if signal_only and (f.endswith("-socket.js") or f.endswith("-tap.js")):
                continue
            problems.append(f"missing from {port}: {f}")
        if signal_only:
            for f in shipped:
                if f.endswith("-socket.js") or f.endswith("-tap.js"):
                    problems.append(f"{port}: signal-only package ships {f}")
            m = json.loads(zf.read("manifest.json"))
            if m.get("content_scripts"):
                problems.append(f"{port}: signal-only manifest declares content_scripts")
            extra = [p for p in m.get("permissions", []) if p != "storage"]
            if extra:
                problems.append(f"{port}: signal-only manifest grants {extra}")
            outside = [h for h in m.get("host_permissions", []) if not any(o in h for o in brand.OWN_HOSTS)]
            if outside:
                problems.append(f"{port}: signal-only manifest grants {outside}")

        if port == "firefox":
            m = json.loads(zf.read("manifest.json"))
            hosts = m.get("host_permissions") or []
            for h in hosts:
                if h.startswith("*://") and "wss://" + h[4:] not in hosts:
                    problems.append(f"{port} manifest has no wss:// twin for {h}")
    return problems


def main(slugs):
    slugs = slugs or [s for family, s in layout.products() if family in layout.DERIVED]
    bad = 0
    for slug in slugs:
        for port in ("firefox", "edge"):
            zip_path = newest_zip(layout.build_dir(slug, port), slug)
            if not zip_path:
                continue
            problems = audit(slug, port, zip_path)
            label = f"{slug} [{port} {os.path.basename(zip_path)}]"
            if problems:
                bad += 1
                print(label)
                for p in problems:
                    print("   " + p)
            else:
                print(label + ": in sync")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main([a for a in sys.argv[1:] if not a.startswith("-")]))
