package com.damirl.ray.tools

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.util.Log
import androidx.core.content.FileProvider
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class CameraVisionManager(private val context: Context) {

    companion object {
        private const val TAG = "CameraVision"
        private var lastSnappedPhotoPath: String? = null

        fun getLastPhotoPath(): String? = lastSnappedPhotoPath
    }

    /**
     * Prepare a file and intent to capture a snapshot from camera.
     */
    fun createCaptureIntent(): Pair<Intent, Uri>? {
        return try {
            val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            val storageDir = context.getExternalFilesDir(Environment.DIRECTORY_PICTURES)
            val imageFile = File.createTempFile("RAY_SNAP_${timeStamp}_", ".jpg", storageDir)
            lastSnappedPhotoPath = imageFile.absolutePath

            val photoUri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                imageFile
            )

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

    /**
     * Snap a photo contextually.
     */
    fun snapPhoto(prompt: String): String {
        Log.d(TAG, "snapPhoto called with prompt: '$prompt'")
        val pair = createCaptureIntent()
        if (pair != null) {
            try {
                context.startActivity(pair.first)
                // the photo is saved on the phone but not sent back yet, so Ray must not claim to have seen it
                return "Opened the camera on the phone. The photo stays on the phone: Ray can't see it yet, so ask the user to describe it if needed."
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start camera activity", e)
            }
        }
        return "Error: the camera could not be opened."
    }

    /**
     * Encode last captured image as Base64 JPEG for Ray.
     */
    fun getLastPhotoBase64(): String? {
        val path = lastSnappedPhotoPath ?: return null
        val file = File(path)
        if (!file.exists()) return null

        return try {
            val bitmap = BitmapFactory.decodeFile(file.absolutePath) ?: return null
            val outputStream = ByteArrayOutputStream()
            // Compress to standard JPEG under 1024px for quick vision inference
            val scaled = if (bitmap.width > 1024 || bitmap.height > 1024) {
                val ratio = 1024f / Math.max(bitmap.width, bitmap.height)
                Bitmap.createScaledBitmap(bitmap, (bitmap.width * ratio).toInt(), (bitmap.height * ratio).toInt(), true)
            } else {
                bitmap
            }
            scaled.compress(Bitmap.CompressFormat.JPEG, 85, outputStream)
            Base64.encodeToString(outputStream.toByteArray(), Base64.NO_WRAP)
        } catch (e: Exception) {
            Log.e(TAG, "Error encoding photo to base64", e)
            null
        }
    }
}
