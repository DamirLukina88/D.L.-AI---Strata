package com.damirl.ray.tools

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
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

        /** Taps a visible element of [pkg] labelled one of [labels] (case-insensitive), trying them in order. */
        fun tapLabelled(pkg: String, labels: List<String>): Boolean {
            val service = instance ?: return false
            val roots = service.windows.mapNotNull { it.root }.filter { it.packageName?.toString() == pkg }
            for (wanted in labels) {
                for (root in roots) {
                    val queue = ArrayDeque(listOf(root))
                    var seen = 0
                    while (queue.isNotEmpty() && seen++ < 4000) {
                        val node = queue.removeFirst()
                        val label = (node.contentDescription ?: node.text)?.toString()?.trim()?.lowercase()
                        if ((label == wanted || label?.startsWith("$wanted (") == true) && node.isVisibleToUser &&
                            tap(service, node, pkg, label)) return true
                        for (i in 0 until node.childCount) node.getChild(i)?.let { queue.add(it) }
                    }
                }
            }
            return false
        }

        // the label can sit on a child of the button: the nearest clickable one gets the click; a web page may
        // ignore that, so a tap on the screen where the button is comes next
        private fun tap(service: RayAccessibilityService, node: AccessibilityNodeInfo, pkg: String, label: String): Boolean {
            var target: AccessibilityNodeInfo? = node
            while (target != null && !target.isClickable) target = target.parent
            if ((target ?: node).performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                Log.d(TAG, "Clicked '$label' in $pkg")
                return true
            }
            val box = Rect().also { node.getBoundsInScreen(it) }
            if (!box.isEmpty && service.tapAt(box.exactCenterX(), box.exactCenterY())) {
                Log.d(TAG, "Tapped '$label' in $pkg at ${box.centerX()},${box.centerY()}")
                return true
            }
            return false
        }

        /** Locks the phone (screen off) - after Ray unlocked a trusted phone to start a song. */
        fun lockScreen(): Boolean = instance?.performGlobalAction(GLOBAL_ACTION_LOCK_SCREEN) == true

        /** Debug only: the labels [pkg]'s windows show (why a tap found nothing). */
        fun labelsOf(pkg: String): String {
            val service = instance ?: return "screen reading is off"
            val out = mutableListOf<String>()
            for (window in service.windows) {
                val root = window.root ?: continue
                if (root.packageName?.toString() != pkg) continue
                val queue = ArrayDeque(listOf(root))
                while (queue.isNotEmpty() && out.size < 60) {
                    val node = queue.removeFirst()
                    (node.contentDescription ?: node.text)?.toString()?.trim()?.takeIf { it.isNotEmpty() }
                        ?.let { out.add(it.take(30)) }
                    for (i in 0 until node.childCount) node.getChild(i)?.let { queue.add(it) }
                }
            }
            return if (out.isEmpty()) "no labels (${service.windows.size} windows)" else out.joinToString(" | ")
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

    private fun tapAt(x: Float, y: Float): Boolean {
        val path = Path().apply { moveTo(x, y) }
        return dispatchGesture(GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 60)).build(), null, null)
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        PhoneToolRelay.ensureBackgroundRelay(this)
        PhoneClipboardManager.ensureListener(this)
        Log.d(TAG, "RayAccessibilityService connected")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val ev = event ?: return
        if (ev.eventType == AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED ||
            ev.eventType == AccessibilityEvent.TYPE_ANNOUNCEMENT ||
            ev.eventType == AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED
        ) {
            PhoneClipboardManager.onAccessibilityCopyCandidate(this)
        }
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
