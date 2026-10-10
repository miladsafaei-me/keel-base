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
  covers-<slug>.zip                                     raw/ and final/, for the store upload

Usage: store-covers.py <slug>
"""
import base64
import glob
import json
import os
import random
import shutil
import sys
import zipfile

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import mobile  # noqa: E402

DEVICES = [("phone", "phone"), ("tablet 7", "tablet7"), ("tablet 10", "tablet10")]
SIZES = {"phone": (1080, 1920), "tablet7": (1920, 1080), "tablet10": (2560, 1440)}


def data_uri(path):
    ext = os.path.splitext(path)[1].lstrip(".").replace("jpg", "jpeg")
    mime = {"woff2": "font/woff2", "webp": "image/webp"}.get(ext, "image/" + ext)
    return "data:%s;base64,%s" % (mime, base64.b64encode(open(path, "rb").read()).decode())


ICONS = {
    "shield": '<path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5z"/><path d="M9 12l2 2 4-4"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12 20 3M16 7l3 3M14 9l2 2"/>',
    "chart": '<path d="M4 20V10M10 20V6M16 20v-8M22 20H2"/><path d="M4 8l6-4 6 5 5-5"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 10h8M8 13h5"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
}

STATUS = ('<div class="sbar"><span>9:41</span><span class="sic">'
          '<svg viewBox="0 0 24 24"><path d="M2 9a15 15 0 0 1 20 0l-10 12z"/></svg>'
          '<svg viewBox="0 0 24 24"><path d="M3 21h18V3z"/></svg>'
          '<svg viewBox="0 0 24 24"><rect x="7" y="3" width="10" height="19" rx="2"/></svg></span></div>')


def candles(w, h, seed):
    rnd = random.Random(seed)
    out, x, y = [], 0, h * 0.62
    while x < w:
        y = max(h * 0.25, min(h * 0.85, y + rnd.uniform(-h * 0.035, h * 0.03)))
        body = rnd.uniform(h * 0.02, h * 0.07)
        wick = body + rnd.uniform(h * 0.02, h * 0.05)
        op = rnd.uniform(0.10, 0.28)
        out.append('<g opacity="%.2f"><rect x="%.0f" y="%.0f" width="3" height="%.0f" fill="#2b6cff"/>'
                   '<rect x="%.0f" y="%.0f" width="%.0f" height="%.0f" rx="2" fill="#1d4fd1"/></g>'
                   % (op, x + w * 0.006, y - wick / 2, wick, x, y - body / 2, w * 0.0135, body))
        x += w * 0.024
    return "".join(out)


CSS = """
@font-face { font-family: Inter; src: url(%(font)s) format("woff2"); font-weight: 100 900; }
* { box-sizing: border-box; margin: 0; }
html, body { width: %(w)dpx; height: %(h)dpx; overflow: hidden; }
body { font-family: Inter, sans-serif; color: #fff; position: relative;
  background: radial-gradient(ellipse at 70%% 35%%, #0b2a63 0%%, #051634 38%%, #020a1a 75%%); }
.bg { position: absolute; inset: 0; }
.glow { position: absolute; border-radius: 50%%; filter: blur(%(blur)dpx); }
.g1 { background: rgba(0, 136, 255, .35); } .g2 { background: rgba(162, 0, 255, .28); } .g3 { background: rgba(25, 181, 107, .22); }
.brand { display: flex; align-items: center; gap: %(bgap)dpx; }
.brand img { width: %(logo)dpx; height: %(logo)dpx; filter: drop-shadow(0 0 30px rgba(25,181,107,.45)); }
.brand b { display: block; font-size: %(bname)dpx; font-weight: 900; letter-spacing: -.01em; line-height: 1.02; }
.brand i { display: inline-block; margin-top: %(tagm)dpx; font-style: normal; font-weight: 800; font-size: %(btag)dpx;
  padding: .12em .55em; border-radius: 999px; background: linear-gradient(90deg, #0088ff, #a200ff); }
h1 { font-size: %(h1)dpx; font-weight: 900; line-height: 1.02; letter-spacing: -.025em; }
h1 span { display: block; }
h1 .acc { background: linear-gradient(90deg, #5fe0a0, #19b56b); -webkit-background-clip: text; color: transparent; }
.rule { height: 3px; width: %(rule)dpx; background: linear-gradient(90deg, transparent, #19b56b, #5fe0a0, #19b56b, transparent); }
.line { font-size: %(line)dpx; font-weight: 500; line-height: 1.35; color: #d3dcea; }
.line em { font-style: normal; color: #5fe0a0; font-weight: 700; }
.feats { display: grid; grid-template-columns: 1fr 1fr; gap: %(fpad)dpx %(fpad)dpx; }
.feat { display: grid; grid-template-columns: auto 1fr; column-gap: .7em; align-items: center; min-width: 0; padding: .55em .8em; border-radius: 16px; background: rgba(95,224,160,.06); border: 1px solid rgba(95,224,160,.22); font-size: %(flab)dpx; }
.feat svg { grid-row: span 2; }
.feat svg { width: %(ficon)dpx; height: %(ficon)dpx; fill: none; stroke: #5fe0a0; stroke-width: 1.7;
  stroke-linecap: round; stroke-linejoin: round; filter: drop-shadow(0 0 12px rgba(95,224,160,.55)); }
.feat b { display: block; white-space: nowrap; font-size: %(flab)dpx; font-weight: 800; }
.feat small { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: %(fsub)dpx; color: #93a5c0; line-height: 1.3; }
.device { position: absolute; background: #0b0f18; border-radius: %(rad)dpx; padding: %(bez)dpx;
  box-shadow: 0 0 0 3px #2a3140, 0 0 0 5px #0a0d14, 0 40px 120px rgba(0,0,0,.65), 0 0 90px rgba(0,136,255,.35); }
.device.light { background: #eef0f3; box-shadow: 0 0 0 3px #c9ccd2, 0 40px 120px rgba(0,0,0,.6), 0 0 90px rgba(0,136,255,.3); }
.screen { position: relative; overflow: hidden; border-radius: %(srad)dpx; background: #031833; display: flex; flex-direction: column; }
.screen img { display: block; width: 100%%; }
.cam { position: absolute; width: %(cam)dpx; height: %(cam)dpx; border-radius: 50%%; background: #05070b; box-shadow: inset 0 0 0 3px #1b2130; }
.sbar { display: flex; justify-content: space-between; align-items: center; padding: 0 %(sbp)dpx; height: %(sbh)dpx;
  font-size: %(sbf)dpx; font-weight: 600; background: #031833; color: #fff; }
.sbar-light { background: #ffffff; color: #0a1a33; } .sbar-light .sic svg { fill: #0a1a33; }
.sic { display: flex; gap: %(sbg)dpx; } .sic svg { width: %(sbf)dpx; height: %(sbf)dpx; fill: #fff; }
.home { position: absolute; left: 50%%; transform: translateX(-50%%); bottom: %(homeb)dpx; width: 28%%; height: 6px; border-radius: 3px; background: rgba(255,255,255,.85); }
.foot { position: absolute; left: 0; right: 0; text-align: center; }
.foot .rule { margin: 0 auto; }
"""


def page(cover, job, w, h):
    dev = cover["device"]
    s = w / 1080 if dev == "phone" else h / 1080
    v = dict(font=job["_font"], w=w, h=h, blur=int(140 * s), bgap=int(22 * s), logo=int(150 * s), bname=int(54 * s),
             btag=int(26 * s), tagm=int(10 * s), h1=int(112 * s), rule=int(520 * s), line=int(44 * s), fpad=int(18 * s),
             ficon=int(84 * s), flab=int(30 * s), fsub=int(22 * s), rad=int(70 * s), bez=int(18 * s), srad=int(52 * s),
             cam=int(26 * s), sbp=int(36 * s), sbh=int(52 * s), sbf=int(24 * s), sbg=int(10 * s), homeb=int(14 * s))
    if dev != "phone":
        v.update(rad=int(54 * s), bez=int(34 * s), srad=int(20 * s), h1=int(80 * s), logo=int(130 * s), flab=int(26 * s), fsub=int(19 * s), ficon=int(52 * s), fpad=int(16 * s), bname=int(46 * s),
                 btag=int(22 * s), line=int(38 * s), sbh=int(40 * s), sbf=int(20 * s))
    feats = "".join('<div class="feat"><svg viewBox="0 0 24 24">%s</svg><b>%s</b><small>%s</small></div>'
                    % (ICONS[i], a, b) for i, a, b in cover.get("features", []))
    title = "".join('<span class="%s">%s</span>' % ("acc" if n % 2 else "", t) for n, t in enumerate(cover["title"]))
    brand = ('<div class="brand"><img src="%s" alt=""><div><b>%s</b><i>%s</i></div></div>'
             % (job["_logo"], job["name"], job["badge"]))
    shot = data_uri(cover["shot"])
    bg = ('<svg class="bg" viewBox="0 0 %d %d" preserveAspectRatio="none">%s'
          '<path d="M0 %d C %d %d, %d %d, %d %d" stroke="#0088ff" stroke-opacity=".35" stroke-width="3" fill="none"/>'
          '<path d="M0 %d C %d %d, %d %d, %d %d" stroke="#19b56b" stroke-opacity=".35" stroke-width="3" fill="none"/></svg>'
          % (w, h, candles(w, h, len(cover["out"])), h * .9, w * .3, h * .7, w * .6, h * 1.0, w, h * .55,
             h * .95, w * .35, h * .8, w * .7, h * .9, w, h * .45))
    if dev == "phone":
        sh = 1000 * s
        sw = sh * 482 / 1038
        dw, dh = sw + 2 * v["bez"], sh + 2 * v["bez"] + v["sbh"]
        dx, dy = (w - dw) / 2, 560 * s
        body = ('<div class="glow g1" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>'
                '<div class="glow g3" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>'
                % (w * .1, h * .4, w * .8, h * .45, w * .3, h * .02, w * .4, h * .2))
        body += '<div style="position:absolute;top:%dpx;left:0;right:0;display:flex;flex-direction:column;align-items:center;gap:%dpx;text-align:center">%s<h1>%s</h1></div>' % (70 * s, 34 * s, brand, title)
        body += ('<div class="device" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"><div class="screen" style="height:100%%">%s<img src="%s"></div>'
                 '<div class="cam" style="left:calc(50%% - %dpx);top:%dpx"></div><div class="home"></div></div>'
                 % (dx, dy, dw, dh, (STATUS.replace('class="sbar"', 'class="sbar sbar-light"') if cover.get("light") else STATUS), shot, v["cam"] / 2, v["bez"] + 12 * s))
        body += '<div class="foot" style="bottom:%dpx"><p class="line" style="padding:0 %dpx;margin-bottom:%dpx">%s</p><div class="rule"></div></div>' % (60 * s, 90 * s, 26 * s, cover["line"])
    else:
        ratio = 932 / 1404 if dev == "tablet10" else 800 / 1027
        sw = w * 0.555
        sh = sw * ratio
        dw, dh = sw + 2 * v["bez"], sh + 2 * v["bez"] + v["sbh"]
        dx, dy = w - dw - w * 0.045, (h - dh) / 2 - h * 0.02
        body = ('<div class="glow g1" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>'
                '<div class="glow g2" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"></div>'
                % (dx, dy, dw, dh * .9, w * .02, h * .6, w * .3, h * .4))
        body += ('<div style="position:absolute;left:%dpx;top:%dpx;width:%dpx;display:flex;flex-direction:column;gap:%dpx">%s<h1>%s</h1>'
                 '<div class="rule" style="width:100%%"></div><p class="line">%s</p><div class="feats" style="margin-top:%dpx">%s</div></div>'
                 % (w * .035, h * .07, dx - w * .07, 30 * s, brand, title, cover["line"], 14 * s, feats))
        body += ('<div class="device light" style="left:%dpx;top:%dpx;width:%dpx;height:%dpx"><div class="screen" style="height:100%%">%s<img src="%s"></div>'
                 '<div class="cam" style="left:calc(50%% - %dpx);top:%dpx;width:%dpx;height:%dpx"></div><div class="home"></div></div>'
                 % (dx, dy, dw, dh, (STATUS.replace('class="sbar"', 'class="sbar sbar-light"') if cover.get("light") else STATUS), shot, 9 * s, 12 * s, 18 * s, 18 * s))
        body += '<div class="foot" style="bottom:%dpx;left:%dpx;width:%dpx;right:auto"><p class="line" style="font-size:%dpx">%s</p></div>' % (38 * s, dx, dw, 30 * s, cover.get("foot", ""))
    return "<!doctype html><html><head><meta charset='utf-8'><style>%s</style></head><body>%s%s</body></html>" % (CSS % v, bg, body)


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
        for sub in ("raw", "final"):
            for f in sorted(glob.glob(os.path.join(covers, sub, "*", "*.png"))):
                z.write(f, os.path.relpath(f, covers))
    print(os.path.relpath(covers, mobile.ROOT))


if __name__ == "__main__":
    main()
