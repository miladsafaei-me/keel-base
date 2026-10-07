#!/usr/bin/env python3
"""Render a member's app as the phone's WebView shows it, and prove it works.

Loads <family>/<slug>/android/assets/index.html at https://<site>/app/index.html in headless Chromium (the engine the
Android WebView is), with the files served from disk exactly as WebViewAssetLoader serves them in the APK, and every
other request going to the live site, so each read is the real signal engine's. The native side is stood in for: the
system bar insets (a 24dp status bar, a 24dp gesture bar) and window.SignalAndroid.

Scenarios, each in the light and the dark theme, at every size:

  gate      first start: the licence gate, its key field, the trial button, the partner link and its disclosure
  app       trial started: the chat with its menu, the tab bar
  forecast  trial, a forecast asked through the keys: OTC, Currency pairs, the first pair, 4h; the card lands
  locked    trial, Get forecast, a locked period tapped: the Access tab opens
  access    licensed (the licence check stubbed): the plan card and this phone's licence
  more      the More tab: appearance, help, legal, partner link, version

A scenario fails on an uncaught error or a console.error, on a missing landmark, on sideways scrolling, and on a touch
target under 44px. The forecast scenario also fails when the forecast's direction banner is not whole inside the chat.

Usage: render.py <slug> [--sizes phone,tablet] [--scenarios gate,app] [--themes light,dark] [--out DIR] [--dpr 2]
Sizes: phone 360x780, phone-l 412x915, tablet 768x1024, tablet-l 1280x800, play 360x640 (at --dpr 3 that is the
1080x1920 a Google Play phone screenshot takes). The cover-* sizes have the aspect of the screen inside the
device frame of a store cover (cover-shots.py).
"""
import argparse
import json
import mimetypes
import os
import sys
import time

from playwright.sync_api import sync_playwright

import mobile

SIZES = {"phone": (360, 780), "phone-l": (412, 915), "tablet": (768, 1024), "tablet-l": (1280, 800), "play": (360, 640),
         "play-7": (600, 960), "play-10": (800, 1280),
         "cover-phone": (412, 887), "cover-7": (1024, 798), "cover-10": (1280, 850)}
SCENARIOS = ["gate", "app", "forecast", "locked", "access", "more"]
INSETS = {"top": int(os.environ.get("INSET_TOP", 24)), "bottom": int(os.environ.get("INSET_BOTTOM", 24)), "left": 0, "right": 0}
DAY = 24 * 3600 * 1000


def serve(mdir):
    roots = [os.path.join(mdir, "android", "assets"), os.path.join(mobile.ROOT, "shell", "assets")]

    def handler(route, request):
        path = request.url.split("/app/", 1)[1].split("?", 1)[0]
        for r in roots:
            f = os.path.join(r, path)
            if os.path.isfile(f):
                ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
                route.fulfill(status=200, body=open(f, "rb").read(), headers={"Content-Type": ctype})
                return
        route.fulfill(status=404, body="")
    return handler


def state(scenario):
    now = int(time.time() * 1000)
    if scenario == "gate":
        return None
    store = {"trialStart": now - DAY, "license": None, "signedOut": False, "notice": None}
    if scenario == "access":
        store["license"] = {"key": "ATB-DEMO7K2Q9X", "token": None, "brokers": [], "expires_at": "2027-04-06T00:00:00Z", "checkedAt": now}
    return store


def check(page, errors, scenario, cfg):
    problems = list(errors)
    sideways = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    if sideways:
        problems.append("the page scrolls sideways")
    small = page.evaluate("""() => [...document.querySelectorAll('button, a[href], input, summary, [role=radio]')]
        .filter(e => e.offsetParent !== null && !e.closest('[hidden]'))
        .map(e => [e, e.getBoundingClientRect()])
        .filter(([e, r]) => r.width > 0 && (r.height < 44 || r.width < 44) && !e.closest('.sa-help__steps, .sa-risk, .gtp-app__foot, .gpt-app__foot'))
        .map(([e, r]) => `${e.tagName.toLowerCase()}.${(e.className.baseVal ?? e.className).split(' ')[0]} "${e.textContent.trim().slice(0, 24)}" ${Math.round(r.width)}x${Math.round(r.height)}`)""")
    problems += ["touch target under 44px: " + s for s in small]
    marks = {"gate": ["#sa-gate:not([hidden])", "[data-affiliate-disclosure]", "[data-start-trial]"],
             "app": ["#sa-tabs:not([hidden])", cfg.get("landmark", ".gtp-chat")], "forecast": [cfg.get("landmark", ".gtp-chat")], "locked": ["#sa-pane-access:not([hidden])"],
             "access": ["[data-plan-state].is-licensed"], "more": ["#sa-pane-more:not([hidden])", "[data-affiliate-link]"]}[scenario]
    for sel in marks:
        if not page.query_selector(sel):
            problems.append("missing " + sel)
    return problems


def tap(page, text, timeout=20000):
    page.locator("#sa-pane-app .gtp-kb[data-live] .gtp-key", has_text=text).last.click(timeout=timeout)


def drive_steps(page, scenario, cfg):
    """A member whose app is not the chat names its own recipe in member.json "render": steps (a list of selectors to
    click) for forecast and locked, and "result" (wait, see, within) for the answer that must be whole on screen."""
    for sel in cfg["steps"][scenario]:
        page.locator(sel).first.click(timeout=20000)
        page.wait_for_timeout(500)
    if scenario == "locked":
        page.wait_for_timeout(400)
        return []
    res = cfg["result"]
    page.wait_for_selector(res["wait"], timeout=60000)
    page.wait_for_timeout(1500)
    hidden = page.evaluate("""([see, within]) => {
        const a = document.querySelector(see).getBoundingClientRect();
        const b = document.querySelector(within).getBoundingClientRect();
        return Math.max(0, b.top - a.top, a.bottom - b.bottom); }""", [res["see"], res["within"]])
    return ["the forecast's direction is %dpx outside its pane" % hidden] if hidden > 1 else []


def drive(page, scenario, cfg):
    if scenario in ("forecast", "locked") and cfg.get("steps"):
        return drive_steps(page, scenario, cfg)
    if scenario in ("forecast", "locked"):
        tap(page, "Get forecast")
        page.wait_for_timeout(900)
        tap(page, "Currency pairs")
        page.wait_for_timeout(900)
        page.locator("#sa-pane-app .gtp-kb[data-live]").last.locator(".gtp-key").first.click()
        page.wait_for_timeout(900)
        if scenario == "locked":
            page.locator("#sa-pane-app .gtp-kb[data-live] .gtp-key[data-locked]").first.click()
            page.wait_for_timeout(400)
            return []
        tap(page, "4h")
        page.wait_for_selector("#sa-pane-app .gtp-banner", timeout=60000)
        page.wait_for_timeout(1500)
        # The direction is what a trader reads first: the newest banner shows whole inside the chat.
        hidden = page.evaluate("""() => {
            const banners = document.querySelectorAll('#sa-pane-app .gtp-banner');
            const banner = banners[banners.length - 1].getBoundingClientRect();
            const chat = document.querySelector('#sa-pane-app .gtp-chat').getBoundingClientRect();
            return Math.max(0, chat.top - banner.top, banner.bottom - chat.bottom); }""")
        return ["the forecast's direction is %dpx outside the chat" % hidden] if hidden > 1 else []
    if scenario == "access":
        page.click("[data-tab=access]")
    if scenario == "more":
        page.click("[data-tab=more]")
    page.wait_for_timeout(300)
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--sizes", default="phone,tablet")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--dpr", type=float, default=2)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-insets", action="store_true", help="draw without system bars (store screenshots)")
    args = ap.parse_args()
    brand = mobile.brand()
    m, mdir = mobile.member(args.slug)
    site = brand["app"]["site"].rstrip("/")
    out = args.out or os.path.join(mdir, "renders")
    os.makedirs(out, exist_ok=True)
    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for size in args.sizes.split(","):
            w, h = SIZES[size]
            for theme in args.themes.split(","):
                for scenario in args.scenarios.split(","):
                    ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=args.dpr, is_mobile=True, has_touch=True,
                                              color_scheme=theme, user_agent="Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36")
                    ctx.route(site + "/app/**", serve(mdir))
                    if scenario == "access":
                        ctx.route(site + "/s-api/license?*", lambda r, q: r.fulfill(status=200, content_type="application/json",
                                  body=json.dumps({"licensed": True, "brokers": [], "expires_at": "2027-04-06T00:00:00Z"})))
                    insets = {"top": 0, "bottom": 0, "left": 0, "right": 0} if args.no_insets else INSETS
                    store = state(scenario)
                    ctx.add_init_script("""(() => {
                        const s = %s;
                        try { if (s && !localStorage.getItem('sa-store')) localStorage.setItem('sa-store', JSON.stringify(s)); } catch (e) {}
                        window.SignalAndroid = { theme() {}, open() {}, version() { return %s; } };
                        document.addEventListener('DOMContentLoaded', () => window.signalShell && window.signalShell.insets(%s));
                    })();""" % (json.dumps(store), json.dumps(m["version_name"]), json.dumps(insets)))
                    page = ctx.new_page()
                    errors = []
                    page.on("pageerror", lambda e, errors=errors: errors.append("page error: %s" % e))
                    page.on("console", lambda msg, errors=errors: msg.type == "error" and "favicon" not in msg.text and errors.append("console: " + msg.text))
                    page.goto("%s/app/index.html?system=%s" % (site, theme))
                    page.wait_for_timeout(700)
                    try:
                        problems = drive(page, scenario, m.get("render", {}))
                    except Exception as e:  # a missing key or a read that never landed
                        problems = ["could not drive %s: %s" % (scenario, str(e).splitlines()[0])]
                    problems += check(page, errors, scenario, m.get("render", {}))
                    shot = os.path.join(out, "%s-%s-%s.png" % (size, scenario, theme))
                    page.screenshot(path=shot)
                    status = "ok" if not problems else "FAIL"
                    failures += bool(problems)
                    print("%-4s %-8s %-8s %-5s %s" % (status, size, scenario, theme, os.path.relpath(shot, mobile.ROOT)))
                    for p in problems:
                        print("       " + p)
                    ctx.close()
        browser.close()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
