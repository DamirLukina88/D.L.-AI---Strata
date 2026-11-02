package com.damirl.ray

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Accessibility
import androidx.compose.material.icons.filled.BatteryChargingFull
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.damirl.ray.tools.RayAccessibilityService
import com.damirl.ray.ui.components.RayAvatar
import com.damirl.ray.ui.theme.RayTheme
import com.damirl.ray.ui.theme.StrataAccent
import com.damirl.ray.ui.theme.StrataAccentText
import com.damirl.ray.ui.theme.StrataAccentTint
import com.damirl.ray.ui.theme.StrataBg
import com.damirl.ray.ui.theme.StrataInk
import com.damirl.ray.ui.theme.StrataInkMuted
import com.damirl.ray.ui.theme.StrataLine
import com.damirl.ray.ui.theme.StrataOk
import com.damirl.ray.ui.theme.StrataOkTint
import com.damirl.ray.ui.theme.StrataSurface
import com.damirl.ray.ui.theme.StrataSurface2

class OnboardingActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
        )

        setContent {
            RayTheme {
                PermissionsDashboard(
                    onContinue = {
                        startActivity(Intent(this, MainActivity::class.java))
                        finish()
                    }
                )
            }
        }
    }
}

@Composable
fun PermissionsDashboard(
    onContinue: () -> Unit
) {
    val context = LocalContext.current
    val powerManager = context.getSystemService(Context.POWER_SERVICE) as? PowerManager

    fun micGranted() = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
        PackageManager.PERMISSION_GRANTED
    fun notificationsGranted() = NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)
    // from Android's list of switched-on services, so it reads right even while the service isn't running
    fun screenReadingOn() = (Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: "")
        .split(':').any { it.equals(ComponentName(context, RayAccessibilityService::class.java).flattenToString(), ignoreCase = true) } ||
        RayAccessibilityService.isRunning()

    var isMicGranted by remember { mutableStateOf(micGranted()) }
    var isBatteryIgnored by remember {
        mutableStateOf(powerManager?.isIgnoringBatteryOptimizations(context.packageName) == true)
    }
    var isNotificationAccess by remember { mutableStateOf(notificationsGranted()) }
    var isAccessibilityActive by remember { mutableStateOf(screenReadingOn()) }
    var autostart by remember { mutableStateOf(xiaomiAutostart(context)) }

    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        isMicGranted = micGranted()
        isBatteryIgnored = powerManager?.isIgnoringBatteryOptimizations(context.packageName) == true
        isNotificationAccess = notificationsGranted()
        isAccessibilityActive = screenReadingOn()
        autostart = xiaomiAutostart(context)
    }

    val micLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        isMicGranted = granted
    }

    // Autostart counts where the phone lets Ray read it (Xiaomi); elsewhere only the other four
    val checks = listOfNotNull(isMicGranted, autostart, isBatteryIgnored, isNotificationAccess, isAccessibilityActive)
    val total = checks.size
    val ready = checks.count { it }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(StrataBg)
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Header: Ray, what this is for, how far along it is
        Row(verticalAlignment = Alignment.CenterVertically) {
            RayAvatar(size = 56.dp)
            Spacer(modifier = Modifier.width(14.dp))
            Column {
                Text("Set up Ray", color = StrataInk, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                Text("Permissions for your phone", color = StrataInkMuted, fontSize = 14.sp)
            }
        }
        Text(
            text = "These let Ray listen when you hold the button, keep talking in the background, " +
                "read 2FA codes and what's playing, and look at your screen when you ask.",
            color = StrataInkMuted,
            fontSize = 14.sp,
            lineHeight = 20.sp
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            LinearProgressIndicator(
                progress = { ready / total.toFloat() },
                modifier = Modifier
                    .weight(1f)
                    .height(6.dp)
                    .clip(CircleShape),
                color = if (ready == total) StrataOk else StrataAccent,
                trackColor = StrataSurface2,
                strokeCap = StrokeCap.Round,
                gapSize = 0.dp,
                drawStopIndicator = {}
            )
            Spacer(modifier = Modifier.width(12.dp))
            Text("$ready of $total ready", color = if (ready == total) StrataOk else StrataAccentText, fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold)
        }

        Spacer(modifier = Modifier.height(4.dp))

        PermissionCard(
            title = "Microphone",
            desc = "So Ray hears you when you hold the button or tap the mic.",
            icon = Icons.Default.Mic,
            isGranted = isMicGranted,
            actionLabel = "Allow microphone",
            onAction = { micLauncher.launch(Manifest.permission.RECORD_AUDIO) }
        )

        PermissionCard(
            title = "Autostart",
            desc = if (autostart == null) {
                "Lets Ray start in the background for headset buttons and wake-up. This phone doesn't tell apps " +
                    "whether it is on, so check it once."
            } else {
                "Lets Ray start in the background for headset buttons and wake-up."
            },
            icon = Icons.Default.PowerSettingsNew,
            isGranted = autostart == true,
            actionLabel = "Open Autostart settings",
            onAction = {
                try {
                    val intent = Intent().apply {
                        component = ComponentName(
                            "com.miui.securitycenter",
                            "com.miui.permcenter.autostart.AutoStartManagementActivity"
                        )
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK
                    }
                    context.startActivity(intent)
                } catch (_: Exception) {
                    val fallback = Intent(Settings.ACTION_SETTINGS).apply {
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK
                    }
                    context.startActivity(fallback)
                }
            }
        )

        PermissionCard(
            title = "No battery restrictions",
            desc = "Keeps Android from stopping Ray's voice while he reads a reply in the background.",
            icon = Icons.Default.BatteryChargingFull,
            isGranted = isBatteryIgnored,
            actionLabel = "Remove restrictions",
            onAction = {
                try {
                    val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                        data = Uri.parse("package:${context.packageName}")
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK
                    }
                    context.startActivity(intent)
                } catch (_: Exception) {
                    val intent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).apply {
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK
                    }
                    context.startActivity(intent)
                }
            }
        )

        PermissionCard(
            title = "Notification access",
            desc = "Lets Ray read 2FA codes and what Spotify or YouTube is playing.",
            icon = Icons.Default.Notifications,
            isGranted = isNotificationAccess,
            actionLabel = "Open notification access",
            onAction = {
                val intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
            }
        )

        PermissionCard(
            title = "Screen reading",
            desc = "Lets Ray read the text on your screen when you ask \"what's on my screen?\". On Xiaomi: " +
                "Accessibility, General tab, scroll to the bottom, Downloaded apps, Ray Screen Accessibility. If " +
                "Android says it's a restricted setting: App info, the ⋮ menu, Allow restricted settings, then try again.",
            icon = Icons.Default.Accessibility,
            isGranted = isAccessibilityActive,
            actionLabel = "Open Accessibility",
            onAction = {
                val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
            }
        )

        Spacer(modifier = Modifier.height(8.dp))

        Button(
            onClick = onContinue,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            shape = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(containerColor = StrataAccent, contentColor = StrataInk)
        ) {
            Text("Open Ray", fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.width(8.dp))
            Icon(Icons.AutoMirrored.Filled.ArrowForward, contentDescription = null)
        }

        Spacer(modifier = Modifier.height(8.dp))
    }
}

// One permission: an icon tile (orange to do, green once done), what it is for, and the way to it.  A permission
// Android reports as done shows a "Ready" badge instead of the button; one it can't report keeps its button
@Composable
fun PermissionCard(
    title: String,
    desc: String,
    icon: ImageVector,
    actionLabel: String,
    isGranted: Boolean = false,
    onAction: () -> Unit
) {
    val shape = RoundedCornerShape(16.dp)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(StrataSurface)
            .border(1.dp, StrataLine, shape)
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(if (isGranted) StrataOkTint else StrataAccentTint),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = if (isGranted) StrataOk else StrataAccentText,
                    modifier = Modifier.size(22.dp)
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            Text(
                text = title,
                color = StrataInk,
                fontWeight = FontWeight.SemiBold,
                fontSize = 16.sp,
                modifier = Modifier.weight(1f)
            )
            if (isGranted) {
                Row(
                    modifier = Modifier
                        .clip(CircleShape)
                        .background(StrataOkTint)
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Default.Check, contentDescription = null, tint = StrataOk, modifier = Modifier.size(14.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Ready", color = StrataOk, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                }
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        Text(text = desc, color = StrataInkMuted, fontSize = 13.sp, lineHeight = 18.sp)
        if (!isGranted) {
            Spacer(modifier = Modifier.height(12.dp))
            OutlinedButton(
                onClick = onAction,
                shape = RoundedCornerShape(12.dp),
                border = BorderStroke(1.dp, StrataAccent.copy(alpha = 0.6f)),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = StrataAccentText),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(actionLabel, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

// Xiaomi's Autostart switch for this app: app-op 10008 (MIUIOP_AUTO_START, shown by `adb shell appops get
// com.damirl.ray`), read through AppOpsManager's hidden int-op check.  null where it can't be read (other phones, or
// Android refusing the hidden call): the card then keeps its button and doesn't count
private fun xiaomiAutostart(context: Context): Boolean? {
    if (!android.os.Build.MANUFACTURER.equals("Xiaomi", ignoreCase = true)) return null
    return try {
        val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as android.app.AppOpsManager
        val check = android.app.AppOpsManager::class.java.getMethod(
            "checkOpNoThrow", Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, String::class.java
        )
        val mode = check.invoke(appOps, 10008, android.os.Process.myUid(), context.packageName) as Int
        android.util.Log.d("RayOnboarding", "Xiaomi autostart app-op mode=$mode")
        mode == android.app.AppOpsManager.MODE_ALLOWED
    } catch (e: Exception) {
        android.util.Log.w("RayOnboarding", "Xiaomi autostart unreadable", e)
        null
    }
}
