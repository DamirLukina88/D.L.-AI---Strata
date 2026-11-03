package com.damirl.ray.tools

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.os.Environment
import android.util.Log
import com.damirl.ray.network.NetworkClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// Ray's camera.  phone_camera_snap takes a photo himself (AutoCamera: back camera, shutter sound, no camera app) and
// sends it (upright, at most 1600 px) to the server's workspace, answering with an [[image: …]] marker that D.L. CLI
// turns into an image the model sees.  phone_get_last_photo sends the newest photo Ray took again
class CameraVisionManager(private val context: Context) {

    companion object {
        private const val TAG = "CameraVision"
        private const val MAX_SIDE = 1600
    }

    /** Ray takes the photo himself (AutoCamera) and it goes straight to the workspace: one tool call, one image. */
    fun snapPhoto(prompt: String): String {
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES)
            ?: return "Error: the phone's picture folder is not available."
        val name = "RAY_SNAP_" + SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date()) + "_auto.jpg"
        val file = File(dir, name)
        AutoCamera.capture(context, file)?.let { return it }
        return upload(file)
    }

    /** The photo taken after the last phone_camera_snap, sent to the server's workspace; blocking (not on the main thread). */
    fun uploadLastPhoto(networkClient: NetworkClient = NetworkClient.shared): String {
        // from the folder, not from memory: while the camera is in front, HyperOS may close Ray's app and its memory
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES)
            ?: return "Error: the phone's picture folder is not available."
        val snaps = dir.listFiles { f -> f.name.startsWith("RAY_SNAP_") && f.name.endsWith(".jpg") }.orEmpty()
            .sortedByDescending { it.lastModified() }
        // empty leftovers (the old camera-app flow left 0-byte files) go
        snaps.filter { it.length() == 0L }.forEach { it.delete() }
        val file = snaps.firstOrNull { it.length() > 0 }
        // nothing from the last 2 minutes: the model asked to "fetch" a photo that was never taken (an older
        // conversation taught it a fetch step), so take one now; whichever photo tool it picks, it gets a photo
        if (file == null || System.currentTimeMillis() - file.lastModified() > 2 * 60_000) {
            Log.d(TAG, "No recent photo: taking one")
            return snapPhoto("")
        }
        return upload(file, networkClient)
    }

    // upright, at most MAX_SIDE px, into the server's workspace (phone-photos/); the answer carries the image marker
    private fun upload(file: File, networkClient: NetworkClient = NetworkClient.shared): String {
        val jpeg = try {
            prepare(file)
        } catch (e: Exception) {
            Log.e(TAG, "Could not read the photo", e)
            return "Error: the photo could not be read: ${e.message}"
        }
        val rel = "phone-photos/${file.nameWithoutExtension.substringBeforeLast('_')}.jpg"
        return try {
            val request = networkClient.newAuthenticatedRequestBuilder(
                "/api/workspace/upload?file=" + URLEncoder.encode(rel, "UTF-8")
            )
                .header("X-Filename", rel)
                .post(jpeg.toRequestBody("application/octet-stream".toMediaType()))
                .build()
            networkClient.okHttpClient.newCall(request).execute().use { r ->
                if (!r.isSuccessful) return "Error: the photo could not be sent to the server (HTTP ${r.code})."
            }
            Log.d(TAG, "Photo sent to the workspace: $rel (${jpeg.size / 1024} KB)")
            "The photo is in the workspace as $rel. [[image: $rel]]"
        } catch (e: Exception) {
            Log.e(TAG, "Upload failed", e)
            "Error: the photo could not be sent to the server: ${e.message}"
        }
    }

    // upright (cameras store the rotation as an EXIF tag) and at most MAX_SIDE px, as JPEG
    private fun prepare(file: File): ByteArray {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2
        val decoded = BitmapFactory.decodeFile(file.absolutePath, BitmapFactory.Options().apply { inSampleSize = sample })
            ?: throw IllegalStateException("not an image")
        val degrees = when (ExifInterface(file.absolutePath)
            .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
        val scale = minOf(1f, MAX_SIDE.toFloat() / maxOf(decoded.width, decoded.height))
        val matrix = Matrix().apply { postScale(scale, scale); postRotate(degrees) }
        val out = Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
        return ByteArrayOutputStream().use { bytes ->
            out.compress(Bitmap.CompressFormat.JPEG, 85, bytes)
            bytes.toByteArray()
        }
    }
}
