package com.damirl.ray.tools

import android.content.ContextWrapper
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

// The voice drawer opens over the lock screen: whoever holds the locked phone must not get its 2FA codes,
// notifications or screen through Ray
class PhoneToolsLockTest {

    private class DummyContext : ContextWrapper(null) {
        override fun getSystemService(name: String): Any? = null
    }

    @Test
    fun privateToolsAreRefusedWhileLocked() {
        val tools = PhoneTools(DummyContext(), isLocked = { true })
        for (name in PhoneTools.PRIVATE) {
            assertEquals(name, PhoneTools.LOCKED_ANSWER, tools.execute(name, JSONObject()))
        }
    }

    @Test
    fun privateToolsRunOnceUnlocked() {
        val tools = PhoneTools(DummyContext(), isLocked = { false })
        for (name in PhoneTools.PRIVATE) {
            assertNotEquals(name, PhoneTools.LOCKED_ANSWER, tools.execute(name, JSONObject()))
        }
    }

    // the lock doesn't block the everyday tools (an unknown name stands in: it reaches the dispatch, not the guard)
    @Test
    fun otherToolsAreNotGuarded() {
        val tools = PhoneTools(DummyContext(), isLocked = { true })
        assertEquals("Error: Unknown tool 'phone_nope'.", tools.execute("phone_nope", JSONObject()))
    }

    // no KeyguardManager (can't tell): counted as locked
    @Test
    fun unknownLockStateCountsAsLocked() {
        assertEquals(PhoneTools.LOCKED_ANSWER, PhoneTools(DummyContext()).execute("phone_get_2fa_code", JSONObject()))
    }
}
