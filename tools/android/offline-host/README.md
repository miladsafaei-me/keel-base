# Offline host: the shared Android shell of the studio's offline apps

An offline app is a web app (plain HTML, CSS and JS in the app repo's `web/`) bundled into the APK and shown in one
WebView. This library is everything around it that is the same for every such app:

| File | What it does |
|---|---|
| `OfflineWebActivity.kt` | Serves the bundled `web/` at `https://appassets.androidplatform.net/app/`, edge-to-edge bars, insets and the system theme pushed to the page, Back offered to the page first, outside links in a Custom Tab, in-app review |
| `Bridge.kt` | `window.NativeApp`: theme, version, entitlement, purchase, restore, review, open, share text, share file |
| `Billing.kt` | Play Billing for one Pro product: query on connect and resume, acknowledge, cached state so Pro works offline. A blank product id means the app sells nothing yet |
| `Entitlement.kt` | The entitlement rules as plain values, unit-tested in `src/test` |

The page side talks back through `window.appShell`: `insets(obj)`, `system("dark"|"light")`, `back()` returning
true when the page handled it, `entitlement(obj)`, `purchaseResult(obj)`.

Users: `~/products/rovinstudio/electrical-calculator`, `~/products/rovinstudio/persian-language-app` (Faramarz).
The site-backed signal apps use `../host` instead.

## Using it in an app

`android/settings.gradle.kts`:

```kotlin
val keelBase = providers.environmentVariable("KEEL_BASE").orNull ?: "${System.getProperty("user.home")}/www/keel-base"
include(":offline-host")
project(":offline-host").projectDir = file("$keelBase/tools/android/offline-host")
```

The root `build.gradle.kts` declares `com.android.library` next to `com.android.application` (same AGP version), the
app module adds `implementation(project(":offline-host"))`, and its activity is one line:

```kotlin
class MainActivity : keel.offlinehost.OfflineWebActivity()
```

The app overrides these resources: colours `surface_light`, `surface_dark`, `surface` (and `values-night/surface`),
string `pro_product_id`. It keeps its own manifest application element (icon, label, `allowBackup`, the backup rules
in this library's `res/xml`), its splash theme and its launcher icon. Build output lands in the app's
`android/build/offline-host/`, so two apps never share build state.

Tests: `./gradlew :offline-host:testDebugUnitTest` from either app.
