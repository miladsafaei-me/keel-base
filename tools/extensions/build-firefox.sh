#!/usr/bin/env bash
#
# Build a Firefox package from the Chrome build of the same extension.
#
# The two are the SAME code. Everything that differs between the browsers is
# either in the manifest or in firefox-shim.js, so this script copies the shipped
# files across untouched, rewrites only the manifest, and then verifies byte for
# byte that nothing else drifted. Hand-copying is how a Firefox build ends up
# quietly running different code from the Chrome one it is supposed to mirror.
#
# What actually differs:
#
#   background      Firefox has no MV3 service worker. Its background is an event
#                   page, declared as background.scripts, which also means
#                   config.js is loaded by the manifest rather than by
#                   importScripts (background.js guards that call for exactly this
#                   reason, so the file itself stays identical).
#   gecko settings  browser_specific_settings.gecko carries the add-on id AMO keys
#                   updates to, the minimum Firefox, and the data-collection
#                   disclosure Firefox 140+ requires.
#   firefox-shim.js Loaded ahead of everything in the background. It fixes two
#                   real Firefox behaviours: instanceof against ArrayBuffer/Blob
#                   fails across compartments, and structured-clone rejects some
#                   objects that Chrome passes through sendMessage happily.
#
# strict_min_version is 142.0. Two things set that floor and neither is arbitrary:
# content scripts in the MAIN world, which every broker's tap (po-tap.js,
# qx-tap.js) needs to see the page's own socket, landed in Firefox 128; and
# data_collection_permissions — required below —
# only reached Firefox for Android in 142, which addons-linter flags as an error
# against any lower minimum. 142 shipped in 2025, so the exclusion is theoretical.
#
# gecko_android carries the same 142.0 floor as gecko. Desktop opens its UI with
# windows.create({type:"popup"}) next to a broker tab; Firefox for Android has no
# windows API at all, so background.js feature-detects it at load time and falls
# back to chrome.action.setPopup("popup.html") there instead — the ordinary
# mobile action popup, same popup.html/popup.js, no separate window. Declaring
# gecko_android used to list a mode that could not run; now it can.
#
# Shared by every site's extension repo, whose tools/ folder links here; the
# brand is the repo's own brand.json (see brand.py).
#
# Usage: tools/build-firefox.sh <slug>
#
# The add-on id and any store-specific product name come from the repo's
# store-listings.json, so a rebuild cannot forget either. An explicit
# gecko-id argument and --name still override, for a one-off.

set -euo pipefail

SLUG="${1:?usage: build-firefox.sh <slug> [<gecko-id>] [--name \"Product Name\"]}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Every tool this script runs works on the same repo, wherever it is run from.
export EXT_ROOT="${EXT_ROOT:-$(python3 "$HERE/brand.py" root)}"
TOOLS="$HERE"
# Both of these are DURABLE properties of a listing rather than choices made at
# build time, so they are declared once in store-listings.json and read from
# there. Passing them by hand is how a rebuild silently produces the wrong
# package: the name reverting to one the store already rejected, or the add-on id
# drifting and opening a SECOND AMO listing instead of updating the first.
# Arguments still override, for a one-off.
GECKO_ID="${2:-}"
GECKO_DOMAIN="$(python3 "$TOOLS/brand.py" get gecko_id_domain)"
[ -n "$GECKO_ID" ] || GECKO_ID="$(python3 "$TOOLS/listing.py" firefox "$SLUG" id "${SLUG}@${GECKO_DOMAIN}")"
LOGO="$(python3 "$TOOLS/brand.py" get logo_file)"

NEW_NAME=""
shift $(( $# > 2 ? 2 : $# ))
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NEW_NAME="${2:?--name needs a value}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
[ -n "$NEW_NAME" ] || NEW_NAME="$(python3 "$TOOLS/listing.py" firefox "$SLUG" name)"

# <family>/<slug>/chrome/ in, <family>/<slug>/firefox/ out - see layout.py.
SRC="$(python3 "$TOOLS/layout.py" dir "$SLUG" chrome)"
OUT="$(python3 "$TOOLS/layout.py" dir "$SLUG" firefox)"

[ -d "$SRC" ] || { echo "no chrome build at $SRC" >&2; exit 1; }
[ -f "$HERE/firefox-shim.js" ] || { echo "no firefox-shim.js in $HERE" >&2; exit 1; }

# The shipped file list is READ OFF the Chrome manifest, not hardcoded - see
# manifest-files.py. It used to name PocketOption's engine and tap
# literally, which meant every other broker's build silently shipped without its
# socket engine, the one file the extension cannot work without.
mapfile -t LISTED < <(python3 "$TOOLS/manifest-files.py" "$SRC/manifest.json" --background-first)
# A missing script the manifest NAMES is fatal; a missing popup asset is only a
# build that does not have one (the same rule build-chrome.sh applies).
SHARED=()
for f in "${LISTED[@]}"; do
  if [ -f "$SRC/$f" ]; then SHARED+=("$f"); continue; fi
  case "$f" in
    popup.*|"$LOGO") ;;
    *) echo "manifest names $f but the chrome build has no such file" >&2; exit 1 ;;
  esac
done
echo "shipping: ${SHARED[*]}"

# The Firefox build carries the Chrome version. Refuse before copying anything if
# this folder already holds a newer build, so a stale Chrome source can never
# overwrite a newer Firefox one.
CHROME_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SRC/manifest.json")"
python3 "$TOOLS/inventory.py" guard "$OUT" "$CHROME_VERSION"

mkdir -p "$OUT"
for f in "${SHARED[@]}"; do mkdir -p "$(dirname "$OUT/$f")"; cp "$SRC/$f" "$OUT/$f"; done
rm -rf "$OUT/icons" && cp -r "$SRC/icons" "$OUT/icons"
rm -rf "$OUT/tests"; [ -d "$SRC/tests" ] && cp -r "$SRC/tests" "$OUT/tests"
[ -f "$SRC/README.md" ] && cp "$SRC/README.md" "$OUT/README.md"
cp "$HERE/firefox-shim.js" "$OUT/firefox-shim.js"

python3 - "$SRC/manifest.json" "$OUT/manifest.json" "$GECKO_ID" <<'PY'
import json, sys, collections

src, dst, gecko_id = sys.argv[1], sys.argv[2], sys.argv[3]
m = json.load(open(src), object_pairs_hook=collections.OrderedDict)

m["background"] = collections.OrderedDict(
    scripts=["firefox-shim.js", "config.js", "background.js"]
)

# Firefox needs the websocket scheme spelled out. In a match pattern the "*"
# scheme wildcard covers only http and https for certain - ws and wss are
# browser-dependent - so "*://*.qxbroker.com/*" does not reliably grant
# "wss://ws2.qxbroker.com/". Chrome's match patterns do not accept wss at all,
# which is why this is added here rather than in the shared Chrome manifest.
hosts = m.get("host_permissions") or []
extra = []
for h in hosts:
    if h.startswith("*://"):
        wss = "wss://" + h[len("*://"):]
        if wss not in hosts and wss not in extra:
            extra.append(wss)
if extra:
    m["host_permissions"] = hosts + extra

# Declared where a reader looks first, right after the version.
bss = collections.OrderedDict()
bss["gecko"] = collections.OrderedDict(
    id=gecko_id,
    strict_min_version="142.0",
    # The licence key and the site's session cookie both go to our own
    # server on every read, and the broker account id goes with them so the
    # server can check the licence is pinned to the account trading on it. That
    # is authentication data leaving the browser, so it is disclosed. "none"
    # would be the easier answer and a false one.
    data_collection_permissions=collections.OrderedDict(required=["authenticationInfo"]),
)
# Same floor for Firefox for Android — background.js's chrome.action.setPopup
# fallback (see above) is what makes this platform actually work, so it is
# declared here rather than left for AMO to infer. Only the version floor goes
# here: GeckoAndroidSpecificProperties in Firefox's own manifest schema accepts
# strict_min_version and strict_max_version and nothing else, so repeating the
# data-collection disclosure made every install log "An unexpected property was
# found in the WebExtension manifest". The disclosure under gecko already covers
# both platforms.
bss["gecko_android"] = collections.OrderedDict(
    strict_min_version="142.0",
)
out = collections.OrderedDict()
for k, v in m.items():
    out[k] = v
    if k == "version":
        out["browser_specific_settings"] = bss
if "browser_specific_settings" not in out:
    out["browser_specific_settings"] = bss

json.dump(out, open(dst, "w"), indent=2, ensure_ascii=False)
open(dst, "a").write("\n")
print("manifest written:", dst)
PY

# Prove the copy is a copy. A Firefox build that has quietly drifted from the
# Chrome one is the failure this whole script exists to prevent.
for f in "${SHARED[@]}"; do
  cmp -s "$SRC/$f" "$OUT/$f" || { echo "DRIFT: $f differs from the chrome build" >&2; exit 1; }
done

if [ -n "$NEW_NAME" ]; then
  python3 "$TOOLS/rename-product.py" "$OUT" "$NEW_NAME"
  # Everything except the two files the rename may touch must still match Chrome.
  for f in "${SHARED[@]}"; do
    [ "$f" = "config.js" ] && continue
    cmp -s "$SRC/$f" "$OUT/$f" || { echo "DRIFT after rename: $f" >&2; exit 1; }
  done
  # And config.js may differ ONLY in its two name lines.
  DIFFLINES="$(diff "$SRC/config.js" "$OUT/config.js" | grep -E '^[<>]' | grep -vcE 'APP_NAME(_HTML)?:' || true)"
  [ "$DIFFLINES" = "0" ] || { echo "config.js differs beyond the product name" >&2; exit 1; }
fi

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$OUT/manifest.json")"
ZIP="$OUT/$(python3 "$TOOLS/layout.py" package "$SLUG" firefox "$VERSION")"
# The affiliate-disclosure gate, on the build about to ship (docs/store-policy.md).
python3 "$TOOLS/check-store-policy.py" "$OUT"
python3 "$TOOLS/check-brand.py" "$OUT"
rm -f "$ZIP"
( cd "$OUT" && zip -qr "$(basename "$ZIP")" manifest.json firefox-shim.js "${SHARED[@]}" icons )

# Prove the package before anyone uploads it — a zip missing one file looks
# exactly like a healthy one until it is installed.
python3 "$TOOLS/verify-package.py" "$ZIP"

# One package per folder: the one just proved replaces every older one, and
# VERSIONS.md is rewritten so it names the new version. An older build is
# recovered from git history, never kept beside the current one.
python3 "$TOOLS/inventory.py" prune "$ZIP"
python3 "$TOOLS/inventory.py" --write || true

echo "built $ZIP"
