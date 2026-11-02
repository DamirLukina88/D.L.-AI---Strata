package com.damirl.ray.assistant

import android.os.Bundle
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService
import android.util.Log

class RayVoiceSessionService : VoiceInteractionSessionService() {

    companion object {
        private const val TAG = "RaySessionService"
    }

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "RayVoiceSessionService onCreate")
    }

    override fun onDestroy() {
        super.onDestroy()
        Log.d(TAG, "RayVoiceSessionService onDestroy")
    }

    override fun onNewSession(args: Bundle?): VoiceInteractionSession {
        Log.d(TAG, "Creating new RayVoiceSession")
        return RayVoiceSession(this)
    }
}
