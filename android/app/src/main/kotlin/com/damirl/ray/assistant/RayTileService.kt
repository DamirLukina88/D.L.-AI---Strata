package com.damirl.ray.assistant

import android.app.PendingIntent
import android.content.Intent
import android.graphics.drawable.Icon
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.util.Log
import com.damirl.ray.R
import com.damirl.ray.audio.AudioPlaybackService

class RayTileService : TileService() {

    companion object {
        private const val TAG = "RayTileService"
    }

    override fun onStartListening() {
        super.onStartListening()
        updateTileState()
    }

    private fun updateTileState() {
        val tile = qsTile ?: return
        val isSpeaking = AudioPlaybackService.isSpeakingState.value

        tile.state = if (isSpeaking) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        tile.label = getString(R.string.tile_name)
        tile.icon = Icon.createWithResource(this, R.drawable.ic_tile_paw)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            tile.subtitle = if (isSpeaking) {
                getString(R.string.tile_subtitle_speaking)
            } else {
                getString(R.string.tile_subtitle_ready)
            }
        }

        tile.updateTile()
    }

    override fun onClick() {
        super.onClick()
        Log.d(TAG, "Quick Settings tile clicked")

        // If currently speaking, tapping tile stops speech
        if (AudioPlaybackService.isSpeakingState.value) {
            AudioPlaybackService.stopSpeaking(this)
            updateTileState()
            return
        }

        val launchAction = {
            val intent = Intent(this, RayAssistTrampolineActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pendingIntent = PendingIntent.getActivity(
                this,
                0,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startActivityAndCollapse(pendingIntent)
            } else {
                @Suppress("DEPRECATION")
                startActivityAndCollapse(intent)
            }
        }

        if (isLocked) {
            unlockAndRun {
                launchAction()
            }
        } else {
            launchAction()
        }
    }
}
