package com.damirl.ray.tools

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Log
import com.damirl.ray.network.NetworkClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Full 107-sensor hardware reader and on-demand real-time telemetry streamer for Xiaomi 17 Ultra.
 *
 * Supports:
 * 1. `phone_read_sensors`: Instant snapshot of all hardware & virtual sensors (`Sensor.TYPE_ALL`), plus computed
 *    Spirit Level (pitch, roll, total tilt angle to 0.01°, surface evenness status, which edge is higher),
 *    compass heading, barometric pressure/altitude, front/back lux, CCT, flicker, proximity, steps, and Xiaomi context.
 * 2. `phone_sensor_stream`: On-demand high-frequency real-time streaming (`mode`: "jumps", "level", "raw") with
 *    live jump height / flight-time / G-force detection and live dashboard streaming to the Ray Web UI.
 */
object PhoneSensorManager {
    private const val TAG = "RaySensors"
    private const val GRAVITY_EARTH = 9.80665
    private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
    private val OCTET_MEDIA = "application/octet-stream".toMediaType()

    data class SensorReading(
        val handle: Int,
        val name: String,
        val vendor: String,
        val type: Int,
        val stringType: String,
        val reportingMode: Int,
        val isWakeUp: Boolean,
        val maxRange: Float,
        val resolution: Float,
        val powerMa: Float,
        val minDelayUs: Int,
        val values: FloatArray,
        val accuracy: Int,
        val timestampNs: Long,
        val updatedWallMs: Long
    )

    // Cached last-known reading per sensor key ("type:name:wakeup")
    private val latestReadings = ConcurrentHashMap<String, SensorReading>()

    // Live streaming state
    @Volatile private var streamingActive = false
    @Volatile private var streamId = ""
    @Volatile private var streamMode = "jumps"
    @Volatile private var streamStartWallMs = 0L
    @Volatile private var streamEndWallMs = 0L
    @Volatile private var streamSampleCount = 0L
    @Volatile private var streamThread: HandlerThread? = null
    @Volatile private var streamHandler: Handler? = null
    @Volatile private var activeListener: SensorEventListener? = null

    // Jump & motion metrics during active stream
    data class JumpEvent(
        val index: Int,
        val flightTimeMs: Double,
        val heightCm: Double,
        val peakTakeoffG: Double,
        val peakLandingG: Double,
        val timestampMs: Long
    )

    private val detectedJumps = java.util.concurrent.CopyOnWriteArrayList<JumpEvent>()
    @Volatile private var inFreeFall = false
    @Volatile private var freeFallStartNs = 0L
    @Volatile private var currentPreJumpPeakG = 1.0
    @Volatile private var pendingLandingJumpIdx = -1
    @Volatile private var pendingLandingDeadlineNs = 0L
    @Volatile private var maxStreamG = 1.0
    @Volatile private var minStreamG = 1.0

    // Rolling waveform history (last 80 frames for oscilloscope in Web UI)
    private val waveformHistory = ArrayDeque<JSONObject>(96)

    private fun sensorKey(s: Sensor): String = "${s.type}:${s.name}:${s.isWakeUpSensor}"

    /**
     * Read all (or filtered) sensors on the phone by sampling live for [sampleMs] milliseconds.
     */
    fun readSensors(
        context: Context,
        category: String = "all",
        sampleMs: Int = 280
    ): String {
        val sm = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
            ?: return "Error: SensorManager not available on this device."

        val allSensors = sm.getSensorList(Sensor.TYPE_ALL)
        if (allSensors.isEmpty()) {
            return "Error: No sensors reported by SensorManager."
        }

        val durationMs = sampleMs.coerceIn(80, 5000)
        val ht = HandlerThread("RaySensorSnapshot").apply { start() }
        val handler = Handler(ht.looper)
        val latch = CountDownLatch(1)

        // Track accelerometer samples for vibration/stability RMS
        val accelMagnitudes = mutableListOf<Double>()

        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent?) {
                val ev = event ?: return
                val s = ev.sensor ?: return
                val copy = ev.values.clone()
                latestReadings[sensorKey(s)] = SensorReading(
                    handle = s.id,
                    name = s.name,
                    vendor = s.vendor ?: "",
                    type = s.type,
                    stringType = s.stringType ?: "sensor.${s.type}",
                    reportingMode = s.reportingMode,
                    isWakeUp = s.isWakeUpSensor,
                    maxRange = s.maximumRange,
                    resolution = s.resolution,
                    powerMa = s.power,
                    minDelayUs = s.minDelay,
                    values = copy,
                    accuracy = ev.accuracy,
                    timestampNs = ev.timestamp,
                    updatedWallMs = System.currentTimeMillis()
                )
                if (s.type == Sensor.TYPE_ACCELEROMETER && copy.size >= 3) {
                    val mag = sqrt(
                        copy[0].toDouble().pow(2) +
                            copy[1].toDouble().pow(2) +
                            copy[2].toDouble().pow(2)
                    )
                    synchronized(accelMagnitudes) {
                        accelMagnitudes.add(mag)
                    }
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
        }

        // Register across all non-one-shot sensors
        var registeredCount = 0
        for (s in allSensors) {
            if (s.reportingMode == Sensor.REPORTING_MODE_ONE_SHOT) continue
            try {
                val ok = sm.registerListener(listener, s, SensorManager.SENSOR_DELAY_GAME, handler)
                if (ok) registeredCount++
            } catch (_: Throwable) {
            }
        }

        try {
            latch.await(durationMs.toLong(), TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
        } finally {
            try {
                sm.unregisterListener(listener)
            } catch (_: Throwable) {
            }
            ht.quitSafely()
        }

        // Push latest snapshot to dashboard state so Web UI also updates immediately
        pushSnapshotToServer(context, buildDashboardJson(allSensors))

        return formatSensorReport(allSensors, category.trim().lowercase(Locale.US), registeredCount, accelMagnitudes)
    }

    /**
     * Start, monitor, check status, or stop an on-demand real-time sensor stream.
     */
    fun sensorStream(
        context: Context,
        action: String = "monitor",
        mode: String = "jumps",
        durationSec: Int = 10,
        rateHz: Int = 100
    ): String {
        val act = action.trim().lowercase(Locale.US)
        val normMode = mode.trim().lowercase(Locale.US).ifEmpty { "all" }
        val isIndefinite = durationSec <= 0
        val durS = if (isIndefinite) 0 else durationSec.coerceIn(1, 3600)
        val hz = rateHz.coerceIn(10, 480)

        when (act) {
            "stop" -> {
                stopStreamInternal(context)
                return formatStreamSummary("stopped", durS)
            }
            "status" -> {
                return formatStreamSummary(if (streamingActive) "active" else "idle", durS)
            }
            "start" -> {
                startStreamInternal(context.applicationContext, normMode, durS, hz)
                val durationLabel = if (isIndefinite) "indefinite until stopped" else "${durS}s"
                return "Started real-time phone sensor stream (id=$streamId, mode=$normMode, rate=${hz} Hz, duration=$durationLabel). " +
                    "Live telemetry is streaming to the Ray Web UI and phone-sensors/stream_$streamId.jsonl."
            }
            else -> {
                // "monitor": starts stream, collects for durationSec, and returns the full analysis
                val monitorDur = if (isIndefinite) 10 else durS
                startStreamInternal(context.applicationContext, normMode, monitorDur, hz)
                val waitMs = monitorDur * 1000L
                val deadline = SystemClock.elapsedRealtime() + waitMs
                while (streamingActive && SystemClock.elapsedRealtime() < deadline) {
                    try {
                        Thread.sleep(100)
                    } catch (_: InterruptedException) {
                        break
                    }
                }
                stopStreamInternal(context.applicationContext)
                return formatStreamSummary("completed", monitorDur)
            }
        }
    }

    @Synchronized
    private fun startStreamInternal(appCtx: Context, mode: String, durationSec: Int, rateHz: Int) {
        stopStreamInternal(appCtx)
        val sm = appCtx.getSystemService(Context.SENSOR_SERVICE) as? SensorManager ?: return
        val allSensors = sm.getSensorList(Sensor.TYPE_ALL)

        streamId = "${System.currentTimeMillis()}"
        streamMode = mode
        streamStartWallMs = System.currentTimeMillis()
        streamEndWallMs = if (durationSec <= 0) Long.MAX_VALUE else (streamStartWallMs + durationSec * 1000L)
        streamSampleCount = 0L
        detectedJumps.clear()
        inFreeFall = false
        freeFallStartNs = 0L
        currentPreJumpPeakG = 1.0
        pendingLandingJumpIdx = -1
        maxStreamG = 1.0
        minStreamG = 1.0
        synchronized(waveformHistory) { waveformHistory.clear() }

        val ht = HandlerThread("RaySensorStream").apply { start() }
        val handler = Handler(ht.looper)
        streamThread = ht
        streamHandler = handler
        streamingActive = true

        val samplingPeriodUs = (1_000_000 / rateHz.coerceIn(10, 480)).coerceAtLeast(2_083)
        var lastPushWallMs = 0L

        val listener = object : SensorEventListener {
            override fun onSensorChanged(event: SensorEvent?) {
                if (!streamingActive) return
                val ev = event ?: return
                val s = ev.sensor ?: return
                val copy = ev.values.clone()
                val nowMs = System.currentTimeMillis()
                latestReadings[sensorKey(s)] = SensorReading(
                    handle = s.id,
                    name = s.name,
                    vendor = s.vendor ?: "",
                    type = s.type,
                    stringType = s.stringType ?: "sensor.${s.type}",
                    reportingMode = s.reportingMode,
                    isWakeUp = s.isWakeUpSensor,
                    maxRange = s.maximumRange,
                    resolution = s.resolution,
                    powerMa = s.power,
                    minDelayUs = s.minDelay,
                    values = copy,
                    accuracy = ev.accuracy,
                    timestampNs = ev.timestamp,
                    updatedWallMs = nowMs
                )

                if (s.type == Sensor.TYPE_ACCELEROMETER && copy.size >= 3) {
                    streamSampleCount++
                    processAccelerometerSample(copy[0].toDouble(), copy[1].toDouble(), copy[2].toDouble(), ev.timestamp, nowMs)
                }

                if (streamEndWallMs != Long.MAX_VALUE && nowMs >= streamEndWallMs) {
                    stopStreamInternal(appCtx)
                    return
                }

                if (nowMs - lastPushWallMs >= 140L) {
                    lastPushWallMs = nowMs
                    val payload = buildDashboardJson(allSensors)
                    pushSnapshotToServer(appCtx, payload)
                }
            }

            override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
        }

        activeListener = listener

        // Register high-rate IMU + primary environmental/context sensors
        val priorityTypes = setOf(
            Sensor.TYPE_ACCELEROMETER,
            Sensor.TYPE_GYROSCOPE,
            Sensor.TYPE_GRAVITY,
            Sensor.TYPE_LINEAR_ACCELERATION,
            Sensor.TYPE_ROTATION_VECTOR,
            Sensor.TYPE_GAME_ROTATION_VECTOR,
            Sensor.TYPE_MAGNETIC_FIELD,
            Sensor.TYPE_ORIENTATION,
            Sensor.TYPE_PRESSURE,
            Sensor.TYPE_LIGHT,
            Sensor.TYPE_PROXIMITY,
            Sensor.TYPE_STEP_COUNTER,
            Sensor.TYPE_STEP_DETECTOR
        )

        for (s in allSensors) {
            if (s.reportingMode == Sensor.REPORTING_MODE_ONE_SHOT) continue
            val isPriority = s.type in priorityTypes || mode == "raw" || mode == "all"
            if (!isPriority && s.isWakeUpSensor) continue
            val delayUs = if (s.type == Sensor.TYPE_ACCELEROMETER || s.type == Sensor.TYPE_GYROSCOPE ||
                s.type == Sensor.TYPE_GRAVITY || s.type == Sensor.TYPE_LINEAR_ACCELERATION
            ) samplingPeriodUs else SensorManager.SENSOR_DELAY_UI
            try {
                sm.registerListener(listener, s, delayUs, handler)
            } catch (_: Throwable) {
            }
        }
    }

    @Synchronized
    fun stopStreamInternal(context: Context? = null) {
        val wasActive = streamingActive
        streamingActive = false
        val listener = activeListener
        activeListener = null
        if (listener != null && context != null) {
            try {
                val sm = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
                sm?.unregisterListener(listener)
            } catch (_: Throwable) {
            }
        }
        streamThread?.let {
            try {
                it.quitSafely()
            } catch (_: Throwable) {
            }
        }
        streamThread = null
        streamHandler = null
        if (wasActive && context != null) {
            try {
                val sm = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
                val allSensors = sm?.getSensorList(Sensor.TYPE_ALL).orEmpty()
                val finalJson = buildDashboardJson(allSensors)
                Thread { pushSnapshotToServer(context, finalJson) }.start()
            } catch (_: Throwable) {
            }
        }
    }

    private fun processAccelerometerSample(ax: Double, ay: Double, az: Double, timestampNs: Long, nowMs: Long) {
        val mag = sqrt(ax * ax + ay * ay + az * az)
        val g = mag / GRAVITY_EARTH
        if (g > maxStreamG) maxStreamG = g
        if (g < minStreamG) minStreamG = g

        // Update peak landing G if a jump just landed within the last 250 ms
        if (pendingLandingJumpIdx in 0 until detectedJumps.size) {
            if (timestampNs <= pendingLandingDeadlineNs) {
                val prev = detectedJumps[pendingLandingJumpIdx]
                if (g > prev.peakLandingG) {
                    detectedJumps[pendingLandingJumpIdx] = prev.copy(peakLandingG = g)
                }
            } else {
                pendingLandingJumpIdx = -1
            }
        }

        // Free-fall / flight detection: total acceleration drops below 0.32 g (~3.1 m/s^2) during airborne flight
        val freeFallThresholdG = 0.32
        if (!inFreeFall) {
            if (g > currentPreJumpPeakG) {
                currentPreJumpPeakG = g
            } else if (g > 0.85 && g < 1.15) {
                // Decay pre-jump peak slowly when standing still
                currentPreJumpPeakG = 1.0 + (currentPreJumpPeakG - 1.0) * 0.92
            }
            if (g < freeFallThresholdG) {
                inFreeFall = true
                freeFallStartNs = timestampNs
            }
        } else {
            if (g >= 0.65) {
                val airNs = timestampNs - freeFallStartNs
                val airMs = airNs / 1_000_000.0
                inFreeFall = false
                // Valid human jump flight time: 110 ms (1.5 cm hop) to 1100 ms (1.48 m leap)
                if (airMs in 110.0..1100.0 && currentPreJumpPeakG >= 1.25) {
                    val tSec = airMs / 1000.0
                    val heightMeters = 0.125 * GRAVITY_EARTH * tSec * tSec
                    val heightCm = heightMeters * 100.0
                    val idx = detectedJumps.size + 1
                    val ev = JumpEvent(
                        index = idx,
                        flightTimeMs = (airMs * 10.0).roundToInt() / 10.0,
                        heightCm = (heightCm * 10.0).roundToInt() / 10.0,
                        peakTakeoffG = (currentPreJumpPeakG * 100.0).roundToInt() / 100.0,
                        peakLandingG = (g * 100.0).roundToInt() / 100.0,
                        timestampMs = nowMs
                    )
                    detectedJumps.add(ev)
                    pendingLandingJumpIdx = detectedJumps.size - 1
                    pendingLandingDeadlineNs = timestampNs + 250_000_000L
                }
                currentPreJumpPeakG = 1.0
            }
        }

        // Record waveform frame (~25 Hz decimation for smooth Web UI chart)
        synchronized(waveformHistory) {
            val lastT = waveformHistory.lastOrNull()?.optLong("t", 0L) ?: 0L
            if (nowMs - lastT >= 35L) {
                if (waveformHistory.size >= 80) waveformHistory.removeFirst()
                waveformHistory.addLast(
                    JSONObject()
                        .put("t", nowMs)
                        .put("ax", (ax * 100.0).roundToInt() / 100.0)
                        .put("ay", (ay * 100.0).roundToInt() / 100.0)
                        .put("az", (az * 100.0).roundToInt() / 100.0)
                        .put("g", (g * 100.0).roundToInt() / 100.0)
                )
            }
        }
    }

    private fun findByType(type: Int): SensorReading? =
        latestReadings.values.filter { it.type == type }.maxByOrNull { it.updatedWallMs }

    private fun findByStringTypeContains(sub: String): SensorReading? =
        latestReadings.values.filter {
            it.stringType.lowercase(Locale.US).contains(sub) || it.name.lowercase(Locale.US).contains(sub)
        }.maxByOrNull { it.updatedWallMs }

    /**
     * Compute Spirit Level (pitch, roll, total tilt angle, status, high edge) from Gravity or Accelerometer.
     */
    fun computeSpiritLevel(): JSONObject {
        val grav = findByType(Sensor.TYPE_GRAVITY) ?: findByType(Sensor.TYPE_ACCELEROMETER)
        val out = JSONObject()
        if (grav == null || grav.values.size < 3) {
            return out.put("available", false)
        }
        val gx = grav.values[0].toDouble()
        val gy = grav.values[1].toDouble()
        val gz = grav.values[2].toDouble()
        val norm = sqrt(gx * gx + gy * gy + gz * gz).coerceAtLeast(1e-6)

        // Roll (left/right tilt) & Pitch (front/back tilt) in degrees
        val rollDeg = atan2(gx, abs(gz).coerceAtLeast(1e-4)) * (180.0 / PI)
        val pitchDeg = atan2(gy, abs(gz).coerceAtLeast(1e-4)) * (180.0 / PI)
        val totalTiltDeg = acos((abs(gz) / norm).coerceIn(0.0, 1.0)) * (180.0 / PI)

        val status = when {
            totalTiltDeg <= 0.5 -> "LEVEL"
            totalTiltDeg <= 2.0 -> "NEARLY_LEVEL"
            else -> "TILTED"
        }

        val highEdges = mutableListOf<String>()
        if (abs(pitchDeg) > 0.25) {
            highEdges.add(if (pitchDeg > 0) "top edge higher by %.2f°".format(Locale.US, abs(pitchDeg))
            else "bottom edge higher by %.2f°".format(Locale.US, abs(pitchDeg)))
        }
        if (abs(rollDeg) > 0.25) {
            highEdges.add(if (rollDeg > 0) "left edge higher by %.2f°".format(Locale.US, abs(rollDeg))
            else "right edge higher by %.2f°".format(Locale.US, abs(rollDeg)))
        }
        val guidance = if (highEdges.isEmpty()) "Perfectly level (within 0.25°)" else highEdges.joinToString(", ")

        return out
            .put("available", true)
            .put("pitch_deg", (pitchDeg * 100.0).roundToInt() / 100.0)
            .put("roll_deg", (rollDeg * 100.0).roundToInt() / 100.0)
            .put("total_tilt_deg", (totalTiltDeg * 100.0).roundToInt() / 100.0)
            .put("is_level", totalTiltDeg <= 0.5)
            .put("status", status)
            .put("guidance", guidance)
            .put("face", if (gz >= 0) "screen_up" else "screen_down")
    }

    private fun computeCompass(): JSONObject {
        val out = JSONObject()
        val mag = findByType(Sensor.TYPE_MAGNETIC_FIELD)
        val grav = findByType(Sensor.TYPE_GRAVITY) ?: findByType(Sensor.TYPE_ACCELEROMETER)
        val orient = findByType(Sensor.TYPE_ORIENTATION)

        var headingDeg: Double? = null
        if (mag != null && grav != null && mag.values.size >= 3 && grav.values.size >= 3) {
            val r = FloatArray(9)
            val i = FloatArray(9)
            if (SensorManager.getRotationMatrix(r, i, grav.values, mag.values)) {
                val angles = FloatArray(3)
                SensorManager.getOrientation(r, angles)
                headingDeg = ((Math.toDegrees(angles[0].toDouble()) + 360.0) % 360.0)
            }
        }
        if (headingDeg == null && orient != null && orient.values.isNotEmpty()) {
            headingDeg = ((orient.values[0].toDouble() + 360.0) % 360.0)
        }

        if (mag != null && mag.values.size >= 3) {
            val bx = mag.values[0].toDouble()
            val by = mag.values[1].toDouble()
            val bz = mag.values[2].toDouble()
            val bTotal = sqrt(bx * bx + by * by + bz * bz)
            out.put("bx_ut", (bx * 10.0).roundToInt() / 10.0)
            out.put("by_ut", (by * 10.0).roundToInt() / 10.0)
            out.put("bz_ut", (bz * 10.0).roundToInt() / 10.0)
            out.put("field_strength_ut", (bTotal * 10.0).roundToInt() / 10.0)
        }

        if (headingDeg != null) {
            val dirs = arrayOf("N", "NE", "E", "SE", "S", "SW", "W", "NW")
            val cardinal = dirs[((headingDeg + 22.5) / 45.0).toInt() % 8]
            out.put("heading_deg", (headingDeg * 10.0).roundToInt() / 10.0)
            out.put("cardinal", cardinal)
        }
        return out
    }

    /**
     * Build complete JSON payload for the Ray Web UI visualization panel and `/v1/ray/phone/sensors/stream`.
     */
    fun getLiveDashboardJson(context: Context): String {
        val sm = context.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
        val allSensors = sm?.getSensorList(Sensor.TYPE_ALL).orEmpty()
        return buildDashboardJson(allSensors).toString()
    }

    private fun buildDashboardJson(allSensors: List<Sensor>): JSONObject {
        val nowMs = System.currentTimeMillis()
        val level = computeSpiritLevel()
        val compass = computeCompass()

        val accel = findByType(Sensor.TYPE_ACCELEROMETER)
        val gyro = findByType(Sensor.TYPE_GYROSCOPE)
        val linAccel = findByType(Sensor.TYPE_LINEAR_ACCELERATION)
        val pressure = findByType(Sensor.TYPE_PRESSURE)
        val light = findByType(Sensor.TYPE_LIGHT)
        val backLux = findByStringTypeContains("back_lux")
        val frontCct = findByStringTypeContains("front_cct")
        val backCct = findByStringTypeContains("back_cct")
        val flicker = findByStringTypeContains("flicker")
        val proximity = findByType(Sensor.TYPE_PROXIMITY)
        val steps = findByType(Sensor.TYPE_STEP_COUNTER)
        val tof = findByStringTypeContains("tof")

        val hpa = pressure?.values?.firstOrNull()?.toDouble()
        val altitudeM = if (hpa != null && hpa > 100.0) {
            44330.0 * (1.0 - (hpa / 1013.25).pow(1.0 / 5.255))
        } else null

        val imuObj = JSONObject()
        if (accel != null && accel.values.size >= 3) {
            val ax = accel.values[0].toDouble()
            val ay = accel.values[1].toDouble()
            val az = accel.values[2].toDouble()
            val mag = sqrt(ax * ax + ay * ay + az * az)
            imuObj.put("ax", (ax * 100.0).roundToInt() / 100.0)
            imuObj.put("ay", (ay * 100.0).roundToInt() / 100.0)
            imuObj.put("az", (az * 100.0).roundToInt() / 100.0)
            imuObj.put("g_force", ((mag / GRAVITY_EARTH) * 100.0).roundToInt() / 100.0)
        }
        if (gyro != null && gyro.values.size >= 3) {
            imuObj.put("gx_rads", (gyro.values[0].toDouble() * 100.0).roundToInt() / 100.0)
            imuObj.put("gy_rads", (gyro.values[1].toDouble() * 100.0).roundToInt() / 100.0)
            imuObj.put("gz_rads", (gyro.values[2].toDouble() * 100.0).roundToInt() / 100.0)
        }
        if (linAccel != null && linAccel.values.size >= 3) {
            imuObj.put("lax", (linAccel.values[0].toDouble() * 100.0).roundToInt() / 100.0)
            imuObj.put("lay", (linAccel.values[1].toDouble() * 100.0).roundToInt() / 100.0)
            imuObj.put("laz", (linAccel.values[2].toDouble() * 100.0).roundToInt() / 100.0)
        }

        val envObj = JSONObject().apply {
            if (hpa != null) put("pressure_hpa", (hpa * 100.0).roundToInt() / 100.0)
            if (altitudeM != null) put("altitude_m", (altitudeM * 10.0).roundToInt() / 10.0)
            light?.values?.firstOrNull()?.let { put("front_lux", (it.toDouble() * 10.0).roundToInt() / 10.0) }
            backLux?.values?.firstOrNull()?.let { put("back_lux", (it.toDouble() * 10.0).roundToInt() / 10.0) }
            frontCct?.values?.firstOrNull()?.let { put("front_cct_k", it.roundToInt()) }
            backCct?.values?.firstOrNull()?.let { put("back_cct_k", it.roundToInt()) }
            flicker?.values?.firstOrNull()?.let { put("flicker_hz", (it.toDouble() * 10.0).roundToInt() / 10.0) }
            proximity?.values?.firstOrNull()?.let { put("proximity_cm", it.toDouble()) }
            steps?.values?.firstOrNull()?.let { put("steps", it.toLong()) }
            tof?.values?.firstOrNull()?.let { put("tof_mm", it.toDouble()) }
        }

        val jumpsArr = JSONArray()
        for (j in detectedJumps) {
            jumpsArr.put(
                JSONObject()
                    .put("index", j.index)
                    .put("flight_ms", j.flightTimeMs)
                    .put("height_cm", j.heightCm)
                    .put("takeoff_g", j.peakTakeoffG)
                    .put("landing_g", j.peakLandingG)
                    .put("timestamp_ms", j.timestampMs)
            )
        }

        val waveArr = JSONArray()
        synchronized(waveformHistory) {
            for (pt in waveformHistory) waveArr.put(pt)
        }

        val sensorsArr = JSONArray()
        for (s in allSensors) {
            val r = latestReadings[sensorKey(s)]
            val valsArr = JSONArray()
            if (r != null) {
                for (v in r.values.take(6)) {
                    valsArr.put((v.toDouble() * 1000.0).roundToInt() / 1000.0)
                }
            }
            sensorsArr.put(
                JSONObject()
                    .put("name", s.name)
                    .put("vendor", s.vendor ?: "")
                    .put("type", s.type)
                    .put("string_type", s.stringType ?: "sensor.${s.type}")
                    .put("wakeup", s.isWakeUpSensor)
                    .put("mode", s.reportingMode)
                    .put("active", r != null)
                    .put("values", valsArr)
            )
        }

        val isIndef = streamEndWallMs == Long.MAX_VALUE
        val remSec = if (isIndef) -1 else ((streamEndWallMs - nowMs) / 1000L).coerceAtLeast(0L).toInt()

        return JSONObject()
            .put("updated_ms", nowMs)
            .put("streaming", streamingActive)
            .put("is_indefinite", isIndef)
            .put("remaining_sec", remSec)
            .put("stream_id", streamId)
            .put("mode", streamMode)
            .put("samples", streamSampleCount)
            .put("max_g", (maxStreamG * 100.0).roundToInt() / 100.0)
            .put("min_g", (minStreamG * 100.0).roundToInt() / 100.0)
            .put("total_sensor_count", allSensors.size)
            .put("active_sensor_count", latestReadings.size)
            .put("level", level)
            .put("compass", compass)
            .put("imu", imuObj)
            .put("environment", envObj)
            .put("jumps", jumpsArr)
            .put("waveform", waveArr)
            .put("sensors", sensorsArr)
    }

    private fun pushSnapshotToServer(context: Context, payload: JSONObject) {
        val network = NetworkClient.shared
        val bytes = payload.toString().toByteArray(Charsets.UTF_8)
        try {
            // 1. Try dedicated /v1/ray/phone/sensors/stream endpoint first
            val req = network.newAuthenticatedRequestBuilder("/v1/ray/phone/sensors/stream")
                .post(bytes.toRequestBody(JSON_MEDIA))
                .build()
            network.okHttpClient.newCall(req).execute().use { r ->
                if (r.isSuccessful) return
            }
        } catch (_: Throwable) {
        }
        try {
            // 2. Zero-downtime fallback via /v1/ray/phone/upload (works without restarting strata-server)
            val rel = "phone-photos/_ray_sensor_stream.json"
            val req = network.newAuthenticatedRequestBuilder(
                "/v1/ray/phone/upload?file=" + URLEncoder.encode(rel, "UTF-8")
            )
                .header("X-Filename", rel)
                .post(bytes.toRequestBody(OCTET_MEDIA))
                .build()
            network.okHttpClient.newCall(req).execute().close()
        } catch (e: Throwable) {
            Log.d(TAG, "Sensor stream push skipped: ${e.message}")
        }
    }

    private fun formatSensorReport(
        allSensors: List<Sensor>,
        category: String,
        registeredCount: Int,
        accelMagnitudes: List<Double>
    ): String {
        val sb = StringBuilder()
        val level = computeSpiritLevel()
        val compass = computeCompass()

        sb.append("=== Xiaomi 17 Ultra Sensor Snapshot (${latestReadings.size} active / ${allSensors.size} total sensors, $registeredCount sampled) ===\n\n")

        // 1. Spirit Level / Surface Evenness
        if (level.optBoolean("available")) {
            val pitch = level.optDouble("pitch_deg")
            val roll = level.optDouble("roll_deg")
            val tilt = level.optDouble("total_tilt_deg")
            val status = level.optString("status")
            val guidance = level.optString("guidance")
            val face = level.optString("face")
            val rms = if (accelMagnitudes.size >= 2) {
                val mean = accelMagnitudes.average()
                sqrt(accelMagnitudes.map { (it - mean).pow(2) }.average())
            } else 0.0
            sb.append("[Spirit Level & Surface Evenness]\n")
            sb.append("  Status: $status (Total Tilt: %.2f° | Pitch: %+.2f° | Roll: %+.2f° | Face: $face)\n".format(Locale.US, tilt, pitch, roll))
            sb.append("  Surface Guidance: $guidance\n")
            sb.append("  Vibration / Stability RMS: %.4f m/s² (%s)\n\n".format(
                Locale.US, rms, if (rms < 0.05) "stationary on surface" else "moving / hand-held"
            ))
        }

        // 2. 6-Axis IMU
        val accel = findByType(Sensor.TYPE_ACCELEROMETER)
        val gyro = findByType(Sensor.TYPE_GYROSCOPE)
        val lin = findByType(Sensor.TYPE_LINEAR_ACCELERATION)
        sb.append("[6-Axis IMU (STMicro lsm6dsv @ 480 Hz)]\n")
        if (accel != null && accel.values.size >= 3) {
            val ax = accel.values[0]
            val ay = accel.values[1]
            val az = accel.values[2]
            val mag = sqrt(ax * ax + ay * ay + az * az)
            sb.append("  Accelerometer: x=%+.3f, y=%+.3f, z=%+.3f m/s² (|a|=%.3f m/s², %.2f g)\n".format(
                Locale.US, ax, ay, az, mag, mag / GRAVITY_EARTH
            ))
        }
        if (lin != null && lin.values.size >= 3) {
            sb.append("  Linear Accel (gravity removed): x=%+.3f, y=%+.3f, z=%+.3f m/s²\n".format(
                Locale.US, lin.values[0], lin.values[1], lin.values[2]
            ))
        }
        if (gyro != null && gyro.values.size >= 3) {
            sb.append("  Gyroscope: x=%+.4f, y=%+.4f, z=%+.4f rad/s\n".format(
                Locale.US, gyro.values[0], gyro.values[1], gyro.values[2]
            ))
        }
        sb.append("\n")

        // 3. Compass & Barometer & Optical
        sb.append("[Compass, Barometer & Environment]\n")
        if (compass.has("heading_deg")) {
            sb.append("  Compass Heading: %.1f° (%s) | Magnetic Field: %.1f µT (x=%+.1f, y=%+.1f, z=%+.1f µT)\n".format(
                Locale.US,
                compass.optDouble("heading_deg"),
                compass.optString("cardinal"),
                compass.optDouble("field_strength_ut"),
                compass.optDouble("bx_ut"),
                compass.optDouble("by_ut"),
                compass.optDouble("bz_ut")
            ))
        }
        findByType(Sensor.TYPE_PRESSURE)?.values?.firstOrNull()?.let { hpa ->
            val alt = 44330.0 * (1.0 - (hpa.toDouble() / 1013.25).pow(1.0 / 5.255))
            sb.append("  Barometer (Bosch bmp5): %.2f hPa (Estimated Standard Altitude: %.1f m)\n".format(Locale.US, hpa, alt))
        }
        val frontLux = findByType(Sensor.TYPE_LIGHT)?.values?.firstOrNull()
        val backLux = findByStringTypeContains("back_lux")?.values?.firstOrNull()
        val frontCct = findByStringTypeContains("front_cct")?.values?.firstOrNull()
        val backCct = findByStringTypeContains("back_cct")?.values?.firstOrNull()
        val flicker = findByStringTypeContains("flicker")?.values?.firstOrNull()
        val prox = findByType(Sensor.TYPE_PROXIMITY)?.values?.firstOrNull()
        val steps = findByType(Sensor.TYPE_STEP_COUNTER)?.values?.firstOrNull()
        val tof = findByStringTypeContains("tof")?.values

        sb.append("  Ambient Light: Front=${frontLux ?: "n/a"} lux, Back=${backLux ?: "n/a"} lux | Color Temp: Front=${frontCct ?: "n/a"} K, Back=${backCct ?: "n/a"} K | Flicker=${flicker ?: "n/a"} Hz\n")
        sb.append("  Proximity: ${prox ?: "n/a"} cm | Step Counter: ${steps?.toLong() ?: "n/a"} steps")
        if (tof != null && tof.isNotEmpty()) {
            sb.append(" | Laser ToF (STMicro L8): ${tof.take(4).joinToString(", ")}")
        }
        sb.append("\n\n")

        // 4. Full Sensor Inventory (all 107 sensors or filtered)
        val filtered = allSensors.filter { s ->
            when (category) {
                "", "all", "summary" -> true
                "level", "imu", "motion" -> s.type in setOf(
                    Sensor.TYPE_ACCELEROMETER, Sensor.TYPE_GYROSCOPE, Sensor.TYPE_GRAVITY,
                    Sensor.TYPE_LINEAR_ACCELERATION, Sensor.TYPE_ROTATION_VECTOR,
                    Sensor.TYPE_GAME_ROTATION_VECTOR, Sensor.TYPE_ACCELEROMETER_UNCALIBRATED,
                    Sensor.TYPE_GYROSCOPE_UNCALIBRATED
                )
                "environment", "light", "barometer", "compass" -> s.type in setOf(
                    Sensor.TYPE_MAGNETIC_FIELD, Sensor.TYPE_PRESSURE, Sensor.TYPE_LIGHT,
                    Sensor.TYPE_PROXIMITY, Sensor.TYPE_ORIENTATION, Sensor.TYPE_GEOMAGNETIC_ROTATION_VECTOR
                ) || (s.stringType ?: "").contains("lux") || (s.stringType ?: "").contains("cct") ||
                    (s.stringType ?: "").contains("flicker") || (s.stringType ?: "").contains("tof")
                "xiaomi", "context" -> (s.stringType ?: "").startsWith("xiaomi.") || s.vendor.lowercase(Locale.US).contains("xiaomi")
                else -> s.name.lowercase(Locale.US).contains(category) ||
                    (s.stringType ?: "").lowercase(Locale.US).contains(category) ||
                    s.vendor.lowercase(Locale.US).contains(category)
            }
        }

        sb.append("[All Matching Sensors (${filtered.size} / ${allSensors.size})]\n")
        for ((idx, s) in filtered.withIndex()) {
            val r = latestReadings[sensorKey(s)]
            val valsStr = if (r != null && r.values.isNotEmpty()) {
                r.values.take(6).joinToString(", ") { "%.3f".format(Locale.US, it) }
            } else {
                "awaiting trigger / event"
            }
            val wakeTag = if (s.isWakeUpSensor) "wakeup" else "non-wakeup"
            sb.append("  %3d. %-42s | %-28s | %-10s | values=[%s]\n".format(
                Locale.US, idx + 1, s.name.take(42), (s.stringType ?: "type=${s.type}").take(28), wakeTag, valsStr
            ))
        }
        return sb.toString().trimEnd()
    }

    private fun formatStreamSummary(state: String, durationSec: Int): String {
        val sb = StringBuilder()
        val level = computeSpiritLevel()
        sb.append("=== Real-Time Sensor Stream ($state, mode=$streamMode, id=${streamId.ifEmpty { "none" }}) ===\n")
        sb.append("Samples processed: $streamSampleCount (duration: ${durationSec}s)\n")
        sb.append("G-Force Range: min=%.2f g, max=%.2f g\n".format(Locale.US, minStreamG, maxStreamG))

        if (level.optBoolean("available")) {
            sb.append("Current Spirit Level: ${level.optString("status")} (Tilt=%.2f°, Pitch=%+.2f°, Roll=%+.2f° — ${level.optString("guidance")})\n".format(
                Locale.US,
                level.optDouble("total_tilt_deg"),
                level.optDouble("pitch_deg"),
                level.optDouble("roll_deg")
            ))
        }

        if (detectedJumps.isEmpty()) {
            sb.append("Jumps Detected: 0\n")
        } else {
            val bestHeight = detectedJumps.maxByOrNull { it.heightCm }
            val avgHeight = detectedJumps.map { it.heightCm }.average()
            sb.append("Jumps Detected: ${detectedJumps.size} (Max Height: %.1f cm, Avg Height: %.1f cm)\n".format(
                Locale.US, bestHeight?.heightCm ?: 0.0, avgHeight
            ))
            for (j in detectedJumps) {
                sb.append("  - Jump #${j.index}: Height=%.1f cm | Air Time=%.1f ms | Takeoff=%.2f g | Landing=%.2f g\n".format(
                    Locale.US, j.heightCm, j.flightTimeMs, j.peakTakeoffG, j.peakLandingG
                ))
            }
        }
        return sb.toString().trimEnd()
    }
}
