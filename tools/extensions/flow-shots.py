#!/usr/bin/env python3
"""Store and cover screenshots of a signal extension's popup, state by state.

Drives the REAL popup of a Chrome build (popup.html, popup.css, config.js,
popup.js and the site/ app inside it) in headless Chromium through Playwright,
against a stubbed `chrome` API. The signal reads and the licence checks are not
canned: the stub's runtime.sendMessage rebuilds the URL exactly as background.js
does and the request is made, from Python, to the live site's signal API, so the
CALL/PUT/WAIT cards show real engine reads. The one exception is a licence key
that only exists in the recipe (store "licensed"): no real key is committed, so
that verdict is stubbed and the key is left off the signal request, which keeps
the free expiries readable.

The popup is loaded at https://<site>/__ext__/popup.html (the files are served
from the build through route interception), so it runs on an https origin.

Per extension, a recipe <extension>/shots.json lists the states:

  {
    "window": {"width": 560, "height": 1030},      optional, default config.js WINDOW
    "stage": "#031833",                             optional, default --navy-900 of site/site.css
    "states": [
      {"name": "licence-gate", "title": "First open: the licence gate",
       "store": "gate" | "trial" | "ended" | "licensed",
       "base": "other-state-name",                  optional: replay its actions first
       "actions": [ ... ],
       "wait_for": "css"}                           optional: must be visible before the shot
    ]
  }

Actions, run in order on a fresh page:
  {"click": css, "text": "...", "nth": -1}
                                  click a match (text filters by visible text; nth 0 = first, -1 = last)
  {"fill": css, "value": "..."}   set an input
  {"type": css, "value": "..."}   type key by key
  {"press": css, "key": "Enter"}  press a key on an element
  {"hover": css}
  {"scroll": css, "y": 400}       scroll an element (or the page if css is "window")
  {"wait": 500}                   milliseconds
  {"wait_for": css}               wait until visible (30 s)

Outputs, in <extension>/covers/:
  screenshots/NN-name.png   the popup alone, dark, device scale 2, at the window size
  screenshots/index.txt     NN-name and title, one per line
  store/NN-name.png         with --store only: 1280x800, the popup on a plain stage with a window shadow
The designed store covers are made from these by store-covers.py.

Usage:
  flow-shots.py <extension-dir> [<extension-dir> ...] [--only name,name] [--store]
where <extension-dir> holds chrome/ and shots.json.
Python: ~/.local/share/keel-render-venv/bin/python (playwright + PIL).
"""
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFilter
from playwright.sync_api import sync_playwright

SCALE = 2
STORE_SIZE = (1280, 800)
STORE_POPUP_HEIGHT = 720
RADIUS = 12
DAY = 24 * 60 * 60 * 1000
LICENCE_KEY = "ATB-TESTTESTAB"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

STUB = """
(() => {
  const seed = %(seed)s;
  const KEY = seed.storeKey;
  let data;
  try { data = JSON.parse(localStorage.getItem("__flow_store") || "null"); } catch (e) { data = null; }
  if (!data) { data = { [KEY]: seed.store }; }
  const save = () => { try { localStorage.setItem("__flow_store", JSON.stringify(data)); } catch (e) {} };
  try { localStorage.setItem("atb-theme", "dark"); } catch (e) {}
  save();
  const params = (s) => new URLSearchParams(s || "");
  window.chrome = {
    runtime: {
      lastError: undefined,
      getURL: (p) => p,
      onMessage: { addListener() {} },
      sendMessage(msg, cb) {
        const CFG = window[seed.prefix + "_CONFIG"];
        const reply = (r) => setTimeout(() => cb && cb(r), 0);
        if (msg.type === seed.prefix + "_GET_SIGNAL") {
          const req = msg.payload || {};
          const p = params(req.query);
          p.set("item", CFG.ITEM);
          p.delete("key");
          if (req.key && req.key !== seed.placeholderKey) p.set("key", req.key);
          window.__flow_relay(CFG.SIGNAL_URL + "?" + p.toString()).then(reply);
          return;
        }
        if (msg.type === seed.prefix + "_CHECK_LICENSE") {
          const req = msg.payload || {};
          if (req.key && req.key === seed.placeholderKey) {
            reply({ ok: true, status: 200, data: { licensed: true, brokers: "all", expires_at: seed.expires } });
            return;
          }
          const p = new URLSearchParams();
          p.set("item", CFG.ITEM);
          if (req.key) p.set("key", req.key);
          if (req.lt) p.set("lt", req.lt);
          window.__flow_relay(CFG.LICENSE_URL + "?" + p.toString()).then(reply);
          return;
        }
        reply(undefined);
      },
    },
    storage: { local: {
      get(k, cb) {
        const out = {};
        const keys = typeof k === "string" ? [k] : Array.isArray(k) ? k : Object.keys(k || {});
        keys.forEach((key) => { if (key in data) out[key] = data[key]; });
        setTimeout(() => cb(out), 0);
      },
      set(o, cb) { Object.assign(data, o); save(); if (cb) setTimeout(cb, 0); },
    } },
    windows: undefined,
    tabs: { create() {} },
    action: { setPopup() {} },
  };
})();
"""


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def detect(chrome_dir):
    """The storage key, the message prefix and the window of a build."""
    popup = read(os.path.join(chrome_dir, "popup.js"))
    background = read(os.path.join(chrome_dir, "background.js"))
    config = read(os.path.join(chrome_dir, "config.js"))
    store_key = re.search(r'STORE_KEY\s*=\s*"(\w+)"', popup).group(1)
    prefix = re.search(r'msg\.type === "([A-Z]+)_GET_SIGNAL"', background).group(1)
    site = re.search(r'var SITE = "(https?://[^"]+)"', config).group(1)
    win = re.search(r"WINDOW:\s*\{\s*width:\s*(\d+),\s*height:\s*(\d+)", config)
    return store_key, prefix, site, (int(win.group(1)), int(win.group(2)))


def stage_colour(chrome_dir):
    css = read(os.path.join(chrome_dir, "site", "site.css"))
    m = re.search(r"--navy-900:\s*(#[0-9a-fA-F]{6})", css)
    return m.group(1) if m else "#031833"


def seed_for(store_name, store_key, prefix, extra):
    now = int(time.time() * 1000)
    store = {"trialStart": None, "license": None, "signedOut": False, "notice": None}
    expires = "2027-12-31T00:00:00+00:00"
    if store_name == "ended":
        store["trialStart"] = now - 10 * DAY
    if store_name == "trial":
        store["trialStart"] = now
    if store_name == "licensed":
        store["trialStart"] = now - 2 * DAY
        store["license"] = {"key": LICENCE_KEY, "token": None, "session": False, "brokers": "all",
                            "expires_at": expires, "checkedAt": now}
    store.update(extra or {})
    return {"store": store, "storeKey": store_key, "prefix": prefix,
            "placeholderKey": LICENCE_KEY, "expires": expires}


def make_relay(log):
    """Fetch a URL from the live site the way the background worker does."""
    def relay(url):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, body = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, body = err.code, err.read()
        except Exception as err:  # network down: the popup shows its own offline message
            log.append("relay failed: %s (%s)" % (url, err))
            return {"ok": False, "status": 0, "error": str(err)}
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = None
        log.append("%d %s" % (status, re.sub(r"key=[^&]+", "key=...", url)))
        return {"ok": 200 <= status < 300, "status": status, "data": data}
    return relay


def locate(page, css, text=None, nth=0):
    loc = page.locator(css)
    if text:
        loc = loc.filter(has_text=text)
    return loc.last if nth == -1 else loc.nth(nth)


def run_action(page, act):
    if "click" in act:
        loc = locate(page, act["click"], act.get("text"), act.get("nth", 0))
        loc.wait_for(state="visible", timeout=10000)
        loc.click()
    elif "fill" in act:
        loc = locate(page, act["fill"])
        loc.wait_for(state="visible", timeout=10000)
        loc.fill(act["value"])
    elif "type" in act:
        loc = locate(page, act["type"])
        loc.wait_for(state="visible", timeout=10000)
        loc.click()
        page.keyboard.type(act["value"], delay=30)
    elif "press" in act:
        locate(page, act["press"]).press(act["key"])
    elif "hover" in act:
        locate(page, act["hover"], act.get("text"), act.get("nth", 0)).hover()
    elif "scroll" in act:
        if act["scroll"] == "window":
            page.evaluate("(y) => window.scrollTo(0, y)", act.get("y", 0))
        else:
            locate(page, act["scroll"]).evaluate("(el, y) => { el.scrollTop = y; }", act.get("y", 0))
    elif "wait" in act:
        page.wait_for_timeout(int(act["wait"]))
    elif "wait_for" in act:
        page.locator(act["wait_for"]).first.wait_for(state="visible", timeout=10000)
    else:
        raise ValueError("unknown action %r" % (act,))


def resolve(states, state, seen=()):
    """The state's store and its full action list, its base replayed first."""
    if state.get("base"):
        base = next(s for s in states if s["name"] == state["base"])
        if base["name"] in seen:
            raise ValueError("base loop at " + base["name"])
        base_store, base_actions = resolve(states, base, seen + (state["name"],))
    else:
        base_store, base_actions = "gate", []
    return state.get("store", base_store), base_actions + state.get("actions", [])


def serve(route, chrome_dir):
    path = urlparse(route.request.url).path.split("/__ext__/", 1)[-1] or "popup.html"
    full = os.path.normpath(os.path.join(chrome_dir, path))
    if full.startswith(chrome_dir) and os.path.isfile(full):
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        route.fulfill(status=200, body=open(full, "rb").read(), headers={"Content-Type": ctype})
    else:
        route.fulfill(status=404, body="")


def capture(browser, chrome_dir, site, store_key, prefix, win, states, state, out_path):
    store_name, actions = resolve(states, state)
    context = browser.new_context(viewport={"width": win[0], "height": win[1]}, device_scale_factor=SCALE,
                                  color_scheme="dark", user_agent=UA)
    problems, relay_log = [], []
    context.route(site + "/__ext__/**", lambda r: serve(r, chrome_dir))
    context.route(re.compile(r"^(?!data:|blob:).*"), lambda r: r.fallback()
                  if "/__ext__/" in r.request.url else r.abort())
    page = context.new_page()
    page.on("pageerror", lambda e: problems.append("pageerror: %s" % e))
    page.on("console", lambda m: problems.append("console.error: %s" % m.text) if m.type == "error" else None)
    page.expose_function("__flow_relay", make_relay(relay_log))
    page.add_init_script(STUB % {"seed": json.dumps(seed_for(store_name, store_key, prefix, state.get("store_extra")))})
    page.goto(site + "/__ext__/popup.html")
    page.wait_for_selector("[id$='-gate']:not([hidden]), [id$='-app']:not([hidden])", timeout=10000)
    for act in actions:
        run_action(page, act)
    if state.get("wait_for"):
        page.locator(state["wait_for"]).first.wait_for(state="visible", timeout=10000)
    if not any("hover" in a for a in actions):
        page.mouse.move(0, 0)  # no stray hover highlight on whatever sat under the pointer
    page.wait_for_timeout(int(state.get("settle", 700)))
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        problems.append("horizontal scroll")
    page.screenshot(path=out_path)
    context.close()
    return problems, relay_log


def store_image(popup_path, out_path, stage):
    """The popup, scaled to fit, centred on a plain stage with a window shadow."""
    pop = Image.open(popup_path).convert("RGBA")
    h = STORE_POPUP_HEIGHT
    w = round(pop.width * h / pop.height)
    pop = pop.resize((w, h), Image.LANCZOS)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=RADIUS, fill=255)
    pop.putalpha(mask)
    canvas = Image.new("RGBA", STORE_SIZE, stage)
    x, y = (STORE_SIZE[0] - w) // 2, (STORE_SIZE[1] - h) // 2
    shadow = Image.new("RGBA", STORE_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x, y + 14, x + w, y + h + 14), radius=RADIUS, fill=(0, 0, 0, 150))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(26)))
    canvas.alpha_composite(pop, (x, y))
    canvas.convert("RGB").save(out_path)


def run_extension(browser, ext_dir, only, make_store):
    ext_dir = os.path.abspath(ext_dir)
    chrome_dir = os.path.join(ext_dir, "chrome")
    recipe = json.loads(read(os.path.join(ext_dir, "shots.json")))
    store_key, prefix, site, cfg_win = detect(chrome_dir)
    w = recipe.get("window") or {}
    win = (w.get("width", cfg_win[0]), w.get("height", cfg_win[1]))
    stage = recipe.get("stage") or stage_colour(chrome_dir)
    out = os.path.join(ext_dir, "covers", "screenshots")
    store_out = os.path.join(ext_dir, "covers", "store")
    dirs = [out] + ([store_out] if make_store else [])
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    states = recipe["states"]
    failures = 0
    if not only:  # a full run owns the folders: drop shots of states that no longer exist
        keep = {"%02d-%s.png" % (i, st["name"]) for i, st in enumerate(states, 1)}
        for d in dirs:
            for old in os.listdir(d):
                if old.endswith(".png") and old not in keep:
                    os.remove(os.path.join(d, old))
    for i, state in enumerate(states, 1):
        if only and state["name"] not in only:
            continue
        fname = "%02d-%s.png" % (i, state["name"])
        popup_path = os.path.join(out, fname)
        try:
            problems, relay_log = capture(browser, chrome_dir, site, store_key, prefix, win, states, state, popup_path)
        except Exception as exc:
            print("FAIL %s/%s: %s" % (os.path.basename(ext_dir), fname, str(exc).splitlines()[0]))
            failures += 1
            continue
        if make_store:
            store_image(popup_path, os.path.join(store_out, fname), stage)
        reads = [r for r in relay_log if "/s-api/" in r]
        print("%s %s/%s  api: %s" % ("WARN" if problems else "ok  ", os.path.basename(ext_dir), fname,
                                     ", ".join(r.split("/s-api/")[0].strip() + " " + r.split("/s-api/")[1][:30] for r in reads) or "-"))
        for p in problems:
            print("     " + p)
        failures += bool(problems)
    with open(os.path.join(out, "index.txt"), "w", encoding="utf-8") as fh:
        for i, state in enumerate(states, 1):
            fh.write("%02d-%s  %s\n" % (i, state["name"], state["title"]))
    return failures


def main(argv):
    only, make_store, dirs = None, False, []
    args = iter(argv)
    for a in args:
        if a == "--only":
            only = set(next(args).split(","))
        elif a.startswith("--only="):
            only = set(a.split("=", 1)[1].split(","))
        elif a == "--store":
            make_store = True
        elif a == "--no-store":
            make_store = False
        else:
            dirs.append(a)
    if not dirs:
        sys.exit(__doc__)
    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for d in dirs:
            failures += run_extension(browser, d, only, make_store)
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
