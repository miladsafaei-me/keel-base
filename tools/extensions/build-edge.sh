#!/usr/bin/env bash
#
# Build an Edge package from the Chrome build of the same extension.
#
# Edge IS Chromium: the manifest, the MV3 service worker, MAIN-world content
# scripts and every API behave identically, so there is nothing to port. Two
# declared transforms are all that separate an Edge package from its Chrome
# source, and both are read from the repo's store-listings.json rather than typed:
#
#   name         the PRODUCT NAME this listing carries, where it differs.
#   signal_only  ship the product WITHOUT its trading half - no broker host
#                permission, no content script, no socket engine, no auto-trade.
#                The strip is the repo's own script, named in brand.json
#                transforms.signal_only; a repo without one cannot declare it.
#
# Everything outside those two is copied untouched and then compared byte for
# byte, because a hand-copied Edge build that has quietly drifted from Chrome is
# the failure this script exists to prevent. Same guarantee the Firefox script
# gives - and the reason the strip lives HERE rather than in the edge/ folder: a
# hand-stripped copy would be silently overwritten by the next run of this.
#
# Shared by every site's extension repo, whose tools/ folder links here; the
# brand is the repo's own brand.json (see brand.py).
#
# Usage: tools/build-edge.sh <slug>
#
# The product name comes from the repo's store-listings.json; --name overrides it.

set -euo pipefail

SLUG="${1:?usage: build-edge.sh <slug> [--name \"Product Name\"]}"
shift

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Every tool this script runs works on the same repo, wherever it is run from.
export EXT_ROOT="${EXT_ROOT:-$(python3 "$HERE/brand.py" root)}"
TOOLS="$HERE"
# <family>/<slug>/chrome/ in, <family>/<slug>/edge/ out - see layout.py.
SRC="$(python3 "$TOOLS/layout.py" dir "$SLUG" chrome)"
OUT="$(python3 "$TOOLS/layout.py" dir "$SLUG" edge)"

# The product name this Edge listing carries is a durable fact, declared once in
# store-listings.json rather than typed at each rebuild - forgotten once and
# the package silently reverts to a name the store already rejected. --name still
# overrides, for a one-off.
NEW_NAME=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NEW_NAME="${2:?--name needs a value}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
[ -n "$NEW_NAME" ] || NEW_NAME="$(python3 "$TOOLS/listing.py" edge "$SLUG" name)"
SIGNAL_ONLY="$(python3 "$TOOLS/listing.py" edge "$SLUG" signal_only)"
# The signal-only strip is the repo's own script (brand.json transforms.signal_only).
STRIP=""
if [ -n "$SIGNAL_ONLY" ]; then
  STRIP_REL="$(python3 "$TOOLS/brand.py" get transforms | python3 -c 'import json,sys; print(json.load(sys.stdin).get("signal_only", ""))')"
  [ -n "$STRIP_REL" ] || { echo "$SLUG: store-listings.json declares signal_only, but brand.json names no transforms.signal_only script" >&2; exit 1; }
  STRIP="$(python3 "$TOOLS/brand.py" root)/$STRIP_REL"
  [ -f "$STRIP" ] || { echo "no signal-only strip at $STRIP" >&2; exit 1; }
fi

[ -d "$SRC" ] || { echo "no chrome build at $SRC" >&2; exit 1; }

# Refuse before copying anything if this folder already holds a newer build than
# the one this run derives (the signal-only strip adds a fourth component:
# 1.1.8 -> 1.1.8.1). A build changed by hand for an Edge review is kept that way.
EXPECTED="$(python3 -c 'import json,sys; v=json.load(open(sys.argv[1]))["version"]; print(v + ".1" if sys.argv[2] and v.count(".") == 2 else v)' "$SRC/manifest.json" "$SIGNAL_ONLY")"
python3 "$TOOLS/inventory.py" guard "$OUT" "$EXPECTED"

mapfile -t SHARED < <(python3 "$TOOLS/manifest-files.py" "$SRC/manifest.json")

mkdir -p "$OUT"
KEEP=()
for f in "${SHARED[@]}"; do
  if [ -f "$SRC/$f" ]; then mkdir -p "$(dirname "$OUT/$f")"; cp "$SRC/$f" "$OUT/$f"; KEEP+=("$f"); fi
done
cp "$SRC/manifest.json" "$OUT/manifest.json"
rm -rf "$OUT/icons" && cp -r "$SRC/icons" "$OUT/icons"
# No tests copied. This is a packaging target, not a second working copy: the
# harnesses run against the Chrome build these files were verified equal to,
# and the build-parity test would look for a sibling that only exists there.
rm -rf "$OUT/tests"
[ -f "$SRC/README.md" ] && cp "$SRC/README.md" "$OUT/README.md"

# Prove the copy is a copy, BEFORE any transform touches anything.
for f in "${KEEP[@]}"; do
  cmp -s "$SRC/$f" "$OUT/$f" || { echo "DRIFT: $f differs from the chrome build" >&2; exit 1; }
done

if [ -n "$NEW_NAME" ]; then
  python3 "$TOOLS/rename-product.py" "$OUT" "$NEW_NAME"
  # Everything except the two files the rename is allowed to touch must still be
  # byte-identical with Chrome.
  for f in "${KEEP[@]}"; do
    [ "$f" = "config.js" ] && continue
    cmp -s "$SRC/$f" "$OUT/$f" || { echo "DRIFT after rename: $f" >&2; exit 1; }
  done
  # And config.js may differ ONLY in its two name lines.
  DIFFLINES="$(diff "$SRC/config.js" "$OUT/config.js" | grep -E '^[<>]' | grep -vcE 'APP_NAME(_HTML)?:' || true)"
  [ "$DIFFLINES" = "0" ] || { echo "config.js differs beyond the product name" >&2; exit 1; }
fi

if [ -n "$SIGNAL_ONLY" ]; then
  python3 "$STRIP" "$OUT"
  # The strip owns three JS files and the manifest, and deletes the engine. Every
  # other shared file is still proved byte-identical with Chrome, so a drift that
  # hides behind the strip is impossible.
  for f in "${KEEP[@]}"; do
    case "$f" in config.js|background.js|popup.js) continue ;; esac
    [ -f "$OUT/$f" ] || continue
    cmp -s "$SRC/$f" "$OUT/$f" || { echo "DRIFT after strip: $f" >&2; exit 1; }
  done
  # And the package must grant no broker access and declare no content script.
  python3 - "$OUT/manifest.json" "$TOOLS" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[2])
import brand
m = json.load(open(sys.argv[1], encoding="utf-8"))
bad = []
if m.get("content_scripts"):
    bad.append("content_scripts")
if [p for p in m.get("permissions", []) if p != "storage"]:
    bad.append("permissions %s" % m["permissions"])
if [h for h in m.get("host_permissions", []) if not any(o in h for o in brand.OWN_HOSTS)]:
    bad.append("host_permissions %s" % m["host_permissions"])
if bad:
    sys.exit("signal-only manifest still grants: " + "; ".join(bad))
PY
fi

# The file list is read off the manifest that is about to ship, not the Chrome
# one: a signal-only build no longer names the socket engine or the tap, and
# zipping the Chrome list would fail on files the strip has deleted.
mapfile -t SHIPPED < <(python3 "$TOOLS/manifest-files.py" "$OUT/manifest.json")
PACK=()
for f in "${SHIPPED[@]}"; do
  [ -f "$OUT/$f" ] && PACK+=("$f")
done

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$OUT/manifest.json")"
ZIP="$OUT/$(python3 "$TOOLS/layout.py" package "$SLUG" edge "$VERSION")"
# The affiliate-disclosure gate, on the build about to ship (docs/store-policy.md).
python3 "$TOOLS/check-store-policy.py" "$OUT"
python3 "$TOOLS/check-brand.py" "$OUT"
rm -f "$ZIP"
( cd "$OUT" && zip -qr "$(basename "$ZIP")" manifest.json "${PACK[@]}" icons )

# Prove the package before anyone uploads it — a zip missing one file looks
# exactly like a healthy one until it is installed.
python3 "$TOOLS/verify-package.py" "$ZIP"

# One package per folder: the one just proved replaces every older one, and
# VERSIONS.md is rewritten so it names the new version.
python3 "$TOOLS/inventory.py" prune "$ZIP"
python3 "$TOOLS/inventory.py" --write || true

echo "built $ZIP"
