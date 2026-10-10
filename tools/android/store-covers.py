#!/usr/bin/env python3
"""Designed Play store covers of one app: each a raw app screenshot in a device frame, with the app's logo, a headline,
a line and, on tablets, four feature cards, drawn in HTML/CSS and rendered by Chromium (no image model, no cost).

The scenes are the member's own, listed in <slug>/covers.json:

  {"name": "GPT Trader Bot", "badge": "AI Pro", "foot": "Educational reads, not financial advice.",
   "scenes": [{"shot": "gate-licence-first-start", "title": ["Unlock", "Your Access"],
               "line": "Enter your licence key, or start the <em>7-day free trial</em>.",
               "features": [["key", "Key or Link", "Either works"], ...], "light": false}]}

  shot      a state name from shots.json; its picture is taken from covers/screenshots/<device>/NN-<shot>.png
  title     two lines, the second in the accent colour
  line      one sentence under the phone, or beside the tablet; <em> marks the accent words
  features  four [icon, label, sub] cards, tablets only; icons: shield key chart bolt clock chat lock layers
  light     true when the shot is the app's light appearance (the frame's status bar turns light)

Folders, all under <slug>/covers/:
  screenshots/{phone,tablet 7,tablet 10}/NN-name.png   every state, made by flow-shots.py (index.txt lists them)
  raw/{phone,tablet 7,tablet 10}/N.png                  the shot each cover uses, copied here
  final/{phone,tablet 7,tablet 10}/N.png                the covers: phone 1080x1920, 7-inch 1920x1080, 10-inch 2560x1440
  covers-<slug>.zip                                     screenshots/, raw/ and final/ together

Usage: store-covers.py <slug>
"""
import glob
import json
import os
import shutil
import sys
import zipfile

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import mobile  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "covers"))
from cover_page import SIZES, data_uri, page  # noqa: E402

DEVICES = [("phone", "phone"), ("tablet 7", "tablet7"), ("tablet 10", "tablet10")]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    m, mdir = mobile.member(sys.argv[1])
    spec = json.load(open(os.path.join(mdir, "covers.json"), encoding="utf-8"))
    covers = os.path.join(mdir, "covers")
    shots = os.path.join(covers, "screenshots")
    assets = os.path.join(mdir, "android", "assets", "site")
    fonts = sorted(glob.glob(os.path.join(assets, "*.woff2")))
    if not fonts:
        sys.exit("no .woff2 font in %s: run sync-from-site.py first" % assets)
    job = dict(spec, _font=data_uri(fonts[0]), _logo=data_uri(os.path.join(assets, "logo-384.webp")))
    plan = []
    for folder, dev in DEVICES:
        for n, scene in enumerate(spec["scenes"], 1):
            hits = glob.glob(os.path.join(shots, folder, "[0-9][0-9]-%s.png" % scene["shot"]))
            if len(hits) != 1:
                sys.exit("covers.json scene %d: no single %s/NN-%s.png; run flow-shots.py, or fix the name" % (n, folder, scene["shot"]))
            plan.append((folder, dev, n, scene, hits[0]))
    for sub in ("raw", "final"):
        shutil.rmtree(os.path.join(covers, sub), ignore_errors=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for folder, dev, n, scene, src in plan:
            raw = os.path.join(covers, "raw", folder, "%d.png" % n)
            os.makedirs(os.path.dirname(raw), exist_ok=True)
            shutil.copyfile(src, raw)
            cover = dict(scene, device=dev, shot=raw, out="%s/%d.png" % (folder, n), foot=spec.get("foot", ""))
            w, h = SIZES[dev]
            pg = br.new_page(viewport={"width": w, "height": h})
            pg.set_content(page(cover, job, w, h))
            pg.wait_for_timeout(400)
            final = os.path.join(covers, "final", folder, "%d.png" % n)
            os.makedirs(os.path.dirname(final), exist_ok=True)
            pg.screenshot(path=final)
            pg.close()
            print("ok   %-9s %2d  %s" % (folder, n, scene["shot"]))
        br.close()
    zpath = os.path.join(covers, "covers-%s.zip" % sys.argv[1])
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("screenshots", "raw", "final"):
            for root, _, files in sorted(os.walk(os.path.join(covers, sub))):
                for f in sorted(files):
                    z.write(os.path.join(root, f), os.path.relpath(os.path.join(root, f), covers))
    print(os.path.relpath(covers, mobile.ROOT))


if __name__ == "__main__":
    main()
