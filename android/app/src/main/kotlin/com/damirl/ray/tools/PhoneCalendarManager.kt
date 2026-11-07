package com.damirl.ray.tools

import android.Manifest
import android.accounts.Account
import android.content.ContentResolver
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.CalendarContract
import android.util.Log
import androidx.core.content.ContextCompat
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Direct Google Calendar integration on the phone via Android's `CalendarContract` provider (`phone_calendar`).
 *
 * Works silently in the background (including while the phone is locked) and triggers an immediate sync with
 * the user's Google Calendar account.
 */
class PhoneCalendarManager(private val context: Context) {

    companion object {
        private const val TAG = "RayCalendar"
    }

    data class TargetCalendar(
        val id: Long,
        val displayName: String,
        val accountName: String,
        val accountType: String,
        val isPrimary: Boolean,
        val accessLevel: Int
    )

    fun execute(
        action: String = "list",
        title: String = "",
        startTime: String = "",
        endTime: String = "",
        durationMinutes: Int = 60,
        location: String = "",
        description: String = "",
        daysAhead: Int = 7,
        reminderMinutes: Int = 15,
        eventId: Long = 0L
    ): String {
        val act = action.trim().lowercase(Locale.US)
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED) {
            return "Error: Calendar permission (READ_CALENDAR) is not granted yet."
        }

        return when (act) {
            "list", "upcoming", "get" -> listUpcomingEvents(daysAhead.coerceIn(1, 90), title)
            "add", "create", "schedule", "insert" -> {
                if (ContextCompat.checkSelfPermission(context, Manifest.permission.WRITE_CALENDAR) != PackageManager.PERMISSION_GRANTED) {
                    return "Error: Calendar write permission (WRITE_CALENDAR) is not granted yet."
                }
                addEvent(title, startTime, endTime, durationMinutes, location, description, reminderMinutes)
            }
            "delete", "remove", "cancel" -> {
                if (ContextCompat.checkSelfPermission(context, Manifest.permission.WRITE_CALENDAR) != PackageManager.PERMISSION_GRANTED) {
                    return "Error: Calendar write permission (WRITE_CALENDAR) is not granted yet."
                }
                deleteEvent(eventId, title)
            }
            "calendars", "accounts" -> listCalendars()
            else -> "Error: Unknown phone_calendar action '$action'. Use 'list', 'add', 'delete', or 'calendars'."
        }
    }

    private fun queryWritableGoogleCalendars(): List<TargetCalendar> {
        val out = mutableListOf<TargetCalendar>()
        val projection = arrayOf(
            CalendarContract.Calendars._ID,
            CalendarContract.Calendars.CALENDAR_DISPLAY_NAME,
            CalendarContract.Calendars.ACCOUNT_NAME,
            CalendarContract.Calendars.ACCOUNT_TYPE,
            CalendarContract.Calendars.IS_PRIMARY,
            CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL,
            CalendarContract.Calendars.OWNER_ACCOUNT
        )
        try {
            context.contentResolver.query(
                CalendarContract.Calendars.CONTENT_URI,
                projection,
                "${CalendarContract.Calendars.VISIBLE} = 1",
                null,
                null
            )?.use { c ->
                while (c.moveToNext()) {
                    val id = c.getLong(0)
                    val disp = c.getString(1) ?: "Calendar"
                    val acct = c.getString(2) ?: ""
                    val type = c.getString(3) ?: ""
                    val primary = c.getInt(4) == 1 || (c.getString(6) ?: "") == acct
                    val access = c.getInt(5)
                    out.add(TargetCalendar(id, disp, acct, type, primary, access))
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error querying calendars", e)
        }
        return out.sortedWith(
            compareByDescending<TargetCalendar> { it.accountType == "com.google" && it.accessLevel >= CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR }
                .thenByDescending { it.isPrimary }
                .thenByDescending { it.accessLevel }
        )
    }

    private fun listCalendars(): String {
        val cals = queryWritableGoogleCalendars()
        if (cals.isEmpty()) return "No calendars found on the phone."
        val sb = StringBuilder("Phone Calendars (${cals.size}):\n")
        for (c in cals) {
            val tag = if (c.accountType == "com.google") "Google Calendar" else c.accountType
            val prim = if (c.isPrimary) ", primary" else ""
            sb.append("  - [id=${c.id}] ${c.displayName} (${c.accountName} — $tag$prim)\n")
        }
        return sb.toString().trimEnd()
    }

    private fun listUpcomingEvents(daysAhead: Int, filterTitle: String): String {
        val now = System.currentTimeMillis()
        val end = now + daysAhead * 24L * 3600_000L
        val builder = CalendarContract.Instances.CONTENT_URI.buildUpon()
        ContentUris.appendId(builder, now - 3600_000L)
        ContentUris.appendId(builder, end)

        val projection = arrayOf(
            CalendarContract.Instances.EVENT_ID,
            CalendarContract.Instances.TITLE,
            CalendarContract.Instances.BEGIN,
            CalendarContract.Instances.END,
            CalendarContract.Instances.EVENT_LOCATION,
            CalendarContract.Instances.DESCRIPTION,
            CalendarContract.Instances.CALENDAR_DISPLAY_NAME,
            CalendarContract.Instances.ALL_DAY
        )

        val fmt = SimpleDateFormat("EEE yyyy-MM-dd HH:mm", Locale.US)
        val q = filterTitle.trim().lowercase(Locale.US)
        val rows = mutableListOf<String>()

        try {
            context.contentResolver.query(
                builder.build(),
                projection,
                "${CalendarContract.Instances.VISIBLE} = 1",
                null,
                "${CalendarContract.Instances.BEGIN} ASC"
            )?.use { c ->
                while (c.moveToNext() && rows.size < 40) {
                    val eventId = c.getLong(0)
                    val evTitle = (c.getString(1) ?: "(No title)").trim()
                    if (q.isNotEmpty() && !evTitle.lowercase(Locale.US).contains(q)) continue
                    val beginMs = c.getLong(2)
                    val endMs = c.getLong(3)
                    val loc = (c.getString(4) ?: "").trim()
                    val calName = (c.getString(6) ?: "Calendar").trim()
                    val allDay = c.getInt(7) == 1

                    val timeStr = if (allDay) {
                        SimpleDateFormat("EEE yyyy-MM-dd (All day)", Locale.US).format(Date(beginMs))
                    } else {
                        "${fmt.format(Date(beginMs))} – ${SimpleDateFormat("HH:mm", Locale.US).format(Date(endMs))}"
                    }
                    val locStr = if (loc.isNotEmpty()) " @ $loc" else ""
                    rows.add("  - [event_id=$eventId] $timeStr: '$evTitle'$locStr ($calName)")
                }
            }
        } catch (e: Exception) {
            return "Error reading Google Calendar events: ${e.message}"
        }

        if (rows.isEmpty()) {
            return "No upcoming calendar events found in the next $daysAhead day(s)."
        }
        return "Upcoming Google Calendar events (next $daysAhead days):\n" + rows.joinToString("\n")
    }

    private fun addEvent(
        title: String,
        startTimeStr: String,
        endTimeStr: String,
        durationMinutes: Int,
        location: String,
        description: String,
        reminderMinutes: Int
    ): String {
        val cleanTitle = title.trim()
        if (cleanTitle.isEmpty()) {
            return "Error: 'title' is required when creating a Google Calendar event."
        }
        val startMs = parseDateTime(startTimeStr)
            ?: return "Error: Could not parse 'start_time' ('$startTimeStr'). Use 'YYYY-MM-DD HH:MM' (e.g. '2026-11-08 14:30')."

        val durMin = durationMinutes.coerceIn(5, 24 * 60)
        val endMs = if (endTimeStr.isNotBlank()) {
            parseDateTime(endTimeStr) ?: (startMs + durMin * 60_000L)
        } else {
            startMs + durMin * 60_000L
        }

        val cals = queryWritableGoogleCalendars().filter {
            it.accessLevel >= CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR
        }
        val targetCal = cals.firstOrNull()
            ?: return "Error: No writable Google Calendar found on the phone. Open the Google Calendar app once to ensure your Google account is signed in."

        val tz = TimeZone.getDefault().id
        val values = ContentValues().apply {
            put(CalendarContract.Events.CALENDAR_ID, targetCal.id)
            put(CalendarContract.Events.TITLE, cleanTitle)
            put(CalendarContract.Events.DTSTART, startMs)
            put(CalendarContract.Events.DTEND, endMs.coerceAtLeast(startMs + 60_000L))
            put(CalendarContract.Events.EVENT_TIMEZONE, tz)
            if (location.isNotBlank()) put(CalendarContract.Events.EVENT_LOCATION, location.trim())
            if (description.isNotBlank()) put(CalendarContract.Events.DESCRIPTION, description.trim())
            put(CalendarContract.Events.HAS_ALARM, if (reminderMinutes >= 0) 1 else 0)
        }

        val uri = try {
            context.contentResolver.insert(CalendarContract.Events.CONTENT_URI, values)
        } catch (e: Exception) {
            return "Error inserting Google Calendar event: ${e.message}"
        } ?: return "Error: ContentResolver returned null when inserting calendar event."

        val eventId = ContentUris.parseId(uri)

        if (reminderMinutes >= 0 && eventId > 0) {
            try {
                val remValues = ContentValues().apply {
                    put(CalendarContract.Reminders.EVENT_ID, eventId)
                    put(CalendarContract.Reminders.MINUTES, reminderMinutes)
                    put(CalendarContract.Reminders.METHOD, CalendarContract.Reminders.METHOD_ALERT)
                }
                context.contentResolver.insert(CalendarContract.Reminders.CONTENT_URI, remValues)
            } catch (e: Exception) {
                Log.w(TAG, "Reminder insert skipped: ${e.message}")
            }
        }

        // Trigger immediate Google Calendar cloud sync
        if (targetCal.accountName.isNotEmpty() && targetCal.accountType.isNotEmpty()) {
            try {
                val extras = Bundle().apply {
                    putBoolean(ContentResolver.SYNC_EXTRAS_MANUAL, true)
                    putBoolean(ContentResolver.SYNC_EXTRAS_EXPEDITED, true)
                }
                ContentResolver.requestSync(
                    Account(targetCal.accountName, targetCal.accountType),
                    CalendarContract.AUTHORITY,
                    extras
                )
            } catch (_: Throwable) {
            }
        }

        val fmt = SimpleDateFormat("EEE yyyy-MM-dd HH:mm", Locale.US)
        return "Scheduled Google Calendar event '$cleanTitle' (event_id=$eventId) on ${targetCal.accountName} " +
            "from ${fmt.format(Date(startMs))} to ${SimpleDateFormat("HH:mm", Locale.US).format(Date(endMs))}."
    }

    private fun deleteEvent(eventId: Long, titleQuery: String): String {
        var targetId = eventId
        if (targetId <= 0L && titleQuery.isNotBlank()) {
            val q = titleQuery.trim()
            try {
                context.contentResolver.query(
                    CalendarContract.Events.CONTENT_URI,
                    arrayOf(CalendarContract.Events._ID, CalendarContract.Events.TITLE),
                    "${CalendarContract.Events.DELETED} = 0 AND ${CalendarContract.Events.TITLE} LIKE ?",
                    arrayOf("%$q%"),
                    "${CalendarContract.Events.DTSTART} DESC"
                )?.use { c ->
                    if (c.moveToFirst()) {
                        targetId = c.getLong(0)
                    }
                }
            } catch (_: Exception) {
            }
        }
        if (targetId <= 0L) {
            return "Error: Specify a valid 'event_id' or matching 'title' to delete a Google Calendar event."
        }
        return try {
            val uri = ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, targetId)
            val rows = context.contentResolver.delete(uri, null, null)
            if (rows > 0) {
                "Deleted Google Calendar event (event_id=$targetId)."
            } else {
                "No Google Calendar event found with event_id=$targetId."
            }
        } catch (e: Exception) {
            "Error deleting calendar event: ${e.message}"
        }
    }

    private fun parseDateTime(raw: String): Long? {
        val s = raw.trim()
        if (s.isEmpty()) return null
        if (s.all { it.isDigit() }) {
            val v = s.toLongOrNull() ?: return null
            return if (v < 10_000_000_000L) v * 1000L else v
        }

        val lower = s.lowercase(Locale.US)
        val cal = Calendar.getInstance()
        if (lower.startsWith("tomorrow") || lower.startsWith("today")) {
            if (lower.startsWith("tomorrow")) cal.add(Calendar.DAY_OF_YEAR, 1)
            val timePart = lower.removePrefix("tomorrow").removePrefix("today").removePrefix("at").trim()
            val hm = timePart.split(":")
            val h = hm.getOrNull(0)?.trim()?.toIntOrNull() ?: 9
            val m = hm.getOrNull(1)?.trim()?.take(2)?.toIntOrNull() ?: 0
            cal.set(Calendar.HOUR_OF_DAY, h.coerceIn(0, 23))
            cal.set(Calendar.MINUTE, m.coerceIn(0, 59))
            cal.set(Calendar.SECOND, 0)
            cal.set(Calendar.MILLISECOND, 0)
            return cal.timeInMillis
        }

        val normalized = s.replace("T", " ").removeSuffix("Z").trim()
        val patterns = listOf(
            "yyyy-MM-dd HH:mm:ss",
            "yyyy-MM-dd HH:mm",
            "yyyy-MM-dd",
            "dd.MM.yyyy HH:mm",
            "dd/MM/yyyy HH:mm"
        )
        for (pat in patterns) {
            try {
                val df = SimpleDateFormat(pat, Locale.US).apply { isLenient = false }
                val d = df.parse(normalized)
                if (d != null) return d.time
            } catch (_: Exception) {
            }
        }
        return null
    }
}
