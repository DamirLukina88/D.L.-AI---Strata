package com.damirl.ray.ui.main

import com.damirl.ray.network.ChatMessage
import com.damirl.ray.network.ChatRequest
import com.damirl.ray.network.NetworkClient
import com.damirl.ray.network.NetworkRoute
import junit.framework.TestCase.assertTrue
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import org.junit.Test

class MainScreenViewModelTest {
  @Test
  fun networkRoute_isNotNull() = runTest {
    val client = NetworkClient(lanUrl = "", remoteUrl = "", apiKey = "")
    val viewModel = MainScreenViewModel(networkClient = client)
    val route = viewModel.networkRoute.first()
    assertTrue(route is NetworkRoute)
  }

  @Test
  fun chatRequest_serializesStreamTrueByDefault() {
    val json = Json { encodeDefaults = true }
    val req = ChatRequest(messages = listOf(ChatMessage("user", "hi")))
    val str = json.encodeToString(ChatRequest.serializer(), req)
    assertTrue("stream must be true in JSON: $str", str.contains("\"stream\":true"))
  }
}
