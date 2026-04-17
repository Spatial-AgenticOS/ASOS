package ai.feral.node

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainActivityTest {

    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun threeTabsAreVisible() {
        composeTestRule.setContent {
            androidx.compose.material3.MaterialTheme(
                colorScheme = androidx.compose.material3.darkColorScheme()
            ) {
                FeralNodeApp()
            }
        }

        composeTestRule.onNodeWithText("Chat").assertIsDisplayed()
        composeTestRule.onNodeWithText("Health").assertIsDisplayed()
        composeTestRule.onNodeWithText("Settings").assertIsDisplayed()
    }

    @Test
    fun navigateToHealthTab() {
        composeTestRule.setContent {
            androidx.compose.material3.MaterialTheme(
                colorScheme = androidx.compose.material3.darkColorScheme()
            ) {
                FeralNodeApp()
            }
        }

        composeTestRule.onNodeWithText("Health").performClick()
        composeTestRule.onNodeWithText("Heart Rate").assertIsDisplayed()
        composeTestRule.onNodeWithText("SpO2").assertIsDisplayed()
        composeTestRule.onNodeWithText("Steps").assertIsDisplayed()
        composeTestRule.onNodeWithText("Sleep").assertIsDisplayed()
    }

    @Test
    fun navigateToSettingsTab() {
        composeTestRule.setContent {
            androidx.compose.material3.MaterialTheme(
                colorScheme = androidx.compose.material3.darkColorScheme()
            ) {
                FeralNodeApp()
            }
        }

        composeTestRule.onNodeWithText("Settings").performClick()
        composeTestRule.onNodeWithText("Brain Host").assertIsDisplayed()
        composeTestRule.onNodeWithText("Port").assertIsDisplayed()
        composeTestRule.onNodeWithText("API Key").assertIsDisplayed()
    }

    @Test
    fun chatTabHasMessageInput() {
        composeTestRule.setContent {
            androidx.compose.material3.MaterialTheme(
                colorScheme = androidx.compose.material3.darkColorScheme()
            ) {
                FeralNodeApp()
            }
        }

        composeTestRule.onNodeWithText("Chat").performClick()
        composeTestRule.onNodeWithText("Message FERAL...").assertIsDisplayed()
    }
}
