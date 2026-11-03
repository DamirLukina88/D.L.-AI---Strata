package com.damirl.ray.ui.main

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.damirl.ray.assistant.AssistantOverlayScreen
import com.damirl.ray.assistant.VoicePhase
import com.damirl.ray.ui.theme.RayTheme
import org.junit.Rule
import org.junit.Test

/**
 * UI tests for the voice drawer ([AssistantOverlayScreen]); the app's main screen is the web app in a WebView.
 * Run on a device with ./gradlew connectedAndroidTest (note: it uninstalls the app it installed afterwards).
 */
class MainScreenTest {

  @get:Rule val composeTestRule = createAndroidComposeRule<ComponentActivity>()

  private fun drawer(phase: VoicePhase, thinking: String = "", thoughtSeconds: Int? = null, response: String = "") {
    composeTestRule.setContent {
      RayTheme {
        AssistantOverlayScreen(
          thinking = thinking, thoughtSeconds = thoughtSeconds, phase = phase, status = phase.name, prompt = "",
          partial = "", micLevel = 0f, response = response, onDismiss = {}, onMicTap = {}
        )
      }
    }
  }

  @Test
  fun listening_asksForSpeech() {
    drawer(VoicePhase.LISTENING)
    composeTestRule.onNodeWithText("Say something…").assertExists()
    composeTestRule.onNodeWithText("Tap to stop").assertExists()
  }

  @Test
  fun thinking_isShownWhileHeThinks() {
    drawer(VoicePhase.THINKING, thinking = "Checking the battery first.")
    composeTestRule.onNodeWithText("Thinking").assertExists()
    composeTestRule.onNodeWithText("Checking the battery first.").assertExists()
  }

  @Test
  fun thinking_foldsOnceTheAnswerStarts() {
    drawer(VoicePhase.ANSWERING, thinking = "Checking the battery first.", thoughtSeconds = 3, response = "It's at 67%.")
    composeTestRule.onNodeWithText("Thought for 3 s").assertExists()
    composeTestRule.onNodeWithText("Checking the battery first.").assertDoesNotExist()
    composeTestRule.onNodeWithText("It's at 67%.").assertExists()
  }
}
