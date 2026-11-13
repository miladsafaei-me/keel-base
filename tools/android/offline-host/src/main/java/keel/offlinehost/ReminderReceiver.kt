package keel.offlinehost

import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * Fires the daily reminder and keeps it scheduled across reboots, app updates and clock or zone
 * changes. The library manifest does not declare it: an app that opts in (keel_reminders) declares
 * it in its own manifest with the four system actions (README.md).
 */
class ReminderReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (!Reminders.enabled(context)) return
        when (intent.action) {
            Reminders.ACTION_FIRE -> fire(context)
            Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED,
            Intent.ACTION_TIME_CHANGED, Intent.ACTION_TIMEZONE_CHANGED -> Reminders.reschedule(context)
        }
    }

    /** Posts unless the day's goal is met or notifications are off; after seven days with no app open it stops until the next open. */
    private fun fire(context: Context) {
        when (Reminders.fireAction(Reminders.isOn(context), Reminders.stale(context), Reminders.doneToday(context))) {
            Reminders.Fire.STOP -> return
            Reminders.Fire.SKIP -> Reminders.reschedule(context)
            Reminders.Fire.POST -> {
                post(context)
                Reminders.reschedule(context)
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun post(context: Context) {
        val manager = NotificationManagerCompat.from(context)
        if (!Reminders.permissionGranted(context) || !manager.areNotificationsEnabled()) return
        context.getSystemService(NotificationManager::class.java)?.createNotificationChannel(
            NotificationChannel(Reminders.CHANNEL, context.getString(R.string.keel_reminder_channel), NotificationManager.IMPORTANCE_DEFAULT),
        )
        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName)
            ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        val tap = launch?.let { PendingIntent.getActivity(context, 0, it, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE) }
        val title = Reminders.title(context).ifEmpty { context.applicationInfo.loadLabel(context.packageManager).toString() }
        val note = NotificationCompat.Builder(context, Reminders.CHANNEL)
            .setSmallIcon(R.drawable.keel_notify)
            .setContentTitle(title)
            .setContentText(Reminders.text(context))
            .setStyle(NotificationCompat.BigTextStyle().bigText(Reminders.text(context)))
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .apply { if (tap != null) setContentIntent(tap) }
            .build()
        try {
            manager.notify(NOTIFICATION_ID, note)
        } catch (_: SecurityException) {
            // Permission withdrawn between the check and the post: nothing to show.
        }
    }

    companion object {
        const val NOTIFICATION_ID = 7301
    }
}
