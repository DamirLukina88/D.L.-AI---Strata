package com.damirl.ray.assistant

import android.content.ComponentName
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import android.util.Log
import android.view.KeyEvent
import com.damirl.ray.audio.MediaButtonHandler

class RayVoiceInteractionService : VoiceInteractionService() {

    companion object {
        private const val TAG = "RayAssistService"
        var instance: RayVoiceInteractionService? = null
            private set

        /**
         * Invokes the system voice interaction session overlay.
         * Returns true if successfully requested, false if service is inactive.
         */
        fun showSession(
            args: Bundle = Bundle(),
            flags: Int = VoiceInteractionSession.SHOW_SOURCE_ASSIST_GESTURE or VoiceInteractionSession.SHOW_WITH_ASSIST
        ): Boolean {
            val service = instance
            if (service != null && isActiveService(service, ComponentName(service, RayVoiceInteractionService::class.java))) {
                Log.d(TAG, "Requesting showSession on active VoiceInteractionService with flags=$flags, args=$args")
                service.showSession(args, flags)
                return true
            }
            Log.d(TAG, "VoiceInteractionService not ready or not active assistant (instance=${service != null})")
            return false
        }
    }

    private var mediaSession: MediaSessionCompat? = null

    override fun onReady() {
        super.onReady()
        instance = this
        Log.d(TAG, "RayVoiceInteractionService onReady: Registered as system assistant")
        setupMediaSession()
    }

    private fun setupMediaSession() {
        try {
            val mediaButtonIntent = Intent(Intent.ACTION_MEDIA_BUTTON).apply {
                setClass(this@RayVoiceInteractionService, com.damirl.ray.audio.MediaButtonReceiver::class.java)
            }
            val mediaButtonPendingIntent = android.app.PendingIntent.getBroadcast(
                this,
                0,
                mediaButtonIntent,
                android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE
            )

            mediaSession = MediaSessionCompat(this, "RayVoiceAssistantMediaSession").apply {
                setFlags(
                    MediaSessionCompat.FLAG_HANDLES_MEDIA_BUTTONS or
                    MediaSessionCompat.FLAG_HANDLES_TRANSPORT_CONTROLS
                )
                setMediaButtonReceiver(mediaButtonPendingIntent)
                setCallback(object : MediaSessionCompat.Callback() {
                    override fun onMediaButtonEvent(mediaButtonEvent: Intent): Boolean {
                        val keyEvent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            mediaButtonEvent.getParcelableExtra(Intent.EXTRA_KEY_EVENT, KeyEvent::class.java)
                        } else {
                            @Suppress("DEPRECATION")
                            mediaButtonEvent.getParcelableExtra(Intent.EXTRA_KEY_EVENT)
                        } ?: return super.onMediaButtonEvent(mediaButtonEvent)

                        return MediaButtonHandler.handleKeyEvent(this@RayVoiceInteractionService, keyEvent)
                    }
                })
                val state = PlaybackStateCompat.Builder()
                    .setActions(
                        PlaybackStateCompat.ACTION_PLAY or
                        PlaybackStateCompat.ACTION_PAUSE or
                        PlaybackStateCompat.ACTION_PLAY_PAUSE or
                        PlaybackStateCompat.ACTION_STOP
                    )
                    .setState(PlaybackStateCompat.STATE_PAUSED, PlaybackStateCompat.PLAYBACK_POSITION_UNKNOWN, 0.0f)
                    .build()
                setPlaybackState(state)
                isActive = true
            }
            Log.d(TAG, "RayVoiceInteractionService media session active for earbud triggers")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to initialize MediaSessionCompat in RayVoiceInteractionService", e)
        }
    }

    // Android 14+: every request to show the drawer, and the ones Android gives up on, so a press that opens nothing
    // shows in the log where it stopped (2026-11-02: about 1 in 4 got showSessionForActiveService() and no onShow)
    override fun onPrepareToShowSession(args: Bundle, showFlags: Int) {
        super.onPrepareToShowSession(args, showFlags)
        Log.d(TAG, "onPrepareToShowSession, showFlags=$showFlags")
    }

    override fun onShowSessionFailed(args: Bundle) {
        super.onShowSessionFailed(args)
        Log.w(TAG, "onShowSessionFailed: $args")
    }

    override fun onShutdown() {
        super.onShutdown()
        mediaSession?.isActive = false
        mediaSession?.release()
        mediaSession = null
        if (instance == this) {
            instance = null
        }
        Log.d(TAG, "RayVoiceInteractionService onShutdown")
    }
}
