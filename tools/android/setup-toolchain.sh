#!/usr/bin/env bash
# Install everything the Android tools need, user-level, no sudo: a JDK 21, the Android SDK (platform 36, build-tools,
# platform-tools), the emulator with an Android 16 Pixel image, and a Python venv with Playwright for the renders.
# Safe to run again: each step is skipped when its result is already there.
#
#   ~/www/keel-base/tools/android/setup-toolchain.sh
#
# Afterwards: JAVA_HOME=~/.local/opt/jdk-21*, ANDROID_HOME=~/Android/Sdk; tools/build.sh finds both on its own.
set -euo pipefail

opt="$HOME/.local/opt"
sdk="$HOME/Android/Sdk"
venv="$HOME/.local/share/keel-render-venv"
mkdir -p "$opt" "$sdk/cmdline-tools"
# An empty proxy variable makes sdkmanager fail ("no protocol").
for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy FTP_PROXY ftp_proxy; do
  [ -z "${!v:-}" ] && unset "$v"
done

if ! ls -d "$opt"/jdk-21* >/dev/null 2>&1; then
  echo "== JDK 21 (Temurin)"
  curl -fsSL -o "$opt/jdk21.tar.gz" "https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse"
  tar xzf "$opt/jdk21.tar.gz" -C "$opt" && rm "$opt/jdk21.tar.gz"
fi
JAVA_HOME="$(ls -d "$opt"/jdk-21* | tail -1)"
export JAVA_HOME

if [ ! -x "$sdk/cmdline-tools/latest/bin/sdkmanager" ]; then
  echo "== Android command-line tools"
  curl -fsSL -o "$sdk/cmdline-tools/ct.zip" https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip
  unzip -q "$sdk/cmdline-tools/ct.zip" -d "$sdk/cmdline-tools" && mv "$sdk/cmdline-tools/cmdline-tools" "$sdk/cmdline-tools/latest"
  rm "$sdk/cmdline-tools/ct.zip"
fi
sm="$sdk/cmdline-tools/latest/bin/sdkmanager"
yes | "$sm" --sdk_root="$sdk" --licenses >/dev/null || true
echo "== SDK packages"
"$sm" --sdk_root="$sdk" "platform-tools" "platforms;android-36" "build-tools;36.0.0" "emulator" "system-images;android-36;google_apis;x86_64" >/dev/null

if [ ! -d "$HOME/.android/avd/signal_pixel.avd" ]; then
  echo "== emulator: signal_pixel (Pixel 7, Android 16)"
  echo no | ANDROID_SDK_ROOT="$sdk" "$sdk/cmdline-tools/latest/bin/avdmanager" create avd -n signal_pixel \
    -k "system-images;android-36;google_apis;x86_64" -d pixel_7 --force >/dev/null
fi

if [ ! -x "$venv/bin/python" ]; then
  echo "== render venv (Playwright, Pillow)"
  python3 -m venv "$venv"
  "$venv/bin/pip" install -q playwright pillow numpy scipy websocket-client
  "$venv/bin/python" -m playwright install chromium >/dev/null
fi

echo "ready: JAVA_HOME=$JAVA_HOME ANDROID_HOME=$sdk venv=$venv"
echo "emulator: $sdk/emulator/emulator -avd signal_pixel -no-window -no-audio -gpu swangle_indirect"
