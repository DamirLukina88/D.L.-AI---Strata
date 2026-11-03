package com.damirl.ray.tools

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import androidx.core.content.ContextCompat
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
// turns into an image the model sees.  phone_get_last_photo sends the newest photo Ray took again;
// phone_get_gallery_image sends the newest photo or screenshot the user took (the phone's gallery, MediaStore)
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

    /** The newest image in the user's gallery: [kind] "photo" (the camera app), "screenshot" or "any"; blocking. */
    fun uploadGalleryImage(kind: String, networkClient: NetworkClient = NetworkClient.shared): String {
        val permission = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES
            else Manifest.permission.READ_EXTERNAL_STORAGE
        if (ContextCompat.checkSelfPermission(context, permission) != PackageManager.PERMISSION_GRANTED) {
            return "Error: Ray may not read the gallery yet. On the phone: long-press Ray's icon › Setup & permissions › " +
                "Photos: Allow."
        }
        val col = MediaStore.Images.Media.RELATIVE_PATH
        // Xiaomi and Pixel keep screenshots in DCIM/Screenshots or Pictures/Screenshots, camera photos in DCIM/Camera
        val (where, what) = when (kind) {
            "photo" -> "$col LIKE 'DCIM/Camera%'" to "photo"
            "screenshot" -> "$col LIKE '%Screenshots%'" to "screenshot"
            else -> null to "image"
        }
        val projection = arrayOf(
            MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME, MediaStore.Images.Media.DATE_ADDED
        )
        val found = try {
            context.contentResolver.query(
                MediaStore.Images.Media.EXTERNAL_CONTENT_URI, projection, where, null,
                "${MediaStore.Images.Media.DATE_ADDED} DESC"
            )?.use { c ->
                if (!c.moveToFirst()) null
                else Triple(c.getLong(0), c.getString(1) ?: "image", c.getLong(2))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Gallery query failed", e)
            return "Error: the gallery could not be read: ${e.message}"
        } ?: return "Error: there is no $what in the phone's gallery."
        val (id, name, added) = found
        val copy = File(context.cacheDir, "gallery_newest")
        try {
            val uri = ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id)
            context.contentResolver.openInputStream(uri)?.use { input ->
                copy.outputStream().use { input.copyTo(it) }
            } ?: return "Error: the $what could not be opened."
        } catch (e: Exception) {
            Log.e(TAG, "Could not copy the gallery image", e)
            return "Error: the $what could not be opened: ${e.message}"
        }
        val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date(added * 1000))
        val minutes = (System.currentTimeMillis() / 1000 - added).coerceAtLeast(0) / 60
        val age = when {
            minutes < 1 -> "just now"
            minutes < 120 -> "$minutes min ago"
            minutes < 48 * 60 -> "${minutes / 60} h ago"
            else -> "${minutes / (24 * 60)} days ago"
        }
        val prefix = if (kind == "screenshot") "GALLERY_SCREENSHOT" else "GALLERY"
        val answer = upload(copy, "phone-photos/${prefix}_$stamp.jpg", networkClient)
        copy.delete()
        return if (answer.startsWith("Error")) answer else "The newest $what in the gallery: $name, added $age. $answer"
    }

    private fun upload(file: File, networkClient: NetworkClient = NetworkClient.shared) =
        upload(file, "phone-photos/${file.nameWithoutExtension.substringBeforeLast('_')}.jpg", networkClient)

    // upright, at most MAX_SIDE px, into the server's workspace as [rel]; the answer carries the image marker
    private fun upload(file: File, rel: String, networkClient: NetworkClient): String {
        val jpeg = try {
            prepare(file)
        } catch (e: Exception) {
            Log.e(TAG, "Could not read the photo", e)
            return "Error: the photo could not be read: ${e.message}"
        }
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
