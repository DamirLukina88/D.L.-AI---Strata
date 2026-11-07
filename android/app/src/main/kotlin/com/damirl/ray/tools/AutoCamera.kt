package com.damirl.ray.tools

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaActionSound
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

// Ray takes a photo himself with the back camera (CameraX): no camera app, no confirm step.  Android allows it only
// while Ray is on screen (the app or the voice drawer), and it is never silent: the shutter sound plays and a short
// "Ray took a photo" notice shows.  PhoneTools refuses it while the phone is locked.  Blocking: call it off the main
// thread (the bridge's and the adb receiver's tool threads)
object AutoCamera {

    private const val TAG = "RayAutoCamera"
    private const val SETTLE_MS = 800L             // exposure and focus settle before the shot

    /** Takes one photo into [out]; null when it worked, else what went wrong, in words for Ray. */
    fun capture(context: Context, out: File, timeoutMs: Long = 8_000): String? {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            return "Error: Ray may not use the camera yet. In the app, About › Android settings › Camera: Allow."
        }
        val needHold = !com.damirl.ray.MainActivity.shown &&
            com.damirl.ray.assistant.VoiceDrawerController.closeOpen == null &&
            !RayMusicActivity.isActive()
        if (needHold) {
            RayUnlockActivity.startCameraHold(context)
        }
        val main = Handler(Looper.getMainLooper())
        val owner = OneShotLifecycle()
        val capture = ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
            .setJpegQuality(90)
            .build()
        val provider = try {
            ProcessCameraProvider.getInstance(context).get(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (e: Exception) {
            Log.e(TAG, "No camera provider", e)
            return "Error: the camera is not available (${e.message})."
        }
        val bound = CountDownLatch(1)
        var bindError: String? = null
        main.post {
            try {
                owner.start()
                provider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, capture)
            } catch (e: Exception) {
                Log.e(TAG, "Could not open the camera", e)
                bindError = "Error: the camera could not be opened (${e.message}). Ray can take photos only while " +
                    "he is on screen (the app or the voice drawer)."
            }
            bound.countDown()
        }
        bound.await(timeoutMs, TimeUnit.MILLISECONDS)
        bindError?.let { release(main, provider, owner); return it }

        Thread.sleep(SETTLE_MS)
        val done = CountDownLatch(1)
        var shotError: String? = null
        val executor = Executors.newSingleThreadExecutor()
        MediaActionSound().play(MediaActionSound.SHUTTER_CLICK)       // never silent
        capture.takePicture(ImageCapture.OutputFileOptions.Builder(out).build(), executor,
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(result: ImageCapture.OutputFileResults) = done.countDown()
                override fun onError(e: ImageCaptureException) {
                    Log.e(TAG, "Photo failed", e)
                    shotError = "Error: the photo failed (${e.message})."
                    done.countDown()
                }
            })
        if (!done.await(timeoutMs, TimeUnit.MILLISECONDS)) shotError = "Error: the camera took too long."
        executor.shutdown()
        release(main, provider, owner)
        if (shotError == null) {
            main.post { Toast.makeText(context, "Ray took a photo", Toast.LENGTH_SHORT).show() }
            Log.d(TAG, "Photo taken: ${out.name} (${out.length() / 1024} KB)")
        }
        return shotError
    }

    private fun release(main: Handler, provider: ProcessCameraProvider, owner: OneShotLifecycle) {
        main.post {
            try { provider.unbindAll() } catch (_: Exception) {}
            owner.stop()
        }
        RayUnlockActivity.finishCameraHold()
    }

    // a lifecycle that is resumed for the one photo (the camera is bound to it), then destroyed
    private class OneShotLifecycle : LifecycleOwner {
        private val registry = LifecycleRegistry(this)
        override val lifecycle: Lifecycle get() = registry
        fun start() { registry.currentState = Lifecycle.State.RESUMED }
        fun stop() { registry.currentState = Lifecycle.State.DESTROYED }
    }
}
