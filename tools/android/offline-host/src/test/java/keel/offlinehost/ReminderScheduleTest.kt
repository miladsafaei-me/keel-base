package keel.offlinehost

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/** nextTrigger, the seven-day stop and the fire decision, with fixed clocks and zones. */
class ReminderScheduleTest {
    private val tehran = ZoneId.of("Asia/Tehran")
    private val berlin = ZoneId.of("Europe/Berlin")
    private fun at(zone: ZoneId, y: Int, mo: Int, d: Int, h: Int, mi: Int, s: Int = 0) =
        LocalDateTime.of(y, mo, d, h, mi, s).atZone(zone).toInstant().toEpochMilli()

    @Test fun laterTodayIsToday() =
        assertEquals(at(tehran, 2026, 11, 12, 20, 0), Reminders.nextTrigger(at(tehran, 2026, 11, 12, 9, 30), 20, 0, tehran))

    @Test fun pastTodayIsTomorrow() =
        assertEquals(at(tehran, 2026, 11, 13, 20, 0), Reminders.nextTrigger(at(tehran, 2026, 11, 12, 21, 0), 20, 0, tehran))

    @Test fun exactlyNowIsTomorrow() =
        assertEquals(at(tehran, 2026, 11, 13, 20, 0), Reminders.nextTrigger(at(tehran, 2026, 11, 12, 20, 0), 20, 0, tehran))

    @Test fun oneSecondBeforeIsToday() =
        assertEquals(at(tehran, 2026, 11, 12, 20, 0), Reminders.nextTrigger(at(tehran, 2026, 11, 12, 19, 59, 59), 20, 0, tehran))

    @Test fun minutesCount() =
        assertEquals(at(tehran, 2026, 11, 12, 7, 45), Reminders.nextTrigger(at(tehran, 2026, 11, 12, 7, 44), 7, 45, tehran))

    @Test fun crossesMonthAndYear() =
        assertEquals(at(tehran, 2027, 1, 1, 8, 0), Reminders.nextTrigger(at(tehran, 2026, 12, 31, 23, 0), 8, 0, tehran))

    @Test fun sameInstantDiffersByZone() {
        val now = at(tehran, 2026, 11, 12, 12, 0)
        assertEquals(at(berlin, 2026, 11, 12, 20, 0), Reminders.nextTrigger(now, 20, 0, berlin))
    }

    @Test fun springForwardGapMovesLater() {
        // 2026-03-29 02:30 does not exist in Berlin; the wall clock jumps from 02:00 to 03:00.
        val got = Reminders.nextTrigger(at(berlin, 2026, 3, 29, 1, 0), 2, 30, berlin)
        assertEquals(at(berlin, 2026, 3, 29, 3, 30), got)
    }

    @Test fun outOfRangeIsClamped() =
        assertEquals(at(tehran, 2026, 11, 12, 23, 59), Reminders.nextTrigger(at(tehran, 2026, 11, 12, 10, 0), 30, 99, tehran))

    @Test fun neverOpenedIsNotStale() = assertFalse(Reminders.isStale(1_000_000_000_000L, 0L))
    @Test fun sixDaysIsNotStale() = assertFalse(Reminders.isStale(6 * DAY + 1, 1))
    @Test fun eightDaysIsStale() = assertTrue(Reminders.isStale(8 * DAY + 1, 1))

    @Test fun offStops() = assertEquals(Reminders.Fire.STOP, Reminders.fireAction(on = false, stale = false, doneToday = false))
    @Test fun staleStopsEvenWhenNotDone() = assertEquals(Reminders.Fire.STOP, Reminders.fireAction(on = true, stale = true, doneToday = false))
    @Test fun staleStopsWhenDone() = assertEquals(Reminders.Fire.STOP, Reminders.fireAction(on = true, stale = true, doneToday = true))
    @Test fun doneTodaySkipsButKeepsChain() = assertEquals(Reminders.Fire.SKIP, Reminders.fireAction(on = true, stale = false, doneToday = true))
    @Test fun activeAndNotDonePosts() = assertEquals(Reminders.Fire.POST, Reminders.fireAction(on = true, stale = false, doneToday = false))

    @Test fun reopenAfterStaleIsFreshAgain() {
        // A resume on day 8 records a new open, so the next fire is no longer stale.
        assertTrue(Reminders.isStale(8 * DAY + 1, 1))
        assertFalse(Reminders.isStale(8 * DAY + 2, 8 * DAY + 1))
    }

    private companion object { const val DAY = 24 * 60 * 60 * 1000L }
}
