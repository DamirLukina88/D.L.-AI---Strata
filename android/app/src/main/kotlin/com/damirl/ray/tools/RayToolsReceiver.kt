package com.damirl.ray.tools

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import org.json.JSONObject

// Phone tools by broadcast, for tools/phone_mcp.py's adb fallback (when the app's web page isn't open to relay them).
// The manifest requires android.permission.DUMP from the sender: the adb shell holds it, ordinary apps can't, so no
// other app on the phone can toggle the torch, launch apps or set alarms through Ray
class RayToolsReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "RayToolsReceiver"
        const val ACTION_EXECUTE_TOOL = "com.damirl.ray.ACTION_EXECUTE_TOOL"
        const val ACTION_TORCH = "com.damirl.ray.ACTION_TORCH"
        // debug builds: the next drawer asks this instead of listening (tools/helmet_test.py ask).  Here and nowhere
        // else: this phone's daily app is a debug build, so only this receiver's DUMP permission keeps other apps out
        const val ACTION_SCRIPTED_PROMPT = "com.damirl.ray.ACTION_SCRIPTED_PROMPT"
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
            ACTION_SCRIPTED_PROMPT -> {
                if (com.damirl.ray.BuildConfig.DEBUG) {
                    com.damirl.ray.assistant.VoiceDrawerController.scriptedPrompt = intent.getStringExtra("text")
                }
            }
            ACTION_EXECUTE_TOOL -> {
                val tool = intent.getStringExtra("tool") ?: return
                val args = try {
                    JSONObject(intent.getStringExtra("args") ?: "{}")
                } catch (_: Exception) {
                    JSONObject()
                }
                // off the main thread: some tools use the network (phone_get_last_photo uploads the photo)
                val pending = goAsync()
                Thread {
                    try {
                        val result = PhoneTools(context).execute(tool, args)
                        Log.d(TAG, "Tool $tool from adb: ${result.take(80)}")
                    } catch (e: Exception) {
                        Log.e(TAG, "Error executing tool from broadcast: $tool", e)
                    } finally {
                        pending.finish()
                    }
                }.start()
            }
        }
    }
}
