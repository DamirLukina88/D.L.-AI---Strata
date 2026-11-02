package com.damirl.ray.tools

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import org.json.JSONObject

class RayToolsReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "RayToolsReceiver"
        const val ACTION_EXECUTE_TOOL = "com.damirl.ray.ACTION_EXECUTE_TOOL"
        const val ACTION_TORCH = "com.damirl.ray.ACTION_TORCH"
        const val ACTION_CAMERA_SNAP = "com.damirl.ray.ACTION_CAMERA_SNAP"
    }

    override fun onReceive(context: Context, intent: Intent?) {
        if (intent == null) return
        val action = intent.action ?: return
        Log.d(TAG, "onReceive action: $action")

        val toolsManager = DeviceToolsManager(context)

        when (action) {
            ACTION_TORCH -> {
                val enabled = intent.getBooleanExtra("enabled", false)
                toolsManager.toggleTorch(enabled)
            }
            ACTION_CAMERA_SNAP -> {
                val prompt = intent.getStringExtra("prompt") ?: ""
                val cameraManager = CameraVisionManager(context)
                cameraManager.snapPhoto(prompt)
            }
            ACTION_EXECUTE_TOOL -> {
                val tool = intent.getStringExtra("tool") ?: return
                val argsStr = intent.getStringExtra("args") ?: "{}"
                try {
                    val args = JSONObject(argsStr)
                    when (tool) {
                        "phone_toggle_torch" -> {
                            val enabled = args.optBoolean("enabled", false)
                            toolsManager.toggleTorch(enabled)
                        }
                        "phone_set_volume" -> {
                            val stream = args.optString("stream", "media")
                            val level = args.optInt("level", 50)
                            toolsManager.setVolume(stream, level)
                        }
                        "phone_set_alarm" -> {
                            val hour = args.optInt("hour", 8)
                            val minute = args.optInt("minute", 0)
                            val label = args.optString("label", "Alarm from Ray")
                            toolsManager.setAlarm(hour, minute, label)
                        }
                        "phone_launch_app" -> {
                            val pkg = args.optString("package_or_name", "")
                            toolsManager.launchApp(pkg)
                        }
                        "phone_control_media" -> {
                            val mediaAction = args.optString("action", "play_pause")
                            RayMediaController(context).controlMedia(mediaAction)
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Error executing tool from broadcast: $tool", e)
                }
            }
        }
    }
}
