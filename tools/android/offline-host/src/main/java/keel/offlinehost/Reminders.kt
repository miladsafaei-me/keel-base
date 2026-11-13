package keel.offlinehost

import android.Manifest
import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime

/**
 * The daily reminder, opt-in per app with the bool resource keel_reminders. State lives in
 * SharedPreferences only (the page reads it through Bridge.reminderState). One inexact alarm a
 * day through AlarmManager.setAndAllowWhileIdle: it is delivered in Doze (setWindow is deferred
 * to the next maintenance window there) and needs no exact-alarm permission.
 */
object Reminders {
    const val CHANNEL = "keel_reminders"
    const val ACTION_FIRE = "keel.offlinehost.REMINDER_FIRE"
    const val STALE_MS = 7 * 24 * 60 * 60 * 1000L
    const val DEFAULT_HOUR = 20

    private const val PREFS = "keel_reminders"
    private const val ON = "on"
    private const val HOUR = "hour"
    private const val MINUTE = "minute"
    private const val TITLE = "title"
    private const val TEXT = "text"
    private const val DONE = "done_date"
    private const val OPENED = "last_open"
    private const val ASKED = "asked"

    /** The next moment strictly after nowMillis that reads hour:minute on the wall clock of zone. */
    fun nextTrigger(nowMillis: Long, hour: Int, minute: Int, zone: ZoneId): Long {
        val now = Instant.ofEpochMilli(nowMillis).atZone(zone)
        val time = LocalTime.of(hour.coerceIn(0, 23), minute.coerceIn(0, 59))
        var at = ZonedDateTime.of(now.toLocalDate(), time, zone)
        if (!at.toInstant().isAfter(now.toInstant())) at = ZonedDateTime.of(now.toLocalDate().plusDays(1), time, zone)
        return at.toInstant().toEpochMilli()
    }

    /** True when the app was last opened more than seven days before nowMillis (no open on record counts as fresh). */
    fun isStale(nowMillis: Long, lastOpenMillis: Long): Boolean = lastOpenMillis > 0 && nowMillis - lastOpenMillis > STALE_MS

    /** What a fired alarm does. */
    enum class Fire { STOP, SKIP, POST }

    /**
     * Off or seven days with no app open: STOP (no notification, no next alarm; the next open
     * schedules again). Today's goal met: SKIP (no notification, next alarm kept). Otherwise POST.
     */
    fun fireAction(on: Boolean, stale: Boolean, doneToday: Boolean): Fire = when {
        !on || stale -> Fire.STOP
        doneToday -> Fire.SKIP
        else -> Fire.POST
    }

    fun enabled(context: Context) = context.resources.getBoolean(R.bool.keel_reminders)

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun isOn(context: Context) = prefs(context).getBoolean(ON, false)
    fun title(context: Context): String = prefs(context).getString(TITLE, null).orEmpty()
    fun text(context: Context): String = prefs(context).getString(TEXT, null).orEmpty()
    fun doneToday(context: Context) = prefs(context).getString(DONE, null) == LocalDate.now().toString()
    fun stale(context: Context) = isStale(System.currentTimeMillis(), prefs(context).getLong(OPENED, 0L))

    fun save(context: Context, on: Boolean, hour: Int, minute: Int, title: String?, text: String?) {
        prefs(context).edit().apply {
            putBoolean(ON, on)
            putInt(HOUR, hour.coerceIn(0, 23))
            putInt(MINUTE, minute.coerceIn(0, 59))
            if (!title.isNullOrBlank()) putString(TITLE, title)
            if (!text.isNullOrBlank()) putString(TEXT, text)
        }.apply()
    }

    fun setOn(context: Context, on: Boolean) = prefs(context).edit().putBoolean(ON, on).apply()
    fun markAsked(context: Context) = prefs(context).edit().putBoolean(ASKED, true).apply()
    fun markDoneToday(context: Context) = prefs(context).edit().putString(DONE, LocalDate.now().toString()).apply()
    fun markOpened(context: Context) = prefs(context).edit().putLong(OPENED, System.currentTimeMillis()).apply()

    /** Every foreground open (cold start or resume): records the open and revives a stopped alarm chain. */
    fun opened(context: Context) {
        if (!enabled(context)) return
        markOpened(context)
        if (isOn(context)) reschedule(context)
    }

    /** POST_NOTIFICATIONS is a runtime permission on 33+; before that, only the app's notification switch counts. */
    fun permissionGranted(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    /** "granted", "denied", or "default" when Android 13+ has never been asked. */
    fun permission(context: Context): String = when {
        permissionGranted(context) && NotificationManagerCompat.from(context).areNotificationsEnabled() -> "granted"
        Build.VERSION.SDK_INT >= 33 && !permissionGranted(context) && !prefs(context).getBoolean(ASKED, false) -> "default"
        else -> "denied"
    }

    fun stateJson(context: Context): String {
        val p = prefs(context)
        return JSONObject()
            .put("on", p.getBoolean(ON, false))
            .put("hour", p.getInt(HOUR, DEFAULT_HOUR))
            .put("minute", p.getInt(MINUTE, 0))
            .put("permission", permission(context))
            .toString()
    }

    private fun pending(context: Context): PendingIntent =
        PendingIntent.getBroadcast(
            context, 0,
            Intent(context, ReminderReceiver::class.java).setAction(ACTION_FIRE),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    /** Schedules the next reminder when the app opted in and the learner turned it on; cancels it otherwise. */
    fun reschedule(context: Context) {
        val alarms = context.getSystemService(AlarmManager::class.java) ?: return
        val p = prefs(context)
        if (!enabled(context) || !p.getBoolean(ON, false)) {
            alarms.cancel(pending(context))
            return
        }
        val at = nextTrigger(System.currentTimeMillis(), p.getInt(HOUR, DEFAULT_HOUR), p.getInt(MINUTE, 0), ZoneId.systemDefault())
        // Inexact but Doze-safe; setWindow would wait for a maintenance window on an idle phone.
        alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending(context))
    }
}
