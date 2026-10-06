#!/usr/bin/env python3
"""Draw a member's launcher emblem from its site logo with Gemini: the logo's emblem alone, no wordmark.

A launcher icon is 48dp on a home screen, and the store and the launcher both print the name under it, so the icon
carries the emblem and never the wordmark. When the wordmark overlaps the emblem in the logo (a crop would cut the
emblem's edge), the emblem is redrawn whole from the logo itself, in the same rendering, on a white ground.

Writes <family>/<slug>/art/emblem-v1.png ... -vN.png. Look at each, copy the chosen one to art/emblem.png and set
"emblem": "art/emblem.png" in member.json; tools/sync-from-site.py then cuts its white ground and builds every icon
from it.

Usage: set -a; . ~/www/signalbots/.env; set +a; draw-emblem.py <slug> [--variants 3]
"""
import argparse
import base64
import concurrent.futures as cf
import io
import json
import os
import subprocess
import sys
import urllib.request

from PIL import Image

import mobile

MODEL = "gemini-3-pro-image"
URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % MODEL
PROMPT_CROP = (
    "The attached image is the emblem of a trading app's logo, cut off at the bottom where the logo's wordmark began. "
    "Redraw this emblem as a complete app icon: exactly the same frame, colours, central character, symbol, glossy rendering, "
    "bevels and lighting, with the frame's missing lower part completed in its natural shape (a shield ends in its point), so "
    "the outline is whole on every side. Nothing else: no text, no letters, no body or object below the frame, no ground "
    "shadow. Centre it on a plain pure white background with generous even margins, filling about 80% of a square image."
)
PROMPT = (
    "The attached image is the logo of a trading app: an emblem with a wordmark under it. Redraw ONLY the emblem as an app "
    "icon: the same frame, the same colours, the same central character and symbol, the same glossy rendering, bevels and "
    "lighting. Show the emblem whole, including the parts the wordmark covers in the logo, so its outline is complete on every "
    "side. No text, no letters, no wordmark, no pill, no shadow on the ground. Centre it on a plain pure white background with "
    "generous even margins, filling about 80% of a square image."
)


def site_logo(brand, m):
    """The site logo as PNG bytes; with emblem_box (fractions of the logo image), only the emblem above the wordmark."""
    site = mobile.expand(brand["site_repo"])
    raw = subprocess.run(["git", "-C", site, "show", "origin/main:" + m["site"]["logo"]], capture_output=True, check=True).stdout
    box = m["site"].get("emblem_box")
    if not box:
        return raw, PROMPT
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = im.size
    crop = im.crop((round(box[0] * w), round(box[1] * h), round(box[2] * w), round(box[3] * h)))
    buf = io.BytesIO()
    crop.save(buf, "PNG")
    return buf.getvalue(), PROMPT_CROP


def draw(key, logo, prompt):
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/png", "data": base64.b64encode(logo).decode()}},
                                    {"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.load(resp)
    for part in data["candidates"][0]["content"]["parts"]:
        inline = part.get("inline_data") or part.get("inlineData")
        if inline:
            return base64.b64decode(inline["data"])
    raise RuntimeError("no image in the answer: %s" % json.dumps(data)[:400])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--variants", type=int, default=3)
    args = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY") or sys.exit("GEMINI_API_KEY is not set")
    brand = mobile.brand()
    m, mdir = mobile.member(args.slug)
    logo, prompt = site_logo(brand, m)
    art = os.path.join(mdir, "art")
    os.makedirs(art, exist_ok=True)
    with cf.ThreadPoolExecutor(args.variants) as pool:
        for i, image in enumerate(pool.map(lambda _: draw(key, logo, prompt), range(args.variants)), 1):
            path = os.path.join(art, "emblem-v%d.png" % i)
            with open(path, "wb") as f:
                f.write(image)
            print(path)


if __name__ == "__main__":
    main()
