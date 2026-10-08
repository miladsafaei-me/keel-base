# Android signal-app tools, shared by every site

Every site that ships Android apps of its signal tools keeps them in its own repo, `~/products/<site>-mobile-apps`.
These scripts build, check and draw those apps. They hold no brand: each repo's `brand.json` supplies the brand name,
its site, its colours, its partner link, its upload key's location and the other brands' names that must never reach
its users. The process that uses them is keel-kit's `methodology/signal-android-standard.md`, run by the
`keel-kit:signal-android` skill.

## What an app is

One activity (`host/`) hosts the site's own app in a WebView. The site's markup, stylesheet and scripts are copied into
the APK unchanged, and served at `https://<site>/app/` by a `WebViewAssetLoader`, so the app's relative calls to
`/s-api/...` reach the live site as same-origin requests. Around the app, the repo's web shell (`shell/`) draws the
licence gate, three tabs and the bridge to the device; the native side passes in the system bar insets, colours the
bar icons, offers Back to the shell first and opens every outside link in a Custom Tab.

Every member is a product flavour of one Gradle module, so one build file serves all of a brand's apps.

## How a repo uses them

A repo's `tools/` holds relative symlinks to the files here, plus its own `site_adapter.py` (how to read an app out of
that site's source). Commands are the same in every repo:

```bash
tools/sync-from-site.py <slug>     # copy the landing's app in, draw the icons
tools/render.py <slug>             # every screen, phone and tablet, both themes, with its checks
tools/play-graphics.py <slug>      # feature graphic and store screenshots
tools/cover-shots.py <slug>        # raw screenshots for the designer covers, <slug>/screenshots/ (play-graphics runs it too)
tools/build.sh <slug>              # signed .aab and .apk, every gate, copied to release/ with a .zip of the member's directory
tools/check.py <slug>              # the gates alone
tools/draw-emblem.py <slug>        # a text-free launcher emblem from the logo, with Gemini
```

A tool finds its repo from `$MOBILE_ROOT`, else from the `tools/` folder it was invoked through, else from the nearest
`brand.json` above the current folder. Python tools that render need the venv `setup-toolchain.sh` makes.

## Setting up

- A machine: `setup-toolchain.sh` (JDK 21, SDK 36, the emulator, the render venv). On Fedora 44 the emulator crashes
  in its Vulkan renderer with `-gpu swiftshader_indirect` or `guest`; start it with `-gpu swangle_indirect`.
- A repo: `brand.json` (below), `shell/` (copied from the newest repo and re-skinned to the site's tokens),
  `android/` (settings, root build file, `app/build.gradle.kts`, the Gradle wrapper), `tools/` with the symlinks and
  `site_adapter.py`, a `.gitignore` for `release/`, `renders/`, `android/app/build/`, `android/.gradle/` and
  `android/local.properties`. `~/products/autotradingbots-mobile-apps` is the first complete example.
- The upload key: one per brand, outside the repo, named by `brand.json` `android.keystore_properties`
  (`storeFile`, `storePassword`, `keyAlias`, `keyPassword`). Make it once with `keytool -genkeypair -keystore
  upload.jks -storetype PKCS12 -alias upload -keyalg RSA -keysize 4096 -validity 10000`, `chmod 600`, and back both
  files up off the laptop. Google Play keeps the app signing key; losing the upload key means a reset request to Play
  support, never a lost app.

## brand.json

| Field | Meaning |
|---|---|
| `brand` | The brand name a user reads |
| `site_repo` | The site's git checkout; the sync reads its `origin/main` |
| `own_hosts` | This brand's hosts |
| `forbidden_traces`, `trace_exceptions` | Another brand's names that must never ship, and the partner URLs exempt from that |
| `family_links` | The partner link each family carries (`name`, `url`) |
| `app` | What `config.js` takes: site, labels, landing, sign-up, risk, privacy and terms URLs, key page, key prefix, Telegram pool, support email |
| `android.application_id_prefix` | Every member's id starts with it |
| `android.keystore_properties` | Where the upload key's properties file is |
| `android.colors` | `stage`, `stage_glow` (icon and launch screen), `surface_light`, `surface_dark` (window behind the WebView) |

## member.json

`slug`, `item` (licence item), `name`, `application_id` (never changes once on Play), `version_name`, `version_code`
(raise it on every upload), `site` (`module`, `markup`, `scripts`, `logo`, `logo_ground`, optional `emblem_box`),
optional `emblem` (`art/emblem.png`), `free_words`, `trial_days`, `contact_message`, `tab_app` (`label`, `icon`),
`tagline` and `eyebrow` (feature graphic).

## What each file does

| File | Job |
|---|---|
| `mobile.py` | Finds the repo, reads `brand.json` and the members |
| `sync-from-site.py` | The site's app into `android/assets/`, the icons into `android/res/`, `play/icon-512.png` |
| `draw-emblem.py` | A launcher emblem without the wordmark, when cropping the logo would cut the emblem |
| `render.py` | The app in headless Chromium as the WebView draws it, against the live engine, with its checks |
| `play-graphics.py` | `play/feature-graphic.png` and the phone and tablet screenshots |
| `cover-shots.py` | `<slug>/screenshots/{phone,tablet 7,tablet 10}/1..5.png`: the app without a frame, sized to the screen inside a store cover device frame |
| `check.py` | Brand traces, partner disclosure, site drift, package (signature, target SDK, id, version, permissions), listing |
| `build.sh` | Sync, Gradle release bundle and APK, the gates, copy to `release/`, then zip the member's whole directory beside them |
| `host/` | The native activity, manifest, themes and backup rules every app shares |
| `setup-toolchain.sh` | The JDK, SDK, emulator and render venv |
