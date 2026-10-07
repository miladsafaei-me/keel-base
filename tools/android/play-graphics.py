#!/usr/bin/env python3
"""Draw a member's Google Play graphics into <family>/<slug>/play/.

  feature-graphic.png        1024x500, the banner at the top of the store page: the site's dark stage, the product's
                             logo, its name and its one-line promise (member.json "tagline"), in the site's own font
  phone-<n>-<scene>.png      1080x1920 phone screenshots (9:16), the app as the WebView draws it, light theme
  tablet7-<n>-<scene>.png    1200x1920, for 7-inch tablets
  tablet10-<n>-<scene>.png   1600x2560, for 10-inch tablets
  icon-512.png               written by sync-from-site.py, not here

It also runs cover-shots.py, so every run leaves <slug>/screenshots/ (raw shots sized for the designer's covers) fresh.

Screenshots come from tools/render.py, so they are the real app against the live signal engine, never a mock.

Usage: play-graphics.py <slug> [--only feature|screens]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

import mobile

SCENES = ["forecast", "app", "gate", "access", "more"]
SETS = [("phone", "play", 3, SCENES), ("tablet7", "play-7", 2, ["forecast", "more"]), ("tablet10", "play-10", 2, ["forecast", "more"])]

FEATURE = """<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<link rel="stylesheet" href="site/site.css">
<style>
  html, body { margin: 0; inline-size: 1024px; block-size: 500px; overflow: hidden; }
  .fg { box-sizing: border-box; display: grid; grid-template-columns: 340px 1fr; align-items: center; gap: var(--space-10);
        inline-size: 1024px; block-size: 500px; padding: 0 var(--space-16) 0 var(--space-14);
        background: var(--stage-fill); color: var(--ink-on-inverse); font-family: var(--font-sans); }
  .fg__logo { inline-size: 340px; block-size: 340px; }
  .fg__eyebrow { margin: 0 0 var(--space-3); font-size: var(--text-3); font-weight: var(--weight-bold); letter-spacing: var(--tracking-eyebrow);
                 text-transform: uppercase; color: var(--accent-ink-on-inverse); }
  .fg__name { margin: 0; font-size: var(--text-7); font-weight: var(--weight-heavy); line-height: 1.05; letter-spacing: var(--tracking-tight); text-wrap: balance; }
  .fg__line { margin: var(--space-5) 0 0; font-size: var(--text-5); font-weight: var(--weight-semibold); line-height: 1.3; color: var(--ink-on-inverse-muted); }
</style></head><body>
<div class="fg"><img class="fg__logo" src="site/logo-384.webp" alt=""><div>
<p class="fg__eyebrow">%(eyebrow)s</p><h1 class="fg__name">%(name)s</h1><p class="fg__line">%(tagline)s</p></div></div>
</body></html>"""


def feature(m, mdir, out):
    assets = os.path.join(mdir, "android", "assets")
    page = os.path.join(assets, "_feature.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(FEATURE % {"name": m["name"], "tagline": m["tagline"], "eyebrow": m.get("eyebrow", "Binary options signal app")})
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            p = browser.new_page(viewport={"width": 1024, "height": 500}, device_scale_factor=1)
            p.goto("file://" + page)
            p.wait_for_timeout(600)
            p.screenshot(path=os.path.join(out, "feature-graphic.png"))
            browser.close()
    finally:
        os.remove(page)
    print(os.path.relpath(os.path.join(out, "feature-graphic.png"), mobile.ROOT))


def screens(slug, out):
    for prefix, size, dpr, scenes in SETS:
        tmp = tempfile.mkdtemp(prefix="sa-play-")
        try:
            run = subprocess.run([sys.executable, os.path.join(mobile.ROOT, "tools", "render.py"), slug, "--sizes", size, "--themes", "light",
                                  "--scenarios", ",".join(scenes), "--dpr", str(dpr), "--no-insets", "--out", tmp], capture_output=True, text=True)
            print(run.stdout.strip())
            if run.returncode:
                sys.exit("a screenshot scene failed; fix it before it goes to the store")
            for n, scene in enumerate(scenes, 1):
                dest = os.path.join(out, "%s-%d-%s.png" % (prefix, n, scene))
                shutil.move(os.path.join(tmp, "%s-%s-light.png" % (size, scene)), dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--only", choices=["feature", "screens"])
    args = ap.parse_args()
    m, mdir = mobile.member(args.slug)
    out = os.path.join(mdir, "play")
    os.makedirs(out, exist_ok=True)
    if args.only != "screens":
        feature(m, mdir, out)
    if args.only != "feature":
        for name in os.listdir(out):
            if name.startswith(("phone-", "tablet7-", "tablet10-")):
                os.remove(os.path.join(out, name))
        screens(args.slug, out)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.realpath(__file__)), "cover-shots.py"), args.slug], check=True)


if __name__ == "__main__":
    main()
