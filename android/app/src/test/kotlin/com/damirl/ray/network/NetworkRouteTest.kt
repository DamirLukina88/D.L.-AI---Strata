package com.damirl.ray.network

import com.damirl.ray.audio.PiperAudioPlayer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

class NetworkRouteTest {

    private val lan = "http://lan.example:8080"
    private val remote = "https://tunnel.example"

    @Test
    fun lanWinsThenTunnelThenOffline() {
        assertEquals(NetworkRoute.Lan(lan), NetworkClient.chooseRoute(true, true, lan, remote))
        assertEquals(NetworkRoute.Remote(remote), NetworkClient.chooseRoute(false, true, lan, remote))
        assertEquals(NetworkRoute.Offline, NetworkClient.chooseRoute(false, false, lan, remote))
    }

    @Test
    fun aRouteFoundLessThanAMinuteAgoIsReused() {
        assertTrue(NetworkClient.isFresh(NetworkRoute.Remote(remote), probedAt = 1_000, now = 30_000))
        assertFalse(NetworkClient.isFresh(NetworkRoute.Remote(remote), probedAt = 1_000, now = 61_001))
        assertFalse(NetworkClient.isFresh(NetworkRoute.Offline, probedAt = 1_000, now = 2_000))
        assertFalse(NetworkClient.isFresh(NetworkRoute.Lan(lan), probedAt = 0, now = 2_000))   // never probed
    }

    @Test
    fun onlyAServerNeverReachedCountsAsUnreached() {
        // how RayChatRepository wraps OkHttp's failure
        assertTrue(NetworkClient.isConnectFailure(IOException("x", ConnectException("refused"))))
        assertTrue(NetworkClient.isConnectFailure(IOException("x", UnknownHostException("no dns"))))
        assertTrue(NetworkClient.isConnectFailure(
            SocketTimeoutException("failed to connect to /192.168.1.100 (port 8080) after 15000ms")))
        // the server answered, then the stream broke or timed out: sending again could ask Ray twice
        assertFalse(NetworkClient.isConnectFailure(SocketTimeoutException("timeout")))
        assertFalse(NetworkClient.isConnectFailure(IOException("Stream failed with HTTP 502")))
        assertFalse(NetworkClient.isConnectFailure(null))
    }

    @Test
    fun labelsForTheTrace() {
        assertEquals("lan", NetworkClient.label(NetworkRoute.Lan(lan)))
        assertEquals("tunnel", NetworkClient.label(NetworkRoute.Remote(remote)))
        assertEquals("offline", NetworkClient.label(NetworkRoute.Offline))
    }

    @Test
    fun aServerWithoutOpusGetsAskedForWav() {
        assertEquals(PiperAudioPlayer.FORMAT_WAV, PiperAudioPlayer.fallbackFormat(PiperAudioPlayer.FORMAT_OPUS, 400))
    }

    @Test
    fun otherServerFailuresAreNotAFormatProblem() {
        assertNull(PiperAudioPlayer.fallbackFormat(PiperAudioPlayer.FORMAT_WAV, 400))     // WAV refused: nothing left
        assertNull(PiperAudioPlayer.fallbackFormat(PiperAudioPlayer.FORMAT_OPUS, 401))
        assertNull(PiperAudioPlayer.fallbackFormat(PiperAudioPlayer.FORMAT_OPUS, 500))
    }

    @Test
    fun thePhoneVoiceGetsTimeForTheWholeAnswer() {
        assertEquals(5_000L, PiperAudioPlayer.systemVoiceLimitMs(0))
        assertTrue(PiperAudioPlayer.systemVoiceLimitMs(200) >= 200 * 1000L / 12)   // about 12 characters a second
    }
}
