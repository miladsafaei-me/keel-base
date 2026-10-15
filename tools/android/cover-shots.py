#!/usr/bin/env python3
"""Raw app screenshots for the designer's store covers, into <family>/<slug>/covers/raw/.

A store cover (the picture with a headline and a device frame) carries the app's screenshot inside the frame's
screen, so the screenshot is sized to that screen, not to the cover. The sizes are measured from the designed
samples in <family>/screenshots/ (screenshot-sizes.html); the cover sizes themselves are in Google Play's rules.

  phone/1.png ... 5.png      482x1038   the screen inside the phone frame of a 1080x1920 cover
  tablet 7/1.png ... 5.png   1027x800   the screen inside the tablet frame of a 1920x1080 cover
  tablet 10/1.png ... 5.png  1404x932   the screen inside the tablet frame of a 2560x1440 cover

The five scenes, the same on every device: 1 licence gate, 2 the chat, 3 a forecast, 4 Access, 5 More. Light and dark,
in covers/raw/<theme>/ (owner, 2026-10-15), no system bars, the real app against the live signal engine. Each file is rendered at
double density and scaled to the exact size.

A member with its own covers.json picks its cover shots from every state instead (store-covers.py fills
covers/raw/), so this skips it.

Usage: cover-shots.py <slug> [--theme both|light|dark]   (both is the default)
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

import mobile

SCENES = ["gate", "app", "forecast", "access", "more"]
SETS = [("phone", "cover-phone", (482, 1038)), ("tablet 7", "cover-7", (1027, 800)), ("tablet 10", "cover-10", (1404, 932))]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--theme", default="both", choices=("both", "light", "dark"))
    args = ap.parse_args()
    m, mdir = mobile.member(args.slug)
    if os.path.isfile(os.path.join(mdir, "covers.json")):
        print("covers.json picks the cover shots: run store-covers.py %s" % args.slug)
        return
    raw_dir = os.path.join(mdir, "covers", "raw")
    shutil.rmtree(raw_dir, ignore_errors=True)
    for theme, folder, size, target in [(t,) + s for t in (("light", "dark") if args.theme == "both" else (args.theme,)) for s in SETS]:
        out = os.path.join(raw_dir, theme)
        tmp = tempfile.mkdtemp(prefix="sa-cover-")
        try:
            run = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.realpath(__file__)), "render.py"), args.slug, "--sizes", size, "--themes", theme,
                                  "--scenarios", ",".join(SCENES), "--dpr", "2", "--no-insets", "--out", tmp], capture_output=True, text=True)
            print(run.stdout.strip())
            if run.returncode:
                sys.exit("a cover screenshot scene failed; fix it before the covers are made")
            os.makedirs(os.path.join(out, folder), exist_ok=True)
            for n, scene in enumerate(SCENES, 1):
                shot = Image.open(os.path.join(tmp, "%s-%s-%s.png" % (size, scene, theme))).convert("RGB")
                shot.resize(target, Image.LANCZOS).save(os.path.join(out, folder, "%d.png" % n), optimize=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(os.path.relpath(raw_dir, mobile.ROOT))


if __name__ == "__main__":
    main()
