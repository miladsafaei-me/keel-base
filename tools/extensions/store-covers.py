#!/usr/bin/env python3
"""Designed store covers of one extension: each a popup screenshot in a browser window, with the extension's logo, a
headline, a line and four feature cards, 1280x800 (the Chrome Web Store, Edge Add-ons and Firefox size), drawn in
HTML/CSS and rendered by Chromium (no image model, no cost). The Chrome Web Store shows the first five, so the
strongest scenes go first.

The scenes are the extension's own, listed in <extension>/covers.json:

  {"name": "GPT Trader Bot", "badge": "AI Pro",
   "scenes": [{"shot": "licence-gate", "title": ["Unlock", "Your Access"],
               "line": "Enter your licence key, or start the <em>7-day free trial</em>.",
               "features": [["key", "Key or Link", "Either works"], ...], "light": false}]}

  shot      a state name from shots.json; its picture is covers/screenshots/NN-<shot>.png
  title     two lines, the second in the accent colour
  line      one sentence; <em> marks the accent words
  features  four [icon, label, sub] cards; icons: shield key chart bolt clock chat lock layers

Folders, all under <extension>/covers/:
  screenshots/NN-name.png   every state, made by flow-shots.py (index.txt lists them)
  raw/N.png                 the shot each cover uses, copied here
  final/N.png               the covers, 1280x800
  covers-<slug>.zip         screenshots/, raw/ and final/ together

Usage: store-covers.py <extension-dir> [<extension-dir> ...]
Python: ~/.local/share/keel-render-venv/bin/python (playwright + PIL).
"""
import glob
import json
import os
import shutil
import sys
import zipfile

from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "covers"))
from cover_page import SIZES, data_uri, page  # noqa: E402


def brand_site(ext_dir):
    d = ext_dir
    while d != os.path.dirname(d):
        if os.path.isfile(os.path.join(d, "brand.json")):
            return json.load(open(os.path.join(d, "brand.json"), encoding="utf-8"))["app"].get("site_label", "")
        d = os.path.dirname(d)
    return ""


def run(br, ext_dir):
    ext_dir = os.path.abspath(ext_dir)
    slug = os.path.basename(ext_dir)
    spec = json.load(open(os.path.join(ext_dir, "covers.json"), encoding="utf-8"))
    covers = os.path.join(ext_dir, "covers")
    site = os.path.join(ext_dir, "chrome", "site")
    fonts = sorted(glob.glob(os.path.join(site, "*.woff2")))
    logos = sorted(glob.glob(os.path.join(site, "%s-160.*.webp" % slug))) or [os.path.join(ext_dir, "chrome", "icons", "mark_192.png")]
    if not fonts:
        sys.exit("%s: no .woff2 font in chrome/site" % slug)
    job = dict(spec, site_label=spec.get("site_label") or brand_site(ext_dir), _font=data_uri(fonts[0]), _logo=data_uri(logos[0]))
    plan = []
    for n, scene in enumerate(spec["scenes"], 1):
        hits = glob.glob(os.path.join(covers, "screenshots", "[0-9][0-9]-%s.png" % scene["shot"]))
        if len(hits) != 1:
            sys.exit("%s covers.json scene %d: no single screenshots/NN-%s.png; run flow-shots.py, or fix the name" % (slug, n, scene["shot"]))
        plan.append((n, scene, hits[0]))
    for sub in ("raw", "final"):
        shutil.rmtree(os.path.join(covers, sub), ignore_errors=True)
        os.makedirs(os.path.join(covers, sub))
    w, h = SIZES["browser"]
    for n, scene, src in plan:
        raw = os.path.join(covers, "raw", "%d.png" % n)
        shutil.copyfile(src, raw)
        cover = dict(scene, device="browser", shot=raw, shot_size=Image.open(raw).size, out="%d.png" % n)
        pg = br.new_page(viewport={"width": w, "height": h})
        pg.set_content(page(cover, job, w, h))
        pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(covers, "final", "%d.png" % n))
        pg.close()
        print("ok   %s %2d  %s" % (slug, n, scene["shot"]))
    zpath = os.path.join(covers, "covers-%s.zip" % slug)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("screenshots", "raw", "final"):
            for root, _, files in sorted(os.walk(os.path.join(covers, sub))):
                for f in sorted(files):
                    z.write(os.path.join(root, f), os.path.relpath(os.path.join(root, f), covers))


def main(argv):
    if not argv:
        sys.exit(__doc__)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for d in argv:
            run(br, d)
        br.close()


if __name__ == "__main__":
    main(sys.argv[1:])
