package ai.feral.node

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class MainActivity : ComponentActivity() {
    private var healthManager: HealthConnectManager? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        healthManager = HealthConnectManager(this).also { hm ->
            if (hm.initialize()) {
                hm.startPeriodicReads(scope)
            }
        }
        
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                FeralNodeApp(
                    onStartService = { startFeralService() },
                    onStopService = { stopFeralService() }
                )
            }
        }
    }
    
    private fun startFeralService() {
        val intent = Intent(this, FeralForegroundService::class.java)
        startForegroundService(intent)
    }
    
    private fun stopFeralService() {
        stopService(Intent(this, FeralForegroundService::class.java))
    }
    
    override fun onDestroy() {
        super.onDestroy()
        healthManager?.stop()
    }
}

enum class FeralTab(val label: String, val icon: ImageVector) {
    Chat("Chat", Icons.AutoMirrored.Filled.Chat),
    Health("Health", Icons.Filled.Favorite),
    Settings("Settings", Icons.Filled.Settings)
}

@Composable
fun FeralNodeApp(onStartService: () -> Unit = {}, onStopService: () -> Unit = {}) {
    var selectedTab by remember { mutableStateOf(FeralTab.Chat) }
    var isConnected by remember { mutableStateOf(false) }
    var host by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("9090") }
    var apiKey by remember { mutableStateOf("") }
    var statusText by remember { mutableStateOf("Not connected") }
    var chatMessages by remember { mutableStateOf(listOf<ChatMessage>()) }

    var heartRate by remember { mutableIntStateOf(0) }
    var spO2 by remember { mutableIntStateOf(0) }
    var steps by remember { mutableIntStateOf(0) }
    var sleepHours by remember { mutableDoubleStateOf(0.0) }

    Scaffold(
        bottomBar = {
            NavigationBar(containerColor = Color(0xFF0A0A0B)) {
                FeralTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = { selectedTab = tab },
                        icon = { Icon(tab.icon, contentDescription = tab.label) },
                        label = { Text(tab.label) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Color(0xFF06B6D4),
                            selectedTextColor = Color(0xFF06B6D4),
                            indicatorColor = Color(0xFF06B6D4).copy(alpha = 0.15f),
                            unselectedIconColor = Color.Gray,
                            unselectedTextColor = Color.Gray,
                        )
                    )
                }
            }
        }
    ) { padding ->
        Box(modifier = Modifier.padding(padding)) {
            when (selectedTab) {
                FeralTab.Chat -> ChatScreen(
                    onSend = { text ->
                        chatMessages = chatMessages + ChatMessage("user", text)
                    },
                    messages = chatMessages
                )
                FeralTab.Health -> HealthScreen(
                    isConnected = isConnected,
                    heartRate = heartRate,
                    spO2 = spO2,
                    steps = steps,
                    sleepHours = sleepHours
                )
                FeralTab.Settings -> SettingsScreen(
                    isConnected = isConnected,
                    host = host,
                    port = port,
                    apiKey = apiKey,
                    statusText = statusText,
                    onHostChange = { host = it },
                    onPortChange = { port = it },
                    onApiKeyChange = { apiKey = it },
                    onConnect = {
                        statusText = "Connecting..."
                        isConnected = true
                        statusText = "Connected to $host:$port"
                        onStartService()
                    },
                    onDisconnect = {
                        isConnected = false
                        statusText = "Disconnected"
                        onStopService()
                    }
                )
            }
        }
    }
}

@Composable
fun HealthScreen(isConnected: Boolean, heartRate: Int, spO2: Int, steps: Int, sleepHours: Double) {
    Column(
        modifier = Modifier.fillMaxSize().background(Color(0xFF0A0A0B)).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Text("Health", style = MaterialTheme.typography.headlineLarge, color = Color.White)
        
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(modifier = Modifier.size(10.dp).clip(CircleShape).background(if (isConnected) Color.Green else Color.Red))
            Text(if (isConnected) "Connected" else "Disconnected", color = Color.Gray, style = MaterialTheme.typography.bodySmall)
        }
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            HealthMetricCard("Heart Rate", "$heartRate", "bpm", Color(0xFFEF4444), Modifier.weight(1f))
            HealthMetricCard("SpO2", "$spO2", "%", Color(0xFF3B82F6), Modifier.weight(1f))
        }
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            HealthMetricCard("Steps", "$steps", "today", Color(0xFF22C55E), Modifier.weight(1f))
            HealthMetricCard("Sleep", String.format("%.1f", sleepHours), "hrs", Color(0xFFA855F7), Modifier.weight(1f))
        }
    }
}

@Composable
fun HealthMetricCard(title: String, value: String, unit: String, color: Color, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = MaterialTheme.shapes.medium,
        color = color.copy(alpha = 0.1f)
    ) {
        Column(modifier = Modifier.padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(title, style = MaterialTheme.typography.bodySmall, color = Color.Gray)
            Spacer(modifier = Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                Text(value, style = MaterialTheme.typography.headlineMedium, color = Color.White)
                Spacer(modifier = Modifier.width(4.dp))
                Text(unit, style = MaterialTheme.typography.bodySmall, color = Color.Gray)
            }
        }
    }
}

@Composable
fun SettingsScreen(
    isConnected: Boolean,
    host: String,
    port: String,
    apiKey: String,
    statusText: String,
    onHostChange: (String) -> Unit,
    onPortChange: (String) -> Unit,
    onApiKeyChange: (String) -> Unit,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize().background(Color(0xFF0A0A0B)).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineLarge, color = Color.White)
        
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(modifier = Modifier.size(12.dp).clip(CircleShape).background(if (isConnected) Color.Green else Color.Red))
            Text(statusText, style = MaterialTheme.typography.bodyLarge, color = Color.White)
        }
        
        Spacer(modifier = Modifier.height(8.dp))
        
        if (!isConnected) {
            OutlinedTextField(value = host, onValueChange = onHostChange,
                label = { Text("Brain Host") }, modifier = Modifier.fillMaxWidth(),
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Color(0xFF06B6D4), focusedTextColor = Color.White, unfocusedTextColor = Color.White))
            OutlinedTextField(value = port, onValueChange = onPortChange,
                label = { Text("Port") }, modifier = Modifier.fillMaxWidth(),
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Color(0xFF06B6D4), focusedTextColor = Color.White, unfocusedTextColor = Color.White))
            OutlinedTextField(value = apiKey, onValueChange = onApiKeyChange,
                label = { Text("API Key") }, modifier = Modifier.fillMaxWidth(),
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Color(0xFF06B6D4), focusedTextColor = Color.White, unfocusedTextColor = Color.White))
            
            Button(onClick = onConnect, modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF06B6D4))) {
                Text("Connect")
            }
            
            OutlinedButton(onClick = { }, modifier = Modifier.fillMaxWidth()) {
                Text("Scan QR Code to Pair")
            }
        } else {
            Button(onClick = onDisconnect,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                modifier = Modifier.fillMaxWidth()) {
                Text("Disconnect")
            }
        }
    }
}
