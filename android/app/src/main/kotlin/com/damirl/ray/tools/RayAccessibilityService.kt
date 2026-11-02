package com.damirl.ray.tools

import android.accessibilityservice.AccessibilityService
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

class RayAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "RayAccessibility"
        private var instance: RayAccessibilityService? = null

        fun isRunning(): Boolean = instance != null

        /**
         * Collect visible screen content from currently active window.
         */
        fun getScreenContent(): String {
            val service = instance
                ?: return "Accessibility service is not enabled. Please enable Ray Screen Accessibility in Settings."

            val root = service.rootInActiveWindow
                ?: return "No active window content accessible."

            val texts = mutableListOf<String>()
            traverseNode(root, texts, depth = 0)
            root.recycle()

            val uniqueTexts = texts.map { it.trim() }.filter { it.length > 1 }.distinct()
            if (uniqueTexts.isEmpty()) {
                return "No readable text detected on the current screen."
            }

            val sb = StringBuilder("Visible screen content:\n")
            for (t in uniqueTexts.take(40)) {
                sb.append("- ").append(t).append("\n")
            }
            return sb.toString().trimEnd()
        }

        private fun traverseNode(node: AccessibilityNodeInfo?, out: MutableList<String>, depth: Int) {
            if (node == null || depth > 15) return

            val text = node.text?.toString()
            val desc = node.contentDescription?.toString()

            if (!text.isNullOrBlank()) out.add(text)
            if (!desc.isNullOrBlank() && desc != text) out.add(desc)

            for (i in 0 until node.childCount) {
                val child = node.getChild(i)
                traverseNode(child, out, depth + 1)
                child?.recycle()
            }
        }
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.d(TAG, "RayAccessibilityService connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Events monitored for screen updates
    }

    override fun onInterrupt() {
        Log.d(TAG, "RayAccessibilityService interrupted")
    }

    override fun onDestroy() {
        super.onDestroy()
        if (instance == this) instance = null
        Log.d(TAG, "RayAccessibilityService destroyed")
    }
}
