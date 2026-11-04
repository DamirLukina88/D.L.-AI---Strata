package com.damirl.ray.audio

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** A 16-bit mono PCM WAV file. */
object Wav {
    fun write(file: File, pcm: ShortArray, samples: Int, rate: Int) {
        RandomAccessFile(file, "rw").use { f ->
            f.setLength(0)
            val dataBytes = samples * 2
            val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
                put("RIFF".toByteArray()); putInt(36 + dataBytes); put("WAVE".toByteArray())
                put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1); putInt(rate); putInt(rate * 2)
                putShort(2); putShort(16); put("data".toByteArray()); putInt(dataBytes)
            }
            f.write(header.array())
            val body = ByteBuffer.allocate(dataBytes).order(ByteOrder.LITTLE_ENDIAN)
            for (i in 0 until samples) body.putShort(pcm[i])
            f.write(body.array())
        }
    }
}
