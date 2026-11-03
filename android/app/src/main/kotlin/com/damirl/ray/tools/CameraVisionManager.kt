package com.damirl.ray.tools

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import androidx.core.content.FileProvider
import com.damirl.ray.network.NetworkClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// Ray's camera, in two steps.  phone_camera_snap opens the phone's camera with a file for the photo; once the user has
// taken it, phone_get_last_photo sends that photo (upright, at most 1600 px) to the server's workspace and answers with
// an [[image: …]] marker, which D.L. CLI turns into an image the model sees.  Two steps because a phone tool call has a
// few seconds, and taking a photo takes longer
class CameraVisionManager(private val context: Context) {

    companion object {
        private const val TAG = "CameraVision"
        private const val MAX_SIDE = 1600
        // kept across PhoneTools instances (the adb receiver makes a new one per call)
        @Volatile private var lastSnappedPhotoPath: String? = null
        @Volatile private var lastSnapAt = 0L
    }

    /** A file in the app's Pictures folder and the camera intent that writes into it. */
    fun createCaptureIntent(): Pair<Intent, Uri>? {
        return try {
            val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            val storageDir = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES)
            val imageFile = File.createTempFile("RAY_SNAP_${timeStamp}_", ".jpg", storageDir)
            lastSnappedPhotoPath = imageFile.absolutePath
            lastSnapAt = System.currentTimeMillis()

            val photoUri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", imageFile)
            val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT, photoUri)
                addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            Pair(intent, photoUri)
        } catch (e: Exception) {
            Log.e(TAG, "Error creating photo capture intent", e)
            null
        }
    }

    fun snapPhoto(prompt: String): String {
        val pair = createCaptureIntent() ?: return "Error: the camera could not be opened."
        return try {
            context.startActivity(pair.first)
            "Opened the camera on the phone. Ask the user to take the photo and tell you when it's done, then call " +
                "phone_get_last_photo to see it."
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start camera activity", e)
            "Error: the camera could not be opened."
        }
    }

    /** The photo taken after the last phone_camera_snap, sent to the server's workspace; blocking (not on the main thread). */
    fun uploadLastPhoto(networkClient: NetworkClient = NetworkClient.shared): String {
        val file = lastSnappedPhotoPath?.let { File(it) }
            ?: return "Error: no photo yet. Open the camera with phone_camera_snap first."
        // the camera writes the file when the user confirms the shot; until then it is empty
        if (!file.isFile || file.length() == 0L) {
            return "Error: the photo hasn't been taken yet (the camera may still be open). Ask the user to take it."
        }
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
