package com.damirl.ray.assistant

import android.content.Context
import android.util.Log
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// The last seconds of the mic, kept in memory only so that a wake can save what was heard (WakeClips).  Older sound is
// overwritten as new sound comes in
class ClipRing(size: Int) {
    private val samples = ShortArray(size)
    private var at = 0
    private var filled = 0

    fun add(source: ShortArray, count: Int) {
        var from = (count - samples.size).coerceAtLeast(0)
        while (from < count) {
            val n = minOf(count - from, samples.size - at)
            source.copyInto(samples, at, from, from + n)
            at = (at + n) % samples.size
            from += n
        }
        filled = minOf(filled + count, samples.size)
    }

    /** What is held now, oldest sample first. */
    fun snapshot(): ShortArray {
        val out = ShortArray(filled)
        val start = (at - filled + samples.size) % samples.size
        val tail = minOf(filled, samples.size - start)
        samples.copyInto(out, 0, start, start + tail)
        samples.copyInto(out, tail, 0, filled - tail)
        return out
    }
}

// Testing "Ok Ray": with WakeWord.savesClips on, each wake leaves a short WAV on the phone, so false wakes can be heard
// later and used for training.  Only wakes are saved, never the sound between them, and nothing leaves the phone.
// adb pull /sdcard/Android/data/com.damirl.ray/files/wake-clips
object WakeClips {

    private const val TAG = "RayWakeClips"
    private const val DIR = "wake-clips"
    private const val MAX_CLIPS = 300                              // about 35 MB; the oldest go first

    /** 16-bit mono WAV bytes for [samples]. */
    fun wav(samples: ShortArray, rate: Int): ByteArray {
        val data = samples.size * 2
        val out = ByteBuffer.allocate(44 + data).order(ByteOrder.LITTLE_ENDIAN)
        out.put("RIFF".toByteArray()).putInt(36 + data).put("WAVE".toByteArray())
        out.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1)
        out.putInt(rate).putInt(rate * 2).putShort(2).putShort(16)
        out.put("data".toByteArray()).putInt(data)
        samples.forEach { out.putShort(it) }
        return out.array()
    }

    fun save(context: Context, samples: ShortArray, rate: Int, text: String) {
        try {
            val dir = context.getExternalFilesDir(DIR) ?: return
            val time = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.ROOT).format(Date())
            val file = File(dir, "wake_${time}_${text.trim().replace(' ', '-')}.wav")
            file.writeBytes(wav(samples, rate))
            dir.listFiles().orEmpty().sortedByDescending { it.name }.drop(MAX_CLIPS).forEach { it.delete() }
            Log.d(TAG, "Saved ${file.name}")
        } catch (e: Exception) {
            Log.w(TAG, "Could not save the clip: ${e.message}")
        }
    }
}
