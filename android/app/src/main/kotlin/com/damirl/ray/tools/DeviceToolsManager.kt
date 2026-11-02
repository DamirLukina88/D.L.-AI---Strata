package com.damirl.ray.tools

import android.app.AlarmManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.os.BatteryManager
import android.os.Build
import android.provider.AlarmClock
import android.util.Log
import org.json.JSONObject

class DeviceToolsManager(private val context: Context) {

    companion object {
        private const val TAG = "DeviceTools"
        private var isTorchOn = false
    }

    /**
     * Toggle device flashlight / torch on or off.
     */
    fun toggleTorch(enabled: Boolean): String {
        val cameraManager = context.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
            ?: return "Error: CameraManager not available on this device."

        try {
            val cameraId = cameraManager.cameraIdList.firstOrNull { id ->
                val chars = cameraManager.getCameraCharacteristics(id)
                val hasFlash = chars.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) ?: false
                val facing = chars.get(CameraCharacteristics.LENS_FACING)
                hasFlash && facing == CameraCharacteristics.LENS_FACING_BACK
            } ?: cameraManager.cameraIdList.firstOrNull()

            if (cameraId == null) {
                return "Error: No camera with flash found on device."
            }

            cameraManager.setTorchMode(cameraId, enabled)
            isTorchOn = enabled
            Log.d(TAG, "toggle_torch: $enabled on camera $cameraId")
            return "Phone flashlight turned ${if (enabled) "ON" else "OFF"}."
        } catch (e: CameraAccessException) {
            Log.e(TAG, "CameraAccessException toggling torch", e)
            return "Error toggling flashlight: ${e.message}"
        } catch (e: Exception) {
            Log.e(TAG, "Unexpected error toggling torch", e)
            return "Error toggling flashlight: ${e.message}"
        }
    }

    /**
     * Get real-time battery status, percentage, charging state, and temperature.
     */
    fun getBatteryInfo(): String {
        return try {
            val batteryStatus: Intent? = IntentFilter(Intent.ACTION_BATTERY_CHANGED).let { filter ->
                context.registerReceiver(null, filter)
            }

            val level = batteryStatus?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
            val scale = batteryStatus?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
            val pct = if (level >= 0 && scale > 0) (level * 100 / scale) else level

            val status = batteryStatus?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
            val isCharging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
                    status == BatteryManager.BATTERY_STATUS_FULL

            val chargePlug = batteryStatus?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) ?: -1
            val plugStr = when (chargePlug) {
                BatteryManager.BATTERY_PLUGGED_USB -> "USB"
                BatteryManager.BATTERY_PLUGGED_AC -> "AC Wall Charger"
                BatteryManager.BATTERY_PLUGGED_WIRELESS -> "Wireless"
                else -> "Unplugged"
            }

            val health = batteryStatus?.getIntExtra(BatteryManager.EXTRA_HEALTH, -1) ?: -1
            val healthStr = when (health) {
                BatteryManager.BATTERY_HEALTH_GOOD -> "Good"
                BatteryManager.BATTERY_HEALTH_OVERHEAT -> "Overheat"
                BatteryManager.BATTERY_HEALTH_DEAD -> "Dead"
                BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE -> "Over Voltage"
                else -> "Normal"
            }

            val tempTenths = batteryStatus?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) ?: 0
            val tempC = tempTenths / 10.0

            val json = JSONObject().apply {
                put("level", pct)
                put("isCharging", isCharging)
                put("source", plugStr)
                put("health", healthStr)
                put("temperatureCelsius", tempC)
            }

            "Battery: $pct%\nCharging: ${if (isCharging) "Yes ($plugStr)" else "No"}\nHealth: $healthStr\nTemperature: $tempC °C"
        } catch (e: Exception) {
            Log.e(TAG, "Error fetching battery info", e)
            "Error reading battery status: ${e.message}"
        }
    }

    /**
     * Set device audio volume for specific stream (media, ring, alarm, notification).
     */
    fun setVolume(stream: String, level: Int): String {
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
            ?: return "Error: AudioManager not available."

        val streamType = when (stream.lowercase().trim()) {
            "media", "music" -> AudioManager.STREAM_MUSIC
            "ring", "ringer", "call" -> AudioManager.STREAM_RING
            "alarm" -> AudioManager.STREAM_ALARM
            "notification" -> AudioManager.STREAM_NOTIFICATION
            else -> AudioManager.STREAM_MUSIC
        }

        val maxVolume = audioManager.getStreamMaxVolume(streamType)
        val targetVolume = if (level > maxVolume) {
            // Scale percentage 0-100 to 0-maxVolume
            (level * maxVolume / 100).coerceIn(0, maxVolume)
        } else {
            level.coerceIn(0, maxVolume)
        }

        audioManager.setStreamVolume(streamType, targetVolume, AudioManager.FLAG_SHOW_UI)
        Log.d(TAG, "set_volume: stream=$stream, target=$targetVolume / $maxVolume")
        return "Volume for $stream set to $targetVolume (max $maxVolume)."
    }

    /**
     * Create an alarm clock entry on the phone.
     */
    fun setAlarm(hour: Int, minute: Int, label: String): String {
        return try {
            val intent = Intent(AlarmClock.ACTION_SET_ALARM).apply {
                putExtra(AlarmClock.EXTRA_HOUR, hour)
                putExtra(AlarmClock.EXTRA_MINUTES, minute)
                putExtra(AlarmClock.EXTRA_MESSAGE, label.ifBlank { "Alarm from Ray" })
                putExtra(AlarmClock.EXTRA_SKIP_UI, true)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            }
            context.startActivity(intent)
            Log.d(TAG, "set_alarm: $hour:$minute label='$label'")
            "Alarm successfully set for %02d:%02d ('%s').".format(hour, minute, label)
        } catch (e: Exception) {
            Log.e(TAG, "Error setting alarm", e)
            "Error setting alarm: ${e.message}"
        }
    }

    /**
     * Launch an application by app name or package identifier.
     */
    fun launchApp(packageOrName: String): String {
        val pm = context.packageManager
        val query = packageOrName.lowercase().trim()

        val commonMap = mapOf(
            "spotify" to "com.spotify.music",
            "youtube" to "com.google.android.youtube",
            "camera" to "com.android.camera",
            "settings" to "com.android.settings",
            "clock" to "com.google.android.deskclock",
            "chrome" to "com.android.chrome",
            "maps" to "com.google.android.apps.maps",
            "gallery" to "com.miui.gallery",
            "calculator" to "com.miui.calculator"
        )

        val targetPkg = commonMap[query] ?: query

        // 1. Try launching by direct package name
        var launchIntent = pm.getLaunchIntentForPackage(targetPkg)

        // 2. Search installed applications by label
        if (launchIntent == null) {
            val installedApps = pm.getInstalledApplications(0)
            for (app in installedApps) {
                val appName = pm.getApplicationLabel(app).toString().lowercase()
                if (appName.contains(query) || query.contains(appName)) {
                    launchIntent = pm.getLaunchIntentForPackage(app.packageName)
                    if (launchIntent != null) break
                }
            }
        }

        if (launchIntent != null) {
            launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(launchIntent)
            Log.d(TAG, "launch_app: $packageOrName -> ${launchIntent.getPackage()}")
            return "Launched app '$packageOrName'."
        }

        return "Could not find an installed app matching '$packageOrName'."
    }
}
