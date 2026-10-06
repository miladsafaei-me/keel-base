#!/usr/bin/env python3
"""Copy one signal app from its site into its Android member, and draw the member's icons.

The Android app runs the very app the landing runs, so it looks and behaves the same: the markup the site draws, the
site's stylesheet and scripts, the icons the app uses and the font. Nothing of it is rewritten by hand. What the phone
adds around the app (the licence gate, the tabs, the bridge to the device) is the repo's own shell, in shell/.

It reads a committed state of the site, never a working tree: `git archive <ref>` of design/ into a temporary folder,
read there through the repo's tools/site_adapter.py, so nothing is written into any checkout. The commit it copied is
recorded in assets/site/SOURCE.

Writes, under <family>/<slug>/:
  android/assets/index.html     shell/index.shell.html with the sprite, the app's markup and the scripts filled in
  android/assets/config.js      every brand and product value the shell reads, from brand.json and member.json
  android/assets/site/          the site's scripts and stylesheet byte for byte, the font, any image the app draws
  android/res/                  the adaptive launcher icon (foreground, stage background, monochrome), the launch
                                screen emblem, and the colours the native side paints before the shell has drawn
  play/icon-512.png             the Google Play store icon

Usage: sync-from-site.py <slug> [--ref origin/main] [--check]
--check exits non-zero when the files on disk differ from what the site would give.
"""
import argparse
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

import mobile

DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
ADAPTIVE_DP = 108
ADAPTIVE_EMBLEM_DP = 60
SPLASH_DP = 288
SPLASH_EMBLEM_DP = 168
LOGO_PX = (384, 168)


def archive(site, ref, dest):
    subprocess.run(["git", "-C", site, "fetch", "-q", "origin"], check=False)
    commit = subprocess.run(["git", "-C", site, "rev-parse", "--short", ref], capture_output=True, text=True, check=True).stdout.strip()
    tar = subprocess.run(["git", "-C", site, "archive", ref, "design"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", dest], input=tar, check=True)
    return commit


def adapter():
    path = os.path.join(mobile.ROOT, "tools", "site_adapter.py")
    spec = importlib.util.spec_from_file_location("site_adapter", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def localise(html, design, out_assets):
    """Point every page asset the markup draws (assets/<name>) at site/<name> and collect the files; turn links to the
    site's pages into data-site-page links, which shell.js points at the live site."""
    def asset(m):
        name = m.group(2)
        out_assets[os.path.basename(name)] = os.path.join(design, "assets", name)
        return '%s="site/%s"' % (m.group(1), os.path.basename(name))
    html = re.sub(r'(href|src)="assets/([^"]+)"', asset, html)
    return re.sub(r'href="([a-z0-9-]+)\.html"', r'href="#" data-site-page="\1"', html)


def config_js(brand, m):
    app = brand["app"]
    site = app["site"].rstrip("/")
    link = brand["family_links"]["binary-signal-apps"]
    cfg = {
        "APP_NAME": m["name"],
        "BRAND": brand["brand"],
        "SITE_URL": site,
        "SITE_LABEL": app["site_label"],
        "ITEM": m["item"],
        "SIGNAL_URL": site + "/s-api/binary-signal",
        "LICENSE_URL": site + "/s-api/license",
        "LANDING_URL": app["landing_url"].format(slug=m["slug"]),
        "SIGNUP_URL": app["signup_url"].format(item=m["item"]),
        "RISK_URL": app["risk_url"],
        "PRIVACY_URL": app["privacy_url"],
        "TERMS_URL": app["terms_url"],
        "KEY_PAGE": app["key_page"],
        "KEY_PAGE_URL": app["key_page_url"],
        "KEY_PREFIX": app["key_prefix"],
        "AFFILIATE_URL": link["url"],
        "AFFILIATE_NAME": link["name"],
        "AFFILIATE_LABEL": "Join " + link["name"],
        "TELEGRAM_POOL": app["telegram_pool"],
        "SUPPORT_EMAIL": app["support_email"],
        "CONTACT_MESSAGE": m["contact_message"],
        "TRIAL_DAYS": m["trial_days"],
        "FREE_WORDS": m["free_words"],
    }
    return ("/* Written by tools/sync-from-site.py from brand.json and member.json: edit those, never this file.\n"
            "   The only file of the app that names the brand, its site or the product. */\n"
            "window.SIGNAL_APP = " + json.dumps(cfg, indent=2) + ";\n")


# Icons.

def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def cut_white(im):
    """Clear the near-white ground that touches the border, and un-mix a 2px rim from white."""
    rgb = np.asarray(im.convert("RGB")).astype(float)
    dist = (255 - rgb).max(axis=2)
    labels, _ = ndimage.label(dist <= 18)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    ground = np.isin(labels, border[border > 0])
    rim = ndimage.binary_dilation(ground, iterations=2) & ~ground
    alpha = np.ones(dist.shape)
    alpha[ground] = 0
    alpha[rim] = np.clip(dist[rim] / 64, 0, 1)
    colour = np.clip(255 + (rgb - 255) / np.maximum(alpha, 1e-6)[..., None], 0, 255)
    return Image.fromarray(np.dstack([colour, alpha * 255]).round().astype(np.uint8), "RGBA")


def emblem(path, ground):
    """The launcher emblem, trimmed to its shape: a drawn emblem (art/emblem.png) or the site logo itself."""
    im = Image.open(path)
    im = cut_white(im) if ground == "white" else im.convert("RGBA")
    return im.crop(im.getchannel("A").getbbox())


def fit(im, canvas, inner):
    """im scaled to fit an inner x inner box, centred on a transparent canvas x canvas square."""
    scale = inner / max(im.size)
    small = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.alpha_composite(small, ((canvas - small.width) // 2, (canvas - small.height) // 2))
    return out


def stage(size, colors):
    """The site's dark stage: its navy with a violet glow at 50% 45%, fading out by 62% of the way to the corner."""
    base = np.array(hex_rgb(colors["stage"]), float)
    glow = np.array(hex_rgb(colors["stage_glow"]), float)
    y, x = np.mgrid[0:size, 0:size].astype(float)
    r = np.hypot(x - size * 0.5, y - size * 0.45) / (np.hypot(size * 0.5, size * 0.55) * 0.62)
    t = (np.clip(1 - r, 0, 1) * 0.30)[..., None]
    rgb = base * (1 - t) + glow * t
    return Image.fromarray(np.dstack([rgb, np.full((size, size), 255.0)]).round().astype(np.uint8), "RGBA")


def monochrome(im):
    """Android 13 themed icons tint one layer: the emblem's shape, its light details kept and its shading softened."""
    arr = np.asarray(im).astype(float)
    lum = (arr[..., :3] @ np.array([0.299, 0.587, 0.114])) / 255
    alpha = arr[..., 3] / 255 * (0.45 + 0.55 * lum)
    white = np.full(lum.shape, 255.0)
    return Image.fromarray(np.dstack([white, white, white, alpha * 255]).round().astype(np.uint8), "RGBA")


def square(im):
    side = max(im.size)
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    return out


def webp(im):
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=86, method=6)
    return buf.getvalue()


def png(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def icons(mark, colors):
    files = {}
    for name, d in DENSITIES.items():
        side = round(ADAPTIVE_DP * d)
        inner = round(ADAPTIVE_EMBLEM_DP * d)
        fg = fit(mark, side, inner)
        files["res/mipmap-%s/ic_launcher_foreground.png" % name] = png(fg)
        files["res/mipmap-%s/ic_launcher_background.png" % name] = png(stage(side, colors).convert("RGB"))
        files["res/mipmap-%s/ic_launcher_monochrome.png" % name] = png(monochrome(fg))
    for name in ("xhdpi", "xxxhdpi"):
        d = DENSITIES[name]
        files["res/drawable-%s/splash_emblem.png" % name] = png(fit(mark, round(SPLASH_DP * d), round(SPLASH_EMBLEM_DP * d)))
    files["res/mipmap-anydpi-v26/ic_launcher.xml"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@mipmap/ic_launcher_background" />\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
        '    <monochrome android:drawable="@mipmap/ic_launcher_monochrome" />\n'
        '</adaptive-icon>\n').encode()
    colour = '    <color name="%s">%s</color>\n'
    files["res/values/colors.xml"] = ('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
                                      + colour % ("stage", colors["stage"])
                                      + colour % ("surface", colors["surface_light"])
                                      + colour % ("surface_light", colors["surface_light"])
                                      + colour % ("surface_dark", colors["surface_dark"])
                                      + "</resources>\n").encode()
    files["res/values-night/colors.xml"] = ('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
                                            + colour % ("surface", colors["surface_dark"])
                                            + "</resources>\n").encode()
    play = stage(512, colors)
    play.alpha_composite(fit(mark, 512, 360))
    return files, png(play.convert("RGB"))


def outputs(slug, ref):
    brand = mobile.brand()
    m, mdir = mobile.member(slug)
    site = mobile.expand(brand["site_repo"])
    tmp = tempfile.mkdtemp(prefix="sa-sync-")
    try:
        commit = archive(site, ref, tmp)
        design = os.path.join(tmp, "design")
        src = os.path.join(design, "src")
        shell = (open(os.path.join(mobile.ROOT, "shell", "index.shell.html"), encoding="utf-8").read()
                 .replace("{{NAME}}", m["name"]).replace("{{SLUG}}", m["slug"])
                 .replace("{{TAB_APP}}", m["tab_app"]["label"]).replace("{{TAB_APP_ICON}}", m["tab_app"]["icon"]))
        app, sprite, css, font = adapter().render(src, m, shell)
        assets = {}
        app = localise(app, design, assets)
        sprite = localise(sprite, design, assets)
        scripts = "\n  ".join('<script src="site/%s"></script>' % s for s in m["site"]["scripts"])
        page = shell.replace("{{SPRITE}}", sprite.strip()).replace("{{APP}}", app.strip()).replace("{{SCRIPTS}}", scripts)
        files = {
            "android/assets/index.html": page.encode(),
            "android/assets/config.js": config_js(brand, m).encode(),
            "android/assets/site/site.css": css.encode(),
            "android/assets/site/inter-latin.woff2": open(font, "rb").read(),
            "android/assets/site/SOURCE": ("%s design/src at %s (%s)\n" % (brand["app"]["site_label"], commit, ref)).encode(),
        }
        for script in m["site"]["scripts"]:
            files["android/assets/site/" + script] = open(os.path.join(src, script), "rb").read()
        for name, path in assets.items():
            if not os.path.isfile(path):
                sys.exit("the app draws %s, which the site does not have at %s" % (name, path))
            files["android/assets/site/" + name] = open(path, "rb").read()
        if m.get("emblem"):
            mark = emblem(os.path.join(mdir, m["emblem"]), "white")
        else:
            mark = emblem(os.path.join(tmp, m["site"]["logo"]), m["site"].get("logo_ground"))
        res, play = icons(mark, brand["android"]["colors"])
        # The full logo, wordmark included, for the gate (128px) and the Access card (56px), at three times those sizes.
        logo = square(emblem(os.path.join(tmp, m["site"]["logo"]), m["site"].get("logo_ground")))
        for px in LOGO_PX:
            files["android/assets/site/logo-%d.webp" % px] = webp(logo.resize((px, px), Image.LANCZOS))
        files.update({"android/" + k: v for k, v in res.items()})
        files["play/icon-512.png"] = play
        return files, mdir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    files, mdir = outputs(args.slug, args.ref)
    generated = [os.path.join(mdir, "android", "assets"), os.path.join(mdir, "android", "res")]
    on_disk = set()
    for top in generated:
        for dirpath, _, names in os.walk(top):
            on_disk.update(os.path.relpath(os.path.join(dirpath, n), mdir) for n in names)
    stale = sorted(n for n, data in files.items()
                   if not os.path.isfile(os.path.join(mdir, n)) or open(os.path.join(mdir, n), "rb").read() != data)
    extra = sorted(on_disk - set(files))
    if args.check:
        # The SOURCE line names the commit; a newer commit with the same files is not drift.
        stale = [n for n in stale if not n.endswith("/SOURCE")]
        if stale or extra:
            print("out of date with the site: " + ", ".join(stale + extra))
            sys.exit(1)
        print("in step with the site (%d files)" % len(files))
        return
    for name, data in files.items():
        path = os.path.join(mdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    for name in extra:
        os.remove(os.path.join(mdir, name))
    print("wrote %d files (%d changed, %d removed) into %s" % (len(files), len(stale), len(extra), os.path.relpath(mdir, mobile.ROOT)))


if __name__ == "__main__":
    main()
