package com.damirl.ray.tools

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import java.util.concurrent.CopyOnWriteArrayList

class RayNotificationListenerService : NotificationListenerService() {

    data class NotificationEntry(
        val packageName: String,
        val title: String,
        val text: String,
        val timestamp: Long
    )

    companion object {
        private const val TAG = "RayNotificationService"
        private const val MAX_HISTORY = 40
        private val history = CopyOnWriteArrayList<NotificationEntry>()

        // Multilingual regex patterns for Croatian (PBZ, ZABA, Erste, A1, HT) and English 2FA codes
        private val PATTERNS = listOf(
            // English standard & bank verification codes
            Regex("""(?i)(?:verification\s+code|security\s+code|passcode|otp|token)\s*(?:is|:)?\s*([0-9]{4,8})\b"""),
            Regex("""\b([0-9]{4,8})\s+is\s+your\s+(?:verification|security|activation)?\s*(?:code|otp|token)\b""", RegexOption.IGNORE_CASE),
            Regex("""\bcode\s*[:\-]\s*([0-9]{4,8})\b""", RegexOption.IGNORE_CASE),
            // Croatian banking & telco patterns
            Regex("""(?i)(?:jednokratna\s+(?:lozinka|zaporka)|jednokratni\s+kod|sigurnosni\s+kod|aktivacijski\s+kod|kod\s+za\s+prijavu|m-token|token)\s*(?:je|:)?\s*([0-9]{4,8})\b"""),
            Regex("""(?i)(?:va[sš]\s+jednokratni\s+kod|va[sš]\s+sigurnosni\s+kod|va[sš]\s+aktivacijski\s+kod)\s*(?:je|:)?\s*([0-9]{4,8})\b"""),
            Regex("""(?i)(?:lozinka|zaporka|kod|token)[^\d\n]{0,25}\b([0-9]{4,8})\b""")
        )

        /**
         * Multilingual Croatian & English 2FA OTP parser.
         */
        fun extract2faCode(text: String): String? {
            if (text.isBlank()) return null
            for (pattern in PATTERNS) {
                val match = pattern.find(text)
                if (match != null && match.groupValues.size > 1) {
                    return match.groupValues[1]
                }
            }
            return null
        }

        /**
         * Get recent notifications formatted for Ray.
         */
        fun getRecentNotifications(count: Int = 5): String {
            if (history.isEmpty()) {
                return "No notifications recorded yet."
            }
            val recent = history.takeLast(count.coerceIn(1, 20)).reversed()
            val sb = StringBuilder("Recent phone notifications:\n")
            for (n in recent) {
                sb.append("- [").append(n.packageName).append("] ")
                if (n.title.isNotBlank()) sb.append(n.title).append(": ")
                sb.append(n.text).append("\n")
            }
            return sb.toString().trimEnd()
        }

        /**
         * Extract the latest 2FA verification code from history.
         */
        fun getLatest2faCode(): String {
            if (history.isEmpty()) {
                return "No notifications recorded yet to check for verification codes."
            }
            for (n in history.reversed()) {
                val combined = "${n.title} ${n.text}"
                val code = extract2faCode(combined)
                if (code != null) {
                    return "Your verification code is $code (from ${n.packageName})"
                }
            }
            return "No verification code found in recent notifications."
        }
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        PhoneToolRelay.ensureBackgroundRelay(this)
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        super.onNotificationPosted(sbn)
        val notif = sbn?.notification ?: return
        val extras = notif.extras ?: return

        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: ""
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
            ?: extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
            ?: ""

        if (title.isBlank() && text.isBlank()) return

        val entry = NotificationEntry(
            packageName = sbn.packageName ?: "unknown",
            title = title,
            text = text,
            timestamp = sbn.postTime
        )

        history.add(entry)
        if (history.size > MAX_HISTORY) {
            history.removeAt(0)
        }

        val otp = extract2faCode("$title $text")
        if (otp != null) {
            Log.d(TAG, "2FA code found in a notification from ${sbn.packageName}")   // never the code itself
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        super.onNotificationRemoved(sbn)
    }
}
