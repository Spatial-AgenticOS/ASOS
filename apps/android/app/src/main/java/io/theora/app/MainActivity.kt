package io.theora.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import io.theora.app.services.BrainClient
import io.theora.app.ui.*
import io.theora.app.ui.theme.TheoraTheme

sealed class Screen(val route: String, val title: String, val icon: ImageVector) {
    data object Chat : Screen("chat", "Chat", Icons.Default.Chat)
    data object Voice : Screen("voice", "Voice", Icons.Default.Mic)
    data object Health : Screen("health", "Health", Icons.Default.Favorite)
    data object Settings : Screen("settings", "Settings", Icons.Default.Settings)
}

class MainActivity : ComponentActivity() {

    private val brainClient = BrainClient()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val prefs = getSharedPreferences("theora", MODE_PRIVATE)
        val host = prefs.getString("brain_host", "10.0.2.2") ?: "10.0.2.2"
        val port = prefs.getInt("brain_port", 9090)
        val apiKey = prefs.getString("brain_api_key", "") ?: ""
        brainClient.configure(host, port, apiKey)

        setContent {
            TheoraTheme {
                TheoraMobileApp(brainClient, prefs)
            }
        }
    }

    override fun onDestroy() {
        brainClient.destroy()
        super.onDestroy()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TheoraMobileApp(
    brainClient: BrainClient,
    prefs: android.content.SharedPreferences,
) {
    val navController = rememberNavController()
    val screens = listOf(Screen.Chat, Screen.Voice, Screen.Health, Screen.Settings)
    val currentRoute = navController.currentBackStackEntryAsState().value?.destination?.route

    Scaffold(
        bottomBar = {
            NavigationBar {
                screens.forEach { screen ->
                    NavigationBarItem(
                        icon = { Icon(screen.icon, contentDescription = screen.title) },
                        label = { Text(screen.title) },
                        selected = currentRoute == screen.route,
                        onClick = {
                            navController.navigate(screen.route) {
                                popUpTo(navController.graph.startDestinationId) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                    )
                }
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Screen.Chat.route,
            modifier = Modifier.padding(innerPadding),
        ) {
            composable(Screen.Chat.route) { ChatScreen(brainClient) }
            composable(Screen.Voice.route) { VoiceScreen(brainClient) }
            composable(Screen.Health.route) { HealthScreen(brainClient) }
            composable(Screen.Settings.route) { SettingsScreen(brainClient, prefs) }
        }
    }
}
