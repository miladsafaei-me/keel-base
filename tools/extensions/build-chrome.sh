#!/usr/bin/env bash
#
# Package a Chrome build from its own manifest.
#
# The file list is READ OFF manifest.json by manifest-files.py — the
# background worker, whatever that worker importScripts(), every content script,
# the icons it declares — plus the popup and its assets. Hand-listing the files is
# how a package ships without the one script it cannot work without, and a zip
# that is missing a file looks exactly like a zip that is fine until it is
# installed. This script kept its own copy of that list and the copy did not know
# about importScripts, so every Chrome package it built shipped without config.js
# and its service worker never registered.
#
# It also refuses to overwrite a package whose version already exists with
# DIFFERENT contents unless asked, because two artifacts sharing one version
# number is the trap that keeps costing us: a store rejects the re-upload, or
# worse, accepts it and nobody can tell which build is live.
#
# Shared by every site's extension repo, whose tools/ folder links here; the
# brand is the repo's own brand.json (see brand.py).
#
# Usage: tools/build-chrome.sh <slug> [--force]

set -euo pipefail

SLUG="${1:?usage: build-chrome.sh <slug> [--force]}"
FORCE="${2:-}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Every tool this script runs works on the same repo, wherever it is run from.
export EXT_ROOT="${EXT_ROOT:-$(python3 "$HERE/brand.py" root)}"
# The popup's logo file name is the repo's own (brand.json logo_file).
LOGO="$(python3 "$HERE/brand.py" get logo_file)"
# <family>/<slug>/chrome/ - see layout.py.
SRC="$(python3 "$HERE/layout.py" dir "$SLUG" chrome)"
[ -f "$SRC/manifest.json" ] || { echo "no manifest at $SRC" >&2; exit 1; }

VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SRC/manifest.json")"
ZIP="$SRC/$(python3 "$HERE/layout.py" package "$SLUG" chrome "$VERSION")"
# Never build backwards over a newer package sitting in the same folder.
python3 "$HERE/inventory.py" guard "$SRC" "$VERSION"
# Never package a build that hides a partner link: the store listing and the UI
# must both disclose it (docs/store-policy.md). Five listings were rejected for this.
python3 "$HERE/check-store-policy.py" "$SRC"
# Never package a build that carries another brand's name or domain (brand.json
# forbidden_traces): two sites share these tools and must never share a trace.
python3 "$HERE/check-brand.py" "$SRC"

mapfile -t FILES < <(python3 "$HERE/manifest-files.py" "$SRC/manifest.json")

MISSING=()
KEEP=()
for f in "${FILES[@]}"; do
  if [ -f "$SRC/$f" ]; then KEEP+=("$f"); else MISSING+=("$f"); fi
done
# A missing script the manifest NAMES is fatal; a missing popup asset is only a
# build that does not have one.
for f in "${MISSING[@]}"; do
  case "$f" in
    popup.*|"$LOGO") ;;
    *) echo "manifest names $f but the build has no such file" >&2; exit 1 ;;
  esac
done

if [ -f "$ZIP" ] && [ "$FORCE" != "--force" ]; then
  TMP="$(mktemp -d)"
  unzip -qo "$ZIP" -d "$TMP"
  DRIFT=""
  while IFS= read -r f; do
    rel="${f#$TMP/}"
    if [ ! -f "$SRC/$rel" ] || ! cmp -s "$f" "$SRC/$rel"; then DRIFT="$DRIFT $rel"; fi
  done < <(find "$TMP" -type f)
  rm -rf "$TMP"
  if [ -n "$DRIFT" ]; then
    echo "$SLUG: $ZIP already exists and its contents differ:$DRIFT" >&2
    echo "bump the version in manifest.json, or pass --force to overwrite" >&2
    exit 1
  fi
fi

rm -f "$ZIP"
# manifest.json is not in the shipped-file list — that list is what the manifest
# NAMES — so it is zipped explicitly, the same way the Edge and Firefox builds do.
( cd "$SRC" && zip -qr "$(basename "$ZIP")" manifest.json "${KEEP[@]}" $([ -d icons ] && echo icons) )

# Prove the package before anyone uploads it — a zip missing one file looks
# exactly like a healthy one until it is installed.
python3 "$HERE/verify-package.py" "$ZIP"
# One package per folder: the one just proved replaces every older one, and
# VERSIONS.md is rewritten so it names the new version.
python3 "$HERE/inventory.py" prune "$ZIP"
python3 "$HERE/inventory.py" --write || true
echo "built $(basename "$ZIP") — $(( ${#KEEP[@]} + 1 )) files$([ -d "$SRC/icons" ] && echo " + icons")"
