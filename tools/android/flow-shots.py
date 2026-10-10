#!/usr/bin/env python3
"""Every state of an app as a screenshot, for the designer's store covers, into <family>/<slug>/covers/screenshots/.

cover-shots.py makes the five headline scenes. This makes the rest: each tab, each step of the chat, each open
dropdown or list, each locked and licensed state. The states are the member's own, listed in <slug>/shots.json:

  {"shots": [
    {"name": "gate", "store": "gate", "actions": []},
    {"name": "broker-open", "store": "trial", "actions": [["click", "button", "Pocket Option"], ["wait", 500]]}
  ]}

  block    optional list of URL fragments whose requests are aborted (a failed read); allow_errors: true tolerates the console error
  stub_licence  true: the licence check answers "licensed" whatever store is used (to activate a key during the shots)
  store    gate (first start, no trial), ended (the 7-day trial is over, gate again), trial (trial running, the default), licensed (a licence is active)
  actions  run in order on a fresh page; "wait_for" (a selector) is awaited before the picture is taken
    ["click", css, text?]      click the first match (text narrows it to the element containing that text)
    ["clicklast", css, text?]  click the last match (the live keyboard of a chat is the last one)
    ["fill", css, value]       type into a field
    ["press", key]             press a key
    ["scroll", css, px]        scroll an element by px (0 scrolls it to its end)
    ["eval", js]               run a JavaScript snippet in the page (for a state the stubbed native side makes too early)
    ["wait", ms]               pause
    ["wait_for", css]          wait for a selector, up to 60 s (a live read), then 1.2 s more so it has settled
    ["eval", js]               run a JavaScript expression in the page (to nudge a state the app should reach by itself)
    ["wait_now", css]          wait for a selector with no settling pause (a state that passes quickly, like a progress bar)

Files: covers/screenshots/{phone,tablet 7,tablet 10}/NN-name.png at the same sizes as cover-shots.py (482x1038, 1027x800,
1404x932), dark theme, no system bars, rendered at double density and scaled to the exact size. Also covers/screenshots/index.txt,
the list of what each number is. A step that cannot be driven fails loudly; a picture of the wrong state is never kept.

Usage: flow-shots.py <slug> [--theme dark|light] [--only name,name]
"""
import argparse
import json
import os
import shutil
import sys
import time

from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import mobile  # noqa: E402
import render  # noqa: E402

SETS = [("phone", "cover-phone", (482, 1038)), ("tablet 7", "cover-7", (1027, 800)), ("tablet 10", "cover-10", (1404, 932))]


def store_for(kind):
    if kind == "gate":
        return None
    if kind == "ended":
        st = render.state("app")
        st["trialStart"] -= 30 * render.DAY
        return st
    return render.state("access" if kind == "licensed" else "app")


def act(page, a):
    op = a[0]
    if op in ("click", "clicklast"):
        loc = page.locator(a[1], has_text=a[2]) if len(a) > 2 else page.locator(a[1])
        (loc.last if op == "clicklast" else loc.first).click(timeout=20000)
        page.wait_for_timeout(500)
    elif op == "fill":
        page.locator(a[1]).first.fill(a[2])
    elif op == "press":
        page.keyboard.press(a[1])
        page.wait_for_timeout(300)
    elif op == "scroll":
        page.locator(a[1]).first.evaluate("(e, px) => { e.scrollTop = px || e.scrollHeight; }", a[2])
        page.wait_for_timeout(300)
    elif op == "eval":
        page.evaluate(a[1])
        page.wait_for_timeout(500)
    elif op == "wait":
        page.wait_for_timeout(a[1])
    elif op == "eval":
        page.evaluate(a[1])
        page.wait_for_timeout(300)
    elif op == "wait_now":
        page.wait_for_selector(a[1], timeout=60000)
    elif op == "wait_for":
        page.wait_for_selector(a[1], timeout=60000)
        page.wait_for_timeout(1200)
    else:
        raise ValueError("unknown action " + op)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    brand = mobile.brand()
    m, mdir = mobile.member(args.slug)
    site = brand["app"]["site"].rstrip("/")
    recipe = json.load(open(os.path.join(mdir, "shots.json")))["shots"]
    only = set(filter(None, args.only.split(",")))
    out = os.path.join(mdir, "covers", "screenshots")
    if not only:
        shutil.rmtree(out, ignore_errors=True)
    failures = 0
    insets = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for folder, size, target in SETS:
            w, h = render.SIZES[size]
            os.makedirs(os.path.join(out, folder), exist_ok=True)
            for n, shot in enumerate(recipe, 1):
                if only and shot["name"] not in only:
                    continue
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, is_mobile=True, has_touch=True,
                                          color_scheme=args.theme, user_agent="Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36")
                ctx.route(site + "/app/**", render.serve(mdir))
                for part in shot.get("block", []):
                    ctx.route("**/*" + part + "*", lambda r: r.abort())
                if shot.get("store") == "licensed" or shot.get("stub_licence"):
                    ctx.route(site + "/s-api/licenses*", lambda r, q: r.fulfill(status=200, content_type="application/json",
                              body=json.dumps({m["item"]: {"licensed": True, "expires_at": "2027-04-06T00:00:00Z"}})))
                    ctx.route(site + "/s-api/license?*", lambda r, q: r.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"licensed": True, "brokers": [], "expires_at": "2027-04-06T00:00:00Z"})))
                ctx.add_init_script("""(() => {
                    const s = %s;
                    try { if (s && !localStorage.getItem('sa-store')) localStorage.setItem('sa-store', JSON.stringify(s)); } catch (e) {}
                    window.SignalAndroid = { theme() {}, open() {}, version() { return %s; } };
                    document.addEventListener('DOMContentLoaded', () => window.signalShell && window.signalShell.insets(%s));
                })();""" % (json.dumps(store_for(shot.get("store", "trial"))), json.dumps(m["version_name"]), json.dumps(insets)))
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e, errors=errors: errors.append("page error: %s" % e))
                page.on("console", lambda msg, errors=errors: msg.type == "error" and "favicon" not in msg.text and errors.append("console: " + msg.text))
                page.goto("%s/app/index.html?system=%s" % (site, args.theme))
                page.wait_for_timeout(900)
                problem = None
                try:
                    for a in shot["actions"]:
                        act(page, a)
                    if shot.get("wait_for"):
                        page.wait_for_selector(shot["wait_for"], timeout=60000)
                        page.wait_for_timeout(1200)
                except Exception as e:
                    problem = str(e).splitlines()[0]
                if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"):
                    problem = problem or "the page scrolls sideways"
                if errors and not shot.get("allow_errors"):
                    problem = problem or errors[0]
                raw = os.path.join(out, folder, "_raw.png")
                page.screenshot(path=raw)
                ctx.close()
                if problem:
                    failures += 1
                    print("FAIL %-9s %02d-%s: %s" % (folder, n, shot["name"], problem))
                    os.remove(raw)
                    continue
                Image.open(raw).convert("RGB").resize(target, Image.LANCZOS).save(os.path.join(out, folder, "%02d-%s.png" % (n, shot["name"])), optimize=True)
                os.remove(raw)
                print("ok   %-9s %02d-%s" % (folder, n, shot["name"]))
        browser.close()
    with open(os.path.join(out, "index.txt"), "w") as f:
        for n, shot in enumerate(recipe, 1):
            f.write("%02d-%s\t%s\n" % (n, shot["name"], shot.get("title", "")))
    print(os.path.relpath(out, mobile.ROOT))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
