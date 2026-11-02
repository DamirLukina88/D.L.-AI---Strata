package com.damirl.ray.ui.webview

import android.content.Context
import com.damirl.ray.tools.RayNotificationListenerService
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.lang.reflect.Proxy

class RayNativeBridgeTest {

    private class DummyContext : android.content.ContextWrapper(null) {
        override fun getSystemService(name: String): Any? = null
        override fun getPackageManager(): android.content.pm.PackageManager? = null
    }

    private fun createDummyContext(): Context = DummyContext()


    @Test
    fun testBridgeAudioCall_invokesSpeechCleanerAndAudioSpeaker() {
        var deliveredSpeech = ""
        val context = createDummyContext()

        val bridge = RayNativeBridge(
            context = context,
            audioSpeaker = { cleaned ->
                deliveredSpeech = cleaned
            }
        )

        bridge.pageUrl = com.damirl.ray.BuildConfig.STRATA_LAN_URL

        val rawInput = "<think>Calculating internal state...</think>Hello from Strata engine! 🐾 Everything is 100% operational."
        bridge.speak(rawInput)

        assertTrue("Speech delivered must not be empty", deliveredSpeech.isNotBlank())
        assertTrue("Speech delivered must strip thinking block", !deliveredSpeech.contains("<think>"))
        assertTrue("Speech delivered must strip paws emoji", !deliveredSpeech.contains("🐾"))
        assertEquals("Hello from Strata engine! Everything is 100 percent operational.", deliveredSpeech)
    }

    @Test
    fun testMultilingual2faOtpParser_allRequiredCases() {
        // 1. Test English standard
        val enStandard = RayNotificationListenerService.extract2faCode("Your verification code is 849201")
        assertEquals("849201", enStandard)

        // 2. Test English short
        val enShort = RayNotificationListenerService.extract2faCode("Google: 492019 is your verification code")
        assertEquals("492019", enShort)

        // 3. Test Croatian PBZ
        val hrPbz = RayNotificationListenerService.extract2faCode("PBZ: jednokratna lozinka 382910 za prijavu")
        assertEquals("382910", hrPbz)

        // 4. Test Croatian ZABA
        val hrZaba = RayNotificationListenerService.extract2faCode("Zagrebacka banka: vas jednokratni kod je 719204")
        assertEquals("719204", hrZaba)

        // 5. Test Croatian Erste George
        val hrErste = RayNotificationListenerService.extract2faCode("Erste: vas aktivacijski kod: 582103")
        assertEquals("582103", hrErste)

        // 6. Test Croatian A1/HT
        val hrA1 = RayNotificationListenerService.extract2faCode("Vas sigurnosni kod za prijavu je 940182")
        assertEquals("940182", hrA1)
    }

    @Test
    fun testHardwareToolDispatching_routesProperly() {
        val context = createDummyContext()
        val bridge = RayNativeBridge(context = context)
        bridge.pageUrl = com.damirl.ray.BuildConfig.STRATA_LAN_URL

        val responseJson = bridge.executeTool(
            name = "phone_toggle_torch",
            argsJson = "{\"enabled\": true}",
            callId = "call_test_123"
        )

        assertNotNull("Response JSON should not be null", responseJson)
        val json = JSONObject(responseJson)
        assertEquals("phone_toggle_torch", json.optString("tool"))
        assertEquals("call_test_123", json.optString("callId"))
        assertTrue(
            "Response should contain result string",
            json.has("result") && json.optString("result").isNotBlank()
        )
    }

    @Test
    fun testToolDispatching_unknownTool_returnsCleanErrorJson() {
        val context = createDummyContext()
        val bridge = RayNativeBridge(context = context)
        bridge.pageUrl = com.damirl.ray.BuildConfig.STRATA_LAN_URL

        val responseJson = bridge.executeTool(
            name = "phone_fake_tool",
            argsJson = "{}",
            callId = "call_err_1"
        )

        assertNotNull(responseJson)
        val json = JSONObject(responseJson)
        assertEquals("phone_fake_tool", json.optString("tool"))
        assertEquals("call_err_1", json.optString("callId"))
        assertTrue(json.optString("result").contains("Unknown tool"))
    }

    @Test
    fun testToolDispatching_malformedJson_doesNotCrash() {
        val context = createDummyContext()
        val bridge = RayNativeBridge(context = context)
        bridge.pageUrl = com.damirl.ray.BuildConfig.STRATA_LAN_URL

        val responseJson = bridge.executeTool(
            name = "phone_toggle_torch",
            argsJson = "{malformed: invalid_json!",
            callId = "call_malformed"
        )

        assertNotNull(responseJson)
        val json = JSONObject(responseJson)
        assertEquals("phone_toggle_torch", json.optString("tool"))
        assertEquals("call_malformed", json.optString("callId"))
        assertTrue(json.has("result"))
    }

    @Test
    fun testGetApiKey_returnsConfiguredOrEmpty() {
        val context = createDummyContext()
        val bridge = RayNativeBridge(context = context)
        bridge.pageUrl = com.damirl.ray.BuildConfig.STRATA_LAN_URL
        val key = bridge.getApiKey()
        assertNotNull(key)
    }

    // another page in the WebView (a link, a redirect) gets nothing from the bridge
    @Test
    fun testUntrustedPage_getsNoKeyAndNoTools() {
        val context = createDummyContext()
        val bridge = RayNativeBridge(context = context)
        bridge.pageUrl = "https://evil.example.org/"
        assertEquals("", bridge.getApiKey())
        val res = org.json.JSONObject(bridge.executeTool("phone_get_battery", "{}", "c1"))
        assertTrue(res.getString("result").startsWith("Error: refused"))
        assertEquals("c1", res.getString("callId"))
        bridge.pageUrl = null
        assertEquals("", bridge.getApiKey())
    }

    // a look-alike host that merely contains the server's host name is not the server
    @Test
    fun testLookAlikeHost_isNotTrusted() {
        val lan = java.net.URI(com.damirl.ray.BuildConfig.STRATA_LAN_URL).host
        assertTrue(com.damirl.ray.network.StrataOrigins.isTrusted(com.damirl.ray.BuildConfig.STRATA_LAN_URL))
        assertFalse(com.damirl.ray.network.StrataOrigins.isTrusted("http://$lan.evil.example.org/"))
        assertFalse(com.damirl.ray.network.StrataOrigins.isTrusted("file:///sdcard/x.html"))
        assertFalse(com.damirl.ray.network.StrataOrigins.isTrusted(null))
    }
}
