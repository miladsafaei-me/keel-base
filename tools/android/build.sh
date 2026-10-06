#!/usr/bin/env bash
# Build one member's release: the signed .aab Google Play takes and a signed .apk for direct installs.
#
#   tools/build.sh <slug>
#
# Copies the site's app in (sync-from-site.py), builds both packages with the upload key named in brand.json, runs every
# gate (check.py), and copies them to <family>/<slug>/release/<slug>-android-<version>.{aab,apk}, removing older builds
# there. The packages stay out of git. Upload the .aab to Google Play; the .apk is for testing on a phone.
set -euo pipefail

slug="${1:?usage: build.sh <slug>}"
tools="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$tools/.." && pwd)"
export MOBILE_ROOT="$root"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
if [ -z "${JAVA_HOME:-}" ]; then
  JAVA_HOME="$(ls -d "$HOME"/.local/opt/jdk-21* 2>/dev/null | tail -1)"
  export JAVA_HOME
fi
export PATH="$JAVA_HOME/bin:$PATH"
# An empty proxy variable breaks the SDK's own downloads.
for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy; do
  [ -z "${!v:-}" ] && unset "$v"
done

read -r flavour version mdir < <(python3 - "$slug" <<'EOF'
import os, sys
sys.path.insert(0, os.environ["MOBILE_ROOT"] + "/tools")
import mobile
m, mdir = mobile.member(sys.argv[1])
print(mobile.flavour(m["slug"]), m["version_name"], mdir)
EOF
)
cap="$(python3 -c 'import sys; s=sys.argv[1]; print(s[:1].upper()+s[1:])' "$flavour")"

keyprops="$(python3 -c 'import json,os,sys; print(os.path.expanduser(json.load(open(sys.argv[1]))["android"]["keystore_properties"]))' "$root/brand.json")"
[ -f "$keyprops" ] || { echo "no upload key at $keyprops: create it first (tools/README.md, 'The upload key')" >&2; exit 1; }

echo "== sync $slug from the site"
python3 "$tools/sync-from-site.py" "$slug"

echo "== gradle :app:bundle${cap}Release :app:assemble${cap}Release"
echo "sdk.dir=$ANDROID_HOME" > "$root/android/local.properties"
"$root/android/gradlew" -p "$root/android" --console=plain -q "clean" ":app:bundle${cap}Release" ":app:assemble${cap}Release"

aab="$root/android/app/build/outputs/bundle/${flavour}Release/app-${flavour}-release.aab"
apk="$root/android/app/build/outputs/apk/${flavour}/release/app-${flavour}-release.apk"

echo "== gates"
python3 "$tools/check.py" "$slug" --apk "$apk" --aab "$aab"

out="$mdir/release"
mkdir -p "$out"
find "$out" -maxdepth 1 -type f \( -name '*.aab' -o -name '*.apk' \) -delete
cp "$aab" "$out/$slug-android-$version.aab"
cp "$apk" "$out/$slug-android-$version.apk"
ls -la "$out"
echo "Built, not published: upload $out/$slug-android-$version.aab to Google Play."
