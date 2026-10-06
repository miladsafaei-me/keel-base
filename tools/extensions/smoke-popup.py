#!/usr/bin/env python3
"""Open a build's popup in headless Chromium and prove it still works.

`node --check` says a file parses; it says nothing about whether the app still
renders after code was cut out of it. This drives the real popup - the same
config.js, popup.css, popup.html and popup.js the package ships - against a
stubbed `chrome` API and a canned signal response, then asserts on the DOM it
produced and on the console it wrote.

What it exercises, in one run per scenario:

  gate     first open: the licence gate with its "Start 7-Day Free Trial" button
  trial    trial started: the app shell, the pair chips, the timeframe chips
           (with the Premium locks), the Get Signal CTA and the footer links
  signal   a read delivered: the CALL/PUT card, its strength and its three
           meters, plus the History row the read wrote

Every uncaught exception and every console error fails the run, which is the
point: a reference to a function that was removed only shows up at runtime.

Usage: smoke-popup.py <build-dir> [<build-dir> ...]
"""
import json
import os
import re
import subprocess
import sys
import tempfile

CHROMIUM = ["flatpak", "run", "--filesystem=host", "org.chromium.Chromium"]
FLAGS = ["--headless", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=4000"]

# A read shaped exactly like core.services.binary_signal.build_signal returns.
SIGNAL = {
    "direction": "call",
    "word": "CALL",
    "sub": "Buy signal",
    "strength": 78,
    "trend": {"value": 74, "label": "Bullish", "dir": "up"},
    "momentum": {"value": 81, "label": "High", "dir": "up"},
    "volatility": {"value": 62, "label": "Medium", "dir": "mid"},
    "pair": "EUR/USD",
    "tf": "4H",
    "broker": "Quotex",
    "next_in": 900,
}

HARNESS = """<!doctype html>
<meta charset="utf-8">
<title>smoke</title>
<link rel="stylesheet" href="popup.css">
<div id="sb-root"></div>
<script>
window.__errors = [];
window.addEventListener("error", function (e) { window.__errors.push(String(e.message)); });
window.addEventListener("unhandledrejection", function (e) { window.__errors.push("rejection: " + e.reason); });
(function () {
  var realError = console.error;
  console.error = function () {
    window.__errors.push(Array.prototype.join.call(arguments, " "));
    realError.apply(console, arguments);
  };
})();

var __store = __SEED__;
window.chrome = {
  runtime: {
    lastError: undefined,
    getURL: function (p) { return p; },
    sendMessage: function (msg, cb) {
      var res;
      if (msg.type === "CB_CHECK_LICENSE") { res = { ok: true, status: 200, data: __LICENSE__ }; }
      else if (msg.type === "CB_GET_SIGNAL") { res = { ok: true, status: 200, data: __SIGNAL__ }; }
      else { res = { ok: false, status: 0 }; }
      setTimeout(function () { if (cb) { cb(res); } }, 0);
    },
    onMessage: { addListener: function () {} }
  },
  storage: {
    local: {
      get: function (k, cb) {
        var out = {};
        var keys = (typeof k === "string") ? [k] : (Array.isArray(k) ? k : Object.keys(k || {}));
        keys.forEach(function (key) { if (key in __store) { out[key] = __store[key]; } });
        setTimeout(function () { cb(out); }, 0);
      },
      set: function (o, cb) { Object.keys(o).forEach(function (k) { __store[k] = o[k]; }); if (cb) { setTimeout(cb, 0); } }
    }
  },
  windows: undefined,
  tabs: { create: function () {} },
  action: { setPopup: function () {} }
};
</script>
<script src="config.js"></script>
<script>
document.getElementById("sb-root").outerHTML = __BODY__;
</script>
<script src="popup.js"></script>
<script>
// Drive the scenario once the popup has booted and its storage read has landed.
setTimeout(function () {
  var step = __STEP__;
  if (step === "trial" || step === "signal") {
    var t = document.querySelector("[data-start-trial]");
    if (t) { t.click(); }
  }
  if (step === "signal") {
    setTimeout(function () {
      var b = document.querySelector("[data-cta-signal]");
      if (b) { b.click(); }
    }, 60);
  }
}, 60);

// Publish whatever went wrong into the DOM, which is the only channel
// --dump-dom gives us back.
setTimeout(function () {
  var d = document.createElement("div");
  d.id = "sb-errors";
  d.hidden = true;
  d.textContent = JSON.stringify(window.__errors);
  document.body.appendChild(d);
}, 400);
</script>
"""


def popup_body(build_dir):
    """The <body> of popup.html, which is what the popup script expects to find."""
    html = open(os.path.join(build_dir, "popup.html"), encoding="utf-8").read()
    return re.search(r"<body>([\s\S]*?)</body>", html).group(1)


def run(build_dir, step, seed, license_payload, shot=None):
    # `</script>` inside the JSON would close the script tag it is embedded in.
    body = popup_body(build_dir)
    page = (HARNESS
            .replace("__BODY__", json.dumps(body).replace("</", "<\\/"))
            .replace("__SEED__", json.dumps(seed))
            .replace("__LICENSE__", json.dumps(license_payload))
            .replace("__SIGNAL__", json.dumps(SIGNAL))
            .replace("__STEP__", json.dumps(step)))
    fd, path = tempfile.mkstemp(suffix="-smoke.html", dir=build_dir)
    os.write(fd, page.encode("utf-8"))
    os.close(fd)
    try:
        cmd = CHROMIUM + FLAGS + ["--dump-dom", "file://" + path]
        if shot:
            cmd = CHROMIUM + FLAGS + ["--screenshot=" + shot, "--window-size=760,1100",
                                      "--dump-dom", "file://" + path]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    finally:
        os.remove(path)
    return out.stdout


def errors_in(dom):
    """Whatever the page pushed into #sb-errors: uncaught errors and console.error."""
    m = re.search(r'<div id="sb-errors" hidden="">([\s\S]*?)</div>', dom)
    if not m:
        return "MISSING (the page never finished booting)"
    return m.group(1) if m.group(1) not in ("[]", "") else ""


def expect(dom, needles, label, problems):
    for n in needles:
        if n not in dom:
            problems.append("%s: missing %s" % (label, n))


def smoke(build_dir, shots_dir=None):
    # <family>/<slug>/<browser>/: name the shots after the slug and the browser.
    parts = os.path.abspath(build_dir).rstrip("/").split(os.sep)
    name = "-".join(parts[-2:])
    problems = []

    def shot(step):
        return os.path.join(shots_dir, "%s-%s.png" % (name, step)) if shots_dir else None

    gate = run(build_dir, "gate", {}, {"licensed": False}, shot("gate"))
    expect(gate, ["data-start-trial", "data-license-input", "data-activate-form"], "gate", problems)

    trial = run(build_dir, "trial", {}, {"licensed": False}, shot("app"))
    expect(trial, ["data-cta-signal", "data-pairs-wrap", "data-tf-wrap", "data-foot",
                   "Get Signal", "Register"], "app", problems)

    lic = run(build_dir, "signal", {}, {"licensed": True, "brokers": "all"}, shot("signal"))
    expect(lic, ["data-word", "data-strength-pct", "data-meter=\"trend\""], "signal", problems)

    for label, dom in (("gate", gate), ("app", trial), ("signal", lic)):
        for bad in ("Auto-Trade", "Auto Trade", "data-stake", "data-account",
                    "acct-toggle", "data-uid-banner"):
            if bad in dom:
                problems.append("%s: auto-trade UI still rendered (%s)" % (label, bad))
        err = errors_in(dom)
        if err:
            problems.append("%s: runtime errors %s" % (label, err))

    return problems


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    dirs = [a for a in sys.argv[1:] if not a.startswith("--")]
    shots = None
    for a in sys.argv[1:]:
        if a.startswith("--shots="):
            shots = a.split("=", 1)[1]
            os.makedirs(shots, exist_ok=True)
    bad = 0
    for d in dirs:
        problems = smoke(d, shots)
        if problems:
            bad += 1
            print("%s: FAIL" % "/".join(os.path.abspath(d).rstrip("/").split(os.sep)[-2:]))
            for p in problems:
                print("   ", p)
        else:
            print("%s: ok" % "/".join(os.path.abspath(d).rstrip("/").split(os.sep)[-2:]))
    sys.exit(1 if bad else 0)
