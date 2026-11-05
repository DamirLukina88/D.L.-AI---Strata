package com.damirl.ray.tools

import android.content.ContextWrapper
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class PhoneToolRelayTest {

    // a server: calls to hand out, what came back, and how many polls or posts should fail first
    private class FakeLink(vararg calls: PhoneToolCall) : PhoneRelayLink {
        val waiting = calls.toMutableList()
        val posted = mutableListOf<Pair<String, String>>()
        var polls = 0
        var failPolls = 0
        var failPosts = 0

        override fun pending(): PhoneToolCall? {
            polls++
            if (failPolls > 0) { failPolls--; throw IOException("HTTP 502") }
            return waiting.removeFirstOrNull()
        }

        override fun post(id: String, result: String) {
            if (failPosts > 0) { failPosts--; throw IOException("reset") }
            posted += id to result
        }
    }

    private fun call(id: String, tool: String = "phone_get_battery") = PhoneToolCall(id, tool, JSONObject())

    @Test
    fun runsACallAndPostsItsResult() = runTest {
        val link = FakeLink(call("c1"))
        val ran = mutableListOf<String>()
        val relay = PhoneToolRelay(link, { name, _ -> ran += name; "Battery: 86%" }, 1000, StandardTestDispatcher(testScheduler))
        val job = launch { relay.run() }
        runCurrent()
        job.cancelAndJoin()
        assertEquals(listOf("phone_get_battery"), ran)
        assertEquals(listOf("c1" to "Battery: 86%"), link.posted)
    }

    @Test
    fun keepsPollingWhenThereIsNothingAndAfterABadPoll() = runTest {
        val link = FakeLink().apply { failPolls = 2 }
        val relay = PhoneToolRelay(link, { _, _ -> "" }, 1000, StandardTestDispatcher(testScheduler))
        val job = launch { relay.run() }
        runCurrent()
        link.waiting += call("c1")
        advanceTimeBy(5000)
        runCurrent()
        job.cancelAndJoin()
        assertEquals(listOf("c1" to ""), link.posted)
        assertTrue("polls: ${link.polls}", link.polls >= 4)
    }

    @Test
    fun aToolThatThrowsStillAnswers() = runTest {
        val link = FakeLink(call("c1"))
        val relay = PhoneToolRelay(link, { _, _ -> error("no camera") }, 1000, StandardTestDispatcher(testScheduler))
        val job = launch { relay.run() }
        runCurrent()
        job.cancelAndJoin()
        assertEquals(listOf("c1" to "Error executing tool: no camera"), link.posted)
    }

    @Test
    fun aResultThatDidNotArriveIsSentAgain() = runTest {
        val link = FakeLink(call("c1")).apply { failPosts = 2 }
        val relay = PhoneToolRelay(link, { _, _ -> "done" }, 1000, StandardTestDispatcher(testScheduler))
        val job = launch { relay.run() }
        advanceTimeBy(2000)
        runCurrent()
        job.cancelAndJoin()
        assertEquals(listOf("c1" to "done"), link.posted)
    }

    @Test
    fun stopsPollingWhenTheTurnEnds() = runTest {
        val link = FakeLink()
        val relay = PhoneToolRelay(link, { _, _ -> "" }, 1000, StandardTestDispatcher(testScheduler))
        val job = launch { relay.run() }
        advanceTimeBy(2500)
        runCurrent()
        job.cancelAndJoin()
        val polls = link.polls
        advanceTimeBy(10_000)
        runCurrent()
        assertEquals(polls, link.polls)
    }

    // the relay goes through PhoneTools, so whoever holds the locked phone gets no codes through the drawer's relay
    @Test
    fun privateToolsStayRefusedOnALockedPhone() = runTest {
        val tools = PhoneTools(object : ContextWrapper(null) {
            override fun getSystemService(name: String): Any? = null
        }, isLocked = { true })
        val link = FakeLink(call("c1", "phone_get_2fa_code"), call("c2", "phone_get_screen"))
        val relay = PhoneToolRelay(link, tools::execute, 1000, StandardTestDispatcher(testScheduler))
        val job = launch { relay.run() }
        runCurrent()
        job.cancelAndJoin()
        assertEquals(listOf("c1" to PhoneTools.LOCKED_ANSWER, "c2" to PhoneTools.LOCKED_ANSWER), link.posted)
    }

    @Test
    fun readsThePendingAnswer() {
        val call = parsePendingCall("""{"pending": {"id": "c1", "tool": "phone_control_media", "args": {"action": "pause"}}}""")
        assertEquals("c1", call?.id)
        assertEquals("phone_control_media", call?.tool)
        assertEquals("pause", call?.args?.getString("action"))
        assertNull(parsePendingCall("""{"pending": null}"""))
        assertNull(parsePendingCall("""{"pending": {"id": "", "tool": "x"}}"""))
        assertNull(parsePendingCall("<html>not json</html>"))
        assertEquals(0, parsePendingCall("""{"pending": {"id": "c1", "tool": "x"}}""")?.args?.length())
    }
}
