# Offline host: the shared Android shell of the studio's offline apps

An offline app is a web app (plain HTML, CSS and JS in the app repo's `web/`) bundled into the APK and shown in one
WebView. This library is everything around it that is the same for every such app:

| File | What it does |
|---|---|
| `OfflineWebActivity.kt` | Serves the bundled `web/` at `https://appassets.androidplatform.net/app/`, edge-to-edge bars, insets and the system theme pushed to the page, Back offered to the page first, outside links in a Custom Tab, in-app review |
| `Bridge.kt` | `window.NativeApp`: theme, version, entitlement, purchase, restore, manage subscription, review, open, share text, share file, capabilities, mail, reminder state and settings, the app's page in the phone's settings |
| `Billing.kt` | Play Billing glue for one Pro product, a one-time item or a subscription: Play's client behind the small `StoreClient` interface, and the cache in SharedPreferences |
| `BillingCore.kt` | Every billing rule as plain logic: query on connect and resume, acknowledge, cached state so Pro works offline, the purchase flow. A blank product id means the app sells nothing yet. Unit-tested against a fake Play in `src/test` |
| `Entitlement.kt` | The entitlement states and rules as plain values, unit-tested in `src/test` |
| `Reminders.kt` | The opt-in daily reminder: its settings, `nextTrigger` (pure, unit-tested in `src/test`) and an inexact, Doze-safe `AlarmManager.setAndAllowWhileIdle` alarm |
| `ReminderReceiver.kt` | Posts the reminder and reschedules it after a reboot, an app update, or a clock or zone change |

The page side talks back through `window.appShell`: `insets(obj)`, `system("dark"|"light")`, `back()` returning
true when the page handled it, `entitlement(obj)`, `purchaseResult(obj)`, `mailResult({ok})`, `reminderResult({on, permission})`, and `resumed()` each time the app comes back to the foreground.

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
strings `pro_product_id` and `pro_product_type` (see Selling Pro). It keeps its own manifest application element (icon, label, `allowBackup`, the backup rules
in this library's `res/xml`), its splash theme and its launcher icon. Build output lands in the app's
`android/build/offline-host/`, so two apps never share build state.

Tests: `./gradlew :offline-host:testDebugUnitTest` from either app.

## Selling Pro

One product per app, named by the string `pro_product_id` (blank: the app sells nothing and Play is never asked).
The string `pro_product_type` says what it is:

- `inapp` (default): a one-time item. The page hears `{state, price}`; `NativeApp.purchase(anything)` buys it.
- `subs`: a subscription with base plans (for example `monthly` and `yearly`, set in Play Console). The page hears
  `{state, subscription: true, renewing, lapsed, plans: [{id, price, period, micros, currency}]}`. Prices and periods
  come from Play for the user's country and are never cached, so an offline page has no plans to show.
  `NativeApp.purchase(planId)` buys one base plan; intro offers are not sold.

`state` is `unknown`, `none`, `pending` or `active`. Active covers a running plan, the grace period after a failed
renewal, and a cancelled plan still paid until its end (then `renewing` is false). Play stops returning a plan that
expired, is on account hold or is paused: the state is `none`, and `lapsed` is true when this install had Pro before.
A failed query keeps the cached state, so Pro works offline. Restore is automatic: every start and every resume
query Play again (a reinstall too); `NativeApp.restore()` runs the same query at once. Every purchase flow ends in
`appShell.purchaseResult({result})` with `ok`, `pending`, `owned`, `cancelled`, `error` or `unavailable`.
`NativeApp.manageSubscription()` opens Play's subscription page for the product, where the user changes plan,
fixes a payment or cancels.

## Opt-in features

Every feature below is off by default, so an app that does nothing keeps exactly its old behaviour and its old merged
manifest. This library's manifest declares no permission and no receiver for them; the app that opts in declares
what it needs in its own manifest.

### Mail (always on)

`NativeApp.mail(to, subject, body)` opens the mail app (`ACTION_SENDTO` on a `mailto:` Uri, plus `EXTRA_EMAIL`,
`EXTRA_SUBJECT`, `EXTRA_TEXT`), then calls `appShell.mailResult({ok})`; `ok` is false when no mail app exists.
`NativeApp.capabilities()` returns `{mic, reminders, mail}` so the page knows what this build offers.

### Microphone for `getUserMedia` (`keel_mic`)

With the bool `keel_mic` true, the activity answers a page's audio-capture request: it grants it when
`RECORD_AUDIO` is held, otherwise asks for `RECORD_AUDIO` and then grants or denies. Video and every other web
permission stay denied. The app adds:

```xml
<!-- res/values/keel.xml -->
<bool name="keel_mic">true</bool>
```

```xml
<!-- AndroidManifest.xml, inside <manifest> -->
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
<uses-feature android:name="android.hardware.microphone" android:required="false" />
```

Android stops showing the permission dialog after two refusals. `NativeApp.openAppSettings()` opens the app's page in
the phone's settings, where the learner turns the microphone on by hand; `appShell.resumed()` fires on the way back,
so the page can try again at once.

### Daily reminder (`keel_reminders`)

With the bool `keel_reminders` true, the page manages one local notification a day:
`NativeApp.reminderState()` returns `{on, hour, minute, permission}` (`granted`, `denied`, or `default` when
Android 13+ was never asked); `NativeApp.setReminder(json)` takes `{on, hour, minute, title, text}`, asks for
`POST_NOTIFICATIONS` on Android 13+ only when the reminder turns on without it (a refusal saves it off), schedules
or cancels, and calls `appShell.reminderResult({on, permission})`; `NativeApp.reminderDoneToday()` keeps today's
reminder quiet. The alarm is inexact (`setAndAllowWhileIdle`, no exact-alarm permission) and is delivered
while the phone is in Doze; `setWindow` would wait for a Doze maintenance window, often hours late. The reminder
is skipped on a day marked done or while notifications are off, and stops after seven days with no app open.
Every open, a cold start or a resume (`onResume`), records the open time and schedules it again. The app adds:

```xml
<!-- res/values/keel.xml -->
<bool name="keel_reminders">true</bool>
<string name="keel_reminder_channel">Daily reminder</string>  <!-- the channel name in system settings -->
```

```xml
<!-- AndroidManifest.xml: inside <manifest> -->
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />

<!-- inside <application> -->
<receiver android:name="keel.offlinehost.ReminderReceiver" android:exported="false">
    <intent-filter>
        <action android:name="android.intent.action.BOOT_COMPLETED" />
        <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />
        <action android:name="android.intent.action.TIME_SET" />
        <action android:name="android.intent.action.TIMEZONE_CHANGED" />
    </intent-filter>
</receiver>
```

The status-bar icon is the drawable `keel_notify` (a plain white bell); an app may override it with its own
monochrome drawable of that name. Tapping the notification opens the app's launcher activity.
