package com.damirl.ray.tools

import android.app.KeyguardManager
import android.content.Context
import org.json.JSONObject

// Ray's 11 phone tools by name, with their arguments' defaults: the one place that runs them, for the web app's
// relay (RayNativeBridge.executeTool) and the adb fallback (RayToolsReceiver).  The names and arguments match the
// schemas in tools/phone_mcp.py (tools/test_phone_tool_parity.py checks it)
class PhoneTools(
    private val context: Context,
    // whether the phone is locked (PIN, pattern or fingerprint not yet given); unknown counts as locked
    private val isLocked: () -> Boolean = {
        (context.getSystemService(Context.KEYGUARD_SERVICE) as? KeyguardManager)?.isDeviceLocked ?: true
    }
) {

    private val deviceTools by lazy { DeviceToolsManager(context) }
    private val mediaController by lazy { RayMediaController(context) }
    private val cameraVision by lazy { CameraVisionManager(context) }

    fun execute(name: String, args: JSONObject): String {
        // the voice drawer opens over the lock screen, so whoever holds the locked phone could ask Ray for these
        if (name in PRIVATE && isLocked()) return LOCKED_ANSWER
        return run(name, args)
    }

    private fun run(name: String, args: JSONObject): String = when (name) {
        "phone_toggle_torch" -> deviceTools.toggleTorch(args.optBoolean("enabled", false))
        "phone_get_battery" -> deviceTools.getBatteryInfo()
        "phone_set_volume" -> deviceTools.setVolume(args.optString("stream", "media"), args.optInt("level", 50))
        "phone_set_alarm" -> deviceTools.setAlarm(
            args.optInt("hour", 8), args.optInt("minute", 0), args.optString("label", "Alarm from Ray")
        )
        "phone_launch_app" -> deviceTools.launchApp(args.optString("package_or_name", ""))
        "phone_get_recent_notifications" -> RayNotificationListenerService.getRecentNotifications(args.optInt("count", 5))
        "phone_get_2fa_code" -> RayNotificationListenerService.getLatest2faCode()
        "phone_get_now_playing" -> mediaController.getNowPlaying()
        "phone_control_media" -> mediaController.controlMedia(args.optString("action", "play_pause"))
        "phone_camera_snap" -> cameraVision.snapPhoto(args.optString("prompt", ""))
        "phone_get_screen" -> RayAccessibilityService.getScreenContent()
        else -> "Error: Unknown tool '$name'."
    }

    companion object {
        /** Tools that read what's private on the phone: refused while it is locked. */
        val PRIVATE = setOf("phone_get_2fa_code", "phone_get_recent_notifications", "phone_get_screen")

        const val LOCKED_ANSWER = "Error: the phone is locked. Codes, notifications and the screen are only read once " +
            "the user has unlocked it, so ask them to unlock the phone and try again."

        /** The tool names above, in order (the parity test reads the `when`, this is for code). */
        val NAMES = listOf(
            "phone_toggle_torch", "phone_get_battery", "phone_set_volume", "phone_set_alarm", "phone_launch_app",
            "phone_get_recent_notifications", "phone_get_2fa_code", "phone_get_now_playing", "phone_control_media",
            "phone_camera_snap", "phone_get_screen"
        )
    }
}
